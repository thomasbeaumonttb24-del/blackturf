"""
Test intégration : db_writer rejette les cotes aberrantes (garde-fou intégrité).
"""
import pytest
from sqlalchemy import select

from db.models import Participation, CoteBookmaker
from scraper.base import CoteBookmakerScrape
from scraper.db_writer import save_cote_bookmaker


async def _seed_participation(db, pid="pp1"):
    db.add(Participation(participation_id=pid, course_id="C1", cheval_id="A", numero=1))
    await db.commit()
    return pid


@pytest.mark.asyncio
async def test_cote_aberrante_non_stockee(db):
    pid = await _seed_participation(db)
    cote = CoteBookmakerScrape(course_id="C1", numero=1, nom="A",
                               source="winamax", cote=0.4)  # < 1.01 → aberrant
    await save_cote_bookmaker(db, cote, pid, "C1")
    await db.commit()

    rows = (await db.execute(select(CoteBookmaker))).scalars().all()
    assert rows == []   # rien stocké
    part = await db.get(Participation, pid)
    assert part.cote_winamax is None


@pytest.mark.asyncio
async def test_cote_plausible_stockee(db):
    pid = await _seed_participation(db, "pp2")
    cote = CoteBookmakerScrape(course_id="C1", numero=1, nom="A",
                               source="winamax", cote=4.5)
    await save_cote_bookmaker(db, cote, pid, "C1")
    await db.commit()

    rows = (await db.execute(select(CoteBookmaker))).scalars().all()
    assert len(rows) == 1
    assert rows[0].cote == 4.5
    part = await db.get(Participation, pid)
    assert part.cote_winamax == 4.5
