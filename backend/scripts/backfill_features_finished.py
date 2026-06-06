"""
backfill_features_finished.py — Calcule et persiste features_ml pour les courses
TERMINÉES qui ont des partants mais pas encore de features.

But : débloquer l'entraînement RÉEL du modèle (features_ml ⋈ historique_courses.position
⋈ resultats) au lieu du prior synthétique. N'invente aucune donnée : calcule les vraies
features à partir des partants réellement scrappés.

Usage (conteneur api) :
    python scripts/backfill_features_finished.py
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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
              AND NOT EXISTS (
                  SELECT 1 FROM features_ml f
                  JOIN participations p2 ON p2.participation_id = f.participation_id
                  WHERE p2.course_id = c.course_id
              )
            ORDER BY c.course_id
        """))
        course_ids = [row[0] for row in r.fetchall()]

    print(f"[backfill] courses terminées sans features : {len(course_ids)}")
    ok = 0
    total_feats = 0
    for cid in course_ids:
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
                        participation_id=pid,
                        features=feat,
                        computed_at=datetime.now(),
                    ).on_conflict_do_update(
                        index_elements=["participation_id"],
                        set_={"features": feat, "computed_at": datetime.now()},
                    )
                    await session.execute(stmt)
                    total_feats += 1
                await session.commit()
                ok += 1
        except Exception as e:
            print(f"[backfill] {cid} ERR {str(e)[:140]}")

    print(f"[backfill] OK {ok}/{len(course_ids)} courses, {total_feats} features persistées")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
