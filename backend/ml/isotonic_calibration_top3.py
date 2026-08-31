"""
Calibration isotonique du proba_top3 (placé) — calibration RÉSIDUELLE.

Constat sur données réelles : la proba_top3 est SUR-CONFIANTE en milieu de gamme
(prédit 0.45-0.75 mais fréquence réelle ~0.31-0.52), bien calibrée aux extrêmes.
Cela gonfle l'EV/proba des paris PLACÉ (Simple Placé, Couplé Placé, 2sur4) qui sont
le cœur des profils prudent/modéré → sélection et espérance trop optimistes.

Méthode : régression isotone (sklearn) sur les couples (proba_top3 prédite,
arrivé-dans-le-top-3 0/1) des courses terminées. Courbe stockée en points de
rupture (x, y), appliquée à l'inférence par interpolation monotone (np.interp),
puis renormalisation Σ = min(3, nb_partants) par course (contrainte : 3 placés).

Intégrité : aucune valeur inventée. < MIN_OBS observations → courbe vide →
calibration = identité. Recalculée chaque nuit sur toutes les données à jour.
Jumeau de [ml/isotonic_calibration.py] (qui calibre, lui, le proba_top1).
"""
from __future__ import annotations

import json
import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="isotonic_calibration_top3")

MIN_OBS = 200

_cached_curve: dict | None = None


async def _fetch_proba_top3_outcomes(session: AsyncSession) -> list[tuple[float, int]]:
    """Retourne [(proba_top3, arrivé top-3 0/1)] sur les courses avec résultat.

    FLAG calib_on_raw : fitte sur proba_top3_raw (brute) + garde pré-départ. COALESCE
    rétro-compat. Flag off → comportement historique (cf. ml/isotonic_calibration)."""
    from ml.algo_flags import FLAGS as _AF
    _col = "COALESCE(pr.proba_top3_raw, pr.proba_top3)" if _AF.calib_on_raw else "pr.proba_top3"
    rows = await session.execute(text(f"""
        SELECT {_col}, pa.numero, pr.course_id, r.classement
        FROM prediction_evaluation pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN resultats r       ON r.course_id        = pr.course_id
        JOIN courses c         ON c.course_id        = pr.course_id
        WHERE {_col} IS NOT NULL AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pr.created_at IS NOT NULL
          AND pr.created_at < c.date_heure
          AND pr.is_replayable = true
    """))
    out: list[tuple[float, int]] = []
    for proba, numero, course_id, classement in rows.fetchall():
        if not classement:
            continue
        top3 = set()
        for e in classement:
            try:
                if int(e.get("position")) in (1, 2, 3):
                    top3.add(int(e.get("numero")))
            except (TypeError, ValueError):
                continue
        if not top3:
            continue
        try:
            p = float(proba); num = int(numero)
        except (TypeError, ValueError):
            continue
        out.append((p, 1 if num in top3 else 0))
    return out


async def compute_and_store(session: AsyncSession) -> dict:
    """Fit régression isotone (proba_top3 → fréquence réelle top-3), stocke en DB."""
    data = await _fetch_proba_top3_outcomes(session)
    curve: dict = {"x": [], "y": [], "n_obs": len(data)}

    if len(data) < MIN_OBS:
        log.warning(
            "isotonic_top3.skipped_insufficient_replayable_data",
            n_obs=len(data), min_obs=MIN_OBS,
        )
        curve["status"] = "skipped_insufficient_replayable_data"
        return curve

    if len(data) >= MIN_OBS:
        x = np.array([d[0] for d in data], dtype=float)
        y = np.array([d[1] for d in data], dtype=float)
        # FLAG cir_calibration : isotone CENTRÉE (pas d'escalier) — cf. ml/isotonic_utils.
        _cir_done = False
        try:
            from ml.algo_flags import FLAGS as _AFc
            if _AFc.cir_calibration:
                from ml.isotonic_utils import centered_isotonic_curve
                cir = centered_isotonic_curve(x, y)
                if cir.get("x"):
                    curve = {"x": cir["x"], "y": cir["y"], "n_obs": len(data)}
                    _cir_done = True
                else:
                    log.warning("isotonic_top3.cir_empty_fallback_step", n_obs=len(data))
        except Exception as e:
            log.warning("isotonic_top3.cir_failed", err=str(e)[:160])
        if not _cir_done:
            try:
                from sklearn.isotonic import IsotonicRegression
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True,
                                         out_of_bounds="clip")
                iso.fit(x, y)
                xs = np.asarray(iso.X_thresholds_, dtype=float)
                ys = np.asarray(iso.y_thresholds_, dtype=float)
                xs_u, idx = np.unique(xs, return_index=True)
                curve = {"x": [round(v, 6) for v in xs_u.tolist()],
                         "y": [round(float(ys[i]), 6) for i in idx],
                         "n_obs": len(data)}
            except Exception as e:
                log.warning("isotonic_top3.fit_failed", err=str(e)[:160])
                curve = {"x": [], "y": [], "n_obs": len(data)}

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS isotonic_calibration_top3 (
            id INT PRIMARY KEY DEFAULT 1,
            curve JSONB NOT NULL,
            n_obs INT,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    await session.execute(text("""
        INSERT INTO isotonic_calibration_top3 (id, curve, n_obs, updated_at)
        VALUES (1, CAST(:c AS JSONB), :n, now())
        ON CONFLICT (id) DO UPDATE SET curve = EXCLUDED.curve,
            n_obs = EXCLUDED.n_obs, updated_at = now()
    """), {"c": json.dumps(curve), "n": curve["n_obs"]})
    await session.commit()

    global _cached_curve
    _cached_curve = curve
    log.info("isotonic_top3.computed", n_points=len(curve["x"]), n_obs=curve["n_obs"])
    return curve


async def load_curve(session: AsyncSession) -> dict:
    """Charge la courbe persistée (cache mémoire). {} si absente/vide."""
    global _cached_curve
    try:
        r = await session.execute(text("SELECT curve FROM isotonic_calibration_top3 WHERE id = 1"))
        row = r.fetchone()
        if row and row[0]:
            _cached_curve = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        log.debug("isotonic_top3.load_skip", err=str(e))
    return _cached_curve or {}


def apply_calibration(probas_top3: np.ndarray, curve: dict, nb_partants: int) -> np.ndarray:
    """Mappe chaque proba_top3 par la courbe isotone puis renormalise Σ = min(3, n).
    Courbe vide → inchangé (identité)."""
    if not curve:
        return probas_top3
    xs = curve.get("x") or []
    ys = curve.get("y") or []
    if len(xs) < 2 or len(xs) != len(ys):
        return probas_top3
    p = np.asarray(probas_top3, dtype=float)
    mapped = np.interp(p, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    mapped = np.clip(mapped, 1e-6, 0.999)
    # Filet anti-palier (cf. ml/isotonic_utils.restore_within_race_order).
    try:
        from ml.isotonic_utils import restore_within_race_order
        mapped = restore_within_race_order(mapped, p)
    except Exception as e:
        log.warning("isotonic_top3.tie_restore_skip", err=str(e)[:120])
    target = float(min(3.0, max(nb_partants, 1)))
    s = float(mapped.sum())
    if s > 0:
        mapped = np.clip(mapped * (target / s), 0.0, 0.99)
    return mapped
