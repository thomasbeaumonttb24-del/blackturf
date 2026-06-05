"""Tests endpoints de base."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


async def test_public_stats(client: AsyncClient):
    resp = await client.get("/api/v1/stats/public")
    assert resp.status_code == 200
    data = resp.json()
    assert "auc_roc" in data
    assert "roi_simule_6mois" in data


async def test_model_version_public(client: AsyncClient):
    resp = await client.get("/api/v1/model/version")
    assert resp.status_code == 200


async def test_docs_not_in_production(client: AsyncClient):
    """Les docs Swagger sont visibles en dev."""
    resp = await client.get("/api/docs")
    # En test l'env est "development" donc docs disponibles
    assert resp.status_code == 200
