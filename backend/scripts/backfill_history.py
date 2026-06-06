"""
Backfill historique PMU — alimente la base avec les VRAIES courses passées.

Problème résolu : la base n'avait quasi aucun historique (~130 courses), donc l'IA
était affamée de données. Ce script rejoue, jour par jour (du plus ANCIEN au plus
récent pour que l'historique cheval s'accumule), le programme PMU + les arrivées
officielles, et écrit :
  - courses + partants            (save_course_to_db)
  - résultats officiels + statut  (save_resultat_to_db, arrivées réelles)
  - features ML par partant       (compute_all_features_for_course → features_ml)
  - historique_courses (positions) (_save_historical_course)

→ build_training_dataset voit alors des milliers de vraies courses. Lancer un
retrain ensuite (le gate walk-forward déploiera le meilleur modèle).

Intégrité : 100% données PMU réelles, aucune fabrication. Idempotent (on peut
relancer, ON CONFLICT DO UPDATE partout). Rate-limité pour ne pas marteler le PMU.

Usage (dans le conteneur api/worker, DATABASE_URL configuré) :
    python -m scripts.backfill_history --days 30
    python -m scripts.backfill_history --from 01012025 --to 31032025
    python -m scripts.backfill_history --days 7 --max-courses 50   # test rapide
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.database import AsyncSessionLocal
from db.models import Course, Resultat, FeatureML
from scraper.sources.pmu import PmuScraper
from scraper.db_writer import save_course_to_db, save_resultat_to_db
from scraper.base import human_delay
from ml.features import compute_all_features_for_course
from ml.pipeline import _save_historical_course

log = structlog.get_logger(module="backfill_history")


async def _backfill_one_course(pmu: PmuScraper, course, ddmmyyyy: str) -> dict:
    """Traite une course : sauvegarde course+partants, résultats, features, historique.
    Retourne un dict de compteurs. Best-effort par étape (une étape ratée n'empêche
    pas les autres)."""
    out = {"course": 0, "resultat": 0, "features": 0, "historique": 0}
    cid = course.course_id
    r_id = course.reunion_id
    try:
        c_num = int(cid.split("C")[-1])
    except (ValueError, IndexError):
        return out

    # 0) Partants : le programme d'une date passée renvoie participants=[] en inline.
    # On enrichit donc via l'endpoint /participants dédié (daté) avant de sauvegarder.
    if not course.partants:
        try:
            partants = await pmu.enrich_partants(r_id, c_num, ddmmyyyy)
            if partants:
                course.partants = partants
                course.nb_partants = len(partants)
        except Exception as e:
            log.warning("backfill.enrich_partants_failed", course_id=cid, err=str(e)[:140])

    # 1) Course + partants
    try:
        async with AsyncSessionLocal() as s:
            await save_course_to_db(s, course)
            await s.commit()
        out["course"] = 1
    except Exception as e:
        log.warning("backfill.save_course_failed", course_id=cid, err=str(e)[:140])
        return out

    # 2) Résultats officiels (arrivées + rapports) → statut termine
    resultat = None
    try:
        resultat = await pmu.get_rapports_definitifs(r_id, c_num, ddmmyyyy)
    except Exception as e:
        log.warning("backfill.results_fetch_failed", course_id=cid, err=str(e)[:140])
    if resultat:
        try:
            async with AsyncSessionLocal() as s:
                await save_resultat_to_db(s, resultat)
                await s.commit()
            out["resultat"] = 1
        except Exception as e:
            log.warning("backfill.save_resultat_failed", course_id=cid, err=str(e)[:140])

    # 3) Features ML par partant (alimente features_ml pour l'entraînement)
    try:
        async with AsyncSessionLocal() as s:
            feats = await compute_all_features_for_course(s, cid)
            for f in feats:
                pid = f.get("participation_id")
                if not pid:
                    continue
                await s.execute(
                    pg_insert(FeatureML).values(
                        participation_id=pid, features=f, computed_at=datetime.now()
                    ).on_conflict_do_update(
                        index_elements=["participation_id"],
                        set_={"features": f, "computed_at": datetime.now()},
                    )
                )
            await s.commit()
            out["features"] = len(feats)
    except Exception as e:
        log.warning("backfill.features_failed", course_id=cid, err=str(e)[:140])

    # 4) historique_courses (positions réelles) — clé pour le label d'entraînement
    if resultat:
        try:
            async with AsyncSessionLocal() as s:
                c_obj = await s.get(Course, cid)
                r_obj = await s.get(Resultat, cid)
                if c_obj and r_obj:
                    await _save_historical_course(s, c_obj, r_obj)
                    await s.commit()
                    out["historique"] = 1
        except Exception as e:
            log.warning("backfill.historique_failed", course_id=cid, err=str(e)[:140])

    return out


async def backfill_date(pmu: PmuScraper, d: date, max_courses: int | None = None) -> dict:
    ddmmyyyy = d.strftime("%d%m%Y")
    try:
        courses = await pmu.get_programme_today(d)
    except Exception as e:
        log.error("backfill.programme_failed", date=ddmmyyyy, err=str(e)[:160])
        return {"date": ddmmyyyy, "courses_found": 0}

    if max_courses:
        courses = courses[:max_courses]

    totals = {"course": 0, "resultat": 0, "features": 0, "historique": 0}
    for course in courses:
        c = await _backfill_one_course(pmu, course, ddmmyyyy)
        for k in totals:
            totals[k] += c[k]
        await human_delay(0.2, 0.5)

    log.info("backfill.date_done", date=ddmmyyyy, courses_found=len(courses), **totals)
    return {"date": ddmmyyyy, "courses_found": len(courses), **totals}


def _parse_ddmmyyyy(s: str) -> date:
    return datetime.strptime(s, "%d%m%Y").date()


async def main(days: int, dfrom: str | None, dto: str | None, max_courses: int | None) -> None:
    today = date.today()
    if dfrom:
        start = _parse_ddmmyyyy(dfrom)
        end = _parse_ddmmyyyy(dto) if dto else today - timedelta(days=1)
    else:
        end = today - timedelta(days=1)              # hier (jours complets)
        start = end - timedelta(days=days - 1)

    # Du plus ANCIEN au plus récent → l'historique cheval s'accumule pour les features.
    all_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    log.info("backfill.start", n_days=len(all_dates), start=str(start), end=str(end))

    pmu = PmuScraper(proxy=None)
    grand = {"course": 0, "resultat": 0, "features": 0, "historique": 0, "courses_found": 0}
    for i, d in enumerate(all_dates, 1):
        r = await backfill_date(pmu, d, max_courses)
        for k in grand:
            grand[k] += r.get(k, 0)
        print(f"[{i}/{len(all_dates)}] {r['date']} — courses={r.get('courses_found',0)} "
              f"resultats={r.get('resultat',0)} features={r.get('features',0)} "
              f"| CUMUL courses={grand['course']} resultats={grand['resultat']}")

    print(f"\nBACKFILL_DONE jours={len(all_dates)} courses={grand['course']} "
          f"resultats={grand['resultat']} features_partants={grand['features']} "
          f"historique={grand['historique']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="nb de jours en arrière (depuis hier)")
    ap.add_argument("--from", dest="dfrom", default=None, help="date début ddmmyyyy (prioritaire sur --days)")
    ap.add_argument("--to", dest="dto", default=None, help="date fin ddmmyyyy (défaut: hier)")
    ap.add_argument("--max-courses", type=int, default=None, help="limite de courses/jour (test)")
    args = ap.parse_args()
    asyncio.run(main(args.days, args.dfrom, args.dto, args.max_courses))
