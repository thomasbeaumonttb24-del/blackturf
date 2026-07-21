"""
backfill_rapports_libelle.py — Re-scrape les rapports définitifs PMU des courses
terminées et met à jour rapports_detail pour y injecter le `libelle` (« e-Multi en
4/5/6/7 »). Nécessaire pour que le tableau des résultats affiche la formule « en N »
à côté de chaque rapport Multi/Mini Multi (les anciens scrapes ne l'avaient pas).

Idempotent : ne touche que rapports/rapports_detail des courses ciblées.

    python scripts/backfill_rapports_libelle.py 18062026          # toutes les courses du jour
    python scripts/backfill_rapports_libelle.py 18062026R3C1 ...   # courses précises
"""
import sys
import os
import re
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")

from sqlalchemy import text
from db.database import AsyncSessionLocal as async_session
from scraper.sources.pmu import PmuScraper
from scraper.db_writer import save_resultat_to_db

_CID = re.compile(r"^(\d{8})R(\d+)C(\d+)$")


async def _course_ids(arg: str) -> list[str]:
    if _CID.match(arg):
        return [arg]
    # un jour ddmmyyyy → toutes les courses terminées de ce jour
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT course_id FROM courses
            WHERE course_id LIKE :pat AND statut = 'termine'
            ORDER BY course_id
        """), {"pat": f"{arg}R%C%"})).all()
    return [r[0] for r in rows]


async def main(args: list[str]) -> int:
    targets: list[str] = []
    for a in args:
        targets += await _course_ids(a)
    targets = sorted(set(targets))
    print(f"Courses à re-scraper : {len(targets)}")

    src = PmuScraper(proxy=None)
    ok = libelle_found = 0
    async with async_session() as session:
        for cid in targets:
            m = _CID.match(cid)
            if not m:
                continue
            d, reunion, num = m.group(1), m.group(2), int(m.group(3))
            try:
                res = await src.get_rapports_definitifs(reunion, num, course_date=d)
            except Exception as e:  # noqa: BLE001
                print(f"  {cid}: échec scrape ({str(e)[:60]})")
                continue
            if not res:
                continue
            rd = getattr(res, "rapports_detail", None) or {}
            has_lib = any(e.get("libelle") for arr in rd.values() for e in arr)
            await save_resultat_to_db(session, res)
            await session.commit()
            ok += 1
            if has_lib:
                libelle_found += 1
            if "e_multi" in rd or "e_mini_multi" in rd:
                key = "e_mini_multi" if "e_mini_multi" in rd else "e_multi"
                labs = [e.get("libelle") for e in rd[key]]
                print(f"  {cid}: {key} libellés = {labs}")
    print(f"Re-scrapées : {ok} ; avec libellés : {libelle_found}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: backfill_rapports_libelle.py <ddmmyyyy | courseId> ...")
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1:])))
