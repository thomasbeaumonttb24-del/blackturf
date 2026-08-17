"""
Régression : `_handle_subscription_created` ne doit accorder le plan payant QUE si
Stripe rapporte un abonnement réellement actif/en essai (`active`/`trialing`).

Bug corrigé le 2026-08-17 : le plan était accordé inconditionnellement dès la
réception du webhook `customer.subscription.created`, que Stripe émet dès la
CRÉATION de l'objet abonnement — y compris quand le paiement n'a jamais abouti
(carte non validée, 3-D Secure non terminé, checkout abandonné avant confirmation,
statut Stripe "incomplete"/"incomplete_expired"). Un utilisateur pouvait donc
apparaître abonné sur le site sans avoir payé.
"""
import time
import uuid
import pytest

from db.models import User
from api.routes import stripe_routes


def _fake_sub(status: str, price_id: str = "price_test_standard", sub_id: str | None = None) -> dict:
    now = int(time.time())
    return {
        "id": sub_id or str(uuid.uuid4()),
        "customer": "cus_test",
        "status": status,
        "items": {"data": [{"price": {"id": price_id, "recurring": {"interval": "month"}}}]},
        "current_period_start": now,
        "current_period_end": now + 30 * 86400,
        "trial_end": None,
    }


@pytest.mark.asyncio
async def test_incomplete_subscription_does_not_grant_plan(db, monkeypatch):
    monkeypatch.setattr(stripe_routes, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})

    user = User(user_id=str(uuid.uuid4()), email="incomplete@blackturf.fr",
                plan="free", stripe_customer_id="cus_test")
    db.add(user)
    await db.commit()

    await stripe_routes._handle_subscription_created(_fake_sub("incomplete"), db)

    await db.refresh(user)
    assert user.plan == "free"


@pytest.mark.asyncio
async def test_incomplete_expired_subscription_does_not_grant_plan(db, monkeypatch):
    monkeypatch.setattr(stripe_routes, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})

    user = User(user_id=str(uuid.uuid4()), email="expired@blackturf.fr",
                plan="free", stripe_customer_id="cus_test")
    db.add(user)
    await db.commit()

    await stripe_routes._handle_subscription_created(_fake_sub("incomplete_expired"), db)

    await db.refresh(user)
    assert user.plan == "free"


@pytest.mark.asyncio
async def test_trialing_subscription_grants_plan(db, monkeypatch):
    monkeypatch.setattr(stripe_routes, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})

    user = User(user_id=str(uuid.uuid4()), email="trial@blackturf.fr",
                plan="free", stripe_customer_id="cus_test")
    db.add(user)
    await db.commit()

    await stripe_routes._handle_subscription_created(_fake_sub("trialing"), db)

    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_active_subscription_grants_plan(db, monkeypatch):
    monkeypatch.setattr(stripe_routes, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})

    user = User(user_id=str(uuid.uuid4()), email="active@blackturf.fr",
                plan="free", stripe_customer_id="cus_test")
    db.add(user)
    await db.commit()

    await stripe_routes._handle_subscription_created(_fake_sub("active"), db)

    await db.refresh(user)
    assert user.plan == "standard"
