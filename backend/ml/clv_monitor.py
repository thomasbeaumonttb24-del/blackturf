"""
clv_monitor.py — Suivi HONNÊTE de la CLV (Closing Line Value).

CLV = cote_figee (notre prix à T-10, où on parie) / cote_cloture (dernière cote PMU
≈ départ) − 1. CLV > 0 sur un cheval = on a obtenu un MEILLEUR prix que la clôture
(le marché s'est resserré APRÈS nous → on a anticipé). C'est le proxy d'edge le plus
robuste à la variance en paris : si nos sélections battent la ligne de clôture de façon
stable, on a un vrai signal, bien avant que le ROI (bruité) ne le confirme.

On suit la CLV des CHOIX DU MODÈLE (top-1, top-3) vs l'ensemble : si les top picks ont
une CLV > la moyenne (~0, marché martingale), le modèle anticipe le marché. Source =
table cote_cloture_log (remplie au post-course). Aucune donnée inventée ; si pas assez
d'obs, on le dit. Persiste un snapshot nightly (table clv_monitor) → on voit si ça tient.

CAVEAT : CLV mesurée contre la clôture PMU (même pool pari-mutuel) ⇒ ne s'affranchit PAS
de la marge PMU (~15%). Une CLV de +2-7% < marge ⇒ pas encore profitable en l'état, mais
c'est un signal directionnel réel. Une CLV contre Betfair (hors marge) serait décisive.
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

MIN_OBS = 100   # sous ce seuil, CLV dominée par la variance → non déclarable


async def compute_clv_monitor(session: AsyncSession) -> dict:
    rows = (await session.execute(text("""
        WITH d AS (
          SELECT l.course_id,
                 l.cote_figee / NULLIF(l.cote_cloture, 0) - 1 AS clv,
                 pr.proba_top1, pr.rang_predit,
                 ROW_NUMBER() OVER (PARTITION BY l.course_id
                                    ORDER BY pr.proba_top1 DESC NULLS LAST) AS rk
          FROM cote_cloture_log l
          JOIN predictions pr ON pr.participation_id = l.participation_id
          WHERE l.cote_figee > 1 AND l.cote_cloture > 1
        )
        SELECT
          count(*) FILTER (WHERE rk = 1)                                   AS n_top1,
          avg(clv) FILTER (WHERE rk = 1)                                   AS clv_top1,
          avg((clv > 0.02)::int::float) FILTER (WHERE rk = 1)             AS pos_top1,
          count(*) FILTER (WHERE rang_predit <= 3)                         AS n_top3,
          avg(clv) FILTER (WHERE rang_predit <= 3)                        AS clv_top3,
          avg((clv > 0.02)::int::float) FILTER (WHERE rang_predit <= 3)   AS pos_top3,
          count(*)                                                        AS n_all,
          avg(clv)                                                        AS clv_all
        FROM d
    """))).first()

    if not rows or (rows[0] or 0) < MIN_OBS:
        return {"n_top1": int(rows[0] or 0) if rows else 0, "insufficient": True, "min_obs": MIN_OBS}

    def _r(v, p=4):
        return round(float(v), p) if v is not None else None

    snap = {
        "n_top1": int(rows[0] or 0), "clv_top1": _r(rows[1]), "pos_top1": _r(rows[2], 3),
        "n_top3": int(rows[3] or 0), "clv_top3": _r(rows[4]), "pos_top3": _r(rows[5], 3),
        "n_all": int(rows[6] or 0), "clv_all": _r(rows[7]),
        # edge directionnel = CLV des top picks nettement > CLV moyenne (marché)
        "edge_signal": bool((rows[1] or 0) > 0.01 and (rows[1] or 0) > (rows[7] or 0) + 0.01),
        "min_obs": MIN_OBS,
    }
    return snap


async def persist_clv_monitor(session: AsyncSession, snap: dict) -> None:
    if snap.get("insufficient"):
        return
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS clv_monitor (
            id BIGSERIAL PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.execute(text("INSERT INTO clv_monitor (data) VALUES (:d)"),
                          {"d": json.dumps(snap)})
    await session.commit()


async def latest_clv_monitor(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text(
            "SELECT data, created_at FROM clv_monitor ORDER BY created_at DESC LIMIT 1"))).first()
        if not r:
            return None
        d = dict(r[0]); d["created_at"] = str(r[1])
        return d
    except Exception:
        return None
