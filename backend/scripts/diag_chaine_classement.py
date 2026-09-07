"""Où se perd (ou se gagne) du classement dans la chaîne servie ?

Comparaisons APPARIÉES course par course, avec IC 95 %. Lecture seule.
"""
import asyncio, json
import numpy as np
from sqlalchemy import text
from db.database import AsyncSessionLocal
from ml.ranking_metrics import within_race_auc_par_course
from ml.blend_calibration import melange, charger_alpha

Q = """
WITH gagnant AS (
  SELECT r.course_id, (e->>'numero')::int AS numero
  FROM resultats r, jsonb_array_elements(r.classement) e
  WHERE (e->>'position')::int = 1
)
SELECT pe.course_id, pa.numero::int, pe.proba_top1, pe.proba_top1_raw,
       pe.cote_figee, g.numero
FROM prediction_evaluation pe
JOIN participations pa ON pa.participation_id = pe.participation_id
JOIN courses c ON c.course_id = pe.course_id
JOIN gagnant g ON g.course_id = pe.course_id
WHERE pe.proba_top1 IS NOT NULL AND pe.proba_top1_raw IS NOT NULL
  AND pe.cote_figee IS NOT NULL AND pe.cote_figee > 0
  AND c.date_heure IS NOT NULL AND pe.created_at IS NOT NULL
  AND pe.created_at < c.date_heure
  AND c.date_heure >= now() - make_interval(days => :jours)
"""

def auc(par):
    labels, scores, groupes = [], [], []
    for cid, y, s in par:
        labels.append(y); scores.append(s); groupes.append(cid)
    return within_race_auc_par_course(np.array(labels, float), np.array(scores, float), np.array(groupes))

def apparie(a, b, nom):
    com = set(a) & set(b)
    d = np.array([a[c] - b[c] for c in com], float)
    if len(d) < 2: return {"nom": nom, "n": len(d)}
    m = float(d.mean()); se = float(d.std(ddof=1)/np.sqrt(len(d)))
    bas, haut = m-1.96*se, m+1.96*se
    return {"nom": nom, "n": len(d), "ecart": round(m,4),
            "ic95": [round(bas,4), round(haut,4)], "conclut": bool(bas>0 or haut<0)}

async def main(jours=90):
    async with AsyncSessionLocal() as db:
        alpha_max = await charger_alpha(db)
        rows = (await db.execute(text(Q), {"jours": jours})).all()
    par_course = {}
    for cid, num, servi, brut, cote, gag in rows:
        d = par_course.setdefault(cid, {"num": [], "servi": [], "brut": [], "cote": [], "gag": gag})
        d["num"].append(num); d["servi"].append(float(servi))
        d["brut"].append(float(brut)); d["cote"].append(float(cote))

    p_servi, p_brut, p_blend, p_marche = [], [], [], []
    for cid, d in par_course.items():
        if d["gag"] not in d["num"] or len(d["num"]) < 2: continue
        y = [1.0 if n == d["gag"] else 0.0 for n in d["num"]]
        praw = np.array(d["brut"]); s = praw.sum()
        praw_n = praw / s if s > 0 else praw
        bl = melange(praw_n, np.array(d["cote"]))
        for i in range(len(y)):
            p_servi.append((cid, y[i], d["servi"][i]))
            p_brut.append((cid, y[i], d["brut"][i]))
            p_blend.append((cid, y[i], float(bl[i])))
            p_marche.append((cid, y[i], 1.0/d["cote"][i]))

    a_servi, a_brut, a_blend, a_marche = auc(p_servi), auc(p_brut), auc(p_blend), auc(p_marche)
    print(f"alpha_max en service : {alpha_max}")
    print(f"fenetre {jours} j — {len(a_servi)} courses exploitables\n")
    for r in (
        apparie(a_brut,   a_marche, "modele nu      vs marche"),
        apparie(a_blend,  a_marche, "melange seul   vs marche"),
        apparie(a_servi,  a_marche, "produit servi  vs marche"),
        apparie(a_blend,  a_brut,   "APPORT du melange (blend - brut)"),
        apparie(a_servi,  a_blend,  "APPORT du post-traitement (servi - blend)"),
    ):
        print(json.dumps(r, ensure_ascii=False))
asyncio.run(main())
