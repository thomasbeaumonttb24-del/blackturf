"""Une adresse inventée n'entre plus dans la base.

Constat du 04/09 en admin : « TEST TEST — testturf@yopmail.com », plan free,
adresse jamais confirmée. `EmailStr` n'y voyait rien à redire — c'est une chaîne
bien formée — et le compte était créé, connecté, comptabilisé.

Ces tests verrouillent les trois filtres posés AVANT l'écriture (boîte jetable,
faute de frappe sur un grand fournisseur, domaine qui ne relève pas de courrier)
et le fait qu'aucun d'eux ne bloque quoi que ce soit quand le DNS est muet.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from services import adresse_email
from services.adresse_email import AdresseRefusee, controler, est_jetable, normaliser


@pytest.fixture(autouse=True)
def _cache_neuf():
    """Le verdict DNS est mémorisé 6 h : sans purge, un test teindrait le suivant."""
    adresse_email.vider_cache()
    yield
    adresse_email.vider_cache()


@pytest.fixture
def dns(monkeypatch):
    """Rallume le contrôle DNS et le branche sur un résolveur en dur.

    Le vrai résolveur ferait dépendre la suite d'un réseau et de la zone MX du
    moment — un test rouge ne dirait alors plus rien du code.
    """
    monkeypatch.setenv("BT_CONTROLE_DNS", "1")

    def _repondre(verdicts: dict[str, bool | None]):
        async def _faux(domaine: str):
            return verdicts.get(domaine, True)
        monkeypatch.setattr(adresse_email, "_interroger_mx", _faux)

    return _repondre


# ── Normalisation ────────────────────────────────────────────────────────────
def test_l_adresse_est_normalisee():
    """« Jean@Gmail.com » et « jean@gmail.com » sont la même boîte : deux comptes
    pour une seule adresse, c'était deux essais gratuits."""
    assert normaliser("  Jean.Dupont@Gmail.COM  ") == "jean.dupont@gmail.com"


# ── Boîtes jetables ──────────────────────────────────────────────────────────
def test_yopmail_est_reconnu_jetable():
    assert est_jetable("yopmail.com") is True


def test_les_sous_domaines_d_un_jetable_le_sont_aussi():
    """Plusieurs services distribuent des adresses en « n'importe.quoi.domaine » :
    ne comparer que la chaîne entière laisserait passer toute la famille."""
    assert est_jetable("boite.yopmail.com") is True


def test_un_vrai_fournisseur_n_est_pas_jetable():
    for domaine in ("gmail.com", "orange.fr", "laposte.net", "blackturf.fr"):
        assert est_jetable(domaine) is False, domaine


async def test_l_adresse_jetable_est_refusee():
    with pytest.raises(AdresseRefusee) as refus:
        await controler("testturf@yopmail.com")
    assert refus.value.motif == "jetable"


async def test_la_liste_s_etend_par_variable_d_environnement(monkeypatch):
    """Un service jetable apparaît chaque mois : le blocage ne doit pas attendre
    un déploiement."""
    monkeypatch.setenv("BT_DOMAINES_JETABLES_EXTRA", "boitebidon.fr, autre.example")
    adresse_email.vider_cache()
    assert est_jetable("boitebidon.fr") is True
    assert est_jetable("autre.example") is True


# ── Fautes de frappe ─────────────────────────────────────────────────────────
async def test_la_faute_de_frappe_est_refusee_avec_la_correction():
    """« gmial.com » répond au DNS (domaine squatté) : le contrôle MX ne le
    rattraperait pas, et le lien de confirmation n'arriverait nulle part."""
    with pytest.raises(AdresseRefusee) as refus:
        await controler("jean@gmial.com")
    assert refus.value.motif == "faute_de_frappe"
    assert "gmail.com" in refus.value.message


async def test_un_domaine_reel_mal_choisi_n_est_pas_refuse(dns):
    """laposte.fr existe et relève le courrier interne de La Poste : on suggère
    laposte.net, on ne ferme pas la porte."""
    dns({})
    assert await controler("jean@laposte.fr") == "jean@laposte.fr"


# ── Le domaine relève-t-il du courrier ? ─────────────────────────────────────
async def test_un_domaine_sans_mx_est_refuse(dns):
    dns({"domaine-inexistant.fr": False})
    with pytest.raises(AdresseRefusee) as refus:
        await controler("jean@domaine-inexistant.fr")
    assert refus.value.motif == "domaine_injoignable"


async def test_un_domaine_qui_recoit_du_courrier_passe(dns):
    dns({"gmail.com": True})
    assert await controler("jean@gmail.com") == "jean@gmail.com"


async def test_une_panne_dns_ne_ferme_pas_l_inscription(dns):
    """Refuser tout le monde le temps d'une panne de résolveur coûterait plus que
    les quelques adresses douteuses que le filtre laisse alors passer — le mail de
    confirmation, lui, reste obligatoire."""
    dns({"gmail.com": None})
    assert await controler("jean@gmail.com") == "jean@gmail.com"


async def test_le_verdict_dns_est_mis_en_cache(dns, monkeypatch):
    """Une zone MX ne bouge pas d'une minute à l'autre : une requête DNS par
    tentative d'inscription offrirait une amplification à qui bourre le formulaire."""
    appels = []

    async def _compter(domaine: str):
        appels.append(domaine)
        return True

    monkeypatch.setenv("BT_CONTROLE_DNS", "1")
    monkeypatch.setattr(adresse_email, "_interroger_mx", _compter)

    await controler("un@gmail.com")
    await controler("deux@gmail.com")

    assert appels == ["gmail.com"]


async def test_un_verdict_incertain_n_est_pas_mis_en_cache(dns, monkeypatch):
    """Sinon une panne de résolveur se figerait en autorisation pour six heures."""
    verdicts = iter([None, False])

    async def _sequence(domaine: str):
        return next(verdicts)

    monkeypatch.setenv("BT_CONTROLE_DNS", "1")
    monkeypatch.setattr(adresse_email, "_interroger_mx", _sequence)

    assert await controler("jean@peut-etre.fr") == "jean@peut-etre.fr"
    with pytest.raises(AdresseRefusee):
        await controler("jean@peut-etre.fr")


# ── Bout en bout sur l'inscription ───────────────────────────────────────────
async def test_l_inscription_refuse_une_adresse_jetable(client: AsyncClient, db: AsyncSession):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "testturf@yopmail.com", "password": "MotDePasse123",
    })

    assert resp.status_code == 422
    assert "jetable" in resp.json()["detail"].lower()
    comptes = (await db.execute(select(User))).scalars().all()
    assert comptes == [], "aucune ligne ne doit être créée pour une adresse refusée"


async def test_l_inscription_refuse_une_faute_de_frappe(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "jean@gmial.com", "password": "MotDePasse123",
    })
    assert resp.status_code == 422
    assert "gmail.com" in resp.json()["detail"]


async def test_l_inscription_enregistre_l_adresse_normalisee(
    client: AsyncClient, db: AsyncSession
):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "  Jean.Dupont@BlackTurf.FR ", "password": "MotDePasse123",
    })

    assert resp.status_code == 200
    user = (await db.execute(select(User))).scalar_one()
    assert user.email == "jean.dupont@blackturf.fr"


async def test_la_connexion_ignore_la_casse(client: AsyncClient, confirmer_adresse):
    """Une majuscule à la saisie renvoyait « identifiants incorrects » sur un
    compte pourtant existant."""
    await client.post("/api/v1/auth/register", json={
        "email": "casse@blackturf.fr", "password": "MotDePasse123",
    })
    await confirmer_adresse("casse@blackturf.fr")

    resp = await client.post("/api/v1/auth/login", data={
        "username": "Casse@BlackTurf.fr", "password": "MotDePasse123",
    })
    assert resp.status_code == 200


async def test_une_inscription_jamais_confirmee_ne_reserve_pas_l_adresse(
    client: AsyncClient, db: AsyncSession, confirmer_adresse
):
    """Sans cela, il suffisait de saisir l'adresse d'un tiers pour l'empêcher à vie
    de s'inscrire — celui qui l'a saisie n'a jamais montré qu'il relevait la boîte."""
    await client.post("/api/v1/auth/register", json={
        "email": "squatte@blackturf.fr", "password": "MotDePasse123",
    })

    resp = await client.post("/api/v1/auth/register", json={
        "email": "squatte@blackturf.fr", "password": "AutreMotDePasse456", "prenom": "Vrai",
    })
    assert resp.status_code == 200

    # Le nouveau mot de passe est celui qui vaut, une fois l'adresse confirmée.
    await confirmer_adresse("squatte@blackturf.fr")
    connexion = await client.post("/api/v1/auth/login", data={
        "username": "squatte@blackturf.fr", "password": "AutreMotDePasse456",
    })
    assert connexion.status_code == 200
    assert len((await db.execute(select(User))).scalars().all()) == 1


async def test_un_compte_confirme_reste_intouchable(
    client: AsyncClient, confirmer_adresse
):
    """La reprise ne vaut QUE pour une inscription en attente : réécrire le mot de
    passe d'un compte confirmé serait un vol de compte à la demande."""
    await client.post("/api/v1/auth/register", json={
        "email": "confirme@blackturf.fr", "password": "MotDePasse123",
    })
    await confirmer_adresse("confirme@blackturf.fr")

    resp = await client.post("/api/v1/auth/register", json={
        "email": "confirme@blackturf.fr", "password": "MotDePasseIntrus999",
    })
    assert resp.status_code == 400

    connexion = await client.post("/api/v1/auth/login", data={
        "username": "confirme@blackturf.fr", "password": "MotDePasse123",
    })
    assert connexion.status_code == 200
