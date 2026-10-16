"""Provenance de l'inscription : cookie bt_src → users.provenance → /admin/api/provenance."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from db.models import User

pytestmark = pytest.mark.asyncio


async def _inscrire(client: AsyncClient, email: str, pseudo: str, cookie: str | None):
    if cookie is None:
        client.cookies.delete("bt_src")
    else:
        client.cookies.set("bt_src", cookie)
    r = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "TestPass12!", "pseudo": pseudo,
    })
    assert r.status_code == 200, r.text


async def _provenance(db, email: str):
    return (await db.execute(select(User.provenance).where(User.email == email))).scalar_one()


async def test_cookie_range_la_provenance(client: AsyncClient, db):
    await _inscrire(client, "pub@blackturf.fr", "Pub1", "facebook:pub_v6")
    assert await _provenance(db, "pub@blackturf.fr") == "facebook:pub_v6"


async def test_cookie_absent_ou_invalide(client: AsyncClient, db):
    await _inscrire(client, "direct@blackturf.fr", "Direct1", None)
    assert await _provenance(db, "direct@blackturf.fr") is None
    await _inscrire(client, "sale@blackturf.fr", "Sale1", "<script>")
    assert await _provenance(db, "sale@blackturf.fr") is None


async def test_admin_agrege_par_provenance(client: AsyncClient, db, admin_headers):
    await _inscrire(client, "a1@blackturf.fr", "Aa1", "instagram:pub_v6")
    await _inscrire(client, "a2@blackturf.fr", "Aa2", "instagram:pub_v6")
    r = await client.get("/admin/api/provenance", headers=admin_headers)
    assert r.status_code == 200, r.text
    lignes = {l["provenance"]: l for l in r.json()["lignes"]}
    assert lignes["instagram:pub_v6"]["inscrits"] == 2
    assert lignes["instagram:pub_v6"]["payants"] == 0
