"""Appels Stripe du parrainage, validés contre la spécification OFFICIELLE.

stripe-mock (https://github.com/stripe/stripe-mock) rejette tout paramètre que
la vraie API refuserait. Ignoré si STRIPE_MOCK_URL n'est pas défini :

    stripe-mock -http-port 12111 &
    STRIPE_MOCK_URL=http://localhost:12111 pytest tests/test_parrainage_stripe_mock.py
"""
import os
import uuid

import pytest

import api.routes.stripe_routes as sr
from db.models import User
from services import parrainage as P

URL = os.getenv("STRIPE_MOCK_URL")
pytestmark = pytest.mark.skipif(not URL, reason="stripe-mock non lancé (STRIPE_MOCK_URL)")


@pytest.fixture
def stripe_mock(monkeypatch):
    monkeypatch.setattr(P.stripe, "api_key", "sk_test_mock")
    monkeypatch.setattr(P.stripe, "api_base", URL)
    monkeypatch.setattr(P.settings, "stripe_secret_key", "sk_test_mock")


def test_coupon_filleul(stripe_mock):
    assert P.coupon_filleul() == P.COUPON_FILLEUL_ID


def test_credit_et_reprise_sur_solde(stripe_mock):
    parrain = User(user_id="u1", email="p@b.fr", stripe_customer_id="cus_mock")
    assert P._crediter(parrain, -500, f"k-{uuid.uuid4()}", "Parrainage", {"parrainage_id": "p1"}).startswith("cbtxn_")
    assert P._crediter(parrain, 500, f"k-{uuid.uuid4()}", "Reprise", {"parrainage_id": "p1"}).startswith("cbtxn_")
    assert P._credit_stripe(parrain) is not None


@pytest.mark.asyncio
async def test_checkout_filleul_avec_remise(db, stripe_mock, monkeypatch):
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_mock"})
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [])
    parrain = User(user_id=str(uuid.uuid4()), email="p@blackturf.fr", email_verified=True)
    filleul = User(user_id=str(uuid.uuid4()), email="f@blackturf.fr", email_verified=True,
                   stripe_customer_id="cus_mock")
    db.add_all([parrain, filleul])
    await db.commit()
    await P.rattacher_filleul(filleul, await P.code_de(parrain, db), db)
    await db.commit()

    # Session.create part réellement vers stripe-mock : discounts + pas de codes promo.
    res = await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, filleul)
    assert res["remise_parrainage"] is True and res["essai"] is False and res["url"]
