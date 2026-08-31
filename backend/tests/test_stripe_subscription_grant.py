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


def _fake_sub(status: str, price_id: str = "price_test_standard", sub_id: str | None = None,
              carte: bool = True) -> dict:
    """Abonnement Stripe factice. `carte=True` par défaut : depuis le 2026-08-20 un
    essai SANS moyen de paiement n'ouvre plus aucun accès (cf.
    test_stripe_essai_et_changement_plan.py), or ces tests-ci portent sur le
    statut de l'abonnement, pas sur la carte."""
    now = int(time.time())
    return {
        "id": sub_id or str(uuid.uuid4()),
        "customer": "cus_test",
        "status": status,
        "items": {"data": [{"price": {"id": price_id, "recurring": {"interval": "month"}}}]},
        "current_period_start": now,
        "current_period_end": now + 30 * 86400,
        "trial_end": None,
        "default_payment_method": "pm_test" if carte else None,
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


@pytest.mark.asyncio
async def test_checkout_ouvre_bien_un_essai_de_7_jours(db, monkeypatch):
    """L'essai de 7 jours est promis sur l'accueil, sur /tarifs et dans les CGU :
    la session Checkout doit réellement le porter.

    La carte est exigée depuis le 2026-08-20 (`always`). L'ancien `if_required`
    — « essai sans carte » — laissait passer des essais qu'aucun moyen de paiement
    ne pouvait convertir ; le détail du nouveau contrat est couvert par
    test_stripe_essai_et_changement_plan.py."""
    import api.routes.stripe_routes as sr

    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return type("S", (), {"url": "https://checkout.stripe.test/x"})()

    monkeypatch.setattr(sr.stripe.checkout.Session, "create", _fake_create)
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_test_standard"})

    user = User(user_id=str(uuid.uuid4()), email="essai@blackturf.fr",
                plan="free", stripe_customer_id="cus_test")
    db.add(user)
    await db.commit()

    await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)

    assert captured["payment_method_collection"] == "always"
    assert captured["subscription_data"]["trial_period_days"] == 7
    assert (captured["subscription_data"]["trial_settings"]["end_behavior"]
            ["missing_payment_method"]) == "cancel"
