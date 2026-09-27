"""
rattraper_commentaires_pmu.py — relit les commentaires post-course du PMU encore
publiés (30 derniers jours, cf. services/commentaires_pmu.py) et complète
historique_courses + resultats.classement. Ne remplace jamais un commentaire.

    python scripts/rattraper_commentaires_pmu.py --dry-run
    python scripts/rattraper_commentaires_pmu.py --jours 30
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf"
)

from services.commentaires_pmu import RETENTION_PMU_JOURS, relire_commentaires  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jours", type=int, default=RETENTION_PMU_JOURS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    hier = date.today() - timedelta(days=1)
    stats = await relire_commentaires(hier - timedelta(days=args.jours - 1), hier, args.dry_run)
    print(f"[commentaires-pmu] {stats}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
