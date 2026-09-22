"""L'essai de 7 jours doit être proposé à ceux qui y ont droit — et à eux seuls.

Constat en production le 2026-09-13 : 44 comptes gratuits, 2 seulement ont
jamais ouvert l'essai. Aucun écran ne le proposait directement ; tous renvoyaient
vers /tarifs. `/auth/me` expose désormais `essai_disponible`, qui pilote le
bandeau d'essai, la navbar et l'écran de confirmation d'adresse.

Même vérité que le checkout (`stripe_routes.create_checkout`) : essai jamais
consommé (`essai_utilise_at`) et aucun abonnement vivant (sinon changement de
plan, pas d'essai). Proposer un essai que le checkout refuserait serait pire que
de ne rien proposer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import api.routes.stripe_routes as sr
from db.models import Subscription, User
from tests._descripteurs_deploiement import RACINE, exiger

FRONT = RACINE / "frontend" / "src"


async def _user(db) -> User:
    return (await db.execute(select(User).where(User.email == "test@blackturf.fr"))).scalar_one()


@pytest.mark.asyncio
async def test_compte_neuf_a_droit_a_lessai(client, auth_headers):
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["essai_disponible"] is True


@pytest.mark.asyncio
async def test_essai_deja_consomme_nest_plus_propose(client, db, auth_headers):
    user = await _user(db)
    user.essai_utilise_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db.commit()
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["essai_disponible"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("statut", sorted(sr.STATUTS_VIVANTS))
async def test_abonnement_vivant_exclut_lessai(client, db, auth_headers, statut):
    """Un abonnement vivant fait passer le checkout en changement de plan (ou 409) :
    aucun essai ne s'ouvrirait, il ne doit donc pas être promis."""
    user = await _user(db)
    db.add(Subscription(
        sub_id=str(uuid.uuid4()), user_id=user.user_id,
        stripe_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        plan="standard", periodicite="monthly", statut=statut,
        periode_debut=datetime.now(timezone.utc),
        periode_fin=datetime.now(timezone.utc) + timedelta(days=30),
    ))
    await db.commit()
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["essai_disponible"] is False, f"statut {statut!r}"


def test_le_bandeau_dessai_est_monte_dans_le_layout():
    layout = exiger(FRONT / "app" / "(main)" / "layout.tsx")
    bandeau = exiger(FRONT / "components" / "billing" / "EssaiGratuitBanner.tsx")
    assert "EssaiGratuitBanner" in layout
    assert "peutDemarrerEssai" in bandeau
    # La carte est dite avant le clic : la découvrir chez Stripe fait abandonner.
    assert "Carte demandée" in bandeau


def test_linscription_affiche_lecran_dattente():
    """Régression constatée le 2026-09-13 : l'écran « Vérifiez votre boîte mail »
    avait disparu lors d'une refonte SEO — après inscription, le formulaire restait
    affiché sans un mot et l'inscrit ignorait qu'un lien l'attendait."""
    source = exiger(FRONT / "app" / "(auth)" / "inscription" / "page.tsx")
    assert "if (enAttente)" in source
    assert "Vérifiez votre boîte mail" in source


def test_la_confirmation_dadresse_propose_lessai():
    source = exiger(FRONT / "app" / "(auth)" / "verifier-email" / "page.tsx")
    assert "CheckoutButton" in source and "peutDemarrerEssai" in source
