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

2026-07-02 : ajout du TIMEOUT (ml.profil_learning.settle_catchup, branché aussi au
nightly) — les runs encore pending/partial après --timeout-days (défaut 7) passent
en statut 'expired' (motif dans meta.expired_reason) : exclus explicitement de
l'apprentissage au lieu de traîner en faux « en attente ». Aucun gain inventé.

À lancer sur le VPS (où vit la DB) :
    python scripts/settle_catchup.py            # rattrape tout + expire + recompute poids
    python scripts/settle_catchup.py --dry-run  # liste seulement, n'écrit rien
    python scripts/settle_catchup.py --no-recompute --timeout-days 7
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
from ml.profil_learning import (
    settle_profil_runs, compute_profil_weights, settle_catchup, CATCHUP_TIMEOUT_DAYS,
)


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


async def main(dry_run: bool, recompute: bool, timeout_days: int) -> int:
    async with async_session() as session:
        before = await _counts(session)
        courses = await _orphan_courses(session)

    print(f"État avant : {before}")
    print(f"Courses orphelines à régler : {len(courses)}")
    if dry_run:
        print("DRY-RUN — aucune écriture. Exemples :", courses[:10])
        return 0

    # Re-règle + expire (timeout) en une passe — même code que le nightly.
    async with async_session() as session:
        out = await settle_catchup(session, timeout_days=timeout_days)
    print(f"Re-réglés : {out['resettled']} · expirés (>{timeout_days}j) : {out['expired']} "
          f"· restants pending/partial : {out['remaining']}")

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
    p.add_argument("--timeout-days", type=int, default=CATCHUP_TIMEOUT_DAYS,
                   help="Ancienneté (jours) au-delà de laquelle un run non réglable expire")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.recompute, args.timeout_days)))
