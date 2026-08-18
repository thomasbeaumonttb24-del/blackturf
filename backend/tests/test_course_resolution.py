"""
Régression 2026-08-17 — cause racine des courses éternellement 'a_venir'.

`poll_resultats` (orchestrator.py) ne repolle que sur une fenêtre glissante de 36h ;
`Course.statut` ne passe à 'termine' que si un ordre d'arrivée PMU arrive. Une course
ANNULÉE n'en recevra JAMAIS → elle sortait du périmètre au bout de 36h et restait
'a_venir' à vie. Diagnostic prod : 159 courses bloquées, 159/159 en
`statut = COURSE_ANNULEE` côté API PMU (Chateaubriant 23/06 8/8, Langon-Libourne
28/07 8/8, Deauville 25/06 7/7, Palermo ARG, Casablanca, Wolvega…).

Ces tests verrouillent les trois couches du correctif :
  1. le scrape mappe COURSE_ANNULEE → statut='annule' (db_writer) ;
  2. le balayage quotidien clôture la traîne au-delà des 36h
     (services/course_resolution) ;
  3. une course sans aucun verdict PMU finit en 'sans_resultat' plutôt que de
     rester ouverte indéfiniment.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import db.database as dbmod
from db.models import Hippodrome, Reunion, Course
from services.course_resolution import (
    STATUT_ANNULE,
    STATUT_SANS_RESULTAT,
    STATUTS_NON_COURUES,
    resolve_courses_sans_resultat,
    statut_interne_depuis_pmu,
)


@pytest.fixture(autouse=True)
def _mute_error_monitor(monkeypatch):
    """`record_error` auto-crée sa table en SQL Postgres (BIGSERIAL/TIMESTAMPTZ) :
    sous SQLite l'INSERT casse et laisse la session à rollback. On la neutralise —
    ce qu'elle journalise est testé côté error_monitor, pas ici."""
    async def _noop_record(*a, **k):
        return None
    import services.error_monitor as em
    monkeypatch.setattr(em, "record_error", _noop_record)


def _use_test_db_as_session_local(monkeypatch, session):
    """Le moteur ouvre ses propres sessions via `db.database.AsyncSessionLocal()`
    (même pattern que job_expire_stale_value_bets) — on la fait pointer sur la
    session de test. `commit()` est neutralisé pour ne pas fermer la transaction
    du fixture."""
    @asynccontextmanager
    async def _ctx():
        yield session
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _ctx)


async def _seed_course(db, *, course_id: str, jours: float, statut: str = "a_venir"):
    """`course_id` doit garder la forme réelle {ddmmyyyy}R{n}C{n} : le moteur en
    déduit le n° de course et la date pour interroger le PMU."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom=f"Hippo {course_id}",
                       code=f"H{uuid.uuid4().hex[:6]}")
    db.add(hippo)
    reunion_id = f"R-{course_id}"
    db.add(Reunion(reunion_id=reunion_id, date=datetime.now(timezone.utc).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom=hippo.nom, numero=1))
    db.add(Course(
        course_id=course_id, reunion_id=reunion_id, numero=1, nom="Prix Test",
        date_heure=datetime.now(timezone.utc) - timedelta(days=jours),
        hippodrome_nom=hippo.nom, discipline="Plat", distance=2000,
        nb_partants=8, statut=statut,
    ))
    await db.commit()


class _FakePmu:
    """Double de PmuScraper : ni réseau, ni Playwright."""

    def __init__(self, *, statut=None, ordre=None):
        self._statut = statut
        self._ordre = ordre
        self.appels_statut = 0

    async def get_rapports_definitifs(self, reunion_id, course_num, course_date=None):
        if not self._ordre:
            return None
        from scraper.base import ResultatScrape
        return ResultatScrape(course_id="X", ordre_arrivee=self._ordre, rapports={})

    async def get_statut_course(self, reunion_id, course_num, course_date=None):
        self.appels_statut += 1
        return self._statut

    async def close(self):
        pass


def _patch_pmu(monkeypatch, fake):
    import scraper.sources.pmu as pmumod
    monkeypatch.setattr(pmumod, "PmuScraper", lambda *a, **k: fake)


async def _statut(db, course_id: str) -> str:
    return (await db.execute(
        select(Course.statut).where(Course.course_id == course_id))).scalar_one()


# ── 1. Mapping du statut PMU ────────────────────────────────────────────────

def test_mapping_course_annulee():
    assert statut_interne_depuis_pmu("COURSE_ANNULEE") == STATUT_ANNULE
    assert statut_interne_depuis_pmu("course_annulee") == STATUT_ANNULE  # casse ignorée
    # On ne déduit JAMAIS 'termine' du statut PMU : 'termine' veut dire « résultat en
    # base » pour tout l'aval (règlement des paris, features ML).
    assert statut_interne_depuis_pmu("ARRIVEE_DEFINITIVE_COMPLETE") is None
    assert statut_interne_depuis_pmu("PROGRAMMEE") is None
    assert statut_interne_depuis_pmu(None) is None


def test_statuts_non_courues_couvre_les_deux_cas():
    """Le programme et les stats doivent masquer les DEUX statuts terminaux."""
    assert STATUT_ANNULE in STATUTS_NON_COURUES
    assert STATUT_SANS_RESULTAT in STATUTS_NON_COURUES


# ── 2. Balayage : course annulée ────────────────────────────────────────────

async def test_course_annulee_passe_a_annule(db, monkeypatch):
    """Le cas des 159 courses de prod : PMU dit COURSE_ANNULEE → statut='annule'."""
    _use_test_db_as_session_local(monkeypatch, db)
    fake = _FakePmu(statut="COURSE_ANNULEE")
    _patch_pmu(monkeypatch, fake)
    await _seed_course(db, course_id="23062026R3C1", jours=60)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None)

    assert cr["annulees"] == 1
    assert await _statut(db, "23062026R3C1") == STATUT_ANNULE


async def test_resultat_tardif_prime_sur_annulation(db, monkeypatch):
    """Une arrivée publiée en retard doit clôturer la course en 'termine', même
    au-delà des 36h — le balayage n'est pas qu'un fossoyeur."""
    _use_test_db_as_session_local(monkeypatch, db)
    ordre = [{"numero": 3, "nom": "GAGNANT", "position": 1}]
    _patch_pmu(monkeypatch, _FakePmu(statut="ARRIVEE_DEFINITIVE_COMPLETE", ordre=ordre))
    await _seed_course(db, course_id="25062026R4C2", jours=5)

    saves = []

    async def _fake_save(session, resultat):
        saves.append(resultat)

    import scraper.db_writer as writer
    monkeypatch.setattr(writer, "save_resultat_to_db", _fake_save)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None)

    assert cr["terminees"] == 1
    assert cr["annulees"] == 0
    assert len(saves) == 1


# ── 3. Balayage : aucun verdict PMU ────────────────────────────────────────

async def test_sans_verdict_passe_sans_resultat_apres_le_delai(db, monkeypatch):
    """Ni arrivée ni COURSE_ANNULEE + course vieille → statut terminal
    'sans_resultat' (au lieu de rester 'a_venir' à vie)."""
    _use_test_db_as_session_local(monkeypatch, db)
    _patch_pmu(monkeypatch, _FakePmu(statut=None))
    await _seed_course(db, course_id="01062026R5C3", jours=9)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None, delai_abandon_jours=4)

    assert cr["sans_resultat"] == 1
    assert await _statut(db, "01062026R5C3") == STATUT_SANS_RESULTAT


async def test_sans_verdict_recent_reste_ouvert(db, monkeypatch):
    """Sous le délai d'abandon on laisse sa chance au PMU : statut inchangé."""
    _use_test_db_as_session_local(monkeypatch, db)
    _patch_pmu(monkeypatch, _FakePmu(statut="FIN_COURSE"))
    await _seed_course(db, course_id="15082026R1C4", jours=2)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None, delai_abandon_jours=4)

    assert cr["sans_resultat"] == 0
    assert await _statut(db, "15082026R1C4") == "a_venir"


async def test_sans_resultat_reste_rejouable(db, monkeypatch):
    """Une course déjà 'sans_resultat' est reprise par le balayage : si le PMU finit
    par publier l'arrivée, elle passe 'termine'. Statut terminal ≠ cul-de-sac."""
    _use_test_db_as_session_local(monkeypatch, db)
    ordre = [{"numero": 1, "nom": "TARDIF", "position": 1}]
    _patch_pmu(monkeypatch, _FakePmu(ordre=ordre))
    await _seed_course(db, course_id="11082026R2C5", jours=6, statut=STATUT_SANS_RESULTAT)

    async def _fake_save(session, resultat):
        return None

    import scraper.db_writer as writer
    monkeypatch.setattr(writer, "save_resultat_to_db", _fake_save)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None)

    assert cr["scannees"] == 1
    assert cr["terminees"] == 1


# ── 4. Bornes du balayage ──────────────────────────────────────────────────

async def test_course_recente_hors_perimetre(db, monkeypatch):
    """Moins de 36h : c'est le domaine de poll_resultats, le balayage n'y touche pas
    (sinon on doublerait les requêtes PMU sur le live)."""
    _use_test_db_as_session_local(monkeypatch, db)
    fake = _FakePmu(statut="COURSE_ANNULEE")
    _patch_pmu(monkeypatch, fake)
    await _seed_course(db, course_id="17082026R6C1", jours=0.5)

    cr = await resolve_courses_sans_resultat()

    assert cr["scannees"] == 0
    assert fake.appels_statut == 0
    assert await _statut(db, "17082026R6C1") == "a_venir"


async def test_course_terminee_ignoree(db, monkeypatch):
    """Une course déjà 'termine' ne doit jamais être rouverte ni re-sondée."""
    _use_test_db_as_session_local(monkeypatch, db)
    fake = _FakePmu(statut="COURSE_ANNULEE")
    _patch_pmu(monkeypatch, fake)
    await _seed_course(db, course_id="07082026R3C2", jours=10, statut="termine")

    cr = await resolve_courses_sans_resultat(fenetre_jours=None)

    assert cr["scannees"] == 0
    assert await _statut(db, "07082026R3C2") == "termine"


async def test_dry_run_n_ecrit_rien(db, monkeypatch):
    """Le backfill doit pouvoir auditer sans muter la base."""
    _use_test_db_as_session_local(monkeypatch, db)
    _patch_pmu(monkeypatch, _FakePmu(statut="COURSE_ANNULEE"))
    await _seed_course(db, course_id="18072026R2C7", jours=30)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None, dry_run=True)

    assert cr["annulees"] == 1
    assert await _statut(db, "18072026R2C7") == "a_venir"


async def test_limite_borne_les_requetes_pmu(db, monkeypatch):
    """La limite protège le PMU d'un balayage massif en un seul appel."""
    _use_test_db_as_session_local(monkeypatch, db)
    fake = _FakePmu(statut="COURSE_ANNULEE")
    _patch_pmu(monkeypatch, fake)
    for i in range(5):
        await _seed_course(db, course_id=f"0{i+1}082026R1C{i+1}", jours=20 + i)

    cr = await resolve_courses_sans_resultat(fenetre_jours=None, limite=2)

    assert cr["scannees"] == 2
    assert fake.appels_statut == 2
