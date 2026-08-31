"""
Régression : la page /value-bets affichait des paris datés de plusieurs mois
(constaté 2026-08-17, ex. Hippodrome de Palermo ARG daté du 01/06 alors que le jour
était le 17/08). Cause : `ValueBet.actif` n'est posé qu'à la création et n'était
JAMAIS remis à False ailleurs ; les endpoints filtrent en plus sur
`Course.statut IN ('a_venir','en_cours')`, mais ce statut ne passe à 'termine' que
si un résultat PMU est reçu — une course jamais résultée (piste étrangère non
couverte, panne scraper) reste 'a_venir' à vie et son value bet reste "actif"
indéfiniment. `job_expire_stale_value_bets` (services/jobs.py) est le filet de
sécurité qui les désactive après 6h, indépendamment du statut de la course.
"""
import uuid
from contextlib import asynccontextmanager

import pytest

from datetime import datetime, timedelta, timezone

from db.models import Hippodrome, Reunion, Course, Cheval, Participation, Prediction, ValueBet
from services.jobs import job_expire_stale_value_bets
import db.database as dbmod

pytestmark = pytest.mark.asyncio


def _use_test_db_as_session_local(monkeypatch, session):
    """`job_expire_stale_value_bets` ouvre sa propre session via
    `db.database.AsyncSessionLocal()` (pattern APScheduler standard, cf.
    job_drift_check) — on la fait pointer vers la session de test pour qu'elle
    voie les données seedées par ce test."""
    @asynccontextmanager
    async def _ctx():
        yield session
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _ctx)


async def _seed_vb(db, *, course_id: str, hours_ago: float, statut: str = "a_venir"):
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Test Hippo", code="TH")
    db.add(hippo)
    reunion = Reunion(reunion_id=f"R{course_id}", date=datetime.now(timezone.utc).date(),
                       hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Test Hippo", numero=1)
    db.add(reunion)
    course = Course(
        course_id=course_id, reunion_id=f"R{course_id}", numero=1, nom="Test",
        date_heure=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        hippodrome_nom="Test Hippo", discipline="Plat", distance=2000,
        nb_partants=6, statut=statut,
    )
    db.add(course)
    cheval = Cheval(cheval_id=str(uuid.uuid4()), nom="Cheval Test", age=5, sexe="H")
    db.add(cheval)
    part = Participation(participation_id=str(uuid.uuid4()), course_id=course_id,
                          cheval_id=cheval.cheval_id, numero=1, cote_pmu=4.5, non_partant=False)
    db.add(part)
    await db.flush()
    pred = Prediction(prediction_id=str(uuid.uuid4()), participation_id=part.participation_id,
                       course_id=course_id, proba_top1=0.28, proba_top3=0.65,
                       rang_predit=1, confidence_score=65.0)
    db.add(pred)
    vb = ValueBet(vb_id=str(uuid.uuid4()), prediction_id=pred.prediction_id, course_id=course_id,
                  participation_id=part.participation_id, ev_pmu=0.25, ev_max=0.25,
                  meilleure_source="pmu", niveau=3, spi_detected=False, actif=True)
    db.add(vb)
    await db.commit()
    return vb.vb_id


async def test_expire_deactivates_old_never_resulted_course(db, monkeypatch):
    """Course vieille de 2 mois, jamais résultée (statut resté 'a_venir') → désactivée."""
    _use_test_db_as_session_local(monkeypatch, db)
    vb_id = await _seed_vb(db, course_id="OLD1", hours_ago=24 * 60, statut="a_venir")

    await job_expire_stale_value_bets()

    from sqlalchemy import select
    vb = (await db.execute(select(ValueBet).where(ValueBet.vb_id == vb_id))).scalar_one()
    assert vb.actif is False


async def test_expire_keeps_recent_active_bet(db, monkeypatch):
    """Course d'il y a 1h, à venir → reste active (le filet ne doit rien casser du live)."""
    _use_test_db_as_session_local(monkeypatch, db)
    vb_id = await _seed_vb(db, course_id="NEW1", hours_ago=1, statut="a_venir")

    await job_expire_stale_value_bets()

    from sqlalchemy import select
    vb = (await db.execute(select(ValueBet).where(ValueBet.vb_id == vb_id))).scalar_one()
    assert vb.actif is True
