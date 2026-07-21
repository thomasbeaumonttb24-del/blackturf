"""
Détecteur de value bets — BlackTurf.

Formule : EV = (Cote × Proba_IA) - 1
EV > 0 = espérance positive à long terme.
Triangulation 6 sources : PMU + Geny + BZH + Winamax + Betclic + Unibet + Betfair Exchange.

SPI (Steam Price Indicator) :
  Priorité 1 : historique de cotes PMU (baisse > 15% en 30min)
  Priorité 2 : gap PMU vs Betfair Exchange (plus efficient du marché)
  Priorité 3 : gap PMU vs médiane bookmakers alternatifs
"""
import uuid
import statistics
import structlog
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import ValueBet

log = structlog.get_logger()

# Seuils EV par niveau
EV_SEUILS = {
    1: 0.05,   # ⭐  Intéressant
    2: 0.10,   # ⭐⭐ Bon signal
    3: 0.20,   # ⭐⭐⭐ Fort signal
    4: 0.30,   # ⭐⭐⭐⭐ Exceptionnel
}

# Seuils de confiance sur la PROBA DE VICTOIRE (proba_top1, normalisée Σ=1).
# Un value bet "gagnant" oppose la cote gagnant à P(victoire) : ces seuils évitent
# de flagger un outsider (faible P(win)) juste parce que sa cote est énorme.
CONFIANCE_SEUILS = {
    1: 0.10,   # ≥10% de victoire
    2: 0.14,
    3: 0.18,
    4: 0.22,   # favori net
}

# NB : pas de couperet dur sur l'EX-CÉDENT d'EV. Les bandes d'EV historiquement
# perdantes (zone toxique) ne sont PAS rejetées mais RÉTROGRADÉES selon le ROI réel
# appris nightly (ml.signal_performance.ev_band_multiplier) — la sélection s'adapte
# à ce que l'algo mesure au fil de l'eau au lieu de bannir une bande en dur.

# ── Garde-fous calibration longshot ──────────────────────────────────────────
# Au-delà de ce ratio proba_modèle / proba_marché_implicite, le "value" est
# presque toujours une erreur de calibration sur outsider (le modèle sur-évalue
# les grosses cotes), PAS un edge réel. On refuse → pas de faux signal.
# NOTE : valeur conservatrice ; à recaler avec scripts/calibration_longshots.py
# (proba prédite vs fréquence réelle observée par bucket de cote).
# Le gate ne s'applique qu'AU-DELÀ de LONGSHOT_COTE_MIN : sur les favoris (cote
# basse) le modèle est bien calibré et un fort écart au marché peut être un vrai
# edge ; c'est uniquement sur les grosses cotes que l'écart trahit le sur-fit.
# Resserré : l'inflation d'EV se produit dès la zone cote 4-8 (ex. proba modèle
# 38% sur une cote 6.8 = 2.5× le marché → EV +118% non crédible), pas seulement
# au-delà de 8. Gate appliqué dès cote 4, écart max 1.7× la proba marché.
# 1.7→1.55 (2026-07-02, priorité ROI) : un modèle qui voit >1.55× la proba du marché
# sur une cote ≥4 est quasi toujours du sur-fit outsider, pas de l'edge. Resserrer
# coupe les faux signaux les plus toxiques (l'inflation d'EV en zone cote 4-8).
MAX_MODEL_MARKET_RATIO = 1.55
LONGSHOT_COTE_MIN = 4.0
# Court-cote : sur cote < LONGSHOT_COTE_MIN, on cape la proba modèle au marché ×
# ce ratio. Le sous-ensemble VB cote<4 est sur-coté (ROI réel −44%) → edge max
# crédible sur favori court = +30% vs marché. Tue les faux value bets courts.
SHORT_MAX_RATIO = 1.3

# Cote max retenue pour le calcul de l'EV = médiane marché × ce facteur.
# Anti winner's curse : empêche de calculer l'EV sur une cote isolée très
# au-dessus du marché (quasi toujours stale/erronée parmi les 7 sources).
COTE_CEIL_FACTOR = 1.15

# Cote gagnant max absolue pour un value bet. Au-delà, le modèle est trop peu
# fiable (cf. biais longshot) pour qu'un edge soit crédible.
COTE_MAX_VB = 25.0

# Poids des sources pour le calcul de la cote marché de référence
# Betfair Exchange = marché sans marge bookmaker → poids le plus élevé
SOURCE_WEIGHTS = {
    "pmu":     1.0,   # source principale mais avec overround ~15%
    "geny":    1.2,
    "bzh":     1.2,
    "winamax": 1.5,
    "betclic": 1.5,
    "unibet":  1.5,
    "betfair": 3.0,   # exchange = cote efficiente, 0% marge
}


def calculer_ev(cote: float, proba: float) -> float:
    """EV = (Cote × Proba) - 1."""
    if cote <= 0 or proba <= 0:
        return -1.0
    return (cote * proba) - 1.0


def determine_niveau(ev: float, proba: float) -> Optional[int]:
    """Détermine le niveau du value bet (1-4 étoiles). None si pas de VB."""
    for niveau in [4, 3, 2, 1]:
        if ev >= EV_SEUILS[niveau] and proba >= CONFIANCE_SEUILS[niveau]:
            return niveau
    return None


def cote_marche_ponderee(cotes: dict[str, float]) -> Optional[float]:
    """
    Calcule la cote de marché pondérée par fiabilité de source.
    Retourne la cote 'juste' — celle qu'utilise le marché efficient.
    """
    valides = {s: c for s, c in cotes.items() if c and c > 1.0}
    if not valides:
        return None
    weighted_sum = sum(c * SOURCE_WEIGHTS.get(s, 1.0) for s, c in valides.items())
    weight_total = sum(SOURCE_WEIGHTS.get(s, 1.0) for s in valides)
    return weighted_sum / weight_total


def triangulation_cotes_v2(
    proba: float,
    cotes: dict[str, Optional[float]],
) -> tuple[dict[str, float], str, float]:
    """
    Calcule l'EV depuis toutes les sources disponibles.
    Retourne (evs_par_source, meilleure_source, cote_marche).
    """
    evs: dict[str, float] = {}
    for source, cote in cotes.items():
        if cote and cote > 1.0:
            evs[source] = calculer_ev(cote, proba)

    if not evs:
        return {}, "pmu", 0.0

    meilleure_source = max(evs, key=lambda k: evs[k])
    cote_ref = cote_marche_ponderee({s: c for s, c in cotes.items() if c}) or 0.0

    return evs, meilleure_source, cote_ref


def compute_spi_v2(
    cote_pmu: Optional[float],
    cotes_alternatives: dict[str, Optional[float]],
    cotes_history: Optional[list[float]] = None,
    steam_move_betclic_pct: Optional[float] = None,
) -> tuple[bool, Optional[float], str]:
    """
    Steam Price Indicator — version améliorée.
    Hiérarchie de signaux :
      1. Historique PMU (baisse > 15% = argent pro sur PMU)
      2. Steam move Betclic ouverture→actuelle (le plus fiable)
      3. Gap PMU vs Betfair Exchange (plus efficient)
      4. Gap PMU vs médiane alternatives

    Retourne (spi_detected, spi_score, spi_method).
    """
    # Signal 1 : historique de cotes PMU
    if cotes_history and len(cotes_history) >= 2:
        from ml.features import compute_spi_from_cotes_history
        score = compute_spi_from_cotes_history(cotes_history)
        if score >= 0.15:
            return True, round(score, 3), "cotes_history"

    # Signal 2 : steam move Betclic ouverture→actuelle
    if steam_move_betclic_pct and steam_move_betclic_pct > 10.0:
        score = float(min(1.0, steam_move_betclic_pct / 50.0))
        return True, round(score, 3), "betclic_steam"

    # Signal 3 : gap PMU vs Betfair Exchange
    cote_betfair = cotes_alternatives.get("betfair")
    if cote_pmu and cote_betfair and cote_pmu > 1.0 and cote_betfair > 1.0:
        gap = (cote_pmu - cote_betfair) / cote_betfair
        if gap >= 0.12:   # Seuil plus bas car Betfair est plus précis
            score = float(min(1.0, gap * 3.0))
            return True, round(score, 3), "betfair_gap"

    # Signal 4 : gap PMU vs médiane alternatives
    alts = [c for s, c in cotes_alternatives.items() if c and c > 1.0 and s != "pmu"]
    if alts and cote_pmu and cote_pmu > 1.0:
        cote_mediane = statistics.median(alts)
        gap = (cote_pmu - cote_mediane) / cote_mediane
        if gap >= 0.15:
            score = float(min(1.0, gap * 2.5))
            return True, round(score, 3), "market_gap"

    return False, None, "none"


def detect_value_bet(
    proba_top1: float,
    cote_pmu: Optional[float] = None,
    cote_geny: Optional[float] = None,
    cote_bzh: Optional[float] = None,
    cote_winamax: Optional[float] = None,
    cote_betclic: Optional[float] = None,
    cote_unibet: Optional[float] = None,
    cote_betfair: Optional[float] = None,
    cotes_history: Optional[list[float]] = None,
    steam_move_betclic_pct: Optional[float] = None,
    jockey_suspendu: bool = False,
    entraineur_suspendu: bool = False,
    non_partant: bool = False,
    cote_calib: Optional[dict] = None,
    signal_mult: Optional[float] = None,
    field_overround: Optional[float] = None,
    ev_band_perf: Optional[dict] = None,
) -> Optional[dict]:
    """
    Détecte si un partant est un value bet — version multi-sources.

    proba_top1 : P(victoire) normalisée (Σ=1) du partant. Pour un value bet
    GAGNANT, passer la P(victoire), pas la proba placé — cf. pipeline.py qui
    passe proba_t1. Les CONFIANCE_SEUILS sont calibrés sur P(victoire).

    Garde-fous :
      - Non-partant déclaré → None
      - Jockey ou entraîneur suspendu → None (invalide le pari)
      - Aucune cote disponible → None

    cotes_history : liste chronologique de cotes PMU (plus récente en dernier).
    steam_move_betclic_pct : % de baisse cote Betclic depuis l'ouverture.
    """
    # Garde-fous critiques
    if non_partant:
        return None
    if jockey_suspendu or entraineur_suspendu:
        log.warning("valuebets.suspended_skip",
                    jockey=jockey_suspendu, entraineur=entraineur_suspendu)
        return None

    cotes = {
        "pmu":     cote_pmu,
        "geny":    cote_geny,
        "bzh":     cote_bzh,
        "winamax": cote_winamax,
        "betclic": cote_betclic,
        "unibet":  cote_unibet,
        "betfair": cote_betfair,
    }

    # ── Calibration par tranche de cote (apprise des résultats réels, nightly) ──
    # Corrige le biais favori-longshot AVANT le calcul d'EV : le modèle sous-estime
    # les favoris et sur-estime les outsiders → sans ça, EV gonflées sur longshots
    # (faux value bets perdants). On rapproche la P(victoire) de la réalité observée
    # par bucket de cote → EV honnête → renta. Neutre (×1.0) si pas de calibration.
    # SHRINK-ONLY pour la sélection value bet : on ne laisse la calibration que
    # RÉDUIRE la proba (couper les outsiders sur-cotés = vrais faux value bets),
    # jamais l'augmenter — un boost de favori pourrait gonfler un faux VB court
    # (le sous-ensemble VB cote<4 est sur-coté, ROI réel mesuré −44%). Prudent = renta.
    if cote_calib and cote_pmu and cote_pmu > 1:
        from ml.cote_calibration import apply_factor
        f = min(1.0, apply_factor(cote_pmu, cote_calib, "win"))
        proba_top1 = float(max(1e-4, min(0.99, proba_top1 * f)))

    evs, meilleure_source, cote_marche = triangulation_cotes_v2(proba_top1, cotes)
    if not evs:
        return None

    # Garde-fou outsiders extrêmes : au-delà de COTE_MAX_VB le modèle est trop peu
    # fiable (biais longshot) pour qu'un edge soit crédible. On refuse pour protéger
    # la bankroll de l'utilisateur (intégrité : pas de faux signal).
    cote_meilleure = cotes.get(meilleure_source) or 0.0
    if cote_meilleure > COTE_MAX_VB:
        return None

    # ── Garde-fou calibration : ratio proba modèle / proba marché ────────────
    # Si le modèle attribue une proba > MAX_MODEL_MARKET_RATIO × la proba marché
    # implicite (1/cote_juste), c'est quasi toujours une surestimation d'outsider,
    # pas un vrai edge. C'est la source des EV absurdes (+296% sur des 37/1).
    if cote_marche and cote_marche >= LONGSHOT_COTE_MIN:
        implied_marche = 1.0 / cote_marche
        # FLAG devig_gates : la proba implicite brute 1/cote contient la marge
        # bookmaker (~12-20% overround) → biaisée HAUTE. On la dé-vigge en la
        # divisant par l'overround du champ pour comparer la proba modèle à la
        # VRAIE proba juste (cf. audit edge : gate qui se déclenchait au mauvais
        # seuil = set EV>0 contaminé = -52% live). Flag off → comportement d'avant.
        from ml.algo_flags import FLAGS as _FLAGS
        if _FLAGS.devig_gates and field_overround and field_overround > 0:
            implied_marche = implied_marche / field_overround
        if proba_top1 > MAX_MODEL_MARKET_RATIO * implied_marche:
            log.info("valuebets.longshot_rejected",
                     proba=round(proba_top1, 4), cote_marche=round(cote_marche, 2),
                     ratio=round(proba_top1 / implied_marche, 2))
            return None

    # ── Garde-fou COURT-COTE (symétrique du longshot) ────────────────────────
    # Sur cote < LONGSHOT_COTE_MIN, le sous-ensemble value bet (modèle > marché) est
    # SUR-coté : ROI réel mesuré −44% (le modèle surestime les courts qu'il aime).
    # On CAPE la P(victoire) au marché × SHORT_MAX_RATIO → EV honnête, plus de faux
    # value bet court (don au PMU). Mesuré sur predictions ⋈ résultats par bucket.
    elif cote_marche and 1.0 < cote_marche < LONGSHOT_COTE_MIN:
        from ml.algo_flags import FLAGS as _FLAGS
        if _FLAGS.devig_gates and field_overround and field_overround > 0:
            # Cap court-cote sur la proba juste dé-viggée (cohérent avec le gate longshot).
            cap_ref = (1.0 / cote_marche) / field_overround
            proba_top1 = min(proba_top1, SHORT_MAX_RATIO * cap_ref)
        else:
            proba_top1 = min(proba_top1, SHORT_MAX_RATIO / cote_marche)

    # ── EV anti winner's curse ───────────────────────────────────────────────
    # ev_max calculé sur une cote PLAFONNÉE à la médiane marché × facteur, pas sur
    # la cote la plus haute des 7 sources (souvent isolée/stale → EV gonflée).
    # On parie quand même sur meilleure_source, mais l'EV affichée reste crédible.
    cotes_valides = [c for c in cotes.values() if c and c > 1.0]
    cote_mediane = statistics.median(cotes_valides) if cotes_valides else cote_meilleure
    cote_ev = min(cote_meilleure, cote_mediane * COTE_CEIL_FACTOR)
    ev_max = calculer_ev(cote_ev, proba_top1)

    niveau = determine_niveau(ev_max, proba_top1)
    if niveau is None:
        return None

    # SPI — hiérarchie de signaux
    cotes_alternatives = {s: c for s, c in cotes.items() if s != "pmu"}
    spi_detected, spi_score, spi_method = compute_spi_v2(
        cote_pmu, cotes_alternatives, cotes_history, steam_move_betclic_pct
    )

    # Boost niveau si SPI confirmé par source fiable
    if spi_detected and spi_method in ("cotes_history", "betclic_steam", "betfair_gap"):
        if spi_score and spi_score >= 0.40 and niveau < 4:
            niveau = min(4, niveau + 1)

    # ── Apprentissage par SIGNAL : module le niveau selon le ROI réel des signaux
    # portés par ce cheval (appris des résultats, recalc nightly). Un cheval avec
    # des signaux historiquement PERDANTS (ex. "forme excellente" surcotée, ROI −25%)
    # est rétrogradé ; des signaux GAGNANTS (duo J/E +218%, ELO sup +74%) le promeuvent.
    # → la sélection se réajuste vers ce qui a VRAIMENT rapporté. Neutre si None.
    if signal_mult is not None:
        if signal_mult <= 0.80 and niveau > 1:
            niveau -= 1
        elif signal_mult >= 1.30 and niveau < 4:
            niveau += 1

    # ── Apprentissage par BANDE D'EV (ROI réel appris nightly, K_SHRINK=60) ──
    # GATE D'ÉMISSION (flag ev_band_gate, audit ROI 2026-07-02) : une bande au ROI
    # shrinké NÉGATIF (multiplier < 1.0) n'émet PLUS de value bet du tout. Mesuré
    # sur 12 432 paris figés : seules les bandes EV 0.10-0.35 rapportent (+1.7/+2.7%) ;
    # 0-0.10 = −14%, 0.35-0.60 = −6%, >0.60 = −21%. Rétrograder d'un niveau (ancien
    # comportement) laissait ces paris sortir → 59% de l'émission en zone perdante.
    # Bande neutre (pas de données, multiplier exactement 1.0) → émission normale
    # (cold-start sûr). Flag off → retour à la simple rétrogradation.
    if ev_band_perf is not None:
        from ml.signal_performance import ev_band_multiplier
        from ml.algo_flags import FLAGS as _AF
        ev_mult = ev_band_multiplier(ev_max, ev_band_perf)
        if _AF.ev_band_gate and ev_mult < 0.9995:
            log.info("valuebets.ev_band_rejected",
                     ev=round(ev_max, 3), band_mult=round(ev_mult, 3))
            return None
        if ev_mult <= 0.65:
            niveau = max(1, niveau - 2)
        elif ev_mult <= 0.85 and niveau > 1:
            niveau -= 1
        elif ev_mult >= 1.20 and niveau < 4:
            niveau += 1

    return {
        "signal_mult": round(float(signal_mult), 3) if signal_mult is not None else None,
        # EVs par source
        "ev_pmu":     evs.get("pmu"),
        "ev_geny":    evs.get("geny"),
        "ev_bzh":     evs.get("bzh"),
        "ev_winamax": evs.get("winamax"),
        "ev_betclic": evs.get("betclic"),
        "ev_unibet":  evs.get("unibet"),
        "ev_betfair": evs.get("betfair"),
        "ev_max":     ev_max,
        "meilleure_source": meilleure_source,
        "cote_marche_reference": round(cote_marche, 2),
        "niveau": niveau,
        # SPI
        "spi_detected": spi_detected,
        "spi_score":    spi_score,
        "spi_method":   spi_method,
        # Nb de sources disponibles
        "nb_sources": sum(1 for c in cotes.values() if c and c > 1.0),
    }


async def save_value_bet(
    session: AsyncSession,
    prediction_id: str,
    course_id: str,
    participation_id: str,
    vb: dict,
) -> str:
    """Sauvegarde un value bet en DB. Retourne vb_id."""
    vb_id = str(uuid.uuid4())
    stmt = pg_insert(ValueBet).values(
        vb_id=vb_id,
        prediction_id=prediction_id,
        course_id=course_id,
        participation_id=participation_id,
        ev_pmu=vb.get("ev_pmu"),
        ev_geny=vb.get("ev_geny"),
        ev_bzh=vb.get("ev_bzh"),
        ev_max=vb["ev_max"],
        meilleure_source=vb["meilleure_source"],
        niveau=vb["niveau"],
        spi_detected=vb.get("spi_detected", False),
        spi_score=vb.get("spi_score"),
        actif=True,
        detecte_a=datetime.now(),
    ).on_conflict_do_update(
        index_elements=["participation_id"],   # upsert si recalculé
        set_={
            "ev_pmu": vb.get("ev_pmu"),
            "ev_geny": vb.get("ev_geny"),
            "ev_bzh": vb.get("ev_bzh"),
            "ev_max": vb["ev_max"],
            "meilleure_source": vb["meilleure_source"],
            "niveau": vb["niveau"],
            "spi_detected": vb.get("spi_detected", False),
            "spi_score": vb.get("spi_score"),
        },
    )
    await session.execute(stmt)
    return vb_id


def calculer_mise_kelly(
    ev: float,
    cote: float,
    bankroll: float,
    fraction: float = 0.5,  # Demi-Kelly par défaut
    max_pct: float = 0.05,  # Plafond 5% bankroll
) -> float:
    """
    Critère de Kelly pour la mise optimale.

    Fraction de Kelly f* = EV / (cote − 1)  (b = cote − 1 = gain net par unité).
    Diviser par `cote` au lieu de `(cote − 1)` sous-mise systématiquement et ne
    correspond à aucun critère standard.
    Mise = bankroll × f* × fraction, plafonnée à `max_pct` de bankroll.
    fraction=0.5 = demi-Kelly (recommandé pour débutants).
    """
    if cote <= 1.0 or ev <= 0:
        return 0.0
    mise = (ev * bankroll) / (cote - 1.0) * fraction
    mise = min(mise, bankroll * max_pct)
    return round(max(0.0, mise), 2)


# ─────────────────────────────────────────────
# Backward compatibility aliases (tests + old callers)
# ─────────────────────────────────────────────
def triangulation_cotes(proba, cote_pmu=None, cote_geny=None, cote_bzh=None):
    """Alias v1 → v2 (3 sources)."""
    evs, best, _ = triangulation_cotes_v2(proba, {"pmu": cote_pmu, "geny": cote_geny, "bzh": cote_bzh})
    return evs.get("pmu"), evs.get("geny"), evs.get("bzh"), best


def compute_spi_from_gap(cote_pmu=None, cote_geny=None, cote_bzh=None):
    """Alias v1 → v2."""
    detected, score, _ = compute_spi_v2(cote_pmu, {"geny": cote_geny, "bzh": cote_bzh})
    return detected, score
