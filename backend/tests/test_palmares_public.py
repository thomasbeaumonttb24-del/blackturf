"""
Régression : la section « Palmarès en direct » de la page d'accueil appelait
`/stats/palmares-gagnants`, gardé par `require_admin` → **401 pour tout visiteur**.
La principale preuve sociale du site n'était donc visible que par le compte admin ;
tous les prospects voyaient l'état vide.

`/stats/palmares-public` sert le même palmarès sans authentification, MAIS sans les
agrégats ROI/gains par profil, qui restent réservés à l'admin (règle produit déjà
appliquée à `/stats/public` : « ROI VOLONTAIREMENT ABSENT du public »).
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_palmares_public_accessible_sans_authentification(client: AsyncClient):
    resp = await client.get("/api/v1/stats/palmares-public")
    assert resp.status_code == 200, resp.text


async def test_palmares_public_ne_divulgue_ni_roi_ni_agregats_par_profil(client: AsyncClient):
    """Le ROI et les gains par profil sont réservés à l'admin — la version publique
    ne doit exposer que la liste des gagnants et ses dénominateurs."""
    data = (await client.get("/api/v1/stats/palmares-public")).json()

    assert "profils" not in data
    assert "roi" not in data
    assert "total_gain" not in data
    assert "total_benefice" not in data


async def test_palmares_public_expose_le_denominateur(client: AsyncClient):
    """Afficher les paris GAGNANTS sans dire sur combien de courses ils ont été joués
    serait un biais du survivant : le nombre de courses réglées doit accompagner la
    liste pour que le front puisse présenter les deux ensemble."""
    data = (await client.get("/api/v1/stats/palmares-public")).json()

    assert "nb_courses_reglees" in data
    assert "nb_paris_gagnes" in data
    assert isinstance(data["nb_courses_reglees"], int)
    assert isinstance(data["nb_paris_gagnes"], int)


async def test_palmares_admin_conserve_le_roi_par_profil(client: AsyncClient, admin_headers):
    """L'endpoint admin garde bien, lui, les agrégats ROI (non régressé par la
    factorisation dans `_palmares_rows`)."""
    resp = await client.get("/api/v1/stats/palmares-gagnants", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert "profils" in resp.json()


async def test_palmares_gagnants_reste_interdit_sans_auth(client: AsyncClient):
    """Le paywall d'origine sur la version admin ne doit PAS avoir sauté."""
    resp = await client.get("/api/v1/stats/palmares-gagnants")
    assert resp.status_code in (401, 403)

