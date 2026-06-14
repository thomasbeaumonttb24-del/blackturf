"""
cote_calibration.py — Calibration de la proba par TRANCHE DE COTE, apprise des
résultats réels (auto-amélioration nightly). Corrige le biais favori-longshot
résiduel mesuré : le modèle SOUS-estime les favoris (cote<4) et SUR-estime les
outsiders (cote 25+). Une EV calculée sur une proba mal calibrée = faux value
bets → renta dégradée. Ce module rapproche la proba de la réalité observée.

Principe (intégrité) :
- Facteur de calibration par bucket = ratio (gains réels / gains attendus modèle),
  SHRINKÉ vers 1.0 par un pseudo-compte K (Bayesien) → un petit échantillon ne
  fait pas surréagir. Aucune valeur inventée : si pas de données → facteur 1.0.
- Recalculé chaque nuit depuis predictions ⋈ resultats (s'affine avec le volume).
- Stocké en table `cote_calibration` (créée inline, comme longshot_calibration).
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Bornes des tranches de cote (gagnant PMU). Bucket index = i tel que
# COTE_EDGES[i] <= cote < COTE_EDGES[i+1].
COTE_EDGES = [1.0, 2.0, 4.0, 7.0, 12.0, 25.0, 1e9]
K_SHRINK = 25.0          # pseudo-compte : shrink le facteur vers 1.0 (anti sur-réaction)
FACTOR_MIN, FACTOR_MAX = 0.4, 1.8   # bornes de sécurité du facteur


def bucket_index(cote: float) -> int:
    for i in range(len(COTE_EDGES) - 1):
        if COTE_EDGES[i] <= cote < COTE_EDGES[i + 1]:
            return i
    return len(COTE_EDGES) - 2


def _shrunk_factor(real_sum: float, model_sum: float) -> float:
    """Facteur = (réels + K) / (attendus + K), borné. K shrink vers 1.0."""
    if model_sum <= 0:
        return 1.0
    f = (real_sum + K_SHRINK) / (model_sum + K_SHRINK)
    return float(max(FACTOR_MIN, min(FACTOR_MAX, f)))


async def compute_cote_calibration(session: AsyncSession) -> dict:
    """Calcule les facteurs win/top3 par tranche de cote depuis les résultats réels.
    Retourne {buckets: [{lo,hi,n,win_factor,top3_factor}], updated_at}."""
    # FLAG calib_guard : n'apprend que sur prédictions FIGÉES AVANT le départ
    # (pr.created_at < c.date_heure). apply_factor multiplie directement la
    # P(victoire) servant à sélectionner les value bets → si le facteur est appris
    # sur des prédictions backfillées (régénérées après résultat connu), il encode
    # du hindsight et mis-shrink en prod. Mêmes guards que signal_performance /
    # edge_monitor. Flag off → comportement historique.
    from ml.algo_flags import FLAGS as _AF
    _guard = (
        "AND pr.created_at IS NOT NULL AND c.date_heure IS NOT NULL AND pr.created_at < c.date_heure"
        if _AF.calib_guard else ""
    )
    # FLAG calib_on_raw : facteurs appris sur la proba BRUTE (COALESCE raw → calibrée).
    _p1c = "COALESCE(pr.proba_top1_raw, pr.proba_top1)" if _AF.calib_on_raw else "pr.proba_top1"
    _p3c = "COALESCE(pr.proba_top3_raw, pr.proba_top3)" if _AF.calib_on_raw else "pr.proba_top3"
    rows = (await session.execute(text(f"""
        SELECT pa.cote_pmu AS cote,
               {_p1c} AS p1, {_p3c} AS p3,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win,
               CASE WHEN pa.numero IN (
                    SELECT (e->>'numero')::int
                    FROM jsonb_array_elements(r.classement) WITH ORDINALITY a(e,o)
                    WHERE o <= 3
               ) THEN 1 ELSE 0 END AS top3
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN courses c ON c.course_id = pr.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pr.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          {_guard}
    """))).fetchall()

    nb = len(COTE_EDGES) - 1
    agg = [{"n": 0, "win_real": 0.0, "win_exp": 0.0, "top3_real": 0.0, "top3_exp": 0.0} for _ in range(nb)]
    for cote, p1, p3, win, top3 in rows:
        i = bucket_index(float(cote))
        a = agg[i]
        a["n"] += 1
        a["win_real"] += float(win); a["win_exp"] += float(p1 or 0.0)
        a["top3_real"] += float(top3); a["top3_exp"] += float(p3 or 0.0)

    buckets = []
    for i in range(nb):
        a = agg[i]
        buckets.append({
            "lo": COTE_EDGES[i],
            "hi": COTE_EDGES[i + 1] if COTE_EDGES[i + 1] < 1e8 else None,
            "n": a["n"],
            "win_factor": round(_shrunk_factor(a["win_real"], a["win_exp"]), 4),
            "top3_factor": round(_shrunk_factor(a["top3_real"], a["top3_exp"]), 4),
        })
    return {"buckets": buckets, "n_total": len(rows)}


async def persist_cote_calibration(session: AsyncSession, calib: dict) -> None:
    """Stocke la calibration (table inline, 1 ligne JSON)."""
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS cote_calibration (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT cote_calib_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO cote_calibration (id, data, updated_at)
        VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(calib)})
    await session.commit()


async def load_cote_calibration(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM cote_calibration WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def apply_factor(cote: float, calib: dict | None, kind: str = "win") -> float:
    """Retourne le facteur de calibration pour une cote (1.0 si pas de calib)."""
    if not calib or not calib.get("buckets"):
        return 1.0
    i = bucket_index(float(cote))
    b = calib["buckets"][i] if i < len(calib["buckets"]) else None
    if not b:
        return 1.0
    return float(b.get("top3_factor" if kind == "top3" else "win_factor", 1.0))
