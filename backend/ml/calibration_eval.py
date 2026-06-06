"""
Évaluation de calibration — mesure HONNÊTE de la qualité des probabilités.

Une proba est "calibrée" si, parmi les chevaux annoncés à ~30% de gagner, ~30%
gagnent réellement. Ce module mesure ça sur les courses terminées :

  - reliability diagram : par bin de proba_top1 prédite, fréquence de victoire RÉELLE
  - ECE (Expected Calibration Error) : écart moyen pondéré |proba prédite − fréquence|
  - Brier score sur la victoire

100% lecture seule (n'altère aucune prédiction). Sert de PREUVE de la qualité du
modèle + des calibrations (temperature, marché, longshots, isotonique) et à détecter
une dérive de calibration. Données réelles uniquement ; NULL si trop peu d'obs.
"""
from __future__ import annotations

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.calibration_longshots import fetch_winners

log = structlog.get_logger(module="calibration_eval")

MIN_OBS = 50  # sous ce nb de couples (proba, résultat), pas de mesure fiable


async def _fetch_proba_outcomes(session: AsyncSession) -> list[tuple[float, int]]:
    """[(proba_top1, gagné 0/1)] sur toutes les courses avec résultat."""
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


async def compute_calibration_quality(session: AsyncSession, n_bins: int = 10) -> dict:
    """
    Calcule reliability diagram + ECE + Brier sur la proba de VICTOIRE.
    Retourne {reliable, n_obs, ece, brier, base_rate, bins:[{lo,hi,n,proba_moy,freq_reelle}]}.
    reliable=False (+ métriques None) si moins de MIN_OBS observations.
    """
    data = await _fetch_proba_outcomes(session)
    n = len(data)
    if n < MIN_OBS:
        return {"reliable": False, "n_obs": n, "ece": None, "brier": None,
                "base_rate": None, "bins": []}

    p = np.array([d[0] for d in data], dtype=float)
    y = np.array([d[1] for d in data], dtype=float)

    brier = float(np.mean((p - y) ** 2))
    base_rate = float(y.mean())

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins_out = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            bins_out.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2),
                             "n": 0, "proba_moy": None, "freq_reelle": None})
            continue
        proba_moy = float(p[mask].mean())
        freq = float(y[mask].mean())
        ece += (cnt / n) * abs(proba_moy - freq)
        bins_out.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2),
                         "n": cnt, "proba_moy": round(proba_moy, 4),
                         "freq_reelle": round(freq, 4)})

    verdict = ("excellente" if ece < 0.03 else "bonne" if ece < 0.06
               else "moyenne" if ece < 0.10 else "à améliorer")
    log.info("calibration_eval.computed", n_obs=n, ece=round(ece, 4), brier=round(brier, 4))
    return {
        "reliable": True,
        "n_obs": n,
        "ece": round(ece, 4),
        "brier": round(brier, 4),
        "base_rate": round(base_rate, 4),
        "verdict": verdict,
        "bins": bins_out,
    }
