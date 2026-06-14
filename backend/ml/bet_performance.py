"""
bet_performance.py — Auto-amélioration de la sélection par le ROI RÉEL observé.

Lit les paris ENREGISTRÉS et RÉGLÉS (bankroll_entries : resultat gagne/perd,
gain_perte net réel issu des vrais rapports PMU) et calcule, par TYPE de pari,
le ROI net réellement réalisé. On en déduit un multiplicateur de conviction
borné, appliqué à la sélection future : on pondère vers les types qui ont
VRAIMENT rapporté, on réduit ceux qui perdent.

Intégrité : 100% données réelles. Un type sans historique suffisant reçoit un
poids NEUTRE (1.0) — aucune invention. Shrinkage vers 1.0 quand l'échantillon
est faible (peu de paris = peu de signal).
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# En-deçà de MIN_SAMPLE paris réglés, le ROI d'un type est fortement ramené vers
# le neutre (peu de signal). Bornes du multiplicateur de conviction.
MIN_SAMPLE = 12
WEIGHT_LO, WEIGHT_HI = 0.5, 1.6

_CACHE_KEY = "bet_roi_weights:v1"
_CACHE_TTL = 3600  # 1h — recalcul à la volée sur données réelles à jour


async def compute_type_roi_weights(session: AsyncSession, only_ia: bool = True) -> dict[str, float]:
    """ROI net réel par type_pari → multiplicateur de conviction borné.

    only_ia : ne compter que les paris issus des plans IA (suivi_reco_ia) — c'est
    le track-record du système sur ses propres recommandations.
    """
    where_ia = "AND suivi_reco_ia = true" if only_ia else ""
    rows = (await session.execute(text(f"""
        SELECT type_pari,
               COUNT(*)                       AS n,
               COALESCE(SUM(mise), 0)         AS somme_mise,
               COALESCE(SUM(gain_perte), 0)   AS somme_net
        FROM bankroll_entries
        WHERE resultat IN ('gagne', 'perd')
          AND gain_perte IS NOT NULL
          AND mise > 0
          {where_ia}
        GROUP BY type_pari
    """))).fetchall()

    weights: dict[str, float] = {}
    for type_pari, n, somme_mise, somme_net in rows:
        n = int(n or 0)
        somme_mise = float(somme_mise or 0.0)
        somme_net = float(somme_net or 0.0)
        if n <= 0 or somme_mise <= 0:
            continue
        roi = somme_net / somme_mise            # gain_perte = net → ROI net réel
        shrink = n / (n + MIN_SAMPLE)           # 0 (peu de data) → 1 (beaucoup)
        eff_roi = roi * shrink
        w = max(WEIGHT_LO, min(WEIGHT_HI, 1.0 + eff_roi))
        weights[type_pari] = round(w, 3)

    if weights:
        log.info("bet_performance.roi_weights", weights=weights)
    return weights


async def get_learned_type_weights(session: AsyncSession,
                                   profil: str | None = None,
                                   discipline: str | None = None,
                                   nb_partants: int | None = None) -> dict[str, float]:
    """Poids de conviction APPRIS par type — c'est le cœur de l'auto-amélioration.

    Source PRIORITAIRE (si `profil` fourni et historique suffisant) : ROI réel des
    PRONOS ÉMIS par CE profil (profil_run_log : plans figés avant course, réglés aux
    vrais rapports PMU). C'est l'apprentissage sur les recommandations réellement
    faites — pas sur le top-3 du modèle ni un rejeu.

    Si `discipline`/`nb_partants` sont fournis, les poids sont RAFFINÉS par contexte
    (discipline × bande de peloton) via effective_type_weights — quand ce bucket a
    suffisamment appris ; sinon on garde le poids type global (zéro effet sinon).

    Source suivante : ROI RÉEL winsorisé par type mesuré sur l'historique réglé
    (backtest profils, cache `stats:profils`, recalculé à chaque fin de course et la
    nuit) → un type qui perd (Simple Gagnant) descend, un type qui rapporte (placé à
    valeur) monte. L'algo « apprend le pourquoi » et adapte les futurs paris.

    Repli : si le cache n'est pas encore peuplé, on utilise le ROI des paris
    utilisateur réglés (bankroll). Jamais d'invention : défaut neutre 1.0 par type.
    """
    # 1. Pronos émis par profil (le plus fidèle à ce que l'utilisateur a vu).
    if profil:
        try:
            from ml.profil_learning import (
                load_profil_weights, effective_type_weights, MIN_RUNS_FOR_WEIGHTS,
            )
            state = await load_profil_weights(session)
            if state:
                pdata = (state.get("profils") or {}).get(profil) or {}
                if (pdata.get("n_runs") or 0) >= MIN_RUNS_FOR_WEIGHTS and pdata.get("type_weights"):
                    # raffinage contextuel (additif : retombe sur le global si bucket vide)
                    return effective_type_weights(pdata, discipline, nb_partants)
        except Exception:
            pass

    learned: dict = {}
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get("stats:profils")
        if cached:
            data = json.loads(cached)
            learned = data.get("type_weights") or {}
    except Exception:
        learned = {}

    if learned:
        return learned
    # Repli : ROI réel des paris joués (échantillon souvent faible) → neutre sinon.
    return await get_type_roi_weights(session)


async def get_type_roi_weights(session: AsyncSession) -> dict[str, float]:
    """Poids ROI par type avec cache Redis (best-effort). Renvoie {} si rien."""
    redis = None
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        redis = None

    weights = await compute_type_roi_weights(session)

    try:
        if redis is not None:
            await redis.set(_CACHE_KEY, json.dumps(weights), ex=_CACHE_TTL)
    except Exception:
        pass
    return weights


# ─────────────────────────────────────────────────────────────
# Thermostat adaptatif "heat" ∈ [-1, +1]
#   Relie APPRENTISSAGE (calibration du modèle, race_learning_log.brier_score) et
#   RÉSULTATS (ROI net récent des paris IA réglés). Sert à durcir/assouplir TOUS
#   les profils de mise : froid (modèle mal calibré OU série perdante) → prudence ;
#   chaud (bien calibré + gagnant) → audace mesurée. 100% données réelles.
# ─────────────────────────────────────────────────────────────
_HEAT_CACHE_KEY = "bet_heat:v1"
_HEAT_TTL = 1800           # 30 min
_RECENT_RACES = 60         # fenêtre brier
_RECENT_BETS = 80          # fenêtre ROI récent
_BRIER_GOOD = 0.16         # brier ≤ → modèle bien calibré
_BRIER_BAD = 0.26          # brier ≥ → mal calibré
_MIN_BETS_FOR_ROI = 15     # en-deçà, le terme ROI est ignoré (pas assez de signal)


async def compute_model_heat(session: AsyncSession) -> dict:
    """Calcule le thermostat adaptatif depuis les données RÉELLES.

    heat = 0.5 × terme_calibration + 0.5 × terme_roi_récent, borné [-1, +1].
      - terme_calibration : brier moyen des dernières courses apprises (mappé
        [_BRIER_GOOD, _BRIER_BAD] → [+1, -1]).
      - terme_roi_récent : ROI net des derniers paris IA réglés (mappé ±30% → ±1) ;
        ignoré si échantillon < _MIN_BETS_FOR_ROI.
    Renvoie {heat, brier, roi_recent, n_races, n_bets} (tout réel ; None si absent).
    """
    # ── Calibration : brier moyen récent (race_learning_log) ──
    brier = None
    n_races = 0
    try:
        row = (await session.execute(text("""
            SELECT AVG(brier_score), COUNT(*) FROM (
                SELECT brier_score FROM race_learning_log
                WHERE brier_score IS NOT NULL
                ORDER BY analyzed_at DESC LIMIT :lim
            ) q
        """), {"lim": _RECENT_RACES})).first()
        if row and row[0] is not None:
            brier = float(row[0])
            n_races = int(row[1] or 0)
    except Exception:
        brier = None

    # ── Résultats : ROI net des derniers paris IA réglés (bankroll_entries) ──
    roi_recent = None
    n_bets = 0
    try:
        row = (await session.execute(text("""
            SELECT COALESCE(SUM(gain_perte), 0), COALESCE(SUM(mise), 0), COUNT(*) FROM (
                SELECT gain_perte, mise FROM bankroll_entries
                WHERE resultat IN ('gagne','perd') AND gain_perte IS NOT NULL
                  AND mise > 0 AND suivi_reco_ia = true
                ORDER BY date DESC LIMIT :lim
            ) q
        """), {"lim": _RECENT_BETS})).first()
        if row and float(row[1] or 0) > 0:
            n_bets = int(row[2] or 0)
            roi_recent = float(row[0]) / float(row[1])
    except Exception:
        roi_recent = None

    # ── Termes ──
    terms = []
    if brier is not None:
        # brier _BRIER_GOOD → +1, _BRIER_BAD → -1 (linéaire borné)
        cal = (_BRIER_BAD - brier) / (_BRIER_BAD - _BRIER_GOOD) * 2.0 - 1.0
        terms.append(max(-1.0, min(1.0, cal)))
    if roi_recent is not None and n_bets >= _MIN_BETS_FOR_ROI:
        terms.append(max(-1.0, min(1.0, roi_recent / 0.30)))

    heat = round(sum(terms) / len(terms), 3) if terms else 0.0
    return {
        "heat": heat,
        "brier": round(brier, 4) if brier is not None else None,
        "roi_recent": round(roi_recent, 4) if roi_recent is not None else None,
        "n_races": n_races,
        "n_bets": n_bets,
    }


async def get_model_heat(session: AsyncSession) -> float:
    """heat ∈ [-1,+1] avec cache Redis (best-effort). 0.0 si aucun signal."""
    redis = None
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(_HEAT_CACHE_KEY)
        if cached is not None:
            return float(cached)
    except Exception:
        redis = None

    ctx = await compute_model_heat(session)
    heat = float(ctx.get("heat", 0.0))
    try:
        if redis is not None:
            await redis.set(_HEAT_CACHE_KEY, str(heat), ex=_HEAT_TTL)
    except Exception:
        pass
    return heat
