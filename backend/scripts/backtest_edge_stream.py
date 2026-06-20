"""
backtest_edge_stream.py — version MÉMOIRE-BORNÉE de backtest_edge.py.

Identique en méthode (re-score le modèle actif, blend marché ALPHA, ROI par bande
d'EV + walk-forward mensuel sur la bande STRAT EV1.0-1.2 cote4-20) mais traite les
courses par CHUNKS : ne charge jamais les 146k features en RAM d'un coup (l'ancien
fetchall OOM-killait le worker en journée). On ne garde que les tuples compacts
(ev, cote, win). Read-only.

  docker compose -f docker-compose.prod.yml exec -T worker python scripts/backtest_edge_stream.py
"""
import sys, os, json, asyncio, gc
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import numpy as np
import pandas as pd
from sqlalchemy import text
import db.models  # noqa
from db.database import AsyncSessionLocal
from ml.models import BlackTurfEnsemble

ALPHA_MAX, ALPHA_MIN, ALPHA_FULL_COTE, ALPHA_DECAY = 0.55, 0.15, 12.0, 0.022
CHUNK = 80  # courses par lot (petit = pic mémoire borné, host saturé)


def market_blend(p1, cotes):
    s1 = p1.sum()
    p1 = (p1 / s1) if s1 > 0 else np.full(len(p1), 1.0 / len(p1))
    alpha = np.clip(ALPHA_MAX - ALPHA_DECAY * np.maximum(cotes - ALPHA_FULL_COTE, 0.0),
                    ALPHA_MIN, ALPHA_MAX)
    implied = np.where(cotes > 1.0, 1.0 / cotes, 0.0)
    si = implied.sum()
    if si > 0:
        implied_norm = implied / si
        blend = np.where(implied > 0, alpha * p1 + (1.0 - alpha) * implied_norm, p1)
        bs = blend.sum()
        if bs > 0:
            return blend / bs
    return p1


def roi(rows):
    if not rows:
        return (0, None, None)
    n = len(rows)
    wins = sum(w for _, _, w in rows)
    ret = sum(c if w else 0 for _, c, w in rows)
    return (n, round(wins / n * 100, 1), round((ret - n) / n * 100, 1))


def report(label, rows):
    bands = [("a <0.7", lambda e: e < 0.7), ("b 0.7-0.9", lambda e: 0.7 <= e < 0.9),
             ("c 0.9-1.0", lambda e: 0.9 <= e < 1.0), ("d 1.0-1.15", lambda e: 1.0 <= e < 1.15),
             ("e 1.15-1.4", lambda e: 1.15 <= e < 1.4), ("f >1.4", lambda e: e >= 1.4)]
    print(f"\n===== {label} (n={len(rows)}) =====", flush=True)
    for name, pred in bands:
        sub = [(e, c, w) for e, c, w in rows if pred(e)]
        n, wp, r = roi(sub)
        print(f"  EV {name:10s} n={n:6d} win={wp}  roi={r}%", flush=True)
    strat = [(e, c, w) for e, c, w in rows if 1.0 <= e < 1.2 and 4 <= c <= 20]
    n, wp, r = roi(strat)
    print(f"  >> STRAT EV1.0-1.2 cote4-20  n={n:6d} win={wp}  roi={r}%", flush=True)


async def main():
    model = BlackTurfEnsemble.load_current()
    assert model is not None, "no current model"
    print("model loaded, n_features:", len(getattr(model, "feature_names", []) or []), flush=True)

    # 1) Liste légère des courses terminées (id + date), ordre temporel.
    async with AsyncSessionLocal() as s:
        crows = (await s.execute(text("""
            SELECT DISTINCT c.course_id, c.date_heure
            FROM courses c
            JOIN participations pa ON pa.course_id = c.course_id
            JOIN features_ml fm ON fm.participation_id = pa.participation_id
            JOIN resultats r ON r.course_id = c.course_id
            WHERE c.statut='termine' AND c.date_heure IS NOT NULL
              AND jsonb_typeof(r.classement)='array' AND fm.computed_at < c.date_heure
            ORDER BY c.date_heure, c.course_id
        """))).fetchall()
    course_ids = [cid for cid, _ in crows]
    cdate = {cid: dh for cid, dh in crows}
    print("courses:", len(course_ids), flush=True)

    # Écriture sur disque (RAM quasi-plate, survit à un OOM-kill → agrégat du partiel).
    # RÉSUMABLE : marqueur de progression → re-run reprend où il s'est arrêté (host saturé
    # tue le process périodiquement ; quelques re-runs couvrent les 15k courses).
    out_path = "/tmp/bt_edge_records.csv"
    prog_path = "/tmp/bt_edge_progress.txt"
    resume_at = 0
    if os.path.exists(prog_path) and os.path.exists(out_path):
        try:
            resume_at = int(open(prog_path).read().strip())
        except Exception:
            resume_at = 0
    if resume_at > 0:
        fout = open(out_path, "a")
        print(f"RESUME @ course index {resume_at}", flush=True)
    else:
        fout = open(out_path, "w")
        fout.write("ev,cote,win,month\n")
    done = resume_at
    for start in range(resume_at, len(course_ids), CHUNK):
        batch = course_ids[start:start + CHUNK]
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT pa.course_id,
                       COALESCE((fm.features->>'cote_pmu')::float, pa.cote_pmu) AS cote_pmu,
                       fm.features,
                       CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
                FROM features_ml fm
                JOIN participations pa ON pa.participation_id = fm.participation_id
                JOIN resultats r ON r.course_id = pa.course_id
                WHERE pa.course_id = ANY(:ids) AND pa.cote_pmu > 1
                ORDER BY pa.course_id
            """), {"ids": batch})).fetchall()
        parts = defaultdict(list)
        for cid, cote, feats, win in rows:
            f = feats if isinstance(feats, dict) else json.loads(feats)
            parts[cid].append((f, float(cote), int(win)))
        for cid, pl in parts.items():
            feats = [p[0] for p in pl]
            cotes = np.array([p[1] for p in pl])
            wins = [p[2] for p in pl]
            X = pd.DataFrame(feats)
            try:
                p1 = model.predict_win_proba(X)
                if p1 is None or len(p1) != len(pl):
                    p3 = model.predict_proba(X)
                    p1 = np.asarray(p3, dtype=float) ** 1.6
                p1 = np.clip(np.asarray(p1, dtype=float), 1e-6, 0.999)
            except Exception:
                continue
            proba = market_blend(p1, cotes)
            ev = proba * cotes
            mon = str(cdate[cid])[:7]
            for i in range(len(pl)):
                fout.write(f"{float(ev[i]):.5f},{float(cotes[i]):.3f},{wins[i]},{mon}\n")
            done += 1
        fout.flush()
        nxt = min(start + CHUNK, len(course_ids))
        with open(prog_path, "w") as pf:
            pf.write(str(nxt))
        del rows, parts
        gc.collect()
        if (start // CHUNK) % 10 == 0:
            print(f"  scored up to course {nxt}/{len(course_ids)}", flush=True)
    fout.close()
    print(f"DONE scoring {done} courses → {out_path}", flush=True)
    aggregate(out_path)


def aggregate(path):
    """Agrège le CSV (streaming) → ROI par bande + walk-forward mensuel. Robuste au
    partiel : si le scoring a été tué, on agrège ce qui a été écrit."""
    from collections import defaultdict
    all_rows = []
    by_month = defaultdict(list)
    with open(path) as f:
        next(f, None)
        for line in f:
            parts = line.rstrip("\n").split(",")
            if len(parts) != 4:
                continue
            ev, cote, win, mon = float(parts[0]), float(parts[1]), int(parts[2]), parts[3]
            all_rows.append((ev, cote, win))
            by_month[mon].append((ev, cote, win))
    report("GLOBAL (toutes courses)", all_rows)
    print("\n===== WALK-FORWARD MENSUEL : bande STRAT EV1.0-1.2 cote4-20 =====", flush=True)
    for mon in sorted(by_month):
        strat = [(e, c, w) for e, c, w in by_month[mon] if 1.0 <= e < 1.2 and 4 <= c <= 20]
        n, wp, r = roi(strat)
        tot = len(by_month[mon])
        print(f"  {mon}  rows={tot:6d}  strat_n={n:5d}  win={wp}  roi={r}%", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
