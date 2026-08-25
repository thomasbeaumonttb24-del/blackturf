"""
signal_performance.py — Apprentissage par SIGNAL (auto-amélioration, renta).

Pour chaque signal qualitatif (mêmes définitions que narrative.explain_prediction :
steam, forme excellente, ELO > champ, duo J×E, descente de catégorie, terrain idéal,
draw favorable, SPI…), mesure sur l'HISTORIQUE RÉEL :
  - n          : nb de fois où un partant portait ce signal
  - win_rate   : taux de victoire réel de ces partants
  - roi        : ROI d'un 1€ Simple Gagnant à la cote PMU réelle (Σpayout−Σstake)/Σstake
  - roi_shrunk : ROI shrinké vers 0 (break-even) par pseudo-compte K → pas de
                 sur-réaction sur petit échantillon

→ On apprend ce qui RAPPORTE souvent vs ce qui ne rapporte casi jamais, et on en
nourrit la sélection des value bets (signal_multiplier). Recalculé nightly.
Aucune valeur inventée : tout vient des résultats réels ; signal absent → neutre.
"""
from __future__ import annotations

import json
import math

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.prediction_evaluation import (
    MIN_EV_BAND_OBS,
    MIN_EV_BAND_REPLAYABLE_OBS,
    MIN_RAPPORT_CALIB_RUNS,
    MIN_SIGNAL_PERF_OBS,
)

log = structlog.get_logger()

# Définitions des signaux = (nom, prédicat sur le dict features). Alignées sur
# narrative.explain_prediction pour cohérence avec ce que l'utilisateur voit.
SIGNALS: dict = {
    # SOURCES MORTES (audit 2026-07-02) : scrapers bookmakers = 0 ligne, ces signaux
    # ne se déclenchent jamais (n=0, neutres). Conservés : ils se réactiveront seuls
    # si les sources revivent. Les équivalents PMU vivants sont ci-dessous.
    "steam_betclic":      lambda f: (f.get("steam_move_betclic") or 0) > 0.08,
    "gap_pmu_betfair":    lambda f: (f.get("gap_pmu_betfair") or 0) > 0.10,
    "spi_actif":          lambda f: (f.get("spi_score") or 0) > 0.15,
    # STEAM PMU (2026-07-02) : mouvement_30min = (début−fin)/début sur cotes_historique
    # PMU 45 min (peuplé à ~80%, positif = cote en BAISSE). Complète spi_actif (spi_score
    # null sur 76% des partants). ROI appris nightly par profil comme tout signal.
    "steam_pmu_30min":    lambda f: (f.get("mouvement_30min") or 0) > 0.08,
    # DRIFT OUT PMU (2026-07-02) : cote qui MONTE ≥5% — l'hypothèse « value contrarian »
    # du clv_monitor (seg_driftout). Forward marginal mesuré −6.6% (le cumul +3.9%
    # masquait la dégradation) → PAS de boost aveugle : signal APPRIS, le multiplicateur
    # par profil suivra son ROI réel et le coupera/boostera tout seul.
    "drift_out_30min":    lambda f: (f.get("mouvement_30min") or 0) < -0.05,
    "forme_excellente":   lambda f: (f.get("forme_5_courses") or 0.5) > 0.65,
    "forme_basse":        lambda f: (f.get("forme_5_courses") or 0.5) < 0.35,
    "en_progression":     lambda f: (f.get("forme_tendance") or 0) > 0.20,
    "en_regression":      lambda f: (f.get("forme_tendance") or 0) < -0.20,
    # Même source que le badge affiché (cf. narrative.py) : `class_drop_ratio_reel`
    # en priorité, repli sur la feature d'origine pour les lignes historiques.
    "descente_categorie": lambda f: (f.get("class_drop_ratio_reel") or f.get("class_drop_ratio") or 1.0) < 0.75,
    "montee_categorie":   lambda f: (f.get("class_drop_ratio_reel") or f.get("class_drop_ratio") or 1.0) > 1.40,
    # terrain_ideal : condition `running_style_terrain_fit > 0.6` RETIRÉE (2026-07-02) —
    # running_style jamais peuplé (0/50645 chevaux) → le AND rendait le signal
    # inerte à vie alors que pref_terrain_actuel vit (terrain_defavorable n=14k).
    "terrain_ideal":      lambda f: (f.get("pref_terrain_actuel") or 0.5) > 0.65,
    "terrain_defavorable": lambda f: (f.get("pref_terrain_actuel") or 0.5) < 0.35,
    "elo_superieur":      lambda f: (f.get("elo_vs_moyenne") or 0) > 50,
    "elo_inferieur":      lambda f: (f.get("elo_vs_moyenne") or 0) < -50,
    "duo_je_efficace":    lambda f: (f.get("asso_jockey_entraineur_nb") or 0) >= 5 and (f.get("asso_jockey_entraineur_taux") or 0) > 0.25,
    "premier_deferre":    lambda f: bool(f.get("premier_deferre")),
    "nouvelles_oeilleres": lambda f: bool(f.get("nouvelles_oeilleres")),
    "draw_favorable":     lambda f: (f.get("draw_bias_score") or 0) > 0.10,
    "sire_dist_fort":     lambda f: (f.get("sire_dist_winrate") or 0.5) > 0.55,
    "pace_conflict":      lambda f: (f.get("pace_conflict_score") or 0) > 0.6,
}

K_SHRINK = 40.0   # pseudo-paris (mise) shrinkant le ROI vers 0
SIG_M_MIN, SIG_M_MAX = 0.6, 1.6   # bornes du multiplicateur d'un signal


# ─────────────────────────────────────────────────────────────
# Un signal se juge par rapport aux AUTRES CHEVAUX, pas par rapport à zéro
# ─────────────────────────────────────────────────────────────
# Le multiplicateur valait `1 + roi`, où `roi` est le rendement d'une mise plate sur
# les chevaux qui portent le signal. Or le rendement d'une mise plate sur N'IMPORTE
# QUEL cheval vaut environ −15 % (le prélèvement PMU du simple gagnant) : TOUS les
# signaux sortent donc sous 1, et le produit de 4 à 6 d'entre eux s'écrase sur la
# borne basse.
#
# Constat du 2026-08-23 sur 242 chevaux de 20 courses : **207 (86 %) recevaient
# exactement 0,50**, la borne. Un multiplicateur constant ne trie plus rien — et
# l'explication affichée à l'utilisateur annonçait « signaux mitigés, mise réduite »
# sur presque chaque cheval, sans que la mise change puisque le facteur était commun.
#
# On mesure donc un signal RELATIVEMENT au rendement moyen de la population : un
# signal à −15 % dans un monde à −15 % est neutre, pas mauvais.
def _roi_reference(agg: dict) -> float:
    """Rendement moyen de la population qui sert de zéro aux multiplicateurs.

    Agrégé sur l'ensemble des observations de signaux : c'est exactement la même
    mise plate, sur le même échantillon, donc le bon point de comparaison.
    """
    stake = sum(a["stake"] for a in agg.values())
    payout = sum(a["payout"] for a in agg.values())
    return ((payout - stake) / stake) if stake > 0 else 0.0


def _multiplicateur_relatif(roi: float, roi_reference: float, n: int) -> float:
    """Avantage du signal sur la population, ramené vers 1 quand l'échantillon est
    mince, puis borné. Un signal exactement dans la moyenne rend 1.0."""
    base = 1.0 + roi_reference
    if base <= 0:
        return 1.0
    ratio = (1.0 + roi) / base
    shrink = n / (n + K_SHRINK)          # peu d'observations → on reste près de 1
    return float(max(SIG_M_MIN, min(SIG_M_MAX, 1.0 + (ratio - 1.0) * shrink)))


async def compute_signal_performance(session: AsyncSession) -> dict:
    # `stream()` + agrégation au fil de l'eau, et NON `fetchall()`.
    # Cette requête ne porte aucune borne temporelle : elle ramène la table
    # `features_ml` entière, soit 212 721 lignes portant chacune un JSONB de
    # 173 clés. Matérialisée en dicts Python, elle pesait ~4 Gio — sur un hôte
    # de 7,6 Gio partagés. C'est ici que le worker était en train de tourner
    # quand l'OOM killer l'a choisi le 20/08/2026, et non dans l'entraînement
    # (mesuré à 1,5 Gio de pic).
    #
    # La fonction n'est qu'un accumulateur de compteurs : elle n'a jamais eu
    # besoin de voir deux lignes en même temps. Résultat strictement identique.
    result = await session.stream(text("""
        SELECT fm.features, pa.cote_pmu,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE : ne garder que les features FIGÉES AVANT le départ.
          -- Tout backfill/recompute post-course bump computed_at à now() (> date_heure)
          -- → exclu. Sinon on apprend "ce qui rapporte" sur des features reconstruites
          -- a posteriori (fuite temporelle) qui pilotent ensuite les value bets en prod.
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
    """))

    agg = {name: {"n": 0, "wins": 0, "stake": 0.0, "payout": 0.0} for name in SIGNALS}
    n_total = 0
    async for partition in result.partitions(2000):
        for feats, cote, win in partition:
            n_total += 1
            f = feats if isinstance(feats, dict) else json.loads(feats)
            cote = float(cote)
            for name, pred in SIGNALS.items():
                try:
                    if pred(f):
                        a = agg[name]
                        a["n"] += 1
                        a["wins"] += int(win)
                        a["stake"] += 1.0
                        a["payout"] += cote if win else 0.0
                except Exception:
                    continue
        # Sans ce `del`, le curseur serveur n'apporte rien : on aurait seulement
        # déplacé l'accumulation du driver vers la liste de partitions.
        del partition

    roi_reference = _roi_reference(agg)
    signals = {}
    for name, a in agg.items():
        n = a["n"]
        if n == 0:
            signals[name] = {"n": 0, "win_rate": None, "roi": None, "roi_shrunk": 0.0,
                             "multiplier": 1.0}
            continue
        roi = (a["payout"] - a["stake"]) / a["stake"]
        # ROI shrinké : (payout - stake) / (stake + K) → tend vers 0 si n petit
        roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + K_SHRINK)
        mult = _multiplicateur_relatif(roi, roi_reference, n)
        signals[name] = {
            "n": n,
            "win_rate": round(a["wins"] / n, 3),
            "roi": round(roi, 3),
            "roi_shrunk": round(roi_shrunk, 3),
            "roi_reference": round(roi_reference, 3),
            "multiplier": round(mult, 3),
        }
    return {"signals": signals, "n_total": n_total, "roi_reference": round(roi_reference, 3)}


def _profile_pnl(profil: str, win: int, top3: int, cote: float) -> tuple[float, float]:
    """(mise, gain) d'un 1€ selon l'OBJECTIF du profil — c'est ce qui différencie
    quels signaux "rapportent" pour chaque profil :
      - conservateur : Simple Placé (réussite = top-3) ; rapport placé ≈ (cote-1)/4+1.
      - équilibré    : Simple Gagnant (réussite = victoire) ; toutes cotes.
      - agressif     : Simple Gagnant mais GROS GAINS → ne compte que cote ≥ 6
                        (les outsiders qui gagnent), 0 sinon (ne joue pas les favoris)."""
    if profil == "conservateur":
        rapport_place = max(1.1, (cote - 1) / 4.0 + 1.0)
        return 1.0, (rapport_place if top3 else 0.0)
    if profil == "agressif":
        if cote < 6.0:
            return 0.0, 0.0  # le profil agressif ne parie pas les courtes cotes
        return 1.0, (cote if win else 0.0)
    # équilibré
    return 1.0, (cote if win else 0.0)


async def compute_signal_performance_by_profile(session: AsyncSession) -> dict:
    """Comme compute_signal_performance mais PAR PROFIL (conservateur/équilibré/agressif),
    avec l'objectif propre à chaque profil → les multiplicateurs diffèrent par profil.
    → permet un pronostic adapté au profil sélectionné."""
    # Même table entière que `compute_signal_performance`, ramenée une SECONDE
    # fois dans la foulée : ces deux appels consécutifs du nightly faisaient à
    # eux seuls l'essentiel du pic mémoire du worker. Ici la version d'origine
    # était pire encore — elle construisait `parsed`, une TROISIÈME copie qui
    # cohabitait avec `rows` le temps de la boucle.
    result = await session.stream(text("""
        SELECT fm.features, pa.cote_pmu,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win,
               CASE WHEN pa.numero IN (
                    SELECT (e->>'numero')::int FROM jsonb_array_elements(r.classement)
                    WITH ORDINALITY a(e,o) WHERE o <= 3
               ) THEN 1 ELSE 0 END AS top3
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE (cf. compute_signal_performance) : features pré-départ only.
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
    """))

    profils = ["conservateur", "equilibre", "agressif"]
    agg = {p: {name: {"n": 0, "stake": 0.0, "payout": 0.0, "hits": 0} for name in SIGNALS} for p in profils}
    n_total = 0
    async for partition in result.partitions(2000):
        for feats, cote, win, top3 in partition:
            n_total += 1
            f = feats if isinstance(feats, dict) else json.loads(feats)
            cote, win, top3 = float(cote), int(win), int(top3)
            present = [name for name, pred in SIGNALS.items() if _safe(pred, f)]
            for p in profils:
                stake, payout = _profile_pnl(p, win, top3, cote)
                if stake <= 0:
                    continue
                success = top3 if p == "conservateur" else win
                for name in present:
                    a = agg[p][name]
                    a["n"] += 1
                    a["stake"] += stake
                    a["payout"] += payout
                    a["hits"] += success
        del partition

    out = {}
    references = {}
    for p in profils:
        sig = {}
        # Chaque profil a son propre zéro : le conservateur mise au placé, l'agressif
        # ne joue que les cotes ≥ 6 — leurs rendements moyens n'ont rien à voir.
        roi_reference = _roi_reference(agg[p])
        references[p] = round(roi_reference, 3)
        for name, a in agg[p].items():
            if a["stake"] <= 0:
                sig[name] = {"n": a["n"], "roi_shrunk": 0.0, "multiplier": 1.0, "hit_rate": None}
                continue
            roi = (a["payout"] - a["stake"]) / a["stake"]
            roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + K_SHRINK)
            sig[name] = {
                "n": a["n"],
                "hit_rate": round(a["hits"] / a["n"], 3) if a["n"] else None,
                "roi": round(roi, 3),
                "roi_shrunk": round(roi_shrunk, 3),
                "roi_reference": round(roi_reference, 3),
                "multiplier": round(_multiplicateur_relatif(roi, roi_reference, a["n"]), 3),
            }
        out[p] = sig
    return {"profils": out, "n_total": n_total, "roi_reference": references}


def _safe(pred, f) -> bool:
    try:
        return bool(pred(f))
    except Exception:
        return False


async def persist_signal_performance(session: AsyncSession, perf: dict) -> bool:
    """Persiste les multiplicateurs de signaux. False = état existant PRÉSERVÉ.

    Cold start : la garde anti-leakage (features figées avant départ) peut ne
    retenir aucune ligne. ``compute_signal_performance`` renvoie alors tous les
    signaux à multiplier=1.0 — une structure complète, donc indiscernable d'un
    apprentissage légitime une fois écrite. On refuse l'écriture sous le seuil.
    """
    if int(perf.get("n_total") or 0) < MIN_SIGNAL_PERF_OBS:
        log.warning(
            "signal_performance.skipped_insufficient_replayable_data",
            n_obs=int(perf.get("n_total") or 0), min_obs=MIN_SIGNAL_PERF_OBS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS signal_performance (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT signal_perf_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO signal_performance (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_signal_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM signal_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


# ── Apprentissage par BANDE D'EV ─────────────────────────────────────────────
# ev = cote_figée × proba_modèle − 1 (excédent d'EV ; 0 = break-even). On mesure le
# ROI RÉEL d'un 1€ Simple Gagnant flat par bande → la sélection des value bets
# rétrograde les bandes perdantes et promeut les gagnantes, au lieu d'un couperet
# dur. Borné par bande [début, fin). Recalculé nightly. Aucune valeur inventée.
EV_BANDS: list[tuple[float, float]] = [
    (-1.0, 0.00),   # EV négatif (sur-coté côté marché)
    (0.00, 0.10),   # léger edge
    (0.10, 0.20),
    (0.20, 0.35),
    (0.35, 0.60),
    (0.60, 99.0),   # gros edge claironné = souvent sur-confiance longshot
]
EV_K_SHRINK = 60.0   # pseudo-mises shrinkant le ROI d'une bande vers 0


def _ev_band_key(ev: float) -> str:
    for lo, hi in EV_BANDS:
        if lo <= ev < hi:
            return f"{lo:.2f}_{hi:.2f}"
    return f"{EV_BANDS[-1][0]:.2f}_{EV_BANDS[-1][1]:.2f}"


async def compute_ev_band_performance(session: AsyncSession) -> dict:
    """ROI réel par bande d'EV, depuis les pronostics FIGÉS avant départ ⋈ résultats.
    ev = cote_figee × proba_top1 − 1. Flat 1€ Simple Gagnant à la cote figée."""
    rows = (await session.execute(text("""
        SELECT p.cote_figee, p.proba_top1,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM prediction_evaluation p
        JOIN participations pa ON pa.participation_id = p.participation_id
        JOIN courses c ON c.course_id = p.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = p.course_id
        WHERE p.cote_figee IS NOT NULL AND p.cote_figee > 1
          AND p.proba_top1 IS NOT NULL AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE : prono FIGÉ avant le départ uniquement (cf. signal learner).
          AND c.date_heure IS NOT NULL AND p.created_at < c.date_heure
          AND p.is_replayable = true
    """))).fetchall()

    agg = {f"{lo:.2f}_{hi:.2f}": {"n": 0, "wins": 0, "stake": 0.0, "payout": 0.0}
           for lo, hi in EV_BANDS}
    for cote, proba, win in rows:
        cote = float(cote); proba = float(proba)
        ev = cote * proba - 1.0
        a = agg[_ev_band_key(ev)]
        a["n"] += 1
        a["wins"] += int(win)
        a["stake"] += 1.0
        a["payout"] += cote if win else 0.0

    # Même correction que pour les signaux : une bande d'EV se juge par rapport aux
    # AUTRES bandes, pas par rapport à zéro. Le ROI d'une mise plate sur n'importe
    # quel partant vaut ~−20 % (prélèvement PMU), donc `1 + roi` mettait TOUTES les
    # bandes sous 1 — mesuré le 2026-08-23 en prod : 0,667 à 0,808, aucune au-dessus.
    # Or ce multiplicateur alimente un GATE DUR dans mise_calculator
    # (`if evb(c) <= 0.80: return False`) : avec toutes les bandes sous 0,81, ce gate
    # rejetait tout candidat spéculatif quelle que soit sa bande. Une interdiction
    # generale deguisee en apprentissage.
    roi_reference = _roi_reference(agg)
    bands = {}
    for key, a in agg.items():
        n = a["n"]
        if n == 0:
            bands[key] = {"n": 0, "win_rate": None, "roi": None, "roi_shrunk": 0.0,
                          "multiplier": 1.0}
            continue
        roi = (a["payout"] - a["stake"]) / a["stake"]
        roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + EV_K_SHRINK)
        reliable = n >= MIN_EV_BAND_OBS
        mult = _multiplicateur_relatif(roi, roi_reference, n) if reliable else 1.0
        bands[key] = {
            "n": n,
            "win_rate": round(a["wins"] / n, 3),
            "roi": round(roi, 3),
            "roi_shrunk": round(roi_shrunk, 3),
            "roi_reference": round(roi_reference, 3),
            "multiplier": round(mult, 3),
            "reliable": reliable,
        }
    return {"bands": bands, "n_total": len(rows), "roi_reference": round(roi_reference, 3)}


async def persist_ev_band_performance(session: AsyncSession, perf: dict) -> bool:
    if int(perf.get("n_total") or 0) < MIN_EV_BAND_REPLAYABLE_OBS:
        log.warning(
            "ev_band_performance.skipped_insufficient_replayable_data",
            n_obs=int(perf.get("n_total") or 0),
            min_obs=MIN_EV_BAND_REPLAYABLE_OBS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS ev_band_performance (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ev_band_perf_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO ev_band_performance (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_ev_band_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM ev_band_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def ev_band_multiplier(ev: float, perf: dict | None) -> float:
    """Multiplicateur de conviction pour la bande d'EV de ce pari, appris du ROI réel.
    1.0 si pas de table / bande inconnue / échantillon nul → neutre."""
    if not perf:
        return 1.0
    bands = perf.get("bands") or {}
    band = bands.get(_ev_band_key(ev))
    if not band or not band.get("n"):
        return 1.0
    return float(band.get("multiplier", 1.0))


# ── Calibration RAPPORT estimé → RÉEL par (profil × type) ─────────────────────
# PROBLÈME RÉSOLU : le moteur estime le rapport d'un pari (TRJ / proba_marché) AVANT la
# course, mais le rapport PMU RÉELLEMENT payé diffère — un Simple Placé sur favori court
# est estimé ~×1.9 (passe la bande prudent ×1.8) mais paie ~×1.3 en réalité → la bande
# affichée dans le BILAN est violée. On apprend, depuis les pronos FIGÉS réglés
# (profil_run_log), le facteur médian rapport_RÉEL / rapport_ESTIMÉ parmi les paris
# GAGNANTS, PAR (profil × type). Le gate de bande s'applique alors au rapport ATTENDU
# (estimé × facteur) : un type qui paie systématiquement sous la bande de son profil est
# ÉCARTÉ — c'est l'apprentissage qui empêche la violation des tranches sur le réel.
# Aucune valeur inventée : facteur 1.0 (neutre) tant que < RC_MIN_WINS gagnants.
RC_K_SHRINK = 12.0          # pseudo-gagnants shrinkant le facteur vers 1.0 (anti petit n)
RC_MIN_WINS = 8             # nb de gagnants min (avec estimé connu) avant d'appliquer un facteur
RC_F_MIN, RC_F_MAX = 0.40, 1.30   # bornes du facteur (correction prudente)

# ── Calibration des PROBABILITÉS de pari (mesurée le 2026-08-19) ────────────
# Le modèle annonce systématiquement plus souvent qu'il ne réalise, et l'écart
# grandit avec le nombre de chevaux à trouver : Simple Gagnant ×1,22 (10,9 %
# annoncés, 8,9 % réels), Simple Placé ×1,23, Couplé Gagnant ×1,34, Couplé Placé
# ×1,46, Trio ×2,26 — sur 19 968 paris réglés. L'EV en hérite : EV = p × rapport
# − 1, donc une proba gonflée de 22 % transforme un vrai −10 % en un +10 % affiché.
# C'est la cause première du ROI négatif, et la raison pour laquelle les bandes
# d'EV ne classaient rien (toutes entre −8 % et −9 % de ROI réel).
PC_MIN_PARIS = 200          # paris réglés minimum sur le type avant de corriger
PC_K_SHRINK = 150.0         # pseudo-observations shrinkant le facteur vers 1.0
# On ne corrige QUE vers le bas au-delà de 1.0 : gonfler une probabilité déjà
# optimiste fabriquerait de faux value bets. Plancher à 0.5 (une proba divisée
# par deux est déjà une correction massive).
PC_F_MIN, PC_F_MAX = 0.50, 1.05


def _bet_key(type_pari, chevaux) -> tuple:
    """Clé d'un pari = (type, numéros triés) pour matcher plan figé ⋈ bilan réglé."""
    nums = tuple(sorted(int(h["numero"]) for h in (chevaux or [])
                        if h.get("numero") is not None))
    return (type_pari, nums)


async def compute_rapport_calibration(session: AsyncSession) -> dict:
    """Facteur rapport_réel / rapport_estimé par (profil × type), depuis profil_run_log
    réglé (figé AVANT départ). Lecture seule. Mêmes gardes anti-leakage que
    compute_profil_weights (flag oos_weights → pronos pré-départ non backfillés)."""
    try:
        from ml.algo_flags import FLAGS as _AF
        oos = bool(getattr(_AF, "oos_weights", False))
    except Exception:
        oos = False
    guard = ("AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure "
             "AND COALESCE(r.meta->>'backfill','') <> 'true'") if oos else ""
    rows = (await session.execute(text(f"""
        SELECT r.profil, r.plan, r.resultat
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL AND r.plan IS NOT NULL
          {guard}
    """))).all()

    # agg[profil][type] = {n_win, sum_est, sum_real, n, mise, gain}
    agg: dict = {}
    for profil, plan, resultat in rows:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan)
        res = resultat if isinstance(resultat, dict) else json.loads(resultat)
        # rapport ESTIMÉ par pari, reconstruit depuis le plan figé (gain_potentiel/mise)
        est: dict = {}
        proba_annoncee: dict = {}
        for niv in plan_d.get("niveaux", []):
            for p in niv.get("paris", []):
                mise = float(p.get("mise") or 0)
                cle = _bet_key(p.get("type"), p.get("chevaux"))
                if mise > 0:
                    est[cle] = float(p.get("gain_potentiel") or 0) / mise
                pr = p.get("probabilite")
                if isinstance(pr, (int, float)) and 0.0 < float(pr) <= 1.0:
                    proba_annoncee[cle] = float(pr)
        pa = agg.setdefault(profil, {})
        for p in res.get("paris", []):
            if p.get("statut") == "rembourse":
                continue                          # NP : neutre, jamais compté
            t = p.get("type")
            if not t:
                continue
            ta = pa.setdefault(t, {"n_win": 0, "sum_est": 0.0, "sum_real": 0.0,
                                   "n": 0, "mise": 0.0, "gain": 0.0,
                                   "n_proba": 0, "sum_proba": 0.0, "n_gagne_proba": 0})
            ta["n"] += 1
            ta["mise"] += float(p.get("mise") or 0)
            pr = proba_annoncee.get(_bet_key(t, p.get("chevaux")))
            if pr is not None:
                ta["n_proba"] += 1
                ta["sum_proba"] += pr
                if p.get("statut") == "gagne":
                    ta["n_gagne_proba"] += 1
            if p.get("statut") == "gagne" and p.get("rapport_reel"):
                re_ = est.get(_bet_key(t, p.get("chevaux")))
                ta["gain"] += float(p.get("gain") or 0)
                if re_ and re_ > 0:               # estimé connu → couple (estimé, réel)
                    ta["n_win"] += 1
                    ta["sum_est"] += re_
                    ta["sum_real"] += float(p["rapport_reel"])

    def _factor(a: dict) -> float:
        if a["n_win"] >= RC_MIN_WINS and a["sum_est"] > 0:
            raw = a["sum_real"] / a["sum_est"]
            w = a["n_win"] / (a["n_win"] + RC_K_SHRINK)       # shrink vers 1.0
            return float(max(RC_F_MIN, min(RC_F_MAX, 1.0 + (raw - 1.0) * w)))
        return 1.0                                            # échantillon insuffisant → neutre

    def _proba_factor(a: dict) -> float:
        """Fréquence RÉELLE / probabilité ANNONCÉE, shrinkée et bornée."""
        n = a.get("n_proba", 0)
        somme = a.get("sum_proba", 0.0)
        if n < PC_MIN_PARIS or somme <= 0:
            return 1.0                                        # jamais de correction à l'aveugle
        annoncee = somme / n
        reelle = a.get("n_gagne_proba", 0) / n
        if annoncee <= 0:
            return 1.0
        brut = reelle / annoncee
        w = n / (n + PC_K_SHRINK)                             # shrink vers 1.0 (anti petit n)
        return float(max(PC_F_MIN, min(PC_F_MAX, 1.0 + (brut - 1.0) * w)))

    def _entry(a: dict) -> dict:
        return {
            "factor": round(_factor(a), 3),
            "proba_factor": round(_proba_factor(a), 3),
            "n_proba": a.get("n_proba", 0),
            "proba_annoncee": (round(a["sum_proba"] / a["n_proba"], 4)
                               if a.get("n_proba") else None),
            "proba_reelle": (round(a["n_gagne_proba"] / a["n_proba"], 4)
                             if a.get("n_proba") else None),
            "n_win": a["n_win"], "n": a["n"],
            "real_mean": round(a["sum_real"] / a["n_win"], 2) if a["n_win"] else None,
            "est_mean": round(a["sum_est"] / a["n_win"], 2) if a["n_win"] else None,
            "roi": round((a["gain"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None,
        }

    # POOL GLOBAL PAR TYPE (tous profils confondus) — fallback quand le couple
    # (profil × type) n'a pas assez de gagnants. Cas mesuré (audit 2026-07-02) :
    # Couplé Ordre estimé ×40 payé ×11 mais 5 gagnants en risqué (< RC_MIN_WINS)
    # → facteur neutre à vie PAR profil alors que le pool tous-profils (21 gagnants)
    # prouve la surestimation. Le rapport parimutuel ne dépend pas du profil.
    out = {"profils": {}, "global": {}, "n_runs": len(rows)}
    glob: dict = {}
    for profil, types in agg.items():
        po = {}
        for t, a in types.items():
            po[t] = _entry(a)
            g = glob.setdefault(t, {"n_win": 0, "sum_est": 0.0, "sum_real": 0.0,
                                    "n": 0, "mise": 0.0, "gain": 0.0,
                                    "n_proba": 0, "sum_proba": 0.0, "n_gagne_proba": 0})
            for k in g:
                g[k] += a[k]
        out["profils"][profil] = po
    for t, a in glob.items():
        out["global"][t] = _entry(a)
    return out


# ── Ne JAMAIS effacer une table annexe qu'on ne recalcule pas ────────────────────
# La ligne `rapport_calibration` porte plusieurs apprentissages FUSIONNÉS (choix
# assumé de l'appelant nightly : la table est déjà chargée et transmise partout où
# un plan se construit) — la calibration estimé→réel, ET le ROI par TRANCHE DE
# RAPPORT (`payout_buckets`), que `mise_calculator.conviction()` décrit comme « de
# loin le facteur le mieux étayé ».
#
# Deux chemins écrivent ici. Le nightly calcule les deux et écrit le tout. Le chemin
# POST-COURSE (pipeline, après CHAQUE arrivée) ne recalcule que la calibration et
# écrasait donc `payout_buckets` quelques minutes après le nightly. Constat du
# 2026-08-23 : la clé était tout simplement ABSENTE de la table en prod, donc
# `payout_bucket_multiplier` renvoyait 1.0 sur chaque candidat — le tilt n'a JAMAIS
# agi, sans un seul signal d'erreur.
CLES_ANNEXES_PRESERVEES = ("payout_buckets",)


def fusionner_cles_preservees(perf: dict, ancien: dict | None) -> dict:
    """Reporte les clés annexes que l'écrivain courant n'apporte pas.

    Un appelant qui RECALCULE la clé la remplace normalement : le report ne fige
    jamais une valeur périmée, il empêche seulement de l'effacer.
    """
    out = dict(perf or {})
    for cle in CLES_ANNEXES_PRESERVEES:
        if cle not in out and cle in (ancien or {}):
            out[cle] = ancien[cle]
    return out


async def persist_rapport_calibration(session: AsyncSession, perf: dict) -> bool:
    """Persiste la calibration estimé→réel des rapports. False = état PRÉSERVÉ.

    Source : ``profil_run_log`` réglé, filtré par les gardes anti-leakage. Si ce
    filtre ne laisse plus rien (règlement en retard, backfills exclus), les
    facteurs retombent tous à 1.0 et le gate de bande cesserait d'écarter les
    types qui paient sous la tranche de leur profil.
    """
    if int(perf.get("n_runs") or 0) < MIN_RAPPORT_CALIB_RUNS:
        log.warning(
            "rapport_calibration.skipped_insufficient_replayable_data",
            n_runs=int(perf.get("n_runs") or 0), min_runs=MIN_RAPPORT_CALIB_RUNS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS rapport_calibration (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT rapport_calib_singleton CHECK (id = 1)
        )
    """))
    if any(k not in perf for k in CLES_ANNEXES_PRESERVEES):
        ancien = (await session.execute(text(
            "SELECT data FROM rapport_calibration WHERE id=1"))).first()
        ancien_d = (ancien[0] if ancien else None) or {}
        if isinstance(ancien_d, str):
            ancien_d = json.loads(ancien_d)
        perf = fusionner_cles_preservees(perf, ancien_d)
    await session.execute(text("""
        INSERT INTO rapport_calibration (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_rapport_calibration(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text(
            "SELECT data FROM rapport_calibration WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def rapport_realization_factor(profil: str | None, type_pari: str | None,
                               calib: dict | None) -> float:
    """Facteur estimé→réel pour ce (profil × type). Fallback sur le POOL GLOBAL du
    type (tous profils) quand le couple (profil × type) n'a pas de facteur appris —
    le rapport parimutuel réel ne dépend pas du profil qui joue. 1.0 (neutre) si pas
    de table / type inconnu / échantillon insuffisant → aucun effet (cold-start sûr)."""
    if not calib or not profil or not type_pari:
        return 1.0
    t = (calib.get("profils") or {}).get(profil, {}).get(type_pari)
    f = float((t or {}).get("factor", 1.0) or 1.0)
    if f != 1.0:
        return f
    g = (calib.get("global") or {}).get(type_pari)
    return float((g or {}).get("factor", 1.0) or 1.0)



# ─────────────────────────────────────────────────────────────────────────────
# ROI RÉEL PAR TRANCHE DE RAPPORT (mesuré le 2026-08-19 sur 19 972 paris réglés)
# ─────────────────────────────────────────────────────────────────────────────
# Le biais favori/outsider, dans NOS propres chiffres :
#
#   Simple Gagnant  ×4-8   -1,7 %   (1 458 paris, 10 324 €)
#   Simple Gagnant  ×8-15  -8,2 %   (2 336 paris)
#   Simple Gagnant  ≥×15  -15,4 %   (2 436 paris)
#   Simple Placé    <×2    -6,2 %
#   Simple Placé    ×2-4   -7,5 %
#   Simple Placé    ×4-8  -25,0 %
#
# Monotone dans les deux types, sur de gros échantillons, et sans dépendre d'un
# gros gain isolé : c'est le signal le plus solide dont nous disposions. La bande
# d'EV, elle, ne trie RIEN (toutes les bandes entre -8 % et -13 % de ROI réel),
# parce que sélectionner sur l'edge estimé revient à sélectionner sur l'erreur
# d'estimation.
#
# On en fait un TILT, pas une barrière : le contrat produit (tranche de rapport
# par profil, un plan sur chaque course) reste intact, seule la préférence entre
# candidats d'une même course bouge.
# La grille est fine AU-DESSUS de ×15 parce que c'est là que vit le profil
# risqué (bande ×10 → ∞) et que l'écart y est le plus violent : ×15-30 rend
# -14,6 %, ×30-60 -21,5 %, ≥×60 -64,7 %. Une tranche ≥×15 unique donnait le même
# multiplicateur à un ×20 et à un ×200 — le tilt ne pouvait pas trier là où le
# profil risqué joue justement tous ses paris.
PB_BUCKETS = ((0.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 15.0),
              (15.0, 30.0), (30.0, 60.0), (60.0, 1e9))
PB_MIN_PARIS = 150          # sous ce volume, le ROI d'une tranche est du bruit
# L'incertitude n'est PAS symétrique, et c'est le point clé.
#
# Affirmer qu'une tranche est BONNE repose sur des gains rares et gros : la preuve
# tient donc au nombre de GAGNANTS. Couplé Gagnant ×15-30 affichait +10,9 % sur
# 836 paris mais ~33 gagnants — retirer ses 20 meilleurs gains le ramène à -38,8 %.
#
# Affirmer qu'une tranche est MAUVAISE ne demande pas de gagnants : 1 849 paris
# qui rendent -66 % établissent la perte, quel que soit le nombre de gains. Le
# doute ne porte que sur la queue haute, jamais sur le fait que l'argent n'est
# pas revenu.
#
# On shrinke donc le HAUT sur les gagnants et le BAS sur les paris. Une première
# version, shrinkée uniformément sur les gagnants, ramenait Trio ≥×60 (-62,9 %) à
# un tilt de 0,952 : la pire tranche mesurée devenait presque neutre.
PB_K_SHRINK_GAGNANTS = 60.0   # pseudo-gagnants — pour FAVORISER une tranche
PB_K_SHRINK_PARIS = 200.0     # pseudo-paris — pour PÉNALISER une tranche
PB_M_MIN, PB_M_MAX = 0.60, 1.40
# WINSORISATION — sans elle, un unique gain aberrant commande la tranche entière.
# Vécu au premier calcul : le Trio ≥×15 affichait +106 % de ROI et décrochait le
# tilt MAXIMAL (1,40) grâce à UN rapport à 4 526 € ; retirer ce seul pari fait
# tomber la tranche à −21 %. Le système aurait donc été poussé vers le billet de
# loterie par un coup de chance. On plafonne chaque gain à 50× la mise (même
# convention que le ROI winsorisé des poids de profil).
PB_GAIN_CAP = 50.0
# Un multiplicateur SUPÉRIEUR à 1 pousse à jouer davantage cette tranche : on ne
# l'accorde qu'avec assez de gagnants pour que le ROI ne soit pas l'histoire de
# quelques coups. En dessous, la tranche peut être pénalisée (le manque de
# gagnants est en soi une information) mais jamais favorisée.
#
# Seuil relevé à 150 après vérification : Couplé Gagnant ×15-30 affichait +10,9 %
# sur 836 paris — mais retirer ses 20 meilleurs gains le ramène à -38,8 %. Une
# cellule à faible taux de réussite ne prouve RIEN de positif à cette échelle ;
# seules les cellules à forte fréquence (Simple Placé ~37 %, Simple Gagnant ~16 %)
# accumulent assez de gagnants pour qu'un ROI proche de zéro soit crédible.
PB_MIN_WINS_POUR_FAVORISER = 150


def _pb_key(rapport: float) -> str:
    for lo, hi in PB_BUCKETS:
        if lo <= rapport < hi:
            return f"{lo:g}_{hi:g}"
    return f"{PB_BUCKETS[-1][0]:g}_{PB_BUCKETS[-1][1]:g}"


async def compute_payout_bucket_performance(session: AsyncSession) -> dict:
    """ROI réel par (type de pari × tranche de rapport), depuis `profil_run_log`.

    Le rapport retenu est celui ESTIMÉ au moment du conseil (gain_potentiel/mise),
    pas le rapport réel : c'est la seule valeur connue à l'instant de la décision,
    donc la seule sur laquelle on puisse arbitrer sans tricher.
    """
    rows = (await session.execute(text("""
        SELECT r.plan, r.resultat
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL AND r.plan IS NOT NULL
          AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure
    """))).all()

    agg: dict = {}
    for plan, resultat in rows:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan)
        res = resultat if isinstance(resultat, dict) else json.loads(resultat)
        rapport_par_pari: dict = {}
        for niv in plan_d.get("niveaux", []):
            for pb in niv.get("paris", []):
                mise = float(pb.get("mise") or 0)
                if mise > 0:
                    rapport_par_pari[_bet_key(pb.get("type"), pb.get("chevaux"))] = \
                        float(pb.get("gain_potentiel") or 0) / mise
        for pari in res.get("paris", []):
            if pari.get("statut") == "rembourse":
                continue
            t = pari.get("type")
            rapport = rapport_par_pari.get(_bet_key(t, pari.get("chevaux")))
            if not t or not rapport or rapport <= 0:
                continue
            cle = (t, _pb_key(rapport))
            a = agg.setdefault(cle, {"n": 0, "mise": 0.0, "gain": 0.0, "n_wins": 0})
            mise = float(pari.get("mise") or 0)
            gain = float(pari.get("gain") or 0)
            a["n"] += 1
            a["mise"] += mise
            # Gain plafonné : une tranche ne doit pas être jugée sur un coup isolé.
            a["gain"] += min(gain, PB_GAIN_CAP * mise) if mise > 0 else gain
            if gain > 0:
                a["n_wins"] += 1

    out: dict = {"types": {}, "n_runs": len(rows)}
    for (t, bucket), a in agg.items():
        roi = ((a["gain"] - a["mise"]) / a["mise"]) if a["mise"] > 0 else None
        if a["n"] >= PB_MIN_PARIS and roi is not None:
            # ROI de -30 % → 0.70, ROI de 0 % → 1.0, borné puis shrinké.
            brut = 1.0 + roi
            if brut >= 1.0:
                w = a["n_wins"] / (a["n_wins"] + PB_K_SHRINK_GAGNANTS)
            else:
                w = a["n"] / (a["n"] + PB_K_SHRINK_PARIS)
            mult = max(PB_M_MIN, min(PB_M_MAX, 1.0 + (brut - 1.0) * w))
            if mult > 1.0 and a["n_wins"] < PB_MIN_WINS_POUR_FAVORISER:
                mult = 1.0                   # trop peu de gagnants pour encourager
        else:
            mult = 1.0                       # échantillon insuffisant → neutre
        out["types"].setdefault(t, {})[bucket] = {
            "multiplier": round(mult, 3),
            "n": a["n"],
            "n_wins": a["n_wins"],
            "roi_winsorise": round(roi * 100, 1) if roi is not None else None,
        }
    return out


async def persist_payout_bucket_performance(session: AsyncSession, perf: dict) -> bool:
    """Persiste la table. False = état PRÉSERVÉ (échantillon trop mince)."""
    if int(perf.get("n_runs") or 0) < MIN_RAPPORT_CALIB_RUNS:
        log.warning("payout_bucket.skipped_insufficient_data",
                    n_runs=int(perf.get("n_runs") or 0))
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS payout_bucket_performance (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT payout_bucket_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO payout_bucket_performance (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_payout_bucket_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text(
            "SELECT data FROM payout_bucket_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def payout_bucket_multiplier(type_pari: str | None, rapport: float | None,
                             perf: dict | None) -> float:
    """Tilt de conviction selon le ROI historique de cette tranche de rapport.
    1.0 (neutre) sans table, type inconnu ou échantillon insuffisant."""
    if not perf or not type_pari or not rapport or rapport <= 0:
        return 1.0
    # La table voyage fusionnee dans `rapport_calibration` (deja charge et passe
    # partout ou un plan se construit) : la router par un nouveau parametre aurait
    # demande de modifier cinq appelants, dont un oubli aurait suffi a desactiver
    # le tilt sans que rien ne le signale.
    tables = perf.get("payout_buckets") or perf.get("types") or {}
    t = tables.get(type_pari)
    if not t:
        return 1.0
    e = t.get(_pb_key(float(rapport)))
    return float((e or {}).get("multiplier", 1.0) or 1.0)


def proba_realization_factor(type_pari: str | None, calib: dict | None) -> float:
    """Facteur annoncé→réel de la PROBABILITÉ d'un type de pari.

    Lu sur le POOL GLOBAL uniquement : la fréquence à laquelle un Couplé tombe ne
    dépend pas du profil qui le joue, et découper par profil diviserait
    l'échantillon sans rien apprendre de plus. 1.0 (neutre) si la table manque ou
    si l'échantillon est trop mince — jamais de correction inventée.
    """
    if not calib or not type_pari:
        return 1.0
    g = (calib.get("global") or {}).get(type_pari)
    return float((g or {}).get("proba_factor", 1.0) or 1.0)


def signal_multiplier(features: dict, perf: dict | None, profil: str | None = None) -> float:
    """Multiplicateur de conviction d'un partant = produit (borné) des multiplicateurs
    des signaux qu'il porte, appris du ROI réel. PROFILE-AWARE : si `profil` fourni et
    une table par profil existe, on utilise le ROI appris POUR CE PROFIL (un même
    signal peut aider à se placer mais pas à gagner). Fallback table globale. 1.0 sinon."""
    if not perf:
        return 1.0
    sigs = None
    if profil and perf.get("profils", {}).get(profil):
        sigs = perf["profils"][profil]
    elif perf.get("signals"):
        sigs = perf["signals"]
    if not sigs:
        return 1.0
    # MOYENNE GÉOMÉTRIQUE, pas produit. Le produit fait payer au cheval le NOMBRE de
    # signaux qu'il porte : six facteurs à 0,9 donnent 0,53 alors que chaque signal pris
    # séparément ne dit « −10 % » qu'une fois. Combiné à des multiplicateurs tous < 1
    # (cf. _multiplicateur_relatif), 86 % des chevaux tombaient sur la borne basse le
    # 2026-08-23 — le tilt ne triait plus rien. La moyenne géométrique garde le sens
    # (un signal neutre ne change rien, deux mauvais pèsent plus qu'un) sans que porter
    # beaucoup de signaux soit en soi une faute.
    mults = []
    for name, pred in SIGNALS.items():
        try:
            if pred(features) and name in sigs:
                m = float(sigs[name].get("multiplier", 1.0) or 1.0)
                if m > 0:
                    mults.append(m)
        except Exception:
            continue
    if not mults:
        return 1.0
    moyenne = math.exp(sum(math.log(m) for m in mults) / len(mults))
    return float(max(0.5, min(2.0, moyenne)))
