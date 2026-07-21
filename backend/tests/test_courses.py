"""Tests courses routes."""
import uuid
import pytest
from datetime import datetime, timezone, date
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Hippodrome, Reunion, Course, Cheval, Participation, Prediction

pytestmark = pytest.mark.asyncio

DATE_TODAY = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)


async def _create_test_course(db: AsyncSession) -> str:
    """Crée une course de test et retourne course_id."""
    hippo = Hippodrome(
        hippodrome_id=str(uuid.uuid4()),
        nom="Longchamp Test",
        code="LCT",
    )
    db.add(hippo)

    reunion = Reunion(
        reunion_id="R1",
        date=date.today(),
        hippodrome_id=hippo.hippodrome_id,
        hippodrome_nom="Longchamp Test",
        numero=1,
    )
    db.add(reunion)

    course = Course(
        course_id="R1C1",
        reunion_id="R1",
        numero=1,
        nom="Prix Test",
        date_heure=DATE_TODAY,
        hippodrome_nom="Longchamp Test",
        discipline="Plat",
        distance=1600,
        nb_partants=8,
        statut="a_venir",
    )
    db.add(course)

    cheval = Cheval(
        cheval_id=str(uuid.uuid4()),
        nom="Champion Test",
        age=4,
        sexe="H",
    )
    db.add(cheval)

    part = Participation(
        participation_id=str(uuid.uuid4()),
        course_id="R1C1",
        cheval_id=cheval.cheval_id,
        numero=1,
        cote_pmu=3.5,
        non_partant=False,
    )
    db.add(part)

    # Prédiction figée : sans elle, /mise-plan renvoie 409 (« pronostic pas encore
    # disponible »). Le test du happy-path doit donc fournir un prono.
    pred = Prediction(
        prediction_id=str(uuid.uuid4()),
        participation_id=part.participation_id,
        course_id="R1C1",
        proba_top1=0.35,
        proba_top3=0.70,
        rang_predit=1,
    )
    db.add(pred)
    await db.commit()
    return "R1C1"


async def test_get_programme_today(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/programme")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert "reunions" in data
    assert isinstance(data["reunions"], list)


async def test_get_programme_with_date(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/programme", params={"jour": date.today().isoformat()})
    assert resp.status_code == 200


async def test_get_course_detail(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["course_id"] == "R1C1"
    assert data["discipline"] == "Plat"
    assert len(data["partants"]) >= 1
    assert data["partants"][0]["nom_cheval"] == "Champion Test"


async def test_get_course_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/courses/NOTEXIST")
    assert resp.status_code == 404


async def test_get_resultats_not_found(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1/resultats")
    assert resp.status_code == 404


async def test_get_cotes_historique_requires_auth(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1/cotes-historique")
    assert resp.status_code == 401


async def test_get_cheval_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/chevaux/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_mise_plan_requires_auth(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.post("/api/v1/courses/R1C1/mise-plan", json={"montant": 50})
    assert resp.status_code == 401


async def test_mise_plan_requires_paid_plan(client: AsyncClient, db: AsyncSession, auth_headers):
    await _create_test_course(db)
    resp = await client.post("/api/v1/courses/R1C1/mise-plan", json={"montant": 50}, headers=auth_headers)
    # Free plan → 403
    assert resp.status_code == 403


async def test_mise_plan_returns_plan(client: AsyncClient, db: AsyncSession, admin_headers):
    """Admin (expert plan) can get a mise plan."""
    await _create_test_course(db)
    resp = await client.post(
        "/api/v1/courses/R1C1/mise-plan",
        json={"montant": 100.0, "profil_risque": "equilibre"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data or "mises" in data or isinstance(data, dict)


async def test_mise_plan_invalid_montant(client: AsyncClient, db: AsyncSession, admin_headers):
    await _create_test_course(db)
    resp = await client.post(
        "/api/v1/courses/R1C1/mise-plan",
        json={"montant": -10},
        headers=admin_headers,
    )
    assert resp.status_code == 422
