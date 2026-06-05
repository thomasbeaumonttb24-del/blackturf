"""Tests admin routes — accès restreint."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_dashboard_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/dashboard", headers=auth_headers)
    assert resp.status_code == 403


async def test_dashboard_admin_ok(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/dashboard", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert "modele" in data


async def test_list_users_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/users", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_users_non_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/users", headers=auth_headers)
    assert resp.status_code == 403


async def test_list_models_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/models", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_scraper_logs_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/scraper/logs", headers=admin_headers)
    assert resp.status_code == 200


async def test_scraper_status_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/scraper/status", headers=admin_headers)
    assert resp.status_code == 200


async def test_update_user_plan(client: AsyncClient, admin_headers, auth_headers):
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["user_id"]

    resp = await client.patch(
        f"/admin/api/users/{user_id}",
        json={"plan": "standard"},
        headers=admin_headers,
    )
    assert resp.status_code == 200

    me_after = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_after.json()["plan"] == "standard"


async def test_alertes_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/alertes", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
