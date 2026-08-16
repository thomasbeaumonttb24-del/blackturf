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
    assert "nb_courses_analysees" in data
    assert "nb_utilisateurs" in data
    assert "precision_top3" in data
    # ROI volontairement absent des stats publiques (api/routes/stats.py:144-146) :
    # exigence produit, le ROI n'est visible que par l'admin (equity-curve,
    # palmares-gagnants, gardes require_admin) pour ne jamais servir un chiffre
    # gonflé/marketing en public. `roi_simule_6mois` a existé puis a été retiré
    # DÉLIBÉRÉMENT — ce test vérifiait l'ancien comportement, pas une régression.
    assert "roi_simule_6mois" not in data


async def test_model_version_public(client: AsyncClient):
    resp = await client.get("/api/v1/model/version")
    assert resp.status_code == 200


async def test_docs_not_in_production(client: AsyncClient):
    """Les docs Swagger sont visibles en dev."""
    resp = await client.get("/api/docs")
    # En test l'env est "development" donc docs disponibles
    assert resp.status_code == 200
