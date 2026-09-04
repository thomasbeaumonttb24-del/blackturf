"""Aucune session sans adresse confirmée.

Le mail de confirmation partait déjà à l'inscription, mais rien ne l'exigeait :
une adresse inexistante — ou jetable — donnait un compte complet, donc un essai
Stripe de plus et des rebonds qui abîment la délivrabilité de tous les envois.
Le compte ne s'ouvre désormais qu'au clic sur le lien reçu.

Ces tests fixent les trois pièces : le mur à la connexion, la dispense accordée
aux comptes antérieurs à la règle, et la deuxième ligne de défense sur ce qui
coûte de l'argent — les sessions ouvertes avant la mise en service vivent encore
jusqu'à 7 jours.
"""
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import _hash
from db.models import User
from services.email_verification import (
    VERIFICATION_OBLIGATOIRE_DEPUIS,
    clause_email_utilisable,
    email_confirme,
)


def _user(**kw) -> User:
    defauts = dict(
        user_id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@blackturf.fr",
        hashed_password=_hash("MotDePasse123"),
        plan="free",
        is_active=True,
        email_verified=False,
        created_at=VERIFICATION_OBLIGATOIRE_DEPUIS + timedelta(days=1),
    )
    defauts.update(kw)
    return User(**defauts)


# ── La règle elle-même ───────────────────────────────────────────────────────
def test_adresse_confirmee_passe():
    assert email_confirme(_user(email_verified=True)) is True


def test_adresse_non_confirmee_est_refusee():
    assert email_confirme(_user()) is False


def test_les_comptes_anterieurs_sont_dispenses():
    """Ils se sont inscrits sous une règle qui ne l'exigeait pas — dont un abonné
    payant. Leur fermer la porte a posteriori serait une régression, pas une
    sécurité."""
    ancien = _user(created_at=VERIFICATION_OBLIGATOIRE_DEPUIS - timedelta(seconds=1))
    assert email_confirme(ancien) is True


def test_date_de_creation_inconnue_ne_penalise_pas():
    assert email_confirme(_user(created_at=None)) is True


# ── Les envois n'atteignent plus les adresses douteuses ──────────────────────
async def test_le_filtre_sql_ecarte_les_adresses_non_confirmees(db: AsyncSession):
    nouveau_non_confirme = _user(email="neuf@blackturf.fr")
    nouveau_confirme = _user(email="neuf-ok@blackturf.fr", email_verified=True)
    ancien = _user(email="ancien@blackturf.fr",
                   created_at=VERIFICATION_OBLIGATOIRE_DEPUIS - timedelta(days=30))
    db.add_all([nouveau_non_confirme, nouveau_confirme, ancien])
    await db.commit()

    destinataires = (await db.execute(
        select(User.email).where(clause_email_utilisable())
    )).scalars().all()

    assert "neuf@blackturf.fr" not in destinataires
    assert {"neuf-ok@blackturf.fr", "ancien@blackturf.fr"} <= set(destinataires)


# ── Bout en bout sur l'API ───────────────────────────────────────────────────
async def _inscrire(client: AsyncClient, email: str) -> None:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "MotDePasse123",
    })
    assert resp.status_code == 200, resp.text


async def _connexion(client: AsyncClient, email: str):
    return await client.post("/api/v1/auth/login",
                             data={"username": email, "password": "MotDePasse123"})


def _entetes(user: User) -> dict[str, str]:
    """Session ouverte pour un compte donné, sans passer par /login.

    Sert à rejouer le seul cas où une adresse non confirmée dispose encore d'un
    jeton : celles ouvertes AVANT la mise en service de la règle, valables
    jusqu'à expiration.
    """
    from api.routes.auth import create_tokens
    return {"Authorization": f"Bearer {create_tokens(user.user_id, user.plan).access_token}"}


async def test_la_connexion_est_refusee_tant_que_l_adresse_n_est_pas_confirmee(
    client: AsyncClient
):
    """Le mur est à l'entrée : sans cela, une adresse inventée donnait un compte
    pleinement utilisable et la confirmation n'était jamais réclamée."""
    await _inscrire(client, "pas-confirme@blackturf.fr")

    resp = await _connexion(client, "pas-confirme@blackturf.fr")

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "email_non_confirme"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_la_connexion_passe_une_fois_l_adresse_confirmee(
    client: AsyncClient, db: AsyncSession, confirmer_adresse
):
    await _inscrire(client, "confirme@blackturf.fr")
    await confirmer_adresse("confirme@blackturf.fr")

    resp = await _connexion(client, "confirme@blackturf.fr")

    assert resp.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_le_lien_de_confirmation_ouvre_directement_la_session(
    client: AsyncClient, db: AsyncSession
):
    """Le clic dans la boîte prouve déjà la possession de l'adresse : redemander
    le mot de passe juste après ne protégerait rien et perdrait l'inscrit."""
    await _inscrire(client, "lien-connecte@blackturf.fr")
    user = (await db.execute(
        select(User).where(User.email == "lien-connecte@blackturf.fr")
    )).scalar_one()

    # Le jeton vit dans Redis (mocké) : on rejoue ce que la route y lit.
    from unittest.mock import AsyncMock, patch
    faux_redis = AsyncMock()
    faux_redis.get = AsyncMock(return_value=user.user_id.encode())
    faux_redis.delete = AsyncMock(return_value=1)
    with patch("redis.asyncio.from_url", return_value=faux_redis):
        resp = await client.get("/api/v1/auth/verify-email?token=peu-importe")

    assert resp.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    await db.refresh(user)
    assert user.email_verified is True


async def test_un_mot_de_passe_reinitialise_vaut_preuve_de_l_adresse(
    client: AsyncClient, db: AsyncSession
):
    """Le jeton de réinitialisation n'a pu être lu que dans la boîte visée.

    Sans cette équivalence, celui dont le lien de confirmation a expiré changeait
    son mot de passe et restait quand même à la porte.
    """
    from unittest.mock import AsyncMock, patch

    await _inscrire(client, "reset-vaut-preuve@blackturf.fr")
    user = (await db.execute(
        select(User).where(User.email == "reset-vaut-preuve@blackturf.fr")
    )).scalar_one()

    faux_redis = AsyncMock()
    faux_redis.get = AsyncMock(return_value=user.user_id.encode())
    with patch("redis.asyncio.from_url", return_value=faux_redis):
        resp = await client.post("/api/v1/auth/reset-password", json={
            "token": "peu-importe", "password": "NouveauMotDePasse123",
        })
    assert resp.status_code == 200

    await db.refresh(user)
    assert user.email_verified is True
    connexion = await client.post("/api/v1/auth/login", data={
        "username": "reset-vaut-preuve@blackturf.fr", "password": "NouveauMotDePasse123",
    })
    assert connexion.status_code == 200


async def test_un_compte_anterieur_a_la_regle_se_connecte_toujours(
    client: AsyncClient, db: AsyncSession
):
    """Dont un abonné payant : lui fermer la porte a posteriori serait une
    régression, pas une sécurité."""
    ancien = _user(email="ancien-abonne@blackturf.fr", plan="expert",
                   created_at=VERIFICATION_OBLIGATOIRE_DEPUIS - timedelta(days=30))
    db.add(ancien)
    await db.commit()

    resp = await _connexion(client, "ancien-abonne@blackturf.fr")

    assert resp.status_code == 200


async def test_le_checkout_stripe_exige_une_adresse_confirmee(
    client: AsyncClient, db: AsyncSession
):
    """Deuxième ligne de défense : une session ouverte avant la règle vit encore
    jusqu'à 7 jours, et l'essai gratuit se multiplierait, une adresse bidon par
    compte."""
    user = _user(email="checkout-non-verifie@blackturf.fr")
    db.add(user)
    await db.commit()

    resp = await client.post("/api/v1/stripe/checkout",
                             json={"plan": "standard", "periodicite": "monthly"},
                             headers=_entetes(user))

    assert resp.status_code == 403
    assert "onfirmez votre adresse" in resp.json()["detail"]


async def test_l_assistant_exige_une_adresse_confirmee(
    client: AsyncClient, db: AsyncSession
):
    """Chaque échange consomme des jetons facturés."""
    user = _user(email="assistant-non-verifie@blackturf.fr")
    db.add(user)
    await db.commit()

    resp = await client.post("/api/v1/assistant/chat",
                             json={"messages": [{"role": "user", "content": "salut"}]},
                             headers=_entetes(user))

    assert resp.status_code == 403
    assert "onfirmez votre adresse" in resp.json()["detail"]


async def test_une_fois_l_adresse_confirmee_le_checkout_repasse(
    client: AsyncClient, db: AsyncSession, confirmer_adresse
):
    await _inscrire(client, "confirme-ensuite@blackturf.fr")
    await confirmer_adresse("confirme-ensuite@blackturf.fr")
    assert (await _connexion(client, "confirme-ensuite@blackturf.fr")).status_code == 200

    resp = await client.post("/api/v1/stripe/checkout",
                             json={"plan": "standard", "periodicite": "monthly"})

    # Plus de 403 : l'appel va jusqu'à Stripe (non configuré en test → autre erreur).
    assert resp.status_code != 403
