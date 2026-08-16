"""
backtest_mise.py — Backtest RÉEL du moteur de plan de mise.

Rejoue `generer_plan` sur les courses TERMINÉES (vraies prédictions sauvegardées),
règle chaque pari contre le RÉSULTAT officiel + vrais rapports PMU (bet_settlement),
et agrège le ROI réel par profil / palier / type de pari.

Intégrité : 100% données réelles. Les paris dont le rapport PMU n'est pas publié
(jackpots, 2sur4 sans e_deux_sur_quatre) sont comptés "en attente" et EXCLUS du ROI
(jamais de gain inventé).

⚠️ Lecture seule. Ne modifie aucune donnée.

Usage (dans le conteneur api) :
    cd /app && PYTHONPATH=/app python scripts/backtest_mise.py [N_COURSES] [MONTANT]

Le ROI "brut" inclut les gros rapports (queue épaisse → forte variance sur petit
échantillon). Le ROI "winsorisé" plafonne chaque gain à 30× la mise pour estimer
le rendement TYPIQUE hors coups de chance. Comparer les deux : un grand écart =
résultat dominé par la variance → non concluant, rassembler plus de données.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services.mise_calculator import generer_plan, plan_to_dict
from services.bet_settlement import settle_plan
from ml.bet_performance import compute_type_roi_weights

WINSOR_CAP = 30.0   # plafond du gain (× mise) pour le ROI winsorisé


async def _load(session, limit):
    cids = [r[0] for r in (await session.execute(text("""
        SELECT c.course_id FROM courses c
        JOIN resultats r ON r.course_id = c.course_id
        WHERE c.statut = 'termine' AND r.classement IS NOT NULL
          AND EXISTS (SELECT 1 FROM predictions p WHERE p.course_id = c.course_id)
        ORDER BY c.date_heure DESC LIMIT :lim
    """), {"lim": limit})).fetchall()]
    data = []
    for cid in cids:
        rows = (await session.execute(text("""
            SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1,
                   COALESCE(pr.cote_figee, pa.cote_pmu), pa.non_partant
            FROM predictions pr
            JOIN participations pa ON pa.participation_id = pr.participation_id
            JOIN chevaux ch ON ch.cheval_id = pa.cheval_id
            JOIN courses co ON co.course_id = pr.course_id
            WHERE pa.course_id = :c
              AND co.date_heure IS NOT NULL AND pr.created_at < co.date_heure
            ORDER BY pr.rang_predit
        """), {"c": cid})).fetchall()
        if not rows:
            continue
        preds = [{"numero": r[0], "nom_cheval": r[1], "proba_top3": r[2],
                  "proba_top1": r[3], "cote_pmu": r[4], "non_partant": r[5]} for r in rows]
        ci = (await session.execute(text(
            """SELECT est_quinte, est_quarte, est_tierce, est_2sur4, nb_partants,
                      paris_disponibles, discipline
               FROM courses WHERE course_id = :c"""
        ), {"c": cid})).first()
        res = (await session.execute(text(
            "SELECT classement, rapports, rapports_detail FROM resultats WHERE course_id = :c"
        ), {"c": cid})).first()
        from services.bet_catalog import derive_bet_flags
        course_info = derive_bet_flags(
            ci[5], est_tierce=bool(ci[2]), est_quarte=bool(ci[1]),
            est_quinte=bool(ci[0]), est_2sur4=bool(ci[3]),
        )
        course_info["nb_partants"] = ci[4]
        course_info["discipline"] = ci[6]
        data.append((preds,
                     course_info, res[0], res[1], res[2], ci[4] or len(preds)))
    return data


def _roi(g, m):
    return (g - m) / m * 100 if m > 0 else 0.0


async def main(limit=400, montants=(5, 20, 100)):
    async with AsyncSessionLocal() as s:
        # Reproduire les mêmes entrées apprises que /mise-plan et profil_run_log.
        # Le repli bankroll reste utile si l'état profils n'existe pas encore.
        rw_fallback = await compute_type_roi_weights(s)
        try:
            from ml.profil_learning import load_profil_weights, effective_type_weights
            profil_state = await load_profil_weights(s) or {}
        except Exception:
            profil_state = {}
            effective_type_weights = None
        try:
            from ml.bet_performance import get_model_heat
            heat = await get_model_heat(s)
        except Exception:
            heat = 0.0
        try:
            from ml.signal_performance import (
                load_rapport_calibration, load_ev_band_performance,
            )
            rapport_calib = await load_rapport_calibration(s)
            ev_band_perf = await load_ev_band_performance(s)
        except Exception:
            rapport_calib = ev_band_perf = None

        data = await _load(s, limit)
        print(f"courses testables : {len(data)} | roi_weights repli : {rw_fallback}"
              f" | heat={heat}\n")

        glob = defaultdict(lambda: {"mise": 0.0, "gain": 0.0, "gainw": 0.0, "n": 0, "win": 0,
                                    "att": 0, "courses": 0})
        bytype = defaultdict(lambda: {"mise": 0.0, "gain": 0.0, "gainw": 0.0, "n": 0, "win": 0})

        for profil in ("conservateur", "equilibre", "agressif"):
            for m in montants:
                key = (profil, m)
                a = glob[key]
                pdata = ((profil_state.get("profils") or {}).get(profil) or {})
                for preds, ci, cl, rp, rd, nbp in data:
                    a["courses"] += 1
                    if effective_type_weights and pdata:
                        rw = effective_type_weights(
                            pdata, ci.get("discipline"), ci.get("nb_partants")
                        )
                    else:
                        rw = rw_fallback
                    plan = plan_to_dict(generer_plan(
                        m, profil, preds, ci, None, rw, heat,
                        respect_montant=True,
                        rapport_calib=rapport_calib,
                        ev_band_perf=ev_band_perf,
                    ))
                    bilan = settle_plan(plan, cl, rp, nbp, rd)
                    for p in bilan["paris"]:
                        if p["statut"] == "en_attente":
                            a["att"] += 1
                            continue
                        g = (p["gain"] or 0) if p["statut"] == "gagne" else 0
                        gw = min(g, p["mise"] * WINSOR_CAP)
                        a["mise"] += p["mise"]; a["gain"] += g; a["gainw"] += gw; a["n"] += 1
                        a["win"] += 1 if p["statut"] == "gagne" else 0
                        if profil == "equilibre" and m == 20:
                            t = bytype[p["type"]]
                            t["mise"] += p["mise"]; t["gain"] += g; t["gainw"] += gw
                            t["n"] += 1; t["win"] += 1 if p["statut"] == "gagne" else 0

        print(f"{'profil':13}{'mont':>5}{'paris':>7}{'/crs':>6}{'win%':>7}{'mise':>9}{'ROI%':>9}{'ROIw%':>8}{'att':>5}")
        for profil in ("conservateur", "equilibre", "agressif"):
            for m in montants:
                a = glob[(profil, m)]
                pc = a["n"] / a["courses"] if a["courses"] else 0
                wr = a["win"] / a["n"] * 100 if a["n"] else 0
                print(f"{profil:13}{m:>5}{a['n']:>7}{pc:>6.1f}{wr:>7.1f}{a['mise']:>9.0f}"
                      f"{_roi(a['gain'], a['mise']):>9.1f}{_roi(a['gainw'], a['mise']):>8.1f}{a['att']:>5}")

        print(f"\nPar type (equilibre / {montants[1] if len(montants) > 1 else montants[0]}€) :")
        print(f"{'type':16}{'n':>5}{'win%':>7}{'mise':>8}{'ROI%':>9}{'ROIw%':>8}")
        for t, b in sorted(bytype.items(), key=lambda x: -x[1]["mise"]):
            wr = b["win"] / b["n"] * 100 if b["n"] else 0
            print(f"{t:16}{b['n']:>5}{wr:>7.1f}{b['mise']:>8.0f}"
                  f"{_roi(b['gain'], b['mise']):>9.1f}{_roi(b['gainw'], b['mise']):>8.1f}")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    asyncio.run(main(limit=lim))
