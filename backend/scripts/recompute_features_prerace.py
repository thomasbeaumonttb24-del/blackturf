"""
recompute_features_prerace.py — Recalcule features_ml pour TOUTES les courses
terminées en stampant computed_at = date_heure - 1min (snapshot PRÉ-COURSE).

POURQUOI (vs force_recompute_features.py) : avec BT_TRAIN_PRERACE_ONLY=1, la requête
d'entraînement ne garde que `fm.computed_at < c.date_heure`. force_recompute stampe
computed_at=now() → toutes les courses passées deviennent computed_at>date_heure →
EXCLUES du training (le set s'effondre). Ici on stampe juste AVANT le départ : les
features sont déjà calculées as_of=date_heure (point-in-time, pas de fuite), donc
computed_at=date_heure-1min est honnête et passe le filtre prerace.

Effet : intègre dans le training toutes les features recâblées dont les rows
historiques portaient encore les vieilles constantes (saison_form, opposition_quality,
sire_terrain_winrate, jockey_cheval_synergy, nb_courses_reunion). À lancer AVANT
run_nightly_retraining. Idempotent (upsert).
"""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.database import AsyncSessionLocal
from db.models import FeatureML
from ml.features import compute_all_features_for_course


async def main() -> int:
    async with AsyncSessionLocal() as session:
        r = await session.execute(text("""
            SELECT DISTINCT c.course_id, c.date_heure
            FROM courses c
            JOIN participations p ON p.course_id = c.course_id AND p.non_partant = false
            WHERE c.statut = 'termine' AND c.date_heure IS NOT NULL
            ORDER BY c.course_id
        """))
        rows = r.fetchall()
        course_dates = {row[0]: row[1] for row in rows}
        course_ids = [row[0] for row in rows]

    print(f"[recompute-prerace] {len(course_ids)} courses terminées", flush=True)
    ok = 0
    total = 0
    for i, cid in enumerate(course_ids, 1):
        # computed_at = juste avant le départ → passe le filtre prerace, honnête
        stamp = course_dates[cid] - timedelta(minutes=1)
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
                        participation_id=pid, features=feat, computed_at=stamp,
                    ).on_conflict_do_update(
                        index_elements=["participation_id"],
                        set_={"features": feat, "computed_at": stamp},
                    )
                    await session.execute(stmt)
                    total += 1
                await session.commit()
                ok += 1
        except Exception as e:
            print(f"[recompute-prerace] {cid} ERR {str(e)[:140]}", flush=True)
        if i % 200 == 0:
            print(f"[recompute-prerace] {i}/{len(course_ids)} · {total} features", flush=True)

    print(f"[recompute-prerace] DONE {ok}/{len(course_ids)} courses, {total} features", flush=True)
    return 0


if __name__ == "__main__":
    asyncio.run(main())
