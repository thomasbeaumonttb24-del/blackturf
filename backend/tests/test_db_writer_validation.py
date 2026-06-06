"""
Test intégration : db_writer rejette les cotes aberrantes (garde-fou intégrité).
"""
import pytest
from sqlalchemy import select

from db.models import Participation, CoteBookmaker
from scraper.base import CoteBookmakerScrape
from scraper.db_writer import save_cote_bookmaker, _historique_numeric


# ── _historique_numeric (pur, sans DB) ──────────────────────────────────────
def test_historique_numeric_valide():
    out = _historique_numeric({"distance": 2700, "nb_partants": 14, "position": 3})
    assert out == {"distance": 2700, "nb_partants": 14, "position_arrivee": 3}


def test_historique_numeric_aberrant_nettoye():
    # distance hors bornes → 0 (sentinelle, colonne NOT NULL) ; le reste → None.
    out = _historique_numeric({"distance": 99999, "nb_partants": 99, "position": 250})
    assert out == {"distance": 0, "nb_partants": None, "position_arrivee": None}


def test_historique_numeric_incident_conserve():
    # 99 = incident (tombé/disqualifié) → conservé, pas nettoyé.
    out = _historique_numeric({"distance": None, "nb_partants": None, "position": 99})
    assert out["position_arrivee"] == 99
    assert out["distance"] == 0  # None → 0 (NOT NULL)


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
