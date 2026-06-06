"""
Calibration isotonique — calibration RÉSIDUELLE de la proba_top1 finale.

Le pipeline empile déjà plusieurs corrections (temperature scaling, blend marché,
calibration longshots par bucket de cote). La calibration isotonique ferme la
boucle : elle ajuste de façon MONOTONE la proba_top1 FINALE pour qu'elle colle à la
fréquence de victoire RÉELLEMENT observée, sans imposer de forme paramétrique.

Méthode : régression isotone (sklearn) sur les couples (proba_top1 prédite, gagné)
des courses terminées. La courbe apprise est stockée comme une liste de points de
rupture (x, y) — pas d'objet picklé — et appliquée à l'inférence par interpolation
linéaire monotone (np.interp), puis renormalisation Σ=1 par course.

Intégrité : aucune valeur inventée. Si trop peu d'observations réelles (< MIN_OBS),
la courbe reste vide → calibration = identité (on n'extrapole jamais). Recalculée
chaque nuit sur toutes les données à jour.
"""
from __future__ import annotations

import json
import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.calibration_longshots import fetch_winners

log = structlog.get_logger(module="isotonic_calibration")

# Nb minimal de couples (prédiction, résultat) pour fitter une courbe fiable.
MIN_OBS = 150

_cached_curve: dict | None = None


async def _fetch_proba_outcomes(session: AsyncSession) -> list[tuple[float, int]]:
    """Retourne [(proba_top1, gagné 0/1)] sur toutes les courses avec résultat."""
    rows = await session.execute(text("""
        SELECT pr.proba_top1, pa.numero, pr.course_id
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN resultats r       ON r.course_id        = pr.course_id
        WHERE pr.proba_top1 IS NOT NULL
    """))
    winners = await fetch_winners(session)
    out: list[tuple[float, int]] = []
    for proba, numero, course_id in rows.fetchall():
        gagnants = winners.get(course_id)
        if gagnants is None:
            continue
        try:
            p = float(proba); num = int(numero)
        except (TypeError, ValueError):
            continue
        out.append((p, 1 if num in gagnants else 0))
    return out


async def compute_and_store(session: AsyncSession) -> dict:
    """
    Fit une régression isotone (proba_top1 → fréquence réelle), stocke ses points de
    rupture en DB. Retourne {x, y, n_obs} ; courbe vide si données insuffisantes.
    """
    data = await _fetch_proba_outcomes(session)
    curve: dict = {"x": [], "y": [], "n_obs": len(data)}

    if len(data) >= MIN_OBS:
        try:
            from sklearn.isotonic import IsotonicRegression
            x = np.array([d[0] for d in data], dtype=float)
            y = np.array([d[1] for d in data], dtype=float)
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True,
                                     out_of_bounds="clip")
            iso.fit(x, y)
            xs = np.asarray(iso.X_thresholds_, dtype=float)
            ys = np.asarray(iso.y_thresholds_, dtype=float)
            # Dédoublonne les x identiques (np.interp exige des abscisses croissantes)
            xs_u, idx = np.unique(xs, return_index=True)
            curve = {"x": [round(v, 6) for v in xs_u.tolist()],
                     "y": [round(float(ys[i]), 6) for i in idx],
                     "n_obs": len(data)}
        except Exception as e:
            log.warning("isotonic.fit_failed", err=str(e)[:160])
            curve = {"x": [], "y": [], "n_obs": len(data)}

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS isotonic_calibration (
            id INT PRIMARY KEY DEFAULT 1,
            curve JSONB NOT NULL,
            n_obs INT,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    await session.execute(text("""
        INSERT INTO isotonic_calibration (id, curve, n_obs, updated_at)
        VALUES (1, CAST(:c AS JSONB), :n, now())
        ON CONFLICT (id) DO UPDATE SET curve = EXCLUDED.curve,
            n_obs = EXCLUDED.n_obs, updated_at = now()
    """), {"c": json.dumps(curve), "n": curve["n_obs"]})
    await session.commit()

    global _cached_curve
    _cached_curve = curve
    log.info("isotonic.computed", n_points=len(curve["x"]), n_obs=curve["n_obs"])
    return curve


async def load_curve(session: AsyncSession) -> dict:
    """Charge la courbe persistée (cache mémoire). {} si absente/vide."""
    global _cached_curve
    try:
        r = await session.execute(text("SELECT curve FROM isotonic_calibration WHERE id = 1"))
        row = r.fetchone()
        if row and row[0]:
            _cached_curve = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        log.debug("isotonic.load_skip", err=str(e))
    return _cached_curve or {}


def apply_calibration(probas_top1: np.ndarray, curve: dict) -> np.ndarray:
    """
    Mappe chaque proba_top1 par la courbe isotone (interpolation linéaire monotone)
    puis renormalise Σ=1. Courbe vide → inchangé (identité).
    """
    if not curve:
        return probas_top1
    xs = curve.get("x") or []
    ys = curve.get("y") or []
    if len(xs) < 2 or len(xs) != len(ys):
        return probas_top1
    p = np.asarray(probas_top1, dtype=float)
    mapped = np.interp(p, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    mapped = np.clip(mapped, 1e-6, 0.999)
    s = float(mapped.sum())
    if s > 0:
        mapped = mapped / s
    return mapped
