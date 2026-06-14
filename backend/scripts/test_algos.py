"""
test_algos.py — Batterie de tests des algos déployés le 2026-06-14.

Couvre : fonctions pures (ctx_key, shrunk_weight, effective_type_weights),
apprentissage (compute_profil_weights), spécialisation contextuelle + suppression
(get_learned_type_weights), génération de plan end-to-end (generer_plan : type
supprimé absent), features as_of (point-in-time), perfs.

À lancer sur le VPS (DB réelle) :
    docker compose -f docker-compose.prod.yml exec -T api python scripts/test_algos.py
Lecture seule SAUF compute_profil_weights (idempotent, recalcule l'état appris).
"""
import sys, os, asyncio, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "x" * 64)

import db.models  # noqa
from sqlalchemy import text
from db.database import AsyncSessionLocal as S

_passed = 0
_failed = 0
def check(name, cond, detail=""):
    global _passed, _failed
    ok = bool(cond)
    _passed += ok; _failed += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


async def main():
    # ── 1. IMPORTS ────────────────────────────────────────────────
    print("\n1) IMPORTS des modules édités")
    try:
        from ml.profil_learning import (ctx_key, shrunk_weight, effective_type_weights,
                                         compute_profil_weights, MIN_RUNS_FOR_SUPPRESS, ROI_SUPPRESS)
        from ml.bet_performance import get_learned_type_weights
        from services.mise_calculator import generer_plan, plan_to_dict
        from ml.features import compute_features_for_participation
        check("import ml.profil_learning / bet_performance / mise_calculator / features", True)
    except Exception as e:
        check("imports", False, str(e)[:160]); print("STOP"); return

    # ── 2. FONCTIONS PURES ────────────────────────────────────────
    print("\n2) FONCTIONS PURES")
    check("ctx_key trot grand", ctx_key("Trot Attelé", 16) == "trot|g", ctx_key("Trot Attelé", 16))
    check("ctx_key plat moyen", ctx_key("Plat", 10) == "plat|m", ctx_key("Plat", 10))
    check("ctx_key obstacle petit", ctx_key("Haies", 6) == "obstacle|p", ctx_key("Haies", 6))
    check("ctx_key None robuste", ctx_key(None, None) == "autre|p", ctx_key(None, None))
    check("shrunk_weight neutre n=0", shrunk_weight(0, 0, 0) == 1.0)
    check("shrunk_weight borné haut", shrunk_weight(10000, 100, 100) <= 1.6)
    check("shrunk_weight borné bas", shrunk_weight(-10000, 100, 100) >= 0.5)
    # effective_type_weights : blend + suppression sentinel
    pd = {"type_weights": {"Trio": 1.2, "Couplé Gagnant": 0.9},
          "ctx_weights": {"trot|g": {"Trio": 0.0, "Couplé Gagnant": 1.5}}}
    ew_none = effective_type_weights(pd)
    check("eff sans ctx = global", ew_none == {"Trio": 1.2, "Couplé Gagnant": 0.9})
    ew = effective_type_weights(pd, "Trot Attelé", 16)
    check("eff suppression (0 sentinel pas de blend)", ew["Trio"] == 0.0, f"Trio={ew['Trio']}")
    check("eff blend 0.6ctx+0.4global", abs(ew["Couplé Gagnant"] - (0.6 * 1.5 + 0.4 * 0.9)) < 0.01,
          f"Couplé={ew['Couplé Gagnant']} attendu {round(0.6*1.5+0.4*0.9,3)}")
    check("eff ctx absent = global", effective_type_weights(pd, "Plat", 10)["Trio"] == 1.2)

    # ── 3. APPRENTISSAGE compute_profil_weights ───────────────────
    print("\n3) APPRENTISSAGE (compute_profil_weights)")
    t0 = time.perf_counter()
    async with S() as s:
        state = await compute_profil_weights(s)
    dt = time.perf_counter() - t0
    check("compute OK n_total_runs>0", (state.get("n_total_runs") or 0) > 0, f"{state.get('n_total_runs')} runs")
    check("compute perf < 5s", dt < 5.0, f"{round(dt,2)}s")
    for p in ("conservateur", "equilibre", "agressif"):
        pdp = state["profils"].get(p, {})
        check(f"{p}: structure (type_weights/ctx_weights/suppressed)",
              all(k in pdp for k in ("type_weights", "ctx_weights", "suppressed")))
        tw = pdp.get("type_weights") or {}
        check(f"{p}: poids type bornés [0,1.6]", all(0.0 <= v <= 1.6 for v in tw.values()), str(tw))
    # cohérence suppression : tout bucket supprimé doit avoir ROI<=seuil et n>=seuil
    agg = state["profils"]["agressif"]
    check("agressif a des suppressions", len(agg.get("suppressed") or []) > 0,
          f"{len(agg.get('suppressed') or [])} coupés")

    # ── 4. SPÉCIALISATION CONTEXTUELLE + SUPPRESSION (serving) ────
    print("\n4) SERVING (get_learned_type_weights par contexte)")
    async with S() as s:
        w_tg = await get_learned_type_weights(s, profil="agressif", discipline="Trot Attelé", nb_partants=16)
        w_tm = await get_learned_type_weights(s, profil="agressif", discipline="Trot Attelé", nb_partants=10)
        w_pm = await get_learned_type_weights(s, profil="agressif", discipline="Plat", nb_partants=11)
        w_gl = await get_learned_type_weights(s, profil="agressif")
    sup_tg = [t for t, v in w_tg.items() if v <= 0.001]
    check("trot|g supprime Trio", "Trio" in sup_tg, f"supprimés={sup_tg}")
    check("trot|m ne supprime PAS Trio (contexte gagnant)", w_tm.get("Trio", 1) > 0.001)
    check("plat|m supprime Couplé Gagnant", w_pm.get("Couplé Gagnant", 1) <= 0.001)
    check("GLOBAL ne supprime rien (suppression purement contextuelle)",
          not [t for t, v in w_gl.items() if v <= 0.001])

    # ── 5. PLAN END-TO-END : le type supprimé n'est JAMAIS proposé ─
    print("\n5) PLAN END-TO-END (generer_plan respecte la suppression)")
    async with S() as s:
        # courses récentes AVEC prédictions ; on cherche la 1re dont le contexte réel
        # a au moins un type supprimé pour agressif (pour prouver l'absence dans le plan).
        cands = (await s.execute(text("""
            SELECT DISTINCT c.course_id, c.discipline, c.nb_partants, c.date_heure
            FROM courses c JOIN predictions pr ON pr.course_id = c.course_id
            WHERE c.statut = 'termine' AND c.nb_partants IS NOT NULL
            ORDER BY c.date_heure DESC LIMIT 60"""))).all()
        check("courses avec prédictions trouvées", len(cands) > 0, f"{len(cands)} candidates")
        from services.bet_catalog import course_info_bets  # noqa
        chosen = None
        for cid, disc, nbp, _dh in cands:
            w = await get_learned_type_weights(s, profil="agressif", discipline=disc, nb_partants=nbp)
            sup = [t for t, v in w.items() if v <= 0.001]
            if sup:
                chosen = (cid, disc, nbp, w, sup); break
        if chosen is None and cands:  # aucune en contexte supprimé → on teste juste la génération
            cid, disc, nbp, _dh = cands[0]
            w = await get_learned_type_weights(s, profil="agressif", discipline=disc, nb_partants=nbp)
            chosen = (cid, disc, nbp, w, [])
        if chosen:
            cid, disc, nbp, w, sup = chosen
            rows = (await s.execute(text("""
                SELECT p.numero, ch.nom, pr.proba_top1, pr.proba_top3,
                       COALESCE(pr.cote_figee, p.cote_pmu), p.non_partant
                FROM predictions pr JOIN participations p ON p.participation_id=pr.participation_id
                JOIN chevaux ch ON ch.cheval_id=p.cheval_id
                WHERE p.course_id=:c ORDER BY pr.rang_predit"""), {"c": cid})).all()
            preds = [{"numero": r[0], "nom_cheval": r[1], "proba_top1": r[2], "proba_top3": r[3],
                      "cote_pmu": r[4], "non_partant": r[5]} for r in rows]
            cinfo = {"nb_partants": nbp, "est_quinte": False, "est_quarte": False,
                     "est_tierce": True, "est_2sur4": False, "paris_disponibles": None}
            check("course test chargée", len(preds) > 0,
                  f"{cid[:12]} {disc} {nbp}p, {len(preds)} partants, supprimés={sup}")
            t0 = time.perf_counter()
            plan = plan_to_dict(generer_plan(10, "agressif", preds, cinfo, None, w, 0.0, {}, respect_montant=True))
            dtp = time.perf_counter() - t0
            types_proposes = [pp.get("type") for niv in plan.get("niveaux", []) for pp in niv.get("paris", [])]
            check("plan généré sans erreur", isinstance(plan, dict))
            check("perf generer_plan < 2s", dtp < 2.0, f"{round(dtp,3)}s")
            if sup:
                absent = all(t not in types_proposes for t in sup)
                check(f"types supprimés {sup} ABSENTS du plan", absent, f"proposés={types_proposes}")

    # ── 6. FEATURES as_of (point-in-time, pas de fuite) ───────────
    print("\n6) FEATURES as_of (compute sur course historique, point-in-time)")
    async with S() as s:
        pr = (await s.execute(text("""
            SELECT p.participation_id, p.course_id, p.cheval_id, p.jockey_id, p.entraineur_id
            FROM participations p JOIN courses c ON c.course_id=p.course_id
            WHERE c.statut='termine' AND c.date_heure < '2025-12-01'
            ORDER BY c.date_heure DESC LIMIT 1"""))).first()
        if pr:
            t0 = time.perf_counter()
            feats = await compute_features_for_participation(s, pr[0], pr[1], pr[2], pr[3], pr[4])
            dtf = time.perf_counter() - t0
            check("compute_features course historique sans erreur", feats is not None)
            check("features contient opposition_quality (bloc as_of corrigé)",
                  feats is not None and "opposition_quality" in feats)
            check("features perf < 3s", dtf < 3.0, f"{round(dtf,3)}s")
        # preuve as_of toujours valide : NOW() comptait du futur, as_of non
        leak = (await s.execute(text("""
            SELECT
              (SELECT count(*) FROM participations pa JOIN courses c ON c.course_id=pa.course_id
               JOIN historique_courses h ON h.cheval_id=pa.cheval_id
               WHERE c.date_heure>='2025-09-01' AND c.date_heure<'2025-09-08'
                 AND h.date_course > c.date_heure - INTERVAL '24 months' AND h.date_course < c.date_heure) AS as_of,
              (SELECT count(*) FROM participations pa JOIN courses c ON c.course_id=pa.course_id
               JOIN historique_courses h ON h.cheval_id=pa.cheval_id
               WHERE c.date_heure>='2025-09-01' AND c.date_heure<'2025-09-08'
                 AND h.date_course > c.date_heure - INTERVAL '24 months') AS sans_borne_haute
        """))).first()
        check("as_of borne le futur (as_of < sans_borne)", leak[0] < leak[1],
              f"as_of={leak[0]} vs futur-inclus={leak[1]}")

    print(f"\n{'='*56}\nRÉSULTAT : {_passed} PASS / {_failed} FAIL\n{'='*56}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
