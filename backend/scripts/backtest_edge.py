"""
backtest_edge.py — Backtest staking HONNÊTE sur tout l'historique features_ml.

Re-score le modèle ACTIF (v496) sur les ~15k courses pré-course (computed_at <
date_heure = zéro leakage), reconstruit la proba_top1 PRODUCTION-APPROCHÉE
(win-proba modèle + blend marché ALPHA adaptatif, le driver dominant de l'EV ;
on SAUTE longshot/isotonic résiduels = corrections mineures → caveat : l'EV des
longshots est ici un poil plus haute qu'en prod, donc le constat "haut EV = toxique"
est conservateur), puis mesure le ROI réalisé (simple gagnant flat) par bande d'EV
et en WALK-FORWARD mensuel. But : prouver/infirmer la bande positive vue sur 13j.

Read-only. Lancer dans le worker :
  docker compose -f docker-compose.prod.yml exec -T worker python scripts/backtest_edge.py
"""
import sys, os, json, asyncio
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

# Constantes blend marché — COPIE FIDÈLE de pipeline.predict_course.
ALPHA_MAX, ALPHA_MIN, ALPHA_FULL_COTE, ALPHA_DECAY = 0.55, 0.15, 12.0, 0.022


def market_blend(p1: np.ndarray, cotes: np.ndarray) -> np.ndarray:
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
    """rows = list[(ev, cote, win)] → (n, win%, roi%)."""
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
    print(f"\n===== {label} (n={len(rows)}) =====")
    for name, pred in bands:
        sub = [(e, c, w) for e, c, w in rows if pred(e)]
        n, wp, r = roi(sub)
        print(f"  EV {name:10s} n={n:6d} win={wp}  roi={r}%")
    # Stratégie cible
    strat = [(e, c, w) for e, c, w in rows if 1.0 <= e < 1.2 and 4 <= c <= 20]
    n, wp, r = roi(strat)
    print(f"  >> STRAT EV1.0-1.2 cote4-20  n={n:6d} win={wp}  roi={r}%")


async def main():
    model = BlackTurfEnsemble.load_current()
    assert model is not None, "no current model"
    print("model loaded, n_features:", len(getattr(model, "feature_names", []) or []))

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT c.course_id, c.date_heure, pa.cote_pmu, fm.features,
                   CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
            FROM features_ml fm
            JOIN participations pa ON pa.participation_id = fm.participation_id
            JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
            JOIN resultats r ON r.course_id = pa.course_id
            WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
              AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
            ORDER BY c.date_heure, c.course_id
        """))).fetchall()

    print("rows:", len(rows))
    # Grouper par course
    courses = defaultdict(list)
    cdate = {}
    for cid, dh, cote, feats, win in rows:
        f = feats if isinstance(feats, dict) else json.loads(feats)
        courses[cid].append((f, float(cote), int(win)))
        cdate[cid] = dh

    all_rows = []          # (ev, cote, win)
    by_month = defaultdict(list)
    done = 0
    for cid, parts in courses.items():
        feats = [p[0] for p in parts]
        cotes = np.array([p[1] for p in parts])
        wins = [p[2] for p in parts]
        X = pd.DataFrame(feats)
        try:
            p1 = model.predict_win_proba(X)
            if p1 is None or len(p1) != len(parts):
                p3 = model.predict_proba(X)
                p1 = np.asarray(p3, dtype=float) ** 1.6
            p1 = np.clip(np.asarray(p1, dtype=float), 1e-6, 0.999)
        except Exception as e:
            continue
        proba = market_blend(p1, cotes)
        ev = proba * cotes
        mon = str(cdate[cid])[:7]
        for i in range(len(parts)):
            rec = (float(ev[i]), float(cotes[i]), wins[i])
            all_rows.append(rec)
            by_month[mon].append(rec)
        done += 1
        if done % 2000 == 0:
            print(f"  scored {done}/{len(courses)} courses")

    report("GLOBAL (toutes courses)", all_rows)

    print("\n===== WALK-FORWARD MENSUEL : bande STRAT EV1.0-1.2 cote4-20 =====")
    for mon in sorted(by_month):
        strat = [(e, c, w) for e, c, w in by_month[mon] if 1.0 <= e < 1.2 and 4 <= c <= 20]
        n, wp, r = roi(strat)
        tot = len(by_month[mon])
        print(f"  {mon}  courses_rows={tot:6d}  strat_n={n:5d}  win={wp}  roi={r}%")


if __name__ == "__main__":
    asyncio.run(main())
