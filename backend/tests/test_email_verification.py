"""L'adresse e-mail doit être confirmée pour ce qui coûte de l'argent.

Le mail de confirmation partait déjà à l'inscription, mais `email_verified`
n'était lu nulle part : une adresse inexistante donnait un compte complet, donc
un essai Stripe de plus et des rebonds qui abîment la délivrabilité de tous les
envois. Ces tests fixent la règle ET la dispense accordée aux anciens comptes.
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


async def test_le_checkout_stripe_exige_une_adresse_confirmee(client: AsyncClient):
    """Sans cela, l'essai gratuit se multiplie : une adresse bidon par compte."""
    await _inscrire(client, "checkout-non-verifie@blackturf.fr")

    resp = await client.post("/api/v1/stripe/checkout",
                             json={"plan": "standard", "periodicite": "monthly"})

    assert resp.status_code == 403
    assert "onfirmez votre adresse" in resp.json()["detail"]


async def test_l_assistant_exige_une_adresse_confirmee(client: AsyncClient):
    """Chaque échange consomme des jetons facturés."""
    await _inscrire(client, "assistant-non-verifie@blackturf.fr")

    resp = await client.post("/api/v1/assistant/chat",
                             json={"messages": [{"role": "user", "content": "salut"}]})

    assert resp.status_code == 403
    assert "onfirmez votre adresse" in resp.json()["detail"]


async def test_le_reste_du_produit_reste_accessible(client: AsyncClient):
    """On ne bloque QUE ce qui coûte : un nouvel inscrit doit pouvoir visiter le
    site et voir son profil, sinon la confirmation devient un mur à l'entrée."""
    await _inscrire(client, "libre@blackturf.fr")

    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (await client.get("/api/v1/programme")).status_code == 200


async def test_une_fois_l_adresse_confirmee_le_checkout_repasse(
    client: AsyncClient, db: AsyncSession
):
    await _inscrire(client, "confirme-ensuite@blackturf.fr")
    user = (await db.execute(
        select(User).where(User.email == "confirme-ensuite@blackturf.fr")
    )).scalar_one()
    user.email_verified = True
    await db.commit()

    resp = await client.post("/api/v1/stripe/checkout",
                             json={"plan": "standard", "periodicite": "monthly"})

    # Plus de 403 : l'appel va jusqu'à Stripe (non configuré en test → autre erreur).
    assert resp.status_code != 403
