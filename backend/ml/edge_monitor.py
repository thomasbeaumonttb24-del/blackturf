"""
edge_monitor.py — Surveillance HONNÊTE de l'edge dans le temps.

Chaque nuit : ré-exécute le test hors-échantillon (apprend les multiplicateurs
signal sur le passé, mesure le filtre conviction≥1.1 sur la fenêtre la plus
récente JAMAIS apprise) et journalise win-rate / ROI / ROI plafonné vs baseline.
→ on sait si l'edge TIENT (taux de gain ≥ 2× marché, ROI plafonné > 0) ou se
dégrade. Append en table `edge_monitor` (historique). Aucune donnée inventée.
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.signal_performance import SIGNALS, _safe

log = structlog.get_logger()

K_SHRINK = 40.0
CONV_THR = 1.1
CAP = 10.0  # plafond du gain par pari pour le ROI winsorisé (neutralise la chance longshot)
# Nb MINIMUM de paris filtrés pour qu'un edge soit déclaré « qui tient ». En-dessous,
# win_filt/ROI sont dominés par la variance (ex. 10 paris → +233% = bruit, pas un edge).
# Règle no-fake-data : on ne clame jamais un avantage sur un échantillon ridicule.
MIN_FILT_FOR_EDGE = 50


async def compute_edge_monitor(session: AsyncSession, test_frac: float = 0.2) -> dict:
    rows = (await session.execute(text("""
        SELECT fm.features, COALESCE((fm.features->>'cote_pmu')::float, pa.cote_pmu) AS cote_pmu,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE : features figées avant départ uniquement (le backfill/recompute
          -- post-course a computed_at > date_heure → exclu). Test edge honnête.
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
        ORDER BY c.date_heure
    """))).fetchall()
    data = [((f if isinstance(f, dict) else json.loads(f)), float(cote), int(win)) for f, cote, win in rows]
    n = len(data)
    if n < 500:
        return {"n_total": n, "insufficient": True}

    split = int(n * (1 - test_frac))
    train, test = data[:split], data[split:]

    mult = {}
    for name, pred in SIGNALS.items():
        st = pa = 0.0
        for ff, c, w in train:
            if _safe(pred, ff):
                st += 1; pa += c if w else 0
        mult[name] = max(0.6, min(1.6, 1 + (pa - st) / (st + K_SHRINK))) if st > 0 else 1.0

    def conv(ff):
        m = 1.0
        for name, pred in SIGNALS.items():
            if _safe(pred, ff):
                m *= mult.get(name, 1.0)
        return m

    fst = fpa = fpa_cap = fw = fn = 0
    for ff, c, w in test:
        if conv(ff) >= CONV_THR:
            fn += 1; fst += 1; fw += w
            if w:
                fpa += c; fpa_cap += min(c, CAP)
    bst = len(test); bw = sum(w for _, _, w in test); bpa = sum(c if w else 0 for _, c, w in test)

    win_filt = round(fw / fn, 3) if fn else None
    win_base = round(bw / bst, 3) if bst else None
    roi_filt = round((fpa - fst) / fst * 100, 1) if fst else None
    roi_cap = round((fpa_cap - fst) / fst * 100, 1) if fst else None
    roi_base = round((bpa - bst) / bst * 100, 1) if bst else None
    # Échantillon filtré suffisant ? Sinon win_filt/ROI = variance, edge NON déclarable.
    enough_filt = fn >= MIN_FILT_FOR_EDGE
    edge_ok = bool(
        enough_filt and win_filt and win_base
        and win_filt >= 1.8 * win_base and (roi_cap or -1) > 0
    )

    return {
        "n_total": n, "n_test": bst, "n_filt": fn,
        "win_filt": win_filt, "win_base": win_base,
        "roi_filt": roi_filt, "roi_cap": roi_cap, "roi_base": roi_base,
        "conv_thr": CONV_THR, "edge_ok": edge_ok,
        # Pour l'affichage honnête : sous ce seuil, ne pas clamer « l'avantage tient ».
        "enough_filt": enough_filt, "min_filt": MIN_FILT_FOR_EDGE,
    }


async def persist_edge_monitor(session: AsyncSession, snap: dict) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS edge_monitor (
            id BIGSERIAL PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.execute(text("INSERT INTO edge_monitor (data) VALUES (:d)"), {"d": json.dumps(snap)})
    await session.commit()


async def latest_edge_monitor(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text(
            "SELECT data, created_at FROM edge_monitor ORDER BY created_at DESC LIMIT 1"))).first()
        if not r:
            return None
        d = dict(r[0]); d["created_at"] = str(r[1])
        return d
    except Exception:
        return None
