"""Correctifs données du scraper (audit du 2026-10-07).

Chaque test fige un défaut constaté : donnée figée au premier scrape (âge, jockey,
terrain), donnée écrasée (pénétromètre de toutes les R1 de l'historique), donnée
fausse (décharge = poids, date d'historique décalée d'un jour) ou file qui ne se
vide jamais (enrichissement post-PMU).
"""
import inspect
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from db.models import Cheval, Course, HistoriqueCourse, Participation, PerformanceCarriere
from scraper.base import CourseScrape, PartantScrape, PenetrometreScrape
import scraper.db_writer as dw
from scraper.db_writer import (
    champs_maj_course, champs_reecrits_participation, dates_historique_pmu,
    detect_jockey_change, oeilleres_portees, propager_penetrometre,
    save_historique_pmu, upsert_cheval,
)


def _partant(**kw):
    base = dict(numero=1, nom="PEGASE", cote_pmu=4.2, jockey="J", entraineur="E")
    base.update(kw)
    return PartantScrape(**base)


# ── 1. L'âge vieillit ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_age_du_cheval_suit_le_pmu(db):
    db.add(Cheval(cheval_id="CH", nom="PEGASE", age=3))
    db.add(PerformanceCarriere(cheval_id="CH"))
    await db.commit()

    await upsert_cheval(db, _partant(age=4))
    assert (await db.get(Cheval, "CH")).age == 4

    # Âge absent du flux : on ne l'efface pas.
    await upsert_cheval(db, _partant(age=None))
    assert (await db.get(Cheval, "CH")).age == 4


# ── 2. Changement de monte de dernière minute ───────────────────────────────

def test_jockey_entraineur_poids_reecrits_au_rescrape():
    champs = champs_reecrits_participation(
        _partant(poids=57.5), 4.2, None, None, jockey_id="jk2", entraineur_id="en2")
    assert champs["jockey_id"] == "jk2"
    assert champs["entraineur_id"] == "en2"
    assert champs["poids_porte"] == 57.5


def test_jockey_entraineur_poids_absents_n_effacent_rien():
    champs = champs_reecrits_participation(_partant(poids=None), 4.2, None, None)
    for k in ("jockey_id", "entraineur_id", "poids_porte"):
        assert k not in champs
    champs = champs_reecrits_participation(_partant(), 4.2, None, None,
                                           jockey_id=None, entraineur_id="")
    assert "jockey_id" not in champs and "entraineur_id" not in champs


def test_l_upsert_passe_bien_le_jockey_du_jour():
    src = inspect.getsource(dw.save_course_to_db)
    assert "jockey_id=jockey_id or None, entraineur_id=entraineur_id or None" in src


async def _course(db, cid, quand, reunion="1"):
    db.add(Course(course_id=cid, reunion_id=reunion, hippodrome_nom="CHANTILLY",
                  numero=1, nom=cid, discipline="Plat", distance=1600, date_heure=quand))


@pytest.mark.asyncio
async def test_le_drapeau_jockey_se_remet_a_false_et_ignore_les_non_partants(db):
    base = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _course(db, "AVANT", base)
    await _course(db, "NP", base + timedelta(days=5))
    await _course(db, "JOUR", base + timedelta(days=10))
    db.add(Participation(participation_id="p_avant", course_id="AVANT", cheval_id="CH",
                         numero=1, jockey_id="jkA", non_partant=False))
    # Forfait : le jockey déclaré n'est jamais monté, ce n'est pas « celui d'avant ».
    db.add(Participation(participation_id="p_np", course_id="NP", cheval_id="CH",
                         numero=1, jockey_id="jkB", non_partant=True))
    db.add(Participation(participation_id="p_jour", course_id="JOUR", cheval_id="CH",
                         numero=1, jockey_id="jkA", changement_jockey=True))
    await db.commit()

    # Même jockey que la dernière course RÉELLEMENT courue → False (et le True
    # posé par erreur est remis à False).
    assert await detect_jockey_change(db, "JOUR", "CH", "jkA", "p_jour") is False
    await db.commit()
    assert (await db.get(Participation, "p_jour")).changement_jockey is False

    assert await detect_jockey_change(db, "JOUR", "CH", "jkC", "p_jour") is True
    await db.commit()
    db.expire_all()
    assert (await db.get(Participation, "p_jour")).changement_jockey is True


# ── 3. Terrain : un NULL n'écrase pas une mesure ─────────────────────────────

def _course_scrape(**kw):
    base = dict(reunion_id="1", course_id="07102026R1C1", hippodrome="CHANTILLY",
                date_heure="", discipline="Plat", distance=1600)
    base.update(kw)
    return CourseScrape(**base)


def test_terrain_absent_n_ecrase_pas():
    champs = champs_maj_course(_course_scrape(terrain=None, terrain_code=None,
                                              penetrometre_coef=None), None, None)
    for k in ("terrain_officiel", "terrain_code", "penetrometre_coef"):
        assert k not in champs


def test_terrain_present_est_reecrit():
    champs = champs_maj_course(_course_scrape(terrain="Souple", terrain_code="SOUPLE",
                                              penetrometre_coef=3.8), None, None)
    assert champs["terrain_officiel"] == "Souple"
    assert champs["terrain_code"] == "SOUPLE"
    assert champs["penetrometre_coef"] == 3.8


# ── 4. Pénétromètre : la R1 du jour, pas toutes les R1 ──────────────────────

@pytest.mark.asyncio
async def test_le_penetrometre_ne_touche_que_la_reunion_du_jour(db):
    jour = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)
    await _course(db, "07102026R1C1", jour)
    await _course(db, "07102026R1C2", jour + timedelta(minutes=30))
    await _course(db, "06102026R1C1", jour - timedelta(days=1))   # R1 de la veille
    await _course(db, "07102026R2C1", jour, reunion="2")
    await db.commit()

    pen = PenetrometreScrape(reunion_id="R1", hippodrome="CHANTILLY",
                             date="2026-10-07", coefficient=4.1, description="Souple")
    await propager_penetrometre(db, pen, 4.1)
    await db.commit()

    rows = dict((await db.execute(text(
        "SELECT course_id, penetrometre_coef FROM courses"))).all())
    assert rows["07102026R1C1"] == 4.1 and rows["07102026R1C2"] == 4.1
    assert rows["06102026R1C1"] is None      # l'historique n'est plus réécrit
    assert rows["07102026R2C1"] is None


@pytest.mark.asyncio
async def test_une_mesure_rejetee_n_efface_pas_le_coefficient(db):
    jour = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)
    db.add(Course(course_id="07102026R1C1", reunion_id="1", hippodrome_nom="X", numero=1,
                  nom="x", discipline="Plat", distance=1600, date_heure=jour,
                  penetrometre_coef=3.2))
    await db.commit()
    pen = PenetrometreScrape(reunion_id="1", hippodrome="X", date="2026-10-07",
                             coefficient=42.0, description="?")
    await propager_penetrometre(db, pen, None)
    await db.commit()
    assert (await db.get(Course, "07102026R1C1")).penetrometre_coef == 3.2


def test_le_journal_penetrometre_reflete_la_derniere_mesure():
    src = inspect.getsource(dw.save_penetrometre)
    for col in ('"date_mesure"', '"hippodrome"', '"heure_mesure"'):
        assert col in src


# ── 5. Premières œillères : libellés PMU ────────────────────────────────────

@pytest.mark.parametrize("raw,attendu", [
    ("SANS_OEILLERES", False), ("Sans", False), ("OEILLERES_CLASSIQUE", True),
    ("OEILLERES_AUSTRALIENNES", True), (None, None), ("", None)])
def test_oeilleres_portees(raw, attendu):
    assert oeilleres_portees(raw) is attendu


class _SessionCapture:
    def __init__(self):
        self.stmts = []

    async def execute(self, stmt, *a, **kw):
        self.stmts.append(stmt)


@pytest.mark.asyncio
@pytest.mark.parametrize("avant,jour,premiere", [
    ("SANS_OEILLERES", "OEILLERES_CLASSIQUE", True),
    ("OEILLERES_CLASSIQUE", "OEILLERES_AUSTRALIENNES", False),
    ("OEILLERES_CLASSIQUE", "SANS_OEILLERES", False),
])
async def test_premieres_oeilleres_avec_les_libelles_pmu(monkeypatch, avant, jour, premiere):
    async def _prec(session, cheval_id, course_id):
        return (None, avant)
    monkeypatch.setattr(dw, "equipement_precedent", _prec)
    s = _SessionCapture()
    await dw._save_equipement(s, "pid", "CH", "C", _partant(oeilleres=jour))
    params = s.stmts[0].compile(dialect=postgresql.dialect()).params
    assert params["oeilleres_change"] is True
    assert params["premieres_oeilleres"] is premiere


# ── 6. Décharge : jamais le poids du handicap ────────────────────────────────

def test_la_decharge_n_est_pas_le_poids_du_handicap():
    from scraper.sources.pmu import PmuScraper
    p = PmuScraper()._parse_partants([{"numPmu": 1, "nom": "A", "handicapPoids": 560}])[0]
    assert p.poids == 56.0
    assert p.decharge is None


def test_date_url_pmu_au_jour_de_paris():
    from scraper.sources.pmu import _fmt_date_pmu
    # 7 oct. 2026 00 h 30 à Paris = 6 oct. 22 h 30 UTC.
    ms = int(datetime(2026, 10, 6, 22, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert _fmt_date_pmu(ms) == "07102026"


# ── 9. Date des performances PMU : le jour à Paris ──────────────────────────

def _minuit_paris_ms(d: date) -> int:
    from zoneinfo import ZoneInfo
    return int(datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("Europe/Paris"))
               .timestamp() * 1000)


def test_dates_historique_pmu():
    reelle, heritee = dates_historique_pmu(_minuit_paris_ms(date(2026, 9, 14)))
    assert reelle == date(2026, 9, 14)
    assert heritee == date(2026, 9, 13)      # ce qu'écrivait l'ancien calcul (UTC)


def _perf(d, **kw):
    base = dict(date_ms=_minuit_paris_ms(d), hippodrome="VINCENNES", discipline="ATTELE",
                distance=2700, position=2, ecart=1.5)
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_une_copie_heritee_n_est_pas_reinseree(db):
    """Les copies déjà en base sont datées de la veille : le premier re-scrape avec
    la date corrigée ne doit pas les dupliquer, seulement les compléter."""
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    db.add(HistoriqueCourse(historique_id="h_old", cheval_id="CH", course_id=None,
                            date_course=date(2026, 9, 13), hippodrome="VINCENNES",
                            discipline="ATTELE", distance=2700, position_arrivee=2))
    await db.commit()

    ajoutees = await save_historique_pmu(db, "PEGASE", [_perf(date(2026, 9, 14))])
    await db.commit()
    assert ajoutees == 0
    rows = (await db.execute(select(HistoriqueCourse))).scalars().all()
    assert len(rows) == 1 and rows[0].ecart_longueurs == 1.5


@pytest.mark.asyncio
async def test_nouvelle_copie_datee_du_bon_jour_et_ligne_interne_preservee(db):
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    # Ligne INTERNE du même jour : elle n'est pas une copie, on ne s'y raccroche pas
    # (c'est la lecture BT_HIST_V2 qui apparie ligne interne et copie).
    db.add(HistoriqueCourse(historique_id="h_int", cheval_id="CH", course_id="14092026R1C1",
                            date_course=date(2026, 9, 14), hippodrome="VINCENNES",
                            discipline="ATTELE", distance=2700, position_arrivee=2))
    await db.commit()

    assert await save_historique_pmu(db, "PEGASE", [_perf(date(2026, 9, 14))]) == 1
    await db.commit()
    copie = (await db.execute(select(HistoriqueCourse).where(
        HistoriqueCourse.course_id.is_(None)))).scalar_one()
    assert copie.date_course == date(2026, 9, 14)
    # Re-scrape : idempotent.
    assert await save_historique_pmu(db, "PEGASE", [_perf(date(2026, 9, 14))]) == 0


@pytest.mark.asyncio
async def test_la_veille_a_une_autre_distance_n_est_pas_la_meme_course(db):
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    db.add(HistoriqueCourse(historique_id="h_veille", cheval_id="CH", course_id=None,
                            date_course=date(2026, 9, 13), hippodrome="VINCENNES",
                            discipline="ATTELE", distance=2100, position_arrivee=5))
    await db.commit()
    assert await save_historique_pmu(db, "PEGASE", [_perf(date(2026, 9, 14))]) == 1


# ── 11. Enrichissement post-PMU : file triée, qui se termine ────────────────

@pytest.mark.asyncio
async def test_enrichissement_traite_tout_le_jour_et_rejoue_le_jockey(engine, db, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    import scraper.orchestrator as orch

    monkeypatch.setattr(orch, "AsyncSessionLocal",
                        async_sessionmaker(engine, expire_on_commit=False))
    aujourd_hui = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0,
                                                     microsecond=0)
    monkeypatch.setattr(orch, "jour_courses", lambda *a: aujourd_hui.date())

    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    db.add(Cheval(cheval_id="DEB", nom="DEBUTANT"))
    db.add(Course(course_id="AVANT", reunion_id="1", hippodrome_nom="X", numero=1, nom="a",
                  discipline="Plat", distance=1600, statut="termine",
                  date_heure=aujourd_hui - timedelta(days=10)))
    db.add(Course(course_id="JOUR", reunion_id="1", hippodrome_nom="X", numero=2, nom="j",
                  discipline="Plat", distance=1600, statut="a_venir", date_heure=aujourd_hui))
    db.add(Participation(participation_id="p_avant", course_id="AVANT", cheval_id="CH",
                         numero=1, jockey_id="jkA", non_partant=False))
    # Repos déjà calculé (le MAX(date_heure) de SQLite rend du texte : le calcul
    # lui-même n'est pas l'objet de ce test). Le débutant, lui, reste à NULL à vie.
    db.add(Participation(participation_id="p_jour", course_id="JOUR", cheval_id="CH",
                         numero=1, jockey_id="jkA", non_partant=False,
                         jours_depuis_derniere=10))
    db.add(Participation(participation_id="p_deb", course_id="JOUR", cheval_id="DEB",
                         numero=2, jockey_id="jkD", non_partant=False))
    await db.commit()

    erreurs = []
    monkeypatch.setattr(orch.log, "error", lambda *a, **kw: erreurs.append((a, kw)))
    o = object.__new__(orch.BlackTurfOrchestrator)
    await o.run_enrichissement_participations()
    db.expire_all()
    p = await db.get(Participation, "p_jour")
    assert p.changement_jockey is False and not erreurs
    assert (await db.get(Participation, "p_deb")).jours_depuis_derniere is None

    # Changement de monte publié APRÈS le premier passage : il est vu.
    await db.execute(text("UPDATE participations SET jockey_id='jkZ' "
                          "WHERE participation_id='p_jour'"))
    await db.commit()
    await o.run_enrichissement_participations()
    db.expire_all()
    assert (await db.get(Participation, "p_jour")).changement_jockey is True
    assert not erreurs
