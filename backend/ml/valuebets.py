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
    proba_top3: float,
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
) -> Optional[dict]:
    """
    Détecte si un partant est un value bet — version multi-sources.

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

    evs, meilleure_source, cote_marche = triangulation_cotes_v2(proba_top3, cotes)
    if not evs:
        return None

    # Garde-fou outsiders extrêmes : un "value bet" sur une cote > 50 est presque
    # toujours une erreur de modèle (proba surestimée), pas un vrai edge. On refuse
    # pour protéger la bankroll de l'utilisateur (intégrité : pas de faux signal).
    cote_meilleure = cotes.get(meilleure_source) or 0.0
    if cote_meilleure > 50.0:
        return None

    ev_max = evs[meilleure_source]
    niveau = determine_niveau(ev_max, proba_top3)
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

    return {
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

    Mise Kelly = (EV × Bankroll) / Cote
    Plafonnée à 5% de bankroll.
    fraction=0.5 = demi-Kelly (recommandé pour débutants).
    """
    if cote <= 1.0 or ev <= 0:
        return 0.0
    mise = (ev * bankroll) / cote * fraction
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
