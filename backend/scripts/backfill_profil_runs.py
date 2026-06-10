"""Backfill profil_run_log sur TOUTES les courses analysées terminées.

Génère le plan de mise 10€ des 3 profils (depuis les prédictions FIGÉES) pour
chaque course terminée ayant prédictions + résultat, le règle aux VRAIS rapports
PMU, et persiste dans profil_run_log (statut settled/partial). Idempotent.

→ La table "Paris gagnés" du palmarès couvre alors TOUTES les courses, pas
seulement celles prédites en live depuis l'ajout de la feature.

Usage : cd /app && PYTHONPATH=/app python scripts/backfill_profil_runs.py [N]
(N = nb de courses récentes, défaut 400). Aucune donnée inventée : gagnant sans
rapport publié → statut 'partial' (exclu des gains).
"""
import asyncio
import json
import sys
import uuid

from sqlalchemy import text

from db.database import AsyncSessionLocal
from ml.profil_learning import ensure_tables, PROFILS, MISE_REF
from services.mise_calculator import generer_plan, plan_to_dict
from services.bet_settlement import settle_plan

N_SIMS = 2000  # plus léger que le live (backfill volumineux)


async def main(limit: int = 400) -> None:
    async with AsyncSessionLocal() as session:
        await ensure_tables(session)
        courses = (await session.execute(text("""
            SELECT c.course_id, c.nb_partants, c.est_quinte, c.est_quarte, c.est_tierce,
                   r.classement, r.rapports, r.rapports_detail
            FROM courses c
            JOIN resultats r ON r.course_id = c.course_id
            WHERE c.statut = 'termine' AND r.classement IS NOT NULL
            ORDER BY c.date_heure DESC
            LIMIT :lim
        """), {"lim": limit})).all()
        print(f"[profil-runs] {len(courses)} courses terminées à traiter")

        n_done = 0
        n_runs = 0
        for cid, nb_part, est_q, est_qa, est_t, classement, rapports, rapports_detail in courses:
            preds = (await session.execute(text("""
                SELECT p.numero, ch.nom, pr.proba_top1, pr.proba_top3, p.cote_pmu, p.non_partant
                FROM predictions pr
                JOIN participations p ON p.participation_id = pr.participation_id
                JOIN chevaux ch ON ch.cheval_id = p.cheval_id
                WHERE p.course_id = :cid
                ORDER BY pr.rang_predit
            """), {"cid": cid})).all()
            if not preds:
                continue
            pred_list = [{
                "numero": n, "nom_cheval": nom, "proba_top1": p1,
                "proba_top3": p3, "cote_pmu": cote, "non_partant": np_,
            } for n, nom, p1, p3, cote, np_ in preds]
            course_info = {
                "nb_partants": nb_part, "est_quinte": bool(est_q),
                "est_quarte": bool(est_qa), "est_tierce": bool(est_t),
            }
            cl = classement if isinstance(classement, list) else []
            rp = rapports or {}
            nbp = nb_part or len(cl)

            for profil in PROFILS:
                # Course déjà réglée pour ce profil en live → ne pas écraser.
                existing = (await session.execute(text("""
                    SELECT statut FROM profil_run_log WHERE course_id = :cid AND profil = :p
                """), {"cid": cid, "p": profil})).first()
                if existing and existing[0] == "settled":
                    continue
                try:
                    plan = plan_to_dict(generer_plan(MISE_REF, profil, pred_list, course_info, None, {}, 0.0))
                except Exception:
                    continue
                nb_paris = sum(len(nv.get("paris", [])) for nv in plan.get("niveaux", []))
                if nb_paris == 0:
                    continue
                bilan = settle_plan(plan, cl, rp, nbp, rapports_detail or None)
                statut = "partial" if bilan.get("en_attente") else "settled"
                roi = bilan.get("roi")
                await session.execute(text("""
                    INSERT INTO profil_run_log
                        (log_id, course_id, profil, plan, resultat, roi_reel, nb_paris,
                         statut, meta, settled_at)
                    VALUES (:id, :cid, :p, CAST(:plan AS jsonb), CAST(:res AS jsonb),
                            :roi, :nb, :st, CAST(:meta AS jsonb), now())
                    ON CONFLICT (course_id, profil) DO UPDATE SET
                        plan = EXCLUDED.plan, resultat = EXCLUDED.resultat,
                        roi_reel = EXCLUDED.roi_reel, nb_paris = EXCLUDED.nb_paris,
                        statut = EXCLUDED.statut, settled_at = now()
                    WHERE profil_run_log.statut <> 'settled'
                """), {
                    "id": str(uuid.uuid4()), "cid": cid, "p": profil,
                    "plan": json.dumps(plan), "res": json.dumps(bilan),
                    "roi": (roi / 100.0) if roi is not None else None,
                    "nb": nb_paris, "st": statut,
                    "meta": json.dumps({"backfill": True, "mise": MISE_REF}),
                })
                n_runs += 1
            n_done += 1
            if n_done % 50 == 0:
                await session.commit()
                print(f"[profil-runs] {n_done}/{len(courses)} courses · {n_runs} runs")
        await session.commit()
        print(f"[profil-runs] DONE — {n_done} courses, {n_runs} runs écrits")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    asyncio.run(main(n))
