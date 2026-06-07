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
