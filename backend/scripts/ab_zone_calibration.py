"""
ab_zone_calibration.py — Rejeu A/B du calibrage du rapport PAR ZONE DE MARCHÉ.

Question tranchée ici : ajouter la clé (zone × type) au facteur estimé→réel
améliore-t-il le respect des tranches de profil SANS dégrader le ROI réel ?

    branche A = calibration telle qu'en production (profil × type, puis global)
    branche B = même calibration + clé (zone × type), et zone passée au moteur

Les deux branches rejouent EXACTEMENT les mêmes courses, avec les mêmes entrées
apprises (heat, poids par type, bandes d'EV) : le seul facteur qui change est le
calibrage. Toute différence observée vient donc de lui.

⚠️ Lecture seule. N'écrit rien, ne persiste aucune calibration.

Anti-fuite (mêmes règles que les autres rejeux) :
  - pronostic FIGÉ strictement avant le départ (`predictions.created_at < date_heure`) ;
  - cote FIGÉE uniquement (`cote_figee`) — jamais `participations.cote_pmu`, qui est
    réécrite avec la cote FINALE après la course ;
  - règlement aux vrais rapports PMU publiés (`services/bet_settlement`).

Ce qu'on mesure, et pourquoi :
  - ROI brut ET winsorisé (plafond ×30) : un écart énorme entre les deux = résultat
    porté par quelques gros rapports, donc non concluant ;
  - « hors bande » = part des paris GAGNANTS dont le rapport RÉELLEMENT payé tombe
    sous la tranche du profil. C'est le défaut que ce changement vise ;
  - le tout ventilé par ZONE : le changement ne doit quasiment rien faire en France
    (facteurs presque inchangés) et agir sur l'étranger ;
  - on compte les COURSES distinctes, pas seulement les paris : à ~2 % de réussite,
    le profil risqué ne se juge pas sur un nombre de tickets.

Usage (dans le conteneur api) :
    cd /app && PYTHONPATH=/app python scripts/ab_zone_calibration.py [N_COURSES]
"""
from __future__ import annotations

import asyncio
import copy
import sys
from collections import defaultdict

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services.bet_catalog import derive_bet_flags
from services.bet_settlement import settle_plan
from services.hippodromes import zone_depuis_pays
from services.mise_calculator import PROFIL_CONFIG, generer_plan, plan_to_dict

MISE = 10.0          # mise de référence, identique au plan figé (ml/profil_learning)
WINSOR_CAP = 30.0    # plafond du gain (× mise) pour le ROI winsorisé
PROFILS = ("conservateur", "equilibre", "agressif")


async def _charger(session, limite: int):
    """Courses réglées dont le pronostic a été figé avant le départ, avec cote figée."""
    cids = [r[0] for r in (await session.execute(text("""
        SELECT DISTINCT c.course_id
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        JOIN resultats res ON res.course_id = c.course_id
        WHERE r.statut = 'settled'
          AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure
          AND COALESCE(r.meta->>'backfill', '') <> 'true'
          AND res.classement IS NOT NULL
        ORDER BY c.course_id DESC
        LIMIT :lim
    """), {"lim": limite})).fetchall()]

    data = []
    for cid in cids:
        rows = (await session.execute(text("""
            SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1,
                   pr.cote_figee, pa.non_partant
            FROM predictions pr
            JOIN participations pa ON pa.participation_id = pr.participation_id
            JOIN chevaux ch ON ch.cheval_id = pa.cheval_id
            JOIN courses co ON co.course_id = pa.course_id
            WHERE pa.course_id = :c
              AND co.date_heure IS NOT NULL AND pr.created_at < co.date_heure
              AND pr.cote_figee IS NOT NULL
            ORDER BY pr.rang_predit
        """), {"c": cid})).fetchall()
        # Un champ amputé fausserait la simulation (probabilités, couvertures) :
        # on exige la cote figée sur TOUS les partants, sinon on saute la course.
        nb_participations = (await session.execute(text(
            "SELECT count(*) FROM participations WHERE course_id = :c"), {"c": cid})).scalar()
        if not rows or len(rows) < (nb_participations or 0):
            continue
        ci = (await session.execute(text("""
            SELECT co.est_quinte, co.est_quarte, co.est_tierce, co.est_2sur4, co.nb_partants,
                   co.paris_disponibles, co.discipline, h.pays
            FROM courses co LEFT JOIN hippodromes h ON h.nom = co.hippodrome_nom
            WHERE co.course_id = :c
        """), {"c": cid})).first()
        res = (await session.execute(text(
            "SELECT classement, rapports, rapports_detail FROM resultats WHERE course_id = :c"
        ), {"c": cid})).first()
        if not ci or not res or not res[0]:
            continue
        course_info = derive_bet_flags(
            ci[5], est_tierce=bool(ci[2]), est_quarte=bool(ci[1]),
            est_quinte=bool(ci[0]), est_2sur4=bool(ci[3]),
        )
        course_info["nb_partants"] = ci[4]
        course_info["discipline"] = ci[6]
        preds = [{"numero": r[0], "nom_cheval": r[1], "proba_top3": r[2],
                  "proba_top1": r[3], "cote_pmu": r[4], "non_partant": r[5]} for r in rows]
        data.append({
            "course_id": cid, "preds": preds, "course_info": course_info,
            "zone": zone_depuis_pays(ci[7]),
            "classement": res[0], "rapports": res[1], "rapports_detail": res[2],
            "nb_partants": ci[4] or len(preds),
        })
    return data


def _stat():
    return {"mise": 0.0, "gain": 0.0, "gainw": 0.0, "n": 0, "win": 0,
            "hors_bande": 0, "courses": set(), "attente": 0}


def _agrege(cible, bilan, profil, course_id):
    seuil = PROFIL_CONFIG[profil]["gain_cible_mult"]
    cible["courses"].add(course_id)
    for p in bilan["paris"]:
        if p["statut"] == "en_attente":
            cible["attente"] += 1
            continue
        if p["statut"] == "rembourse":
            continue
        mise = float(p["mise"] or 0)
        gagne = p["statut"] == "gagne"
        gain = float(p["gain"] or 0) if gagne else 0.0
        cible["n"] += 1
        cible["mise"] += mise
        cible["gain"] += gain
        cible["gainw"] += min(gain, mise * WINSOR_CAP)
        if gagne:
            cible["win"] += 1
            # « hors bande » se juge sur le multiple RÉELLEMENT payé rapporté à la
            # mise du ticket — la grandeur que voit l'utilisateur au palmarès.
            if mise > 0 and (gain / mise) < seuil:
                cible["hors_bande"] += 1


def _roi(g, m):
    return (g - m) / m * 100 if m > 0 else 0.0


async def main(limite=4000):
    async with AsyncSessionLocal() as s:
        from ml.bet_performance import compute_type_roi_weights, get_model_heat
        from ml.signal_performance import (
            compute_rapport_calibration, load_ev_band_performance,
            load_rapport_calibration,
        )

        heat = await get_model_heat(s)
        rw = await compute_type_roi_weights(s)
        ev_band_perf = await load_ev_band_performance(s)

        # A = ce que la production applique aujourd'hui (aucune clé de zone).
        calib_a = copy.deepcopy(await load_rapport_calibration(s) or {})
        calib_a.pop("zones", None)
        # B = calibration recalculée AVEC les zones. La clé annexe payout_buckets
        # n'est pas recalculée ici : on la reprend de A, sinon son absence changerait
        # le tilt par tranche de rapport et polluerait la comparaison.
        calib_b = await compute_rapport_calibration(s)
        for cle in ("payout_buckets",):
            if cle in calib_a and cle not in calib_b:
                calib_b[cle] = calib_a[cle]

        print(f"heat={heat}")
        for zone, types in sorted((calib_b.get("zones") or {}).items()):
            for t, e in sorted(types.items(), key=lambda kv: -kv[1]["n_win"]):
                if e["n_win"] >= 8:
                    print(f"   {zone:4s} {t:18s} n_win={e['n_win']:5d} facteur={e['factor']}")

        data = await _charger(s, limite)
        print(f"\ncourses rejouables (figées avant départ, cote figée) : {len(data)}")

    agg = defaultdict(_stat)     # (branche, zone, profil) -> stats
    for d in data:
        zone_lbl = d["zone"] or "?"
        for profil in PROFILS:
            for branche, calib, zone in (("A", calib_a, None), ("B", calib_b, d["zone"])):
                try:
                    plan = plan_to_dict(generer_plan(
                        MISE, profil, d["preds"], d["course_info"], None, rw, heat,
                        respect_montant=True, rapport_calib=calib,
                        ev_band_perf=ev_band_perf, zone=zone))
                except Exception as e:  # noqa: BLE001 — une course KO ne casse pas le rejeu
                    print(f"  [KO] {d['course_id']} {profil} {branche}: {str(e)[:90]}")
                    continue
                bilan = settle_plan(plan, d["classement"], d["rapports"],
                                    d["nb_partants"], d["rapports_detail"])
                _agrege(agg[(branche, zone_lbl, profil)], bilan, profil, d["course_id"])

    print("\n" + "=" * 110)
    print(f"{'zone':5s} {'profil':13s} {'br':3s} {'courses':>8s} {'paris':>7s} {'gagnes':>7s} "
          f"{'hors bande':>13s} {'mise':>10s} {'ROI brut':>10s} {'ROI winso':>10s}")
    print("=" * 110)
    for zone in ("FRA", "ETR", "?"):
        for profil in PROFILS:
            vu = False
            for branche in ("A", "B"):
                a = agg.get((branche, zone, profil))
                if not a or not a["n"]:
                    continue
                vu = True
                hb = f"{a['hors_bande']}/{a['win']}"
                pct = (a["hors_bande"] / a["win"] * 100) if a["win"] else 0.0
                print(f"{zone:5s} {profil:13s} {branche:3s} {len(a['courses']):8d} {a['n']:7d} "
                      f"{a['win']:7d} {hb:>7s} {pct:5.1f}% {a['mise']:9.0f}EUR "
                      f"{_roi(a['gain'], a['mise']):9.1f}% {_roi(a['gainw'], a['mise']):9.1f}%")
            if vu:
                print("-" * 110)


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    asyncio.run(main(lim))
