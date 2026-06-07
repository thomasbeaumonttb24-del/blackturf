"""
force_recompute_features.py — Recalcule features_ml pour TOUTES les courses
terminées (overwrite via upsert), pour intégrer les données fraîchement
backfillées (terrain/corde/vitesse/poids) + sire_dist_winrate. À lancer avant
run_nightly_retraining. Idempotent.
"""
import asyncio
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.database import AsyncSessionLocal
from db.models import FeatureML
from ml.features import compute_all_features_for_course


async def main() -> int:
    async with AsyncSessionLocal() as session:
        r = await session.execute(text("""
            SELECT DISTINCT c.course_id
            FROM courses c
            JOIN participations p ON p.course_id = c.course_id AND p.non_partant = false
            WHERE c.statut = 'termine'
            ORDER BY c.course_id
        """))
        course_ids = [row[0] for row in r.fetchall()]

    print(f"[force-recompute] {len(course_ids)} courses terminées", flush=True)
    ok = 0
    total = 0
    for i, cid in enumerate(course_ids, 1):
        try:
            async with AsyncSessionLocal() as session:
                feats = await compute_all_features_for_course(session, cid)
                if not feats:
                    continue
                for feat in feats:
                    pid = feat.get("participation_id")
                    if not pid:
                        continue
                    stmt = pg_insert(FeatureML).values(
                        participation_id=pid, features=feat, computed_at=datetime.now(),
                    ).on_conflict_do_update(
                        index_elements=["participation_id"],
                        set_={"features": feat, "computed_at": datetime.now()},
                    )
                    await session.execute(stmt)
                    total += 1
                await session.commit()
                ok += 1
        except Exception as e:
            print(f"[force-recompute] {cid} ERR {str(e)[:140]}", flush=True)
        if i % 100 == 0:
            print(f"[force-recompute] {i}/{len(course_ids)} · {total} features", flush=True)

    print(f"[force-recompute] DONE {ok}/{len(course_ids)} courses, {total} features", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
