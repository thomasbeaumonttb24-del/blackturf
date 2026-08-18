"""
Calibration longshots — APPLIQUÉE à l'inférence (pas juste diagnostic).

Le modèle sur-évalue les outsiders : sur les buckets de grosse cote, la proba de
victoire prédite est supérieure à la fréquence RÉELLE observée. On corrige la
proba_top1 par un facteur = fréquence_réelle / proba_moyenne_prédite, par bucket
de cote, puis on renormalise (Σ=1 par course).

Intégrité : facteurs calculés UNIQUEMENT sur des buckets avec assez d'observations
réelles (>= MIN_OBS). Les buckets non fiables gardent un facteur 1.0 (aucune
extrapolation, aucune valeur inventée). Recalculé chaque nuit.
"""
from __future__ import annotations

import json
import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.calibration_longshots import (
    bucket_label, fetch_rows, fetch_winners, compute_bucket_stats,
)
from ml.prediction_evaluation import MIN_LONGSHOT_REPLAYABLE_OBS

log = structlog.get_logger(module="longshot_calibration")

# Bornes du facteur de correction (évite les corrections absurdes sur petit n)
_FACTOR_MIN = 0.15
_FACTOR_MAX = 1.5

_cached_factors: dict[str, float] | None = None


async def compute_and_store(session: AsyncSession, cote_col: str = "cote_pmu") -> dict[str, float]:
    """
    Calcule les facteurs de calibration par bucket depuis les vraies données
    (predictions.proba_top1 vs gagnants réels) et les persiste en DB.
    Retourne {bucket: facteur}. Bucket non fiable → 1.0.
    """
    global _cached_factors
    rows = await fetch_rows(session, cote_col)
    winners = await fetch_winners(session)
    stats = compute_bucket_stats(rows, winners)
    n_obs = sum(s["n"] for s in stats)
    if n_obs < MIN_LONGSHOT_REPLAYABLE_OBS or not any(s["reliable"] for s in stats):
        log.warning(
            "longshot_calibration.skipped_insufficient_replayable_data",
            n_obs=n_obs,
            min_obs=MIN_LONGSHOT_REPLAYABLE_OBS,
        )
        return _cached_factors or {}

    factors: dict[str, float] = {}
    for s in stats:
        if s["reliable"] and s["proba_moy"] and s["proba_moy"] > 0 and s["freq"] is not None:
            f = s["freq"] / s["proba_moy"]
            factors[s["bucket"]] = float(max(_FACTOR_MIN, min(f, _FACTOR_MAX)))
        else:
            factors[s["bucket"]] = 1.0

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS longshot_calibration (
            id INT PRIMARY KEY DEFAULT 1,
            factors JSONB NOT NULL,
            n_obs INT,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    await session.execute(text("""
        INSERT INTO longshot_calibration (id, factors, n_obs, updated_at)
        VALUES (1, CAST(:f AS JSONB), :n, now())
        ON CONFLICT (id) DO UPDATE SET factors = EXCLUDED.factors, n_obs = EXCLUDED.n_obs, updated_at = now()
    """), {"f": json.dumps(factors), "n": n_obs})
    await session.commit()

    _cached_factors = factors
    log.info("longshot_calibration.computed", factors=factors, n_obs=n_obs)
    return factors


async def load_factors(session: AsyncSession) -> dict[str, float]:
    """Charge les facteurs persistés (cache mémoire). {} si absent."""
    global _cached_factors
    try:
        r = await session.execute(text("SELECT factors FROM longshot_calibration WHERE id = 1"))
        row = r.fetchone()
        if row and row[0]:
            _cached_factors = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        log.debug("longshot_calibration.load_skip", err=str(e))
    return _cached_factors or {}


def apply_calibration(probas_top1: np.ndarray, cotes, factors: dict[str, float]) -> np.ndarray:
    """
    Applique le facteur de bucket à chaque proba_top1 selon la cote du partant,
    puis renormalise (Σ=1). Sans facteurs → inchangé.
    """
    if not factors:
        return probas_top1
    out = np.asarray(probas_top1, dtype=float).copy()
    cotes = np.asarray(cotes, dtype=float)
    for i in range(len(out)):
        c = cotes[i] if i < len(cotes) else None
        if c is not None and c > 1.0:
            out[i] *= float(factors.get(bucket_label(float(c)), 1.0))
    s = float(out.sum())
    if s > 0:
        out = out / s
    return out
