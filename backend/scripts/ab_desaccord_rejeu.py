"""Rejeu A/B — jouer le Simple Gagnant du rang 1 quand le modele contredit le marche.

Ce que la mesure du jour a etabli, et pourquoi ce rejeu existe :
  - 1 EUR SG a plat sur le rang 1, courses de DESACCORD : +11,45 % (837 courses,
    robuste au retrait des 5 plus gros gains, stable sur 2 trimestres) ;
  - les PLANS reels sur ces memes courses : -6,32 %.
L'avantage vit dans le classement et meurt dans la construction du plan. On mesure
donc, en rejeu, ce qu'on recupere en jouant le signal tel qu'il a ete mesure.

DISCIPLINE DE METHODE (memoire blackturf-rejeu-ab-0823) :
  - JEU DE COURSES FIGE par une borne de date. Une fenetre glissante
    (ORDER BY date_heure DESC LIMIT n) n'est PAS un A/B : elle se decale a chaque
    arrivee, et un premier sondage avait ainsi annonce "+13 a +19 points, quatre
    mesures concordantes" — pur artefact.
  - Les DEUX bras tournent dans le MEME processus sur la MEME liste : seule la
    variable d'environnement change entre deux appels.
  - Anti-fuite : predictions.created_at < courses.date_heure, et cote_figee,
    jamais la cote finale.
  - Winsorisation a 50x la mise, ET retrait des plus gros gains : une cellule qui
    s'effondre quand on retire 20 gagnants n'est pas une cellule rentable.
  - CONTROLE : les courses d'ACCORD ne doivent pas bouger d'un centime entre les
    bras. Si elles bougent, la variante fuit hors de son perimetre.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
from collections import defaultdict

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services.mise_calculator import generer_plan, plan_to_dict
from services.bet_settlement import settle_plan
from ml.bet_performance import compute_type_roi_weights

# asyncpg exige un datetime, pas une chaine : une borne en texte leve DataError.
BORNE = _dt.datetime(2026, 9, 1, tzinfo=_dt.timezone.utc)
WINSOR = 50.0
MONTANT = 20


async def _charger(s, limite):
    cids = [r[0] for r in (await s.execute(text("""
        SELECT c.course_id FROM courses c
        JOIN resultats r ON r.course_id = c.course_id
        WHERE c.statut = 'termine' AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL AND c.date_heure < :borne
        ORDER BY c.date_heure DESC LIMIT :lim
    """), {"borne": BORNE, "lim": limite})).fetchall()]
    data = []
    for cid in cids:
        rows = (await s.execute(text("""
            SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1, pr.cote_figee,
                   pa.non_partant
            FROM predictions pr
            JOIN participations pa ON pa.participation_id = pr.participation_id
            JOIN chevaux ch ON ch.cheval_id = pa.cheval_id
            JOIN courses co ON co.course_id = pr.course_id
            WHERE pa.course_id = :c
              AND co.date_heure IS NOT NULL AND pr.created_at < co.date_heure
              AND pr.cote_figee IS NOT NULL AND pr.cote_figee > 1.0
            ORDER BY pr.rang_predit
        """), {"c": cid})).fetchall()
        if len(rows) < 4:
            continue
        preds = [{"numero": r[0], "nom_cheval": r[1], "proba_top3": r[2],
                  "proba_top1": r[3], "cote_pmu": r[4], "non_partant": r[5]} for r in rows]
        ci_r = (await s.execute(text("""
            SELECT est_quinte, est_quarte, est_tierce, est_2sur4, nb_partants,
                   paris_disponibles, discipline
            FROM courses WHERE course_id = :c"""), {"c": cid})).fetchone()
        res = (await s.execute(text("""
            SELECT classement, rapports, rapports_detail FROM resultats
            WHERE course_id = :c
        """), {"c": cid})).fetchone()
        if not ci_r or not res or not res[0]:
            continue
        ci = {"est_quinte": ci_r[0], "est_quarte": ci_r[1], "est_tierce": ci_r[2],
              "est_2sur4": ci_r[3], "nb_partants": ci_r[4],
              "paris_disponibles": ci_r[5], "discipline": ci_r[6]}
        vivants = [p for p in preds if not p["non_partant"]]
        if len(vivants) < 4:
            continue
        # DESACCORD calcule ICI, sur les memes entrees que le moteur : le deriver
        # d'une autre source ferait diverger la partition entre les deux bras.
        rang1 = max(vivants, key=lambda p: float(p["proba_top1"] or 0))["numero"]
        favori = min(vivants, key=lambda p: float(p["cote_pmu"]))["numero"]
        data.append((preds, ci, res[0], res[1], res[2],
                     {int(p["numero"]) for p in preds if p["non_partant"]},
                     int(rang1) != int(favori)))
    return data


def _agr():
    return {"mise": 0.0, "gain": 0.0, "n": 0, "gains": []}


def bras(data, entrees, mode):
    """Un bras du A/B. mode=None = production actuelle."""
    os.environ.pop("BT_DESACCORD_MODE", None)
    if mode:
        os.environ["BT_DESACCORD_MODE"] = mode
    out = defaultdict(_agr)
    for profil in ("conservateur", "equilibre", "agressif"):
        pdata = ((entrees["profil_state"].get("profils") or {}).get(profil) or {})
        for preds, ci, cl, rp, rd, nps, desaccord in data:
            rw = entrees["rw"]
            if entrees["etw"] and pdata:
                rw = entrees["etw"](pdata, ci.get("discipline"), ci.get("nb_partants"))
            plan = generer_plan(MONTANT, profil, preds, ci, roi_weights=rw,
                                heat=entrees["heat"], rapport_calib=entrees["rc"],
                                ev_band_perf=entrees["ev"], respect_montant=False)
            bilan = settle_plan(plan_to_dict(plan), cl, rp, ci.get("nb_partants") or 0,
                                rd, nps)
            seg = "desaccord" if desaccord else "accord"
            for cle in ((profil, seg), (profil, "TOUS")):
                a = out[cle]
                for pari in bilan.get("paris", []):
                    m = float(pari.get("mise") or 0)
                    statut = pari.get("statut")
                    if m <= 0:
                        continue
                    # `gain` vaut None pour un pari PERDU comme pour un pari en attente
                    # de rapport : filtrer sur `gain is None` ne gardait que les
                    # GAGNANTS et donnait des ROI a +1400 %. Le statut tranche.
                    if statut == "en_attente":
                        continue          # rapport non publie : jamais de gain invente
                    if statut == "rembourse":
                        continue          # non-partant : neutre, ni mise ni gain
                    g = float(pari.get("gain") or 0.0) if statut == "gagne" else 0.0
                    a["mise"] += m
                    a["gain"] += g
                    a["gains"].append(g)
                    a["n"] += 1
    os.environ.pop("BT_DESACCORD_MODE", None)
    return out


def roi(a, retirer=0):
    if not a["mise"]:
        return float("nan")
    g = sorted(a["gains"], reverse=True)[retirer:]
    return 100 * (sum(min(x, WINSOR * MONTANT) for x in g) - a["mise"]) / a["mise"]


async def main(limite=4000):
    async with AsyncSessionLocal() as s:
        rw = await compute_type_roi_weights(s)
        try:
            from ml.profil_learning import load_profil_weights, effective_type_weights
            ps = await load_profil_weights(s) or {}
        except Exception:
            ps, effective_type_weights = {}, None
        try:
            from ml.bet_performance import get_model_heat
            heat = await get_model_heat(s)
        except Exception:
            heat = 0.0
        try:
            from ml.signal_performance import (
                load_rapport_calibration, load_ev_band_performance)
            rc = await load_rapport_calibration(s)
            ev = await load_ev_band_performance(s)
        except Exception:
            rc = ev = None
        data = await _charger(s, limite)

    nd = sum(1 for d in data if d[6])
    print("jeu FIGE : %d courses avant %s  (desaccord %d = %.1f %%)\n"
          % (len(data), BORNE.isoformat(), nd, 100 * nd / max(len(data), 1)))
    entrees = {"rw": rw, "profil_state": ps, "etw": effective_type_weights,
               "heat": heat, "rc": rc, "ev": ev}

    res = {}
    for nom, mode in (("BASE", None), ("sg_seul", "sg_seul"),
                      ("sg_prioritaire", "sg_prioritaire")):
        res[nom] = bras(data, entrees, mode)
        print("  bras %s termine" % nom)
    print()

    entete = ("%-14s %-10s %-16s %6s %9s %9s %9s"
              % ("profil", "segment", "bras", "n", "ROI", "sans 5", "sans 20"))
    print(entete)
    for profil in ("conservateur", "equilibre", "agressif"):
        for seg in ("accord", "desaccord", "TOUS"):
            for nom in ("BASE", "sg_seul", "sg_prioritaire"):
                a = res[nom].get((profil, seg))
                if not a or not a["n"]:
                    continue
                print("%-14s %-10s %-16s %6d %8.2f%% %8.2f%% %8.2f%%"
                      % (profil, seg, nom, a["n"], roi(a), roi(a, 5), roi(a, 20)))
            print()

    print("CONTROLE — les courses d'ACCORD doivent etre IDENTIQUES entre les bras :")
    for profil in ("conservateur", "equilibre", "agressif"):
        b = res["BASE"].get((profil, "accord"))
        for nom in ("sg_seul", "sg_prioritaire"):
            v = res[nom].get((profil, "accord"))
            ok = (b and v and abs(b["mise"] - v["mise"]) < 1e-6
                  and abs(b["gain"] - v["gain"]) < 1e-6)
            print("   %-14s %-16s %s"
                  % (profil, nom, "OK" if ok else "DIVERGE <<< la variante fuit"))


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 4000))
