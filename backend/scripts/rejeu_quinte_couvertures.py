"""
rejeu_quinte_couvertures.py — ROI historique du module Quinté+ par couverture.

Lecture seule. Pour chaque course Quinté+ terminée dont les prédictions ont été
figées AVANT le départ (prediction_evaluation, created_at < date_heure) et dont
le détail des rapports est publié, construit le ticket du module (tendu, champ 6,
champ 7) avec les mêmes fonctions que la production, puis le règle aux vrais
rapports PMU (settle_module_quinte : Désordre, Ordre, Bonus 4sur5, Bonus 3).

Sert à fixer les parts du Quinté+ (15/20/25 %) sur une mesure plutôt qu'un choix.

    python scripts/rejeu_quinte_couvertures.py [--jours 365]
"""
import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np  # noqa: E402
import db.models  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402
from db.database import AsyncSessionLocal  # noqa: E402
from services import mise_calculator as mc  # noqa: E402
from services.bet_settlement import settle_module_quinte  # noqa: E402
from services.bet_catalog import derive_bet_flags  # noqa: E402


def _j(v):
    if isinstance(v, (dict, list)):
        return v
    return json.loads(v) if isinstance(v, str) and v else None


async def main(jours: int) -> int:
    async with AsyncSessionLocal() as s:
        courses = (await s.execute(text("""
            SELECT c.course_id, c.nb_partants, c.paris_disponibles, c.est_tierce,
                   c.est_quarte, c.est_2sur4, r.classement, r.rapports, r.rapports_detail
            FROM courses c JOIN resultats r ON r.course_id = c.course_id
            WHERE c.est_quinte = true AND c.statut = 'termine'
              AND r.classement IS NOT NULL AND r.rapports_detail ? 'e_quinte_plus'
              AND c.date_heure > now() - make_interval(days => :j)
            ORDER BY c.date_heure
        """), {"j": jours})).all()
        agg = {n: {"n": 0, "mise": 0.0, "gain": 0.0, "gagnants": 0, "bonus": 0,
                   "gains": []} for n in (5, 6, 7)}
        n_ok = 0
        for cid, nbp, pd, et, eq, e24, cl, rp, det in courses:
            det = _j(det) or {}
            if not any("libelle" in e for e in det.get("e_quinte_plus", [])):
                continue  # anciennes collectes sans libellés : non réglables
            preds = (await s.execute(text("""
                SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1,
                       COALESCE(pr.cote_figee, pa.cote_pmu), pa.non_partant
                FROM prediction_evaluation pr
                JOIN participations pa ON pa.participation_id = pr.participation_id
                JOIN chevaux ch ON ch.cheval_id = pa.cheval_id
                JOIN courses co ON co.course_id = pr.course_id
                WHERE pa.course_id = :c AND pr.created_at < co.date_heure
            """), {"c": cid})).all()
            if len(preds) < 5:
                continue
            np_rows = {int(r[0]) for r in preds if r[5]}
            p = [{"numero": r[0], "nom_cheval": r[1], "proba_top3": r[2], "proba_top1": r[3],
                  "cote_pmu": r[4], "non_partant": r[5]} for r in preds]
            info = derive_bet_flags(_j(pd), est_tierce=bool(et), est_quarte=bool(eq),
                                    est_quinte=True, est_2sur4=bool(e24))
            info["nb_partants"] = nbp
            cl = _j(cl) or []
            n_ok += 1
            for n in (5, 6, 7):
                # Montant assez grand pour que la part du profil paie ce champ :
                # tendu 20 € (prudent), champ 6 70 € (modéré 20 %), champ 7 180 €
                # (risqué 25 %). Force la couverture n sans toucher à la règle.
                mod = mc._construire_module_quinte(
                    p, info, {5: "conservateur", 6: "equilibre", 7: "agressif"}[n],
                    {5: 20, 6: 70, 7: 180}[n])
                if not mod or not mod.get("disponible") or mod.get("nb_chevaux") != n:
                    continue
                res = settle_module_quinte(mod, cl, _j(rp) or {}, nbp or len(cl), det,
                                           non_partants=np_rows)
                if res.get("en_attente"):
                    continue
                a = agg[n]
                a["n"] += 1
                a["mise"] += float(res["total_mise"])
                a["gain"] += float(res["total_gain"])
                a["gains"].append(float(res["total_gain"]) - float(res["total_mise"]))
                a["gagnants"] += 1 if res["total_gain"] > 0 else 0
                a["bonus"] += sum(1 for g in res.get("gagnantes", [])
                                  if "bonus" in str(g).lower())
    print(f"Courses Quinté+ rejouables : {n_ok}")
    for n, a in agg.items():
        if not a["n"]:
            print(f"champ {n}: aucune course")
            continue
        roi = (a["gain"] - a["mise"]) / a["mise"] * 100
        nets = np.array(a["gains"])
        # IC 95 % du ROI par bootstrap sur les courses (retours très asymétriques).
        rng = np.random.default_rng(0)
        mise_c = a["mise"] / a["n"]
        boots = [nets[rng.integers(0, len(nets), len(nets))].sum() / (mise_c * len(nets)) * 100
                 for _ in range(4000)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
        print(f"{'tendu' if n == 5 else f'champ {n}'} ({math.comb(n, 5)} comb, "
              f"{mc._cout_plein_quinte(n):g} €) : {a['n']} courses, mise {a['mise']:.0f} €, "
              f"retour {a['gain']:.0f} €, ROI {roi:+.1f} % [IC95 {lo:+.0f} ; {hi:+.0f}], "
              f"tickets payants {a['gagnants']}/{a['n']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=365)
    sys.exit(asyncio.run(main(ap.parse_args().jours)))
