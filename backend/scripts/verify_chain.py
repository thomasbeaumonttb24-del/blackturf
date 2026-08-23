"""
verify_chain.py — Audit de bout en bout du moteur de pronostic/mise.

Vérifie sur DONNÉES RÉELLES que tout est cohérent et lié :
  A. Analyse IA      : Σproba_top1≈1, Σproba_top3≈min(3,n), rang cohérent.
  B. Générateur      : EV = proba×rapport−1, edge, types (dont Simple Placé).
  C. Plan de mise    : Σmises==montant, espérance==Σmise×ev, gates profil, mode.
  D. Règlement       : règles gagné/perdu + vrais rapports (+ non-régression 2sur4).
  E. Chaîne complète : prono→plan→settlement sur courses terminées, ROI par profil.
  F. Apprentissage   : heat & roi_weights dérivés du réel et bornés.

Lecture seule. Usage : cd /app && PYTHONPATH=/app python scripts/verify_chain.py
"""
import asyncio
import collections

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services.mise_calculator import generer_plan, plan_to_dict, _effective_config, _mode_label
from services.bet_settlement import settle_pari, settle_plan
from ml.combo_bets import enumerate_bet_candidates
from ml.bet_performance import get_type_roi_weights, get_model_heat, compute_model_heat

P = [0]
F = [0]


def chk(name, cond, detail=""):
    (P if cond else F)[0] += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if (detail and not cond) else ""))


async def _course_preds(s, cid):
    rows = (await s.execute(text(
        "SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1, pa.cote_pmu, pa.non_partant "
        "FROM predictions pr JOIN participations pa ON pa.participation_id = pr.participation_id "
        "JOIN chevaux ch ON ch.cheval_id = pa.cheval_id WHERE pa.course_id = :c ORDER BY pr.rang_predit"
    ), {"c": cid})).fetchall()
    preds = [{"numero": r[0], "nom": r[1], "nom_cheval": r[1], "proba_top3": r[2],
              "proba_top1": r[3], "cote_pmu": r[4], "non_partant": r[5]} for r in rows]
    ci = (await s.execute(text(
        "SELECT est_quinte, est_quarte, est_tierce, nb_partants FROM courses WHERE course_id = :c"
    ), {"c": cid})).first()
    return preds, {"est_quinte": ci[0], "est_quarte": ci[1], "est_tierce": ci[2], "nb_partants": ci[3]}


async def main():
    async with AsyncSessionLocal() as s:
        roi_w = await get_type_roi_weights(s)
        heat = await get_model_heat(s)
        print(f"roi_weights={roi_w}\nheat={heat}\n")

        # ===== A. ANALYSE IA =====
        print("A. Analyse IA -- coherence des probabilites")
        cids = [r[0] for r in (await s.execute(text(
            "SELECT pr.course_id FROM predictions pr GROUP BY pr.course_id "
            "ORDER BY MAX(pr.created_at) DESC LIMIT 8"
        ))).fetchall()]
        for cid in cids[:5]:
            rows = (await s.execute(text(
                "SELECT pr.proba_top1, pr.proba_top3, pr.rang_predit, pa.numero, pa.non_partant "
                "FROM predictions pr JOIN participations pa ON pa.participation_id = pr.participation_id "
                "WHERE pr.course_id = :c"), {"c": cid})).fetchall()
            act = [r for r in rows if not r[4]]
            if len(act) < 3:
                continue
            n = len(act)
            s1 = sum(float(r[0]) for r in act)
            s3 = sum(float(r[1]) for r in act)
            chk(f"{cid} sum(proba_top1)~1", abs(s1 - 1.0) < 0.05, f"={s1:.3f}")
            chk(f"{cid} sum(proba_top3)~min(3,n)", abs(s3 - min(3, n)) < 0.2, f"={s3:.3f} target={min(3, n)}")
            chk(f"{cid} probas in [0,1]", all(0 <= float(r[0]) <= 1 and 0 <= float(r[1]) <= 1 for r in act))
            order = sorted(act, key=lambda r: (float(r[0]), float(r[1])), reverse=True)
            top1_rang = min(act, key=lambda r: int(r[2]))
            chk(f"{cid} rang 1 == max proba", int(top1_rang[2]) == 1 and top1_rang[3] == order[0][3])

        # ===== B. GENERATEUR =====
        print("\nB. Generateur -- EV = proba x rapport - 1, edge, types")
        cid = cids[0]
        preds, course_info = await _course_preds(s, cid)
        cands = enumerate_bet_candidates(preds, course_info)
        chk("candidats generes", len(cands) > 0, f"n={len(cands)}")
        # L'EV n'a de sens QUE sur les paris a cote ferme (simples) : le rapport d'un
        # combo parimutuel depend du pool, inconnu avant la course. Le drapeau
        # `combo_ev_none` la neutralise donc a 0 pour les combos — sinon
        # ev = p_modele x (TRJ / p_marche) - 1 est mecaniquement positive des que le
        # modele depasse le marche, et tout combo franchissait les gates d'EV.
        from ml.algo_flags import FLAGS as _F
        simples = [c for c in cands if "Simple" in c["type_pari"]]
        combos = [c for c in cands if "Simple" not in c["type_pari"]]
        chk("EV == proba x rapport - 1 (simples)",
            all(abs(c["ev"] - (c["proba_gain"] * c["rapport_estime"] - 1)) < 0.06
                for c in simples), f"n={len(simples)}")
        if _F.combo_ev_none:
            chk("EV des combos neutralisee (rapport parimutuel inconnu)",
                all(c["ev"] == 0.0 for c in combos), f"n={len(combos)}")
        chk("proba in ]0,1], rapport >= 1", all(0 < c["proba_gain"] <= 1 and c["rapport_estime"] >= 1 for c in cands))
        chk("niveaux valides", all(c["niveau"] in ("securite", "rendement", "surprise", "coup") for c in cands))
        types = set(c["type_pari"] for c in cands)
        chk("Simple Place genere (socle prudent)", "Simple Place".replace("Place", "Placé") in types or "Simple Placé" in types, str(types))

        # ===== C. PLAN DE MISE =====
        print("\nC. Plan de mise -- sommes, esperance, gates profil")
        for prof in ("conservateur", "equilibre", "agressif"):
            cfg = _effective_config(prof, heat)
            for m in (5, 20, 100):
                plan = plan_to_dict(generer_plan(m, prof, preds, course_info, 200.0, roi_w, heat))
                paris = [p for nv in plan["niveaux"] for p in nv["paris"]]
                tot = sum(p["mise"] for p in paris)
                # Le montant SAISI est deploye en entier ; en staking AUTO
                # (respect_montant absent) la discipline de mise engage moins et
                # met le reliquat en RESERVE. L'invariant est donc :
                # somme des mises == montant_joue, et joue + reserve == montant.
                chk(f"{prof}/{m}E sum(mises)==montant_joue",
                    abs(tot - plan["montant_joue"]) < 0.01, f'{tot}!={plan["montant_joue"]}')
                # `montant_total` peut etre INFERIEUR au montant demande : en staking
                # AUTO, le cap `staking_safe` limite l'exposition a bankroll_cap_frac
                # du bankroll (ici 3 % de 200 EUR = 6 EUR). L'invariant porte donc sur
                # le montant RETENU, et le cap ne peut que reduire.
                chk(f"{prof}/{m}E joue+reserve==montant_total",
                    abs(plan["montant_joue"] + plan["montant_reserve"]
                        - plan["montant_total"]) < 0.01,
                    f'{plan["montant_joue"]}+{plan["montant_reserve"]}'
                    f'!={plan["montant_total"]}')
                chk(f"{prof}/{m}E cap staking ne fait que reduire",
                    plan["montant_total"] <= m, f'{plan["montant_total"]}>{m}')
                tot_force = sum(
                    p["mise"] for nv in plan_to_dict(generer_plan(
                        m, prof, preds, course_info, 200.0, roi_w, heat,
                        respect_montant=True))["niveaux"] for p in nv["paris"])
                chk(f"{prof}/{m}E montant saisi deploye en entier", tot_force == m,
                    f"{tot_force}!={m}")
                esp = round(sum(p["mise"] * p["ev_estime"] for p in paris), 2)
                chk(f"{prof}/{m}E esperance==sum(mise*ev)", abs(esp - plan["esperance_gain"]) < 0.05, f"{esp} vs {plan['esperance_gain']}")
                at = cfg.get("types")
                if at is not None:
                    chk(f"{prof}/{m}E types dans methode", all(p["type"] in at for p in paris), str(set(p["type"] for p in paris)))
                chk(f"{prof}/{m}E montant niveau coherent", all(nv["montant"] == sum(p["mise"] for p in nv["paris"]) for nv in plan["niveaux"]))
                chk(f"{prof}/{m}E mode==label(heat)", plan["mode_adaptatif"] == _mode_label(heat))
                chk(f"{prof}/{m}E profil expose", plan["profil"] == prof)

        # ===== D. REGLEMENT =====
        print("\nD. Reglement -- regles gagne/perdu + vrais rapports")
        cl = [{"numero": 7, "position": 1}, {"numero": 3, "position": 2}, {"numero": 5, "position": 3}, {"numero": 9, "position": 4}]
        rp = {"e_simple_gagnant": 4.2, "e_simple_place": 1.8, "e_couple_gagnant": 12.0,
              "e_couple_place": 3.5, "e_trio": 25.0, "e_deux_sur_quatre": 2.1}
        nb = 12
        chk("SG gagnant=1er", settle_pari("Simple Gagnant", [7], cl, rp, nb)["gagne"] and not settle_pari("Simple Gagnant", [3], cl, rp, nb)["gagne"])
        chk("SP top-3", settle_pari("Simple Placé", [5], cl, rp, nb)["gagne"] and not settle_pari("Simple Placé", [9], cl, rp, nb)["gagne"])
        chk("CG exact top-2", settle_pari("Couplé Gagnant", [7, 3], cl, rp, nb)["gagne"] and not settle_pari("Couplé Gagnant", [7, 5], cl, rp, nb)["gagne"])
        chk("CP top-3 (2)", settle_pari("Couplé Placé", [7, 5], cl, rp, nb)["gagne"] and not settle_pari("Couplé Placé", [7, 9], cl, rp, nb)["gagne"])
        chk("Trio exact top-3", settle_pari("Trio", [7, 3, 5], cl, rp, nb)["gagne"] and not settle_pari("Trio", [7, 3, 9], cl, rp, nb)["gagne"])
        chk("2sur4 >=2 dans top-4", settle_pari("2sur4", [7, 3, 99, 98], cl, rp, nb)["gagne"] and not settle_pari("2sur4", [7, 11, 12, 13], cl, rp, nb)["gagne"])
        chk("SG rapport reel", abs(settle_pari("Simple Gagnant", [7], cl, rp, nb)["rapport_reel"] - 4.2) < 0.01)
        r2 = settle_pari("2sur4", [7, 3, 99, 98], cl, {"e_super_quatre": 711.8}, nb)
        chk("2sur4 n'utilise PAS e_super_quatre", r2["gagne"] and r2["rapport_reel"] is None, str(r2["rapport_reel"]))

        # ===== E. CHAINE COMPLETE + RESULTATS PAR PROFIL =====
        print("\nE. Chaine complete : prono->plan->settlement, ROI par profil (80 courses)")
        term = [r[0] for r in (await s.execute(text(
            "SELECT c.course_id FROM courses c JOIN resultats r ON r.course_id = c.course_id "
            "WHERE c.statut = 'termine' AND r.classement IS NOT NULL "
            "AND EXISTS(SELECT 1 FROM predictions p WHERE p.course_id = c.course_id) "
            "ORDER BY c.date_heure DESC LIMIT 80"))).fetchall()]
        prof_stat = collections.defaultdict(lambda: {"n": 0, "win": 0, "mise": 0.0, "gain": 0.0})
        net_ok = True
        for cid in term:
            pr2, cinfo = await _course_preds(s, cid)
            res = (await s.execute(text("SELECT classement, rapports FROM resultats WHERE course_id = :c"), {"c": cid})).first()
            for prof in ("conservateur", "equilibre", "agressif"):
                plan = plan_to_dict(generer_plan(20, prof, pr2, cinfo, None, roi_w, heat))
                bilan = settle_plan(plan, res[0], res[1], cinfo["nb_partants"] or len(pr2))
                if abs(bilan["net"] - (bilan["total_gain"] - bilan["total_mise"])) > 0.01:
                    net_ok = False
                st = prof_stat[prof]
                for p in bilan["paris"]:
                    if p["statut"] == "en_attente":
                        continue
                    st["n"] += 1
                    st["mise"] += p["mise"]
                    if p["statut"] == "gagne":
                        st["win"] += 1
                        st["gain"] += (p["gain"] or 0)
        chk("settle_plan net == gain - mise", net_ok)
        wr = {}
        for prof in ("conservateur", "equilibre", "agressif"):
            st = prof_stat[prof]
            wr[prof] = st["win"] / st["n"] * 100 if st["n"] else 0
            roi = (st["gain"] - st["mise"]) / st["mise"] * 100 if st["mise"] else 0
            print(f"     {prof:13} win={wr[prof]:5.1f}%  ROI={roi:8.1f}%  paris={st['n']}")
        chk("gradient risque : prudent gagne plus souvent que risque", wr["conservateur"] > wr["agressif"], f"{wr['conservateur']:.0f} vs {wr['agressif']:.0f}")

        # ===== F. APPRENTISSAGE =====
        print("\nF. Apprentissage -- heat & roi_weights derives du reel")
        ctx = await compute_model_heat(s)
        chk("heat in [-1,1]", -1 <= ctx["heat"] <= 1, str(ctx["heat"]))
        chk("heat sur vraies donnees", (ctx["n_races"] or 0) > 0 or (ctx["n_bets"] or 0) > 0, str(ctx))
        chk("roi_weights bornes [0.5,1.6]", all(0.5 <= v <= 1.6 for v in roi_w.values()) if roi_w else True)

        print(f"\n===== RESULTAT : {P[0]} PASS / {F[0]} FAIL =====")


if __name__ == "__main__":
    asyncio.run(main())
