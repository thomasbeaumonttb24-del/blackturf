"""Rattrapage de la stalle (`participations.numero_corde`) — réponses PMU simulées.

Ce qu'on verrouille : appariement par numéro (jamais par nom), écriture seulement
sur NULL, garde des noms, journal, débit.
"""
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts.backfill_numero_corde import (
    Bilan,
    courses_a_traiter,
    decouper_course_id,
    noms_concordent,
    traiter,
)
from scraper.sources.pmu import PmuScraper


@pytest_asyncio.fixture
async def fabrique():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.exec_driver_sql(
            "CREATE TABLE courses (course_id TEXT PRIMARY KEY, date_heure TIMESTAMP, discipline TEXT)")
        await c.exec_driver_sql(
            "CREATE TABLE chevaux (cheval_id TEXT PRIMARY KEY, nom TEXT)")
        await c.exec_driver_sql(
            "CREATE TABLE participations (participation_id TEXT PRIMARY KEY, course_id TEXT, "
            "cheval_id TEXT, numero INTEGER, numero_corde INTEGER)")
        await c.exec_driver_sql(
            "INSERT INTO courses VALUES ('18032026R4C5', '2026-03-18 17:48:00', 'Plat'),"
            "('18032026R4C6', '2026-03-18 18:15:00', 'Plat'),"
            "('18032026R1C1', '2026-03-18 13:00:00', 'Attelé'),"
            "('01092026R1C1', '2026-09-01 13:00:00', 'Plat')")
        noms = ["NEBUR", "WITTELSBACH", "CANENA", "ICE CRACKER"]
        for i, n in enumerate(noms, 1):
            await c.exec_driver_sql(f"INSERT INTO chevaux VALUES ('ch{i}', '{n}')")
            # Course 1 : 3 stalles NULL, la 4e déjà posée par le scraper live (=99).
            corde = "99" if i == 4 else "NULL"
            await c.exec_driver_sql(
                f"INSERT INTO participations VALUES ('p{i}', '18032026R4C5', 'ch{i}', {i}, {corde})")
        # Course 2 : noms qui ne correspondent PAS à ce que renverra le PMU.
        for i in range(1, 4):
            await c.exec_driver_sql(f"INSERT INTO chevaux VALUES ('x{i}', 'AUTRE CHEVAL {i}')")
            await c.exec_driver_sql(
                f"INSERT INTO participations VALUES ('q{i}', '18032026R4C6', 'x{i}', {i}, NULL)")
        await c.exec_driver_sql(
            "INSERT INTO participations VALUES ('t1', '18032026R1C1', 'ch1', 1, NULL)")
        # Course déjà entièrement remplie : ne doit pas être retenue.
        await c.exec_driver_sql(
            "INSERT INTO participations VALUES ('f1', '01092026R1C1', 'ch1', 1, 3)")
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


def _p(numero, nom, corde):
    return SimpleNamespace(numero=numero, nom=nom, numero_corde=corde)


# Réponse PMU brute (forme de l'API /participants) passée par le VRAI parseur du
# scraper — garantit que le script lit `placeCorde` comme le live.
_REPONSE_R4C5 = [
    {"numPmu": 1, "nom": "NEBUR", "placeCorde": 11},
    {"numPmu": 2, "nom": "WITTELSBACH", "placeCorde": 12},
    {"numPmu": 3, "nom": "CANENA (FR)", "placeCorde": 0},      # 0 = pas de corde → None
    {"numPmu": 4, "nom": "ICE CRACKER", "placeCorde": 7},       # déjà rempli en base
    {"numPmu": 9, "nom": "INCONNU", "placeCorde": 2},           # absent de la base
]


def test_decoupe_identifiant_pmu():
    assert decouper_course_id("18032026R4C5") == ("18032026", "4", 5)
    assert decouper_course_id("18032026R12C10") == ("18032026", "12", 10)
    assert decouper_course_id("R4C5") is None
    assert decouper_course_id("abc") is None


def test_garde_des_noms():
    assert noms_concordent({1: "CHESTNUT"}, {1: "CHESTNUT (SWE)"})
    assert noms_concordent({1: "Épée d'or"}, {1: "EPEE D'OR"})
    assert not noms_concordent({1: "A", 2: "B", 3: "C"}, {1: "X", 2: "Y", 3: "C"})
    assert noms_concordent({1: None}, {1: "X"})   # rien de comparable : on ne bloque pas


@pytest.mark.asyncio
async def test_selection_courses(fabrique):
    from datetime import datetime, timezone
    async with fabrique() as s:
        ids = await courses_a_traiter(s, datetime(2025, 9, 1, tzinfo=timezone.utc), ["Plat"], 100)
    assert set(ids) == {"18032026R4C5", "18032026R4C6"}   # ni trot, ni course déjà remplie


@pytest.mark.asyncio
async def test_rattrapage_par_numero_seulement_sur_null(fabrique, tmp_path):
    appels = []
    parseur = PmuScraper()

    async def fetch(date_s, reunion, course_num):
        appels.append((date_s, reunion, course_num))
        if (reunion, course_num) == ("4", 5):
            return parseur._parse_partants(_REPONSE_R4C5)
        if (reunion, course_num) == ("4", 6):
            return [_p(1, "NEBUR", 5), _p(2, "WITTELSBACH", 6), _p(3, "CANENA", 7)]
        return []

    journal = tmp_path / "corde.log"
    bilan = await traiter(fabrique, fetch, ["18032026R4C5", "18032026R4C6", "18032026R9C9", "bidon"],
                          pause=0, journal=journal, progression=0)

    # Appariement par (date, réunion, course) tiré de l'identifiant.
    assert appels == [("18032026", "4", 5), ("18032026", "4", 6), ("18032026", "9", 9)]
    async with fabrique() as s:
        rows = dict((await s.execute(text(
            "SELECT participation_id, numero_corde FROM participations"))).all())
    assert rows["p1"] == 11 and rows["p2"] == 12
    assert rows["p3"] is None            # placeCorde 0 → pas de stalle inventée
    assert rows["p4"] == 99              # jamais écrasé
    assert rows["q1"] is None and rows["q2"] is None   # course incohérente écartée
    assert rows["t1"] is None and rows["f1"] == 3

    assert bilan.mis_a_jour == 2
    assert bilan.deja_remplis == 1
    assert bilan.absents_en_base == 1
    assert bilan.courses_incoherentes == 1
    assert bilan.courses_introuvables == 1
    assert bilan.courses_id_non_standard == 1
    lignes = journal.read_text(encoding="utf-8").strip().splitlines()
    assert [l.split(";")[1:] for l in lignes] == [
        ["p1", "18032026R4C5", "1", "11"], ["p2", "18032026R4C5", "2", "12"]]

    # Idempotent : un second passage n'écrit plus rien.
    bilan2 = await traiter(fabrique, fetch, ["18032026R4C5"], pause=0, progression=0)
    assert bilan2.mis_a_jour == 0


@pytest.mark.asyncio
async def test_dry_run_n_ecrit_rien(fabrique):
    async def fetch(*_):
        return [_p(1, "NEBUR", 4)]
    bilan = await traiter(fabrique, fetch, ["18032026R4C5"], pause=0, dry_run=True, progression=0)
    assert bilan.mis_a_jour == 1
    async with fabrique() as s:
        v = (await s.execute(text(
            "SELECT numero_corde FROM participations WHERE participation_id='p1'"))).scalar()
    assert v is None


@pytest.mark.asyncio
async def test_debit_poli(fabrique):
    instants = []

    async def fetch(*_):
        instants.append(time.monotonic())
        return []
    await traiter(fabrique, fetch, ["18032026R4C5", "18032026R4C6", "18032026R1C1"],
                  pause=0.2, progression=0)
    ecarts = [b - a for a, b in zip(instants, instants[1:])]
    # Horloge Windows à ~15 ms de résolution : marge de 30 ms.
    assert all(e >= 0.17 for e in ecarts), ecarts
