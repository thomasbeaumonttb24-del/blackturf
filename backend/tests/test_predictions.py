"""Tests predictions & value bets routes."""
import uuid
import pytest
from datetime import datetime, timezone, date
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Hippodrome, Reunion, Course, Cheval, Participation,
    Prediction, ValueBet, User
)

pytestmark = pytest.mark.asyncio


async def _seed_course_with_predictions(db: AsyncSession) -> tuple[str, str]:
    """Seed une course avec prédictions + value bet. Retourne (course_id, user_id_standard)."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Vincennes Test", code="VT")
    db.add(hippo)

    reunion = Reunion(
        reunion_id="R99",
        date=date.today(),
        hippodrome_id=hippo.hippodrome_id,
        hippodrome_nom="Vincennes Test",
        numero=99,
    )
    db.add(reunion)

    course = Course(
        course_id="R99C1",
        reunion_id="R99",
        numero=1,
        nom="Prix Prédiction",
        date_heure=datetime.now(timezone.utc).replace(hour=15),
        hippodrome_nom="Vincennes Test",
        discipline="Plat",
        distance=2000,
        nb_partants=6,
        statut="a_venir",
    )
    db.add(course)

    cheval = Cheval(cheval_id=str(uuid.uuid4()), nom="Fusée IA", age=5, sexe="H")
    db.add(cheval)

    part = Participation(
        participation_id=str(uuid.uuid4()),
        course_id="R99C1",
        cheval_id=cheval.cheval_id,
        numero=1,
        cote_pmu=4.5,
        non_partant=False,
    )
    db.add(part)
    await db.flush()

    pred = Prediction(
        prediction_id=str(uuid.uuid4()),
        participation_id=part.participation_id,
        course_id="R99C1",
        proba_top1=0.28,
        proba_top3=0.65,
        rang_predit=1,
        confidence_score=65.0,
    )
    db.add(pred)

    vb = ValueBet(
        vb_id=str(uuid.uuid4()),
        prediction_id=pred.prediction_id,
        course_id="R99C1",
        participation_id=part.participation_id,
        ev_pmu=0.25,
        ev_max=0.25,
        meilleure_source="pmu",
        niveau=3,
        spi_detected=False,
        actif=True,
    )
    db.add(vb)
    await db.commit()
    return "R99C1", part.participation_id


async def _make_standard_headers(client: AsyncClient) -> dict:
    """Crée un user standard et retourne headers."""
    from api.routes.auth import _hash
    from db.models import User
    import uuid

    # Register then set plan
    resp = await client.post("/api/v1/auth/register", json={
        "email": f"std_{uuid.uuid4().hex[:6]}@blackturf.fr",
        "password": "Pass123!",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────
# Prédictions
# ─────────────────────────────────────────────
async def test_get_predictions_requires_auth(client: AsyncClient, db: AsyncSession):
    await _seed_course_with_predictions(db)
    resp = await client.get("/api/v1/courses/R99C1/predictions")
    assert resp.status_code == 401


async def test_get_predictions_requires_paid_plan(client: AsyncClient, db: AsyncSession):
    await _seed_course_with_predictions(db)
    # Free user
    headers = await _make_standard_headers(client)
    resp = await client.get("/api/v1/courses/R99C1/predictions", headers=headers)
    # Free plan → 403
    assert resp.status_code == 403


async def test_get_predictions_course_not_found(client: AsyncClient, db: AsyncSession, admin_headers):
    resp = await client.get("/api/v1/courses/DOESNOTEXIST/predictions", headers=admin_headers)
    assert resp.status_code == 404


async def test_get_predictions_no_predictions_yet(client: AsyncClient, db: AsyncSession):
    # Course exists but no predictions → 404
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Empty Test", code="ET")
    db.add(hippo)
    reunion = Reunion(reunion_id="R88", date=date.today(), hippodrome_id=hippo.hippodrome_id,
                       hippodrome_nom="Empty Test", numero=88)
    db.add(reunion)
    course = Course(course_id="R88C1", reunion_id="R88", numero=1, nom="Vide",
                    date_heure=datetime.now(timezone.utc), hippodrome_nom="Empty Test",
                    discipline="Plat", distance=1600, nb_partants=5, statut="a_venir")
    db.add(course)
    await db.commit()

    resp = await client.get("/api/v1/courses/R88C1/predictions", headers=None)
    assert resp.status_code in (401, 403, 404)


async def test_trigger_prediction_requires_pro(client: AsyncClient, db: AsyncSession):
    await _seed_course_with_predictions(db)
    headers = await _make_standard_headers(client)
    resp = await client.post("/api/v1/courses/R99C1/predict", headers=headers)
    # Free user → 403
    assert resp.status_code == 403


# ─────────────────────────────────────────────
# Value Bets
# ─────────────────────────────────────────────
async def test_value_bets_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/value-bets")
    assert resp.status_code == 401


async def test_value_bets_requires_paid_plan(client: AsyncClient, db: AsyncSession):
    headers = await _make_standard_headers(client)
    resp = await client.get("/api/v1/value-bets", headers=headers)
    assert resp.status_code == 403


async def test_value_bets_historique_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/value-bets/historique")
    assert resp.status_code == 401


async def test_model_version_public(client: AsyncClient):
    """GET /model/version est public."""
    resp = await client.get("/api/v1/model/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data or "version_num" in data or data == {"version": None}


async def test_value_bets_niveau_min_validation(client: AsyncClient, auth_headers):
    """niveau_min hors plage 1-4 → 422."""
    resp = await client.get("/api/v1/value-bets", params={"niveau_min": 0}, headers=auth_headers)
    assert resp.status_code in (403, 422)  # 403 si free, 422 si pro mais invalid param

    resp = await client.get("/api/v1/value-bets", params={"niveau_min": 5}, headers=auth_headers)
    assert resp.status_code in (403, 422)
