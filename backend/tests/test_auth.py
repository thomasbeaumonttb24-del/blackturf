"""Tests auth routes."""
import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "new@blackturf.fr",
        "password": "TestPass12!",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["plan"] == "free"


async def test_register_duplicate_email(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@blackturf.fr",
        "password": "TestPass12!",
    })
    assert resp.status_code == 400


async def test_login_success(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/auth/login", data={
        "username": "test@blackturf.fr",
        "password": "TestPassword123!",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/auth/login", data={
        "username": "test@blackturf.fr",
        "password": "WrongPass",
    })
    assert resp.status_code == 401


async def test_me(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@blackturf.fr"
    assert data["plan"] == "free"


async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_refresh_token(client: AsyncClient, auth_headers):
    login = await client.post("/api/v1/auth/login", data={
        "username": "test@blackturf.fr",
        "password": "TestPassword123!",
    })
    refresh_token = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_refresh_with_access_token_fails(client: AsyncClient, auth_headers):
    """Access token ne peut pas servir de refresh token."""
    login = await client.post("/api/v1/auth/login", data={
        "username": "test@blackturf.fr",
        "password": "TestPassword123!",
    })
    access_token = login.json()["access_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


async def test_update_me(client: AsyncClient, auth_headers):
    resp = await client.patch("/api/v1/auth/me", json={"profil_risque": "agressif"}, headers=auth_headers)
    assert resp.status_code == 200

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.json()["profil_risque"] == "agressif"


async def test_forgot_password_anti_enumeration(client: AsyncClient):
    """Always returns ok=True regardless of email existence (anti-enumeration)."""
    for email in ["nonexistent@blackturf.fr", "also@unknown.com"]:
        resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


async def test_forgot_password_existing_email_still_ok(client: AsyncClient, auth_headers):
    """Real registered email also returns ok=True without leaking info."""
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "test@blackturf.fr"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_reset_password_invalid_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/reset-password", json={
        "token": "invalid-token-xyz",
        "new_password": "NewPass123!",
    })
    assert resp.status_code == 400


async def test_resend_verification_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/auth/resend-verification")
    assert resp.status_code == 401


async def test_resend_verification_authenticated(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/auth/resend-verification", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_verify_email_invalid_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/verify-email?token=bad-token-xyz")
    assert resp.status_code == 400


async def test_register_new_user_plan_is_free(client: AsyncClient):
    """Nouveaux inscrits → plan free par défaut."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser2@blackturf.fr",
        "password": "TestPass12!",
        "prenom": "Jean",
        "nom": "Dupont",
    })
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"


async def test_profil_risque_defaut_equilibre(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser3@blackturf.fr",
        "password": "TestPass12!",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["profil_risque"] in ("equilibre", None, "")  # Default


async def test_update_me_bankroll(client: AsyncClient, auth_headers):
    resp = await client.patch("/api/v1/auth/me", json={"bankroll_initiale": 500.0}, headers=auth_headers)
    assert resp.status_code == 200
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.json()["bankroll_initiale"] == 500.0
