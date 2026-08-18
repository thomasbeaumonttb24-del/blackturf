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
          JOIN prediction_evaluation pr ON pr.participation_id = l.participation_id
          JOIN courses c ON c.course_id = pr.course_id
          WHERE l.cote_figee > 1 AND l.cote_cloture > 1
            AND c.date_heure IS NOT NULL AND pr.created_at IS NOT NULL
            AND pr.created_at < c.date_heure
            AND pr.is_replayable = true
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

    # SEGMENT VALUE CONTRARIAN (hypothèse à forward-valider, NE PAS encore miser) :
    # top-3 modèle dont la cote a DÉRIVÉ (montée) ouverture→T-10 (le marché les pousse
    # dehors, le modèle les aime) → ils reviennent + gagnent plus. In-sample ~13j : ROI
    # +19% (n~394). On le SUIT nightly pour confirmer (ou infirmer) hors échantillon avant
    # de toucher la sélection de paris. ROI flat-stake à la cote figée (T-10, où on parierait).
    seg = (await session.execute(text("""
        WITH d AS (
          SELECT l.cote_figee,
                 CASE WHEN (r.classement->0->>'numero')::int = l.numero THEN 1 ELSE 0 END AS win
          FROM cote_cloture_log l
          JOIN participations pa ON pa.participation_id = l.participation_id
          JOIN prediction_evaluation pr ON pr.participation_id = l.participation_id
          JOIN resultats r ON r.course_id = l.course_id
          JOIN courses c ON c.course_id = l.course_id
          WHERE l.cote_figee > 1 AND l.cote_cloture > 1 AND pa.cote_reference > 1
            AND jsonb_typeof(r.classement) = 'array' AND pr.rang_predit <= 3
            AND c.date_heure IS NOT NULL AND pr.created_at IS NOT NULL
            AND pr.created_at < c.date_heure
            AND pr.is_replayable = true
            AND pa.cote_reference / NULLIF(l.cote_figee, 0) - 1 < -0.05   -- cote a monté avant T-10
        )
        SELECT count(*) AS n, avg(win) AS winrate,
               avg(CASE WHEN win = 1 THEN cote_figee ELSE 0 END) - 1 AS roi
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
        # segment value contrarian (drift-out) — à forward-valider avant de miser
        "seg_driftout_n": int(seg[0] or 0) if seg else 0,
        "seg_driftout_winrate": _r(seg[1], 3) if seg else None,
        "seg_driftout_roi": _r(seg[2], 4) if seg else None,
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
