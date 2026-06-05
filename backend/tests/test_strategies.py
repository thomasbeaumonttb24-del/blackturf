"""Tests strategies routes — plan Expert requis."""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from api.routes.auth import _hash

pytestmark = pytest.mark.asyncio

STRAT_PAYLOAD = {
    "nom": "Test EV+",
    "filtres": {"discipline": "Plat", "distance_min": 1400},
    "indicateurs": {"proba_top3_min": 0.45, "ev_min": 0.08, "niveau_vb_min": 1},
    "alerte_email": False,
    "partage_communaute": False,
}


async def _expert_headers(client: AsyncClient, db: AsyncSession) -> dict:
    expert = User(
        user_id=str(uuid.uuid4()),
        email=f"expert_{uuid.uuid4().hex[:6]}@blackturf.fr",
        hashed_password=_hash("Expert123!"),
        plan="expert",
        is_admin=False,
    )
    db.add(expert)
    await db.commit()

    resp = await client.post("/api/v1/auth/login", data={
        "username": expert.email,
        "password": "Expert123!",
    })
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ─── Auth / plan gates ───────────────────────────────────────
async def test_strategies_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/strategies")
    assert resp.status_code == 401


async def test_strategies_requires_expert_plan(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/strategies", headers=auth_headers)
    assert resp.status_code == 403


# ─── CRUD ────────────────────────────────────────────────────
async def test_create_strategy(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    resp = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["nom"] == "Test EV+"
    assert data["filtres"]["discipline"] == "Plat"
    assert "strategie_id" in data
    return data["strategie_id"]


async def test_list_strategies(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    resp = await client.get("/api/v1/strategies", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


async def test_update_strategy(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    create = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    strat_id = create.json()["strategie_id"]

    resp = await client.patch(
        f"/api/v1/strategies/{strat_id}",
        json={"nom": "Renamed", "alerte_email": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["nom"] == "Renamed"
    assert resp.json()["alerte_email"] is True


async def test_delete_strategy(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    create = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    strat_id = create.json()["strategie_id"]

    resp = await client.delete(f"/api/v1/strategies/{strat_id}", headers=headers)
    assert resp.status_code == 204

    # Verify gone
    list_resp = await client.get("/api/v1/strategies", headers=headers)
    ids = [s["strategie_id"] for s in list_resp.json()]
    assert strat_id not in ids


async def test_delete_other_user_strategy_404(client: AsyncClient, db: AsyncSession, admin_headers):
    headers = await _expert_headers(client, db)
    create = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    strat_id = create.json()["strategie_id"]

    # Admin tries to delete other user's strategy
    resp = await client.delete(f"/api/v1/strategies/{strat_id}", headers=admin_headers)
    assert resp.status_code == 404


# ─── Backtest ────────────────────────────────────────────────
async def test_backtest_no_data_returns_zero(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    create = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    strat_id = create.json()["strategie_id"]

    resp = await client.post(
        f"/api/v1/strategies/{strat_id}/backtest",
        params={"jours": 30, "mise_fixe": 10.0},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # No historical data in test DB → 0 bets simulated
    assert data["nb_paris"] == 0
    assert data["mise_totale"] == 0.0
    assert "courbe" in data
    assert "avertissement" in data


async def test_backtest_requires_expert(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v1/strategies/some-id/backtest",
        headers=auth_headers,
    )
    assert resp.status_code == 403


async def test_backtest_invalid_jours(client: AsyncClient, db: AsyncSession):
    headers = await _expert_headers(client, db)
    create = await client.post("/api/v1/strategies", json=STRAT_PAYLOAD, headers=headers)
    strat_id = create.json()["strategie_id"]

    resp = await client.post(
        f"/api/v1/strategies/{strat_id}/backtest",
        params={"jours": 3},  # < 7 minimum
        headers=headers,
    )
    assert resp.status_code == 422
