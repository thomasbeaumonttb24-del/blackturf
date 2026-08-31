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
# Nb minimal d'obs PAR SEGMENT pour fitter une courbe dédiée (sinon → courbe globale).
MIN_OBS_SEG = 400

_cached_curve: dict | None = None


def _nb_bucket(nb: int) -> str:
    """Tranche de taille de peloton (la calibration favori/longshot dépend du champ)."""
    if nb <= 0:
        return "na"
    if nb <= 8:
        return "small"
    if nb <= 13:
        return "med"
    return "large"


def seg_key(discipline, nb_partants) -> str:
    """Clé de segment de calibration : discipline × tranche de partants. IDENTIQUE
    au fit (compute_and_store) et à l'inférence (apply_calibration) — toute divergence
    casserait la correspondance des courbes."""
    disc = (str(discipline or "na").strip().lower())[:16]
    try:
        nb = int(nb_partants or 0)
    except (TypeError, ValueError):
        nb = 0
    return f"{disc}|{_nb_bucket(nb)}"


async def _fetch_proba_outcomes(session: AsyncSession) -> list[tuple[float, int, str]]:
    """Retourne [(proba_top1, gagné 0/1, seg_key)] sur toutes les courses avec résultat.

    FLAG calib_on_raw : fitte sur la proba MODÈLE BRUTE (proba_top1_raw) au lieu de
    la proba déjà calibrée → casse la boucle fermée (la calibration ne chasse plus
    son propre résidu). + garde anti-leakage (pronos pré-départ only). COALESCE pour
    rétro-compat sur les lignes historiques sans raw. Flag off → comportement d'avant.
    Le seg_key (discipline × tranche partants) permet une calibration PAR SEGMENT.
    """
    from ml.algo_flags import FLAGS as _AF
    _col = "COALESCE(pr.proba_top1_raw, pr.proba_top1)" if _AF.calib_on_raw else "pr.proba_top1"
    rows = await session.execute(text(f"""
        SELECT {_col}, pa.numero, pr.course_id, c.discipline,
               (SELECT count(*) FROM participations pp
                 WHERE pp.course_id = pr.course_id AND pp.non_partant = false) AS nb_part
        FROM prediction_evaluation pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN resultats r       ON r.course_id        = pr.course_id
        JOIN courses c         ON c.course_id        = pr.course_id
        WHERE {_col} IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pr.created_at IS NOT NULL
          AND pr.created_at < c.date_heure
          AND pr.is_replayable = true
    """))
    winners = await fetch_winners(session)
    out: list[tuple[float, int, str]] = []
    for proba, numero, course_id, discipline, nb_part in rows.fetchall():
        gagnants = winners.get(course_id)
        if gagnants is None:
            continue
        try:
            p = float(proba); num = int(numero)
        except (TypeError, ValueError):
            continue
        out.append((p, 1 if num in gagnants else 0, seg_key(discipline, nb_part)))
    return out


def _fit_curve(data: list[tuple[float, int]]) -> dict:
    """Fit isotone sur [(proba, gagné)] → {x, y, n_obs}. Courbe vide si insuffisant.

    FLAG cir_calibration (défaut ON) : régression isotone CENTRÉE — chaque palier
    plat est réduit à son centroïde, la courbe devient strictement croissante. Sans
    ça la courbe est un escalier qui écrase des probas distinctes sur une seule
    valeur (mesuré : 31 `y` distincts pour 62 points de rupture, 39 % de la
    discrimination intra-course détruite). Flag off → escalier d'avant.
    """
    curve = {"x": [], "y": [], "n_obs": len(data)}
    if len(data) < MIN_OBS:
        return curve
    x = np.array([d[0] for d in data], dtype=float)
    y = np.array([d[1] for d in data], dtype=float)

    from ml.algo_flags import FLAGS as _AFc
    if _AFc.cir_calibration:
        from ml.isotonic_utils import centered_isotonic_curve
        cir = centered_isotonic_curve(x, y)
        if cir.get("x"):
            return {"x": cir["x"], "y": cir["y"], "n_obs": len(data)}
        log.warning("isotonic.cir_empty_fallback_step", n_obs=len(data))

    try:
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        iso.fit(x, y)
        xs = np.asarray(iso.X_thresholds_, dtype=float)
        ys = np.asarray(iso.y_thresholds_, dtype=float)
        xs_u, idx = np.unique(xs, return_index=True)
        curve = {"x": [round(v, 6) for v in xs_u.tolist()],
                 "y": [round(float(ys[i]), 6) for i in idx],
                 "n_obs": len(data)}
    except Exception as e:
        log.warning("isotonic.fit_failed", err=str(e)[:160])
        curve = {"x": [], "y": [], "n_obs": len(data)}
    return curve


async def compute_and_store(session: AsyncSession) -> dict:
    """
    Fit une régression isotone (proba_top1 → fréquence réelle), stocke ses points de
    rupture en DB. Retourne {x, y, n_obs} ; courbe vide si données insuffisantes.
    """
    data = await _fetch_proba_outcomes(session)
    if len(data) < MIN_OBS:
        log.warning(
            "isotonic.skipped_insufficient_replayable_data",
            n_obs=len(data), min_obs=MIN_OBS,
        )
        return {"x": [], "y": [], "n_obs": len(data), "segments": {},
                "status": "skipped_insufficient_replayable_data"}
    # Courbe GLOBALE (fallback) sur toutes les obs.
    curve: dict = _fit_curve([(p, w) for p, w, _ in data])

    # Courbes PAR SEGMENT (discipline × tranche partants) là où assez d'obs. La
    # calibration favori/longshot diffère fortement entre trot/plat/obstacle et entre
    # petits et grands pelotons : une courbe unique sur-corrige certains segments et
    # sous-corrige d'autres (ECE global bon mais hétérogène). Fallback global si < MIN_OBS_SEG.
    by_seg: dict[str, list] = {}
    for p, w, sk in data:
        by_seg.setdefault(sk, []).append((p, w))
    segments: dict[str, dict] = {}
    for sk, sd in by_seg.items():
        if len(sd) >= MIN_OBS_SEG:
            c = _fit_curve(sd)
            if c.get("x"):
                segments[sk] = c
    curve["segments"] = segments

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
    log.info("isotonic.computed", n_points=len(curve["x"]), n_obs=curve["n_obs"],
             n_segments=len(curve.get("segments") or {}))
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


def apply_calibration(probas_top1: np.ndarray, curve: dict, seg: str | None = None) -> np.ndarray:
    """
    Mappe chaque proba_top1 par la courbe isotone (interpolation linéaire monotone)
    puis renormalise Σ=1. Courbe vide → inchangé (identité).

    Si `seg` (clé de segment) est fourni ET qu'une courbe de segment existe, on
    l'utilise en priorité (calibration par discipline × tranche de partants), sinon
    on retombe sur la courbe globale. Rétro-compat : ancien format sans "segments" →
    courbe globale, comportement d'avant inchangé.
    """
    if not curve:
        return probas_top1
    seg_curve = (curve.get("segments") or {}).get(seg) if seg else None
    active = seg_curve if (seg_curve and seg_curve.get("x")) else curve
    xs = active.get("x") or []
    ys = active.get("y") or []
    if len(xs) < 2 or len(xs) != len(ys):
        return probas_top1
    p = np.asarray(probas_top1, dtype=float)
    mapped = np.interp(p, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    mapped = np.clip(mapped, 1e-6, 0.999)
    # Filet : une courbe EN ESCALIER (ancien fit encore en base tant que le recalcul
    # nocturne n'a pas tourné) colle la même proba à des chevaux que le modèle
    # séparait. On leur rend leur ordre — jamais aux chevaux réellement à égalité.
    try:
        from ml.isotonic_utils import restore_within_race_order
        mapped = restore_within_race_order(mapped, p)
    except Exception as e:
        log.warning("isotonic.tie_restore_skip", err=str(e)[:120])
    s = float(mapped.sum())
    if s > 0:
        mapped = mapped / s
    return mapped
