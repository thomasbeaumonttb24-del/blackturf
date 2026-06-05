"""
activate_phase1.py — Active les signaux Phase 1 sur la base réelle.

Étapes (à lancer APRÈS `alembic upgrade head` qui crée les colonnes 0009) :
  1. Backfill : recalcule reduction_km + acceleration_* sur l'historique existant.
  2. (option --features) Recalcule les features ML des courses à venir + récentes,
     pour intégrer dyn_* et conf_* dans features_ml.

Le retrain complet reste à déclencher ensuite (voir message final).
Écritures limitées à des colonnes DÉRIVÉES (aucune donnée brute touchée).

Usage :
    python scripts/activate_phase1.py
    python scripts/activate_phase1.py --features --jours 14
"""
import sys
import os
import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from db.database import AsyncSessionLocal as async_session
from sqlalchemy import text
from ml.backfill_dynamics import backfill_historique_dynamics


async def _check_columns(session) -> bool:
    """Vérifie que la migration 0009 est appliquée (colonnes présentes)."""
    try:
        await session.execute(text("SELECT reduction_km, acceleration_label FROM historique_courses LIMIT 1"))
        return True
    except Exception:
        return False


async def main(do_features: bool, jours: int):
    async with async_session() as session:
        if not await _check_columns(session):
            print("ERREUR : colonnes Phase 1 absentes. Lance d'abord :")
            print("    alembic upgrade head")
            sys.exit(2)

        print("[1/2] Backfill dynamique (réduction km + accélération)…")
        stats = await backfill_historique_dynamics(session)
        print(f"      scannées={stats['rows_scannees']} "
              f"réduction={stats['reduction_remplie']} "
              f"accélération={stats['acceleration_remplie']}")

        if do_features:
            from ml.features import compute_all_features_for_course
            from db.models import FeatureML
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from datetime import datetime

            depuis = date.today() - timedelta(days=jours)
            ids_r = await session.execute(text("""
                SELECT course_id FROM courses
                WHERE date_heure::date >= :d ORDER BY date_heure
            """), {"d": depuis})
            course_ids = [r[0] for r in ids_r.fetchall()]
            print(f"[2/2] Recalcul features sur {len(course_ids)} courses (≥ {depuis})…")
            n_feat = 0
            for cid in course_ids:
                feats = await compute_all_features_for_course(session, cid)
                for feat in feats or []:
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
                    n_feat += 1
                await session.commit()
            print(f"      features recalculées : {n_feat}")
        else:
            print("[2/2] Features non recalculées (relance avec --features).")

    print("=" * 55)
    print("Phase 1 activée. Étape suivante : RETRAIN du modèle pour")
    print("exploiter dyn_* et conf_*, ex. :")
    print("    python -c \"import asyncio; from ml.pipeline import run_nightly_retraining; asyncio.run(run_nightly_retraining())\"")
    print("=" * 55)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--features", action="store_true", help="Recalculer aussi les features ML")
    p.add_argument("--jours", type=int, default=14, help="Fenêtre (jours) pour le recalcul features")
    args = p.parse_args()
    asyncio.run(main(args.features, args.jours))
