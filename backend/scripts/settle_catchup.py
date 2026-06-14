"""
settle_catchup.py — Passe de RATTRAPAGE du règlement des runs profils orphelins.

Problème (constaté 2026-06-14) : des runs de profil_run_log restent 'pending' ou
'partial' alors que la course est terminée et a un résultat :
  - pending sur course termine+resultat = le règlement inline (pipeline) n'a jamais
    été déclenché pour cette course (course réglée avant l'enregistrement du run, ou
    appel sauté) → orphelin à vie, signal d'apprentissage perdu.
  - partial = pari gagnant sans rapport PMU publié au moment du règlement ; le rapport
    arrive 5-10 min après → re-réglable, mais aucune passe ne repasse les chercher.

Cette passe relance settle_profil_runs (IDEMPOTENT : ne touche jamais un run déjà
'settled') sur toute course termine + résultat ayant des runs pending/partial, puis
recalcule les poids appris une fois à la fin.

À lancer sur le VPS (où vit la DB) :
    python scripts/settle_catchup.py            # rattrape tout + recompute poids
    python scripts/settle_catchup.py --dry-run  # liste seulement, n'écrit rien
    python scripts/settle_catchup.py --no-recompute
"""
import sys
import os
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from sqlalchemy import text
from db.database import AsyncSessionLocal as async_session
from ml.profil_learning import settle_profil_runs, compute_profil_weights


async def _orphan_courses(session) -> list[str]:
    """Courses termine + résultat ayant ≥1 run pending/partial."""
    rows = (await session.execute(text("""
        SELECT DISTINCT pl.course_id
        FROM profil_run_log pl
        JOIN courses c   ON c.course_id = pl.course_id
        JOIN resultats r ON r.course_id = pl.course_id
        WHERE pl.statut IN ('pending', 'partial')
          AND c.statut = 'termine'
          AND r.classement IS NOT NULL
        ORDER BY pl.course_id
    """))).all()
    return [r[0] for r in rows]


async def _counts(session) -> dict:
    rows = (await session.execute(text(
        "SELECT statut, count(*) FROM profil_run_log GROUP BY statut"
    ))).all()
    return {r[0]: r[1] for r in rows}


async def main(dry_run: bool, recompute: bool) -> int:
    async with async_session() as session:
        before = await _counts(session)
        courses = await _orphan_courses(session)

    print(f"État avant : {before}")
    print(f"Courses orphelines à régler : {len(courses)}")
    if not courses:
        print("Rien à rattraper.")
        return 0
    if dry_run:
        print("DRY-RUN — aucune écriture. Exemples :", courses[:10])
        return 0

    total_settled = 0
    ok = 0
    fail = 0
    for cid in courses:
        try:
            async with async_session() as session:  # session par course : un échec n'avorte pas le reste
                n = await settle_profil_runs(session, cid)
                total_settled += n
                ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  ÉCHEC course {cid}: {str(e)[:120]}")

    print(f"Réglés : {total_settled} runs sur {ok} courses OK ({fail} échecs).")

    if recompute:
        async with async_session() as session:
            state = await compute_profil_weights(session)
        print(f"Poids recalculés : {state.get('n_total_runs')} runs settled agrégés.")

    async with async_session() as session:
        after = await _counts(session)
    print(f"État après : {after}")
    # delta lisible
    for st in ("pending", "partial", "settled"):
        b, a = before.get(st, 0), after.get(st, 0)
        if b != a:
            print(f"   {st}: {b} -> {a}  ({a - b:+d})")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Liste seulement, n'écrit rien")
    p.add_argument("--no-recompute", dest="recompute", action="store_false",
                   help="Ne pas recalculer les poids appris après rattrapage")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.recompute)))
