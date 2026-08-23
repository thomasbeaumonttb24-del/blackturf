"""Lettre d'information — inscription en double opt-in.

Les invariants testés ici ne sont pas cosmétiques :

- une réponse qui varierait selon l'existence de l'adresse ferait du formulaire un
  oracle : n'importe qui pourrait tester une liste et savoir qui est client ;
- une adresse non confirmée qui recevrait la lettre, c'est du spam et une perte de
  réputation d'expédition ;
- un jeton de confirmation réutilisable permettrait de réactiver une adresse
  désinscrite avec un vieux lien.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from db.models import NewsletterAbonne

pytestmark = pytest.mark.asyncio


async def _abonne(db, email: str) -> NewsletterAbonne | None:
    res = await db.execute(select(NewsletterAbonne).where(NewsletterAbonne.email == email))
    return res.scalar_one_or_none()


async def test_inscription_cree_une_ligne_en_attente(client: AsyncClient, db):
    resp = await client.post(
        "/api/v1/newsletter/inscription",
        json={"email": "Jean.Dupont@Exemple.fr", "source": "accueil"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # L'adresse est normalisée en minuscules, sans quoi « Jean@x.fr » et « jean@x.fr »
    # créeraient deux lignes et donc deux envois.
    a = await _abonne(db, "jean.dupont@exemple.fr")
    assert a is not None
    assert a.statut == "en_attente"
    assert a.token_confirmation
    assert a.token_desinscription
    assert a.source == "accueil"
    # La formulation exacte du consentement est conservée : sans elle, on ne peut pas
    # dire À QUOI la personne a consenti.
    assert a.consentement_texte


async def test_reponse_identique_que_l_adresse_existe_ou_non(client: AsyncClient):
    """Aucune énumération : le formulaire ne dit jamais si une adresse est connue."""
    inconnue = await client.post(
        "/api/v1/newsletter/inscription", json={"email": "inconnue@exemple.fr"}
    )
    await client.post("/api/v1/newsletter/inscription", json={"email": "connue@exemple.fr"})
    connue = await client.post(
        "/api/v1/newsletter/inscription", json={"email": "connue@exemple.fr"}
    )

    assert inconnue.status_code == connue.status_code == 200
    assert inconnue.json() == connue.json()


async def test_seconde_inscription_ne_duplique_pas_la_ligne(client: AsyncClient, db):
    for _ in range(3):
        await client.post("/api/v1/newsletter/inscription", json={"email": "double@exemple.fr"})

    res = await db.execute(
        select(NewsletterAbonne).where(NewsletterAbonne.email == "double@exemple.fr")
    )
    assert len(res.scalars().all()) == 1


async def test_confirmation_active_l_abonne_et_consomme_le_jeton(client: AsyncClient, db):
    await client.post("/api/v1/newsletter/inscription", json={"email": "confirme@exemple.fr"})
    a = await _abonne(db, "confirme@exemple.fr")
    jeton = a.token_confirmation

    resp = await client.get("/api/v1/newsletter/confirmer", params={"jeton": jeton})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    await db.refresh(a)
    assert a.statut == "confirme"
    assert a.confirme_at is not None
    assert a.token_confirmation is None  # usage unique

    # Rejouer le même lien ne doit PAS reconfirmer : le jeton est consommé.
    rejeu = await client.get("/api/v1/newsletter/confirmer", params={"jeton": jeton})
    assert rejeu.json()["ok"] is False


async def test_jeton_de_confirmation_inconnu_est_refuse(client: AsyncClient):
    resp = await client.get(
        "/api/v1/newsletter/confirmer", params={"jeton": "x" * 40}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


async def test_desinscription_conserve_la_ligne(client: AsyncClient, db):
    """Supprimer la ligne permettrait à un tiers de réinscrire l'adresse."""
    await client.post("/api/v1/newsletter/inscription", json={"email": "partant@exemple.fr"})
    a = await _abonne(db, "partant@exemple.fr")
    await client.get("/api/v1/newsletter/confirmer", params={"jeton": a.token_confirmation})

    resp = await client.get(
        "/api/v1/newsletter/desinscription", params={"jeton": a.token_desinscription}
    )
    assert resp.json()["ok"] is True

    await db.refresh(a)
    assert a.statut == "desinscrit"
    assert a.desinscrit_at is not None


async def test_desinscription_rejouee_reste_un_succes(client: AsyncClient, db):
    """Un vieux lien de désinscription doit rassurer, jamais afficher « lien invalide »."""
    await client.post("/api/v1/newsletter/inscription", json={"email": "rejeu@exemple.fr"})
    a = await _abonne(db, "rejeu@exemple.fr")

    premier = await client.get(
        "/api/v1/newsletter/desinscription", params={"jeton": a.token_desinscription}
    )
    second = await client.get(
        "/api/v1/newsletter/desinscription", params={"jeton": a.token_desinscription}
    )
    assert premier.json()["ok"] is True
    assert second.json()["ok"] is True


async def test_reinscription_apres_desinscription_repasse_par_la_confirmation(
    client: AsyncClient, db
):
    """Une adresse désinscrite ne redevient jamais active sans un nouveau clic."""
    await client.post("/api/v1/newsletter/inscription", json={"email": "retour@exemple.fr"})
    a = await _abonne(db, "retour@exemple.fr")
    await client.get("/api/v1/newsletter/confirmer", params={"jeton": a.token_confirmation})
    await client.get(
        "/api/v1/newsletter/desinscription", params={"jeton": a.token_desinscription}
    )

    await client.post("/api/v1/newsletter/inscription", json={"email": "retour@exemple.fr"})
    await db.refresh(a)
    assert a.statut == "en_attente"
    assert a.token_confirmation is not None


async def test_adresse_invalide_rejetee(client: AsyncClient):
    resp = await client.post("/api/v1/newsletter/inscription", json={"email": "pas-une-adresse"})
    assert resp.status_code == 422
