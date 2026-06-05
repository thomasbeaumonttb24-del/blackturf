"""Tests bankroll routes."""
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

ENTRY_PAYLOAD = {
    "date": datetime.now(timezone.utc).isoformat(),
    "type_pari": "Simple Gagnant",
    "chevaux": "3",
    "mise": 10.0,
    "cote": 4.5,
    "suivi_reco_ia": True,
}


async def test_create_entry(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["mise"] == 10.0
    assert data["type_pari"] == "Simple Gagnant"
    return data["entry_id"]


async def test_list_entries_empty(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/bankroll/entries", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_entries_after_create(client: AsyncClient, auth_headers):
    await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    resp = await client.get("/api/v1/bankroll/entries", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_update_entry(client: AsyncClient, auth_headers):
    create = await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    entry_id = create.json()["entry_id"]

    resp = await client.patch(
        f"/api/v1/bankroll/entries/{entry_id}",
        json={"resultat": "gagne", "gain_perte": 35.0},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["resultat"] == "gagne"
    assert resp.json()["gain_perte"] == 35.0


async def test_delete_entry(client: AsyncClient, auth_headers):
    create = await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    entry_id = create.json()["entry_id"]

    resp = await client.delete(f"/api/v1/bankroll/entries/{entry_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Vérifier suppression
    list_resp = await client.get("/api/v1/bankroll/entries", headers=auth_headers)
    ids = [e["entry_id"] for e in list_resp.json()]
    assert entry_id not in ids


async def test_delete_other_user_entry_fails(client: AsyncClient, auth_headers, admin_headers):
    """Un utilisateur ne peut pas supprimer l'entrée d'un autre."""
    create = await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    entry_id = create.json()["entry_id"]

    resp = await client.delete(f"/api/v1/bankroll/entries/{entry_id}", headers=admin_headers)
    assert resp.status_code == 404


async def test_get_stats(client: AsyncClient, auth_headers):
    # Créer une entrée gagnante
    create = await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    entry_id = create.json()["entry_id"]
    await client.patch(
        f"/api/v1/bankroll/entries/{entry_id}",
        json={"resultat": "gagne", "gain_perte": 35.0},
        headers=auth_headers,
    )

    resp = await client.get("/api/v1/bankroll/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "roi_global" in data
    assert "nb_paris" in data
    assert data["nb_paris"] >= 1


async def test_stats_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/bankroll/stats")
    assert resp.status_code == 401


async def test_export_csv(client: AsyncClient, auth_headers):
    await client.post("/api/v1/bankroll/entries", json=ENTRY_PAYLOAD, headers=auth_headers)
    resp = await client.get("/api/v1/bankroll/export", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "Simple Gagnant" in resp.text
