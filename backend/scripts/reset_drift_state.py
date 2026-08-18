"""Inspecte ou réinitialise l'état du détecteur de dérive.

Lecture seule par défaut :
    python -m scripts.reset_drift_state

Application, uniquement après arrêt de api/worker/scheduler et déploiement des
correctifs du contrat post-course :
    python -m scripts.reset_drift_state --apply \
      --services-stopped --confirm RESET-CORRUPTED-DRIFT \
      --reason "contrat Brier/confiance corrigé"
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "SECRET_KEY",
    "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok",
)

from sqlalchemy import text  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from ml.drift_detector import DriftDetector, persisted_state_corruption_reasons  # noqa: E402

CONFIRMATION = "RESET-CORRUPTED-DRIFT"


def validate_apply_request(args: argparse.Namespace, reasons: list[str]) -> None:
    if not args.apply:
        return
    if args.confirm != CONFIRMATION:
        raise ValueError(f"--confirm doit valoir exactement {CONFIRMATION}")
    if not args.services_stopped:
        raise ValueError(
            "--services-stopped est obligatoire pour empêcher une réécriture concurrente"
        )
    if not args.reason or len(args.reason.strip()) < 10:
        raise ValueError("--reason doit documenter le reset (10 caractères minimum)")
    if not reasons and not args.force:
        raise ValueError(
            "état non reconnu comme corrompu ; utiliser --force seulement après vérification"
        )


async def read_state(session, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    result = await session.execute(text(
        "SELECT severity, n_updates, last_drift_at, state_json "
        "FROM drift_detector_state WHERE state_id = 'singleton'" + suffix
    ))
    return result.first()


def summarize(row) -> dict:
    if row is None:
        return {"exists": False, "severity": None, "n_updates": 0, "reasons": []}
    blob = row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}")
    return {
        "exists": True,
        "severity": row[0],
        "n_updates": int(row[1] or 0),
        "last_drift_at": row[2].isoformat() if row[2] else None,
        "reasons": persisted_state_corruption_reasons(blob),
    }


async def run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        before = summarize(await read_state(session))
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "before": before}))

        validate_apply_request(args, before["reasons"])
        if not args.apply:
            print("DRY-RUN — aucune écriture effectuée")
            return 0

        # Verrou de ligne et seconde vérification dans la transaction d'écriture.
        locked_before = summarize(await read_state(session, lock=True))
        validate_apply_request(args, locked_before["reasons"])

        fresh_detector = DriftDetector()
        await fresh_detector.save_state(session)
        await session.commit()

        after = summarize(await read_state(session))
        print(json.dumps({
            "reset": "applied",
            "reason": args.reason.strip(),
            "before": locked_before,
            "after": after,
        }))
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="applique réellement le reset")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--force",
        action="store_true",
        help="autorise un état non reconnu comme corrompu",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except ValueError as exc:
        print(f"REFUSÉ: {exc}", file=sys.stderr)
        raise SystemExit(2)
