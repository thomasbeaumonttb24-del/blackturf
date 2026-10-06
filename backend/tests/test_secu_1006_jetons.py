"""
Correctifs sécurité du 06/10 (suite) : révocation des jetons à la déconnexion,
rotation du refresh, jetons absents du corps pour un navigateur, inscription
(noms, alias, chronométrage), export CSV, pagination bornée.
"""
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

MDP = "MotDePasse123"


@pytest.fixture
def vrai_redis(monkeypatch):
    """Moteur Redis en mémoire : la révocation est écrite puis relue pour de bon."""
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr("db.redis_client.get_redis", AsyncMock(return_value=r))
    return r


async def _session(client: AsyncClient, confirmer_adresse, email: str, inscrire=True):
    if inscrire:
        assert (await client.post("/api/v1/auth/register", json={
            "email": email, "password": MDP, "pseudo": email.split("@")[0][:20],
        })).status_code == 200
        await confirmer_adresse(email)
    login = await client.post("/api/v1/auth/login", data={"username": email, "password": MDP})
    assert login.status_code == 200, login.text
    return login.json()


async def test_la_deconnexion_revoque_les_jetons_presentes(client, confirmer_adresse, vrai_redis):
    jetons = await _session(client, confirmer_adresse, "deco@blackturf.fr")
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    client.cookies.clear()

    # Copiés avant la déconnexion, ils ne valent plus rien.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['access_token']}"})
    assert me.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": jetons["refresh_token"]})
    assert r.status_code == 401


async def test_la_deconnexion_ne_coupe_pas_les_autres_appareils(client, confirmer_adresse, vrai_redis):
    autre = await _session(client, confirmer_adresse, "deux@blackturf.fr")
    await _session(client, confirmer_adresse, "deux@blackturf.fr", inscrire=False)
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    client.cookies.clear()

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {autre['access_token']}"})
    assert me.status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": autre["refresh_token"]})
    assert r.status_code == 200


async def test_un_refresh_consomme_meurt_apres_le_delai_de_grace(
    client, confirmer_adresse, vrai_redis, monkeypatch
):
    jetons = await _session(client, confirmer_adresse, "rotation@blackturf.fr")
    client.cookies.clear()
    ancien = jetons["refresh_token"]

    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": ancien})).status_code == 200
    # Deux onglets au même instant : le second passe encore.
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": ancien})).status_code == 200

    import api.routes.auth as auth
    monkeypatch.setattr(auth, "GRACE_ROTATION_S", -1)
    client.cookies.clear()
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": ancien})
    assert r.status_code == 401, "un refresh rejoué après rotation doit être refusé"


async def test_un_ancien_refresh_sans_jti_reste_valable(client, confirmer_adresse, vrai_redis):
    """Sessions ouvertes avant le déploiement : pas de `jti`, pas de déconnexion forcée."""
    from api.config import get_settings
    from api.routes.auth import _create_token
    jetons = await _session(client, confirmer_adresse, "ancien@blackturf.fr")
    from jose import jwt
    s = get_settings()
    sub = jwt.decode(jetons["access_token"], s.secret_key, algorithms=[s.jwt_algorithm])["sub"]
    ancien = _create_token({"sub": sub, "type": "refresh"}, timedelta(days=1))
    client.cookies.clear()

    for _ in range(2):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": ancien})
        assert r.status_code == 200


async def test_un_navigateur_ne_recoit_pas_les_jetons_dans_le_corps(client, confirmer_adresse):
    await _session(client, confirmer_adresse, "navigateur@blackturf.fr")
    origine = {"Origin": "http://localhost:3000"}
    login = await client.post("/api/v1/auth/login", headers=origine,
                              data={"username": "navigateur@blackturf.fr", "password": MDP})
    assert login.status_code == 200
    assert "access_token" not in login.json() and "refresh_token" not in login.json()
    assert "access_token" in login.cookies or "access_token" in client.cookies

    r = await client.post("/api/v1/auth/refresh", headers=origine)
    assert r.status_code == 200
    assert "access_token" not in r.json() and "refresh_token" not in r.json()


# ── Inscription : noms, alias, chronométrage ────────────────────────────────
async def test_nom_et_prenom_hors_regle_refuses(client, auth_headers):
    r = await client.post("/api/v1/auth/register", json={
        "email": "nom-libre@blackturf.fr", "password": MDP, "pseudo": "NomLibre",
        "prenom": "Gagnez 500€ sur http://arnaque.fr"})
    assert r.status_code == 422
    r = await client.patch("/api/v1/auth/me", json={"prenom": "<b>x</b>"}, headers=auth_headers)
    assert r.status_code == 422
    r = await client.patch("/api/v1/auth/me", json={"prenom": "Jean-Éric", "nom": "D'Artagnan"},
                           headers=auth_headers)
    assert r.status_code == 200
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert (me["prenom"], me["nom"]) == ("Jean-Éric", "D'Artagnan")


async def test_un_alias_recent_non_confirme_ne_cree_pas_un_compte_de_plus(client, db):
    from sqlalchemy import func, select
    from db.models import User
    for i, alias in enumerate(("bombe@gmail.com", "bombe+1@gmail.com", "b.o.m.b.e@gmail.com")):
        r = await client.post("/api/v1/auth/register", json={
            "email": alias, "password": MDP, "pseudo": f"Bombe{i}"})
        assert r.status_code == 200, r.text
    assert (await db.execute(select(func.count()).select_from(User))).scalar() == 1


async def test_login_sans_compte_passe_quand_meme_par_bcrypt(client, monkeypatch):
    import api.routes.auth as auth
    appels = []
    vrai = auth._verify
    monkeypatch.setattr(auth, "_verify", lambda p, h: appels.append(h) or vrai(p, h))
    r = await client.post("/api/v1/auth/login", data={"username": "personne@blackturf.fr", "password": MDP})
    assert r.status_code == 401
    assert appels == [auth._HASH_FACTICE]


# ── Export CSV admin : injection de formule ─────────────────────────────────
def test_cellule_csv_neutralise_les_formules():
    from api.routes.admin import cellule_csv
    for piege in ("=HYPERLINK(\"http://x\")", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "\tx", "\rx"):
        assert cellule_csv(piege) == "'" + piege
    assert cellule_csv("Jean") == "Jean"
    assert cellule_csv(-12.5) == -12.5 and cellule_csv(None) is None


# ── Pagination bornée ───────────────────────────────────────────────────────
async def test_pagination_hors_bornes_refusee_proprement(client, auth_headers):
    for url in ("/api/v1/notifications?page=-1", "/api/v1/notifications?page=1000000000000",
                "/api/v1/recherche?q=ab&limit=-5", "/api/v1/strategies/communaute?limit=-5"):
        r = await client.get(url, headers=auth_headers)
        assert r.status_code == 422, (url, r.status_code)
