"""La session vit dans des cookies httpOnly, plus dans localStorage.

Un jeton rangé dans localStorage est lisible par n'importe quel script de la page :
une seule XSS suffisait à emporter un refresh token valable 7 jours. Ces tests
verrouillent le nouveau contrat côté API.
"""
import pytest
from httpx import AsyncClient


MDP = "MotDePasse123"


async def _inscrire(client: AsyncClient, email: str = "cookie@blackturf.fr"):
    return await client.post("/api/v1/auth/register", json={
        "email": email, "password": MDP, "nom": "T", "prenom": "U",
    })


async def _ouvrir_session(client: AsyncClient, confirmer_adresse,
                          email: str = "cookie@blackturf.fr"):
    """Parcours complet — inscription, confirmation, connexion.

    Ce sont désormais DEUX étapes distinctes : l'inscription n'ouvre plus de
    session, c'est la connexion qui pose les cookies, et elle n'est accordée
    qu'une fois l'adresse confirmée.
    """
    assert (await _inscrire(client, email)).status_code == 200
    await confirmer_adresse(email)
    login = await client.post("/api/v1/auth/login",
                              data={"username": email, "password": MDP})
    assert login.status_code == 200, login.text
    return login


def _cookies_poses(resp) -> dict[str, str]:
    """Entêtes Set-Cookie de la réponse, indexés par nom de cookie."""
    out = {}
    for brut in resp.headers.get_list("set-cookie"):
        nom = brut.split("=", 1)[0].strip()
        out[nom] = brut
    return out


async def test_l_inscription_ne_pose_aucun_cookie_de_session(client: AsyncClient):
    """Elle envoie un lien, elle ne connecte pas : une adresse inventée n'ouvre
    donc plus rien du tout."""
    resp = await _inscrire(client, "inscription-sans-session@blackturf.fr")
    assert resp.status_code == 200
    poses = _cookies_poses(resp)
    assert not ({"access_token", "refresh_token"} & set(poses))
    assert "access_token" not in client.cookies


async def test_login_pose_des_cookies_httponly(client: AsyncClient, confirmer_adresse):
    resp = await _ouvrir_session(client, confirmer_adresse, "login-cookie@blackturf.fr")

    poses = _cookies_poses(resp)
    assert "access_token" in poses and "refresh_token" in poses
    for nom in ("access_token", "refresh_token"):
        assert "httponly" in poses[nom].lower(), (
            f"{nom} doit être httpOnly, sinon une XSS le lit comme avant")
        assert "samesite=lax" in poses[nom].lower(), (
            f"{nom} sans SameSite serait envoyé sur une requête d'un autre site (CSRF)")
    # Le cookie de rafraîchissement ne sert que sur les routes d'authentification.
    assert "path=/api/v1/auth" in poses["refresh_token"].lower()


async def test_le_temoin_de_session_est_lisible_et_ne_contient_aucun_secret(
    client: AsyncClient, confirmer_adresse
):
    """Sans témoin, le front ne peut pas savoir qu'une session existe (cookies
    httpOnly) et interrogerait /auth/me pour chaque visiteur anonyme."""
    resp = await _ouvrir_session(client, confirmer_adresse, "temoin@blackturf.fr")
    poses = _cookies_poses(resp)
    assert "bt_session" in poses
    temoin = poses["bt_session"]
    assert "httponly" not in temoin.lower(), "le témoin doit rester lisible en JS"
    assert temoin.split(";")[0].split("=", 1)[1] == "1", "le témoin ne porte aucune valeur secrète"


async def test_le_cookie_seul_authentifie(client: AsyncClient, confirmer_adresse):
    """Aucun en-tête Authorization : la requête ne doit tenir que par le cookie."""
    await _ouvrir_session(client, confirmer_adresse, "cookie-seul@blackturf.fr")
    assert "access_token" in client.cookies

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "cookie-seul@blackturf.fr"


async def test_l_entete_authorization_reste_accepte(client: AsyncClient, confirmer_adresse):
    """Clients non navigateur et onglets pas encore rechargés : l'en-tête vit encore."""
    resp = await _ouvrir_session(client, confirmer_adresse, "entete@blackturf.fr")
    token = resp.json()["access_token"]
    client.cookies.clear()

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


async def test_sans_cookie_ni_entete_c_est_401(client: AsyncClient):
    await _inscrire(client, "anonyme@blackturf.fr")
    client.cookies.clear()
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_refresh_sans_corps_utilise_le_cookie(client: AsyncClient, confirmer_adresse):
    """Le front ne peut plus lire le refresh token : il ne peut donc plus l'envoyer."""
    await _ouvrir_session(client, confirmer_adresse, "refresh-cookie@blackturf.fr")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in _cookies_poses(resp)


async def test_refresh_accepte_encore_le_corps_pour_la_bascule(client: AsyncClient, confirmer_adresse):
    """Une session ouverte AVANT les cookies échange son ancien jeton contre des
    cookies — sinon tous ces comptes seraient déconnectés au déploiement."""
    resp = await _ouvrir_session(client, confirmer_adresse, "bascule@blackturf.fr")
    ancien = resp.json()["refresh_token"]
    client.cookies.clear()

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": ancien})
    assert resp.status_code == 200
    assert "access_token" in _cookies_poses(resp)


async def test_refresh_sans_rien_est_refuse(client: AsyncClient):
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_efface_les_cookies(client: AsyncClient, confirmer_adresse):
    """Un cookie httpOnly ne peut être effacé que par le serveur."""
    await _ouvrir_session(client, confirmer_adresse, "logout@blackturf.fr")
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200

    poses = _cookies_poses(resp)
    for nom in ("access_token", "refresh_token", "bt_session"):
        assert nom in poses, f"{nom} doit être explicitement expiré"

    assert (await client.get("/api/v1/auth/me")).status_code == 401
