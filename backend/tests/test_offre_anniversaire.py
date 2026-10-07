"""Offre anniversaire : −50 % le premier mois, code envoyé par mail seulement.

Ce qui doit tenir :
  · le bon code, sur le mensuel, pour un compte inscrit AVANT l'offre et sans
    abonnement → le coupon part chez Stripe, sans `allow_promotion_codes` ;
  · tout autre cas → 400 avec la raison, et AUCUNE page de paiement ouverte ;
  · le code n'est révélé qu'aux comptes éligibles.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import api.routes.stripe_routes as sr
from db.models import Subscription, User
from services import offre_anniversaire as oa

CODE = "TESTANNIV50"
AVANT = datetime(2026, 9, 1, tzinfo=timezone.utc)
PENDANT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
_VRAIE_RAISON = oa.raison_refus
_VRAI_COUPON = oa.assurer_coupon


@pytest.fixture(autouse=True)
def _offre_ouverte(monkeypatch):
    monkeypatch.setattr(oa.get_settings(), "code_anniversaire", CODE)
    monkeypatch.setattr(oa, "_deja_utilisee", lambda user: False)
    monkeypatch.setattr(oa, "assurer_coupon", lambda: oa.COUPON_ID)
    # L'offre est datée : les tests se placent pendant sa durée.
    monkeypatch.setattr(oa, "raison_refus", lambda user, db, now=None: _VRAIE_RAISON(user, db, now or PENDANT))


def _capture(monkeypatch) -> dict:
    captured: dict = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return type("S", (), {"url": "https://checkout.stripe.test/x"})()

    monkeypatch.setattr(sr.stripe.checkout.Session, "create", _fake_create)
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_std_m", "standard_annual": "price_std_a",
                                          "expert_monthly": "price_exp_m"})
    return captured


async def _user(db, created_at=AVANT, **kw) -> User:
    user = User(user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@blackturf.fr",
                plan=kw.pop("plan", "free"), stripe_customer_id=f"cus_{uuid.uuid4().hex[:10]}",
                created_at=created_at, email_verified=True, **kw)
    db.add(user)
    await db.commit()
    return user


async def _checkout(db, user, code=CODE, plan="expert", periodicite="monthly"):
    return await sr.create_checkout(
        sr.CheckoutRequest(plan=plan, periodicite=periodicite, code_promo=code), db, user)


@pytest.mark.asyncio
async def test_code_valide_applique_le_coupon(db, monkeypatch):
    captured = _capture(monkeypatch)
    user = await _user(db)
    res = await _checkout(db, user, code=" testanniv50 ")  # casse et espaces tolérés

    assert res["offre_anniversaire"] is True
    assert captured["discounts"] == [{"coupon": oa.COUPON_ID}]
    assert "allow_promotion_codes" not in captured  # exclusif de `discounts` chez Stripe
    assert captured["subscription_data"]["metadata"]["offre"] == oa.COUPON_ID
    assert captured["line_items"] == [{"price": "price_exp_m", "quantity": 1}]


@pytest.mark.asyncio
async def test_sans_code_rien_ne_change(db, monkeypatch):
    captured = _capture(monkeypatch)
    user = await _user(db)
    await _checkout(db, user, code=None)
    assert "discounts" not in captured
    assert captured["allow_promotion_codes"] is True
    assert "offre" not in captured["subscription_data"]["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cas, message", [
    ("mauvais_code", "n'est pas valide"),
    ("annuel", "mensuel uniquement"),
    ("compte_recent", "inscrits avant le 8 octobre"),
    ("abonne", "sans abonnement en cours"),
    ("deja_utilisee", "déjà profité"),
    ("offre_fermee", "pas valide"),  # code retiré du .env : il ne vaut plus rien
])
async def test_refus_sans_page_de_paiement(db, monkeypatch, cas, message):
    captured = _capture(monkeypatch)
    user = await _user(db, created_at=datetime(2026, 10, 9, tzinfo=timezone.utc) if cas == "compte_recent" else AVANT)
    code, periodicite = CODE, "monthly"
    if cas == "mauvais_code":
        code = "ANNIV10"
    elif cas == "annuel":
        periodicite = "annual"
    elif cas == "abonne":
        db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id, stripe_subscription_id="sub_x",
                            plan="standard", periodicite="monthly", statut="active",
                            periode_debut=AVANT, periode_fin=AVANT + timedelta(days=30)))
        await db.commit()
    elif cas == "deja_utilisee":
        monkeypatch.setattr(oa, "_deja_utilisee", lambda u: True)
    elif cas == "offre_fermee":
        monkeypatch.setattr(oa.get_settings(), "code_anniversaire", "")

    with pytest.raises(HTTPException) as exc:
        await _checkout(db, user, code=code, plan="standard", periodicite=periodicite)
    assert exc.value.status_code == 400
    assert message in exc.value.detail
    assert captured == {}


@pytest.mark.asyncio
async def test_valable_jusquau_15_octobre(db):
    user = await _user(db)
    assert oa.FIN == datetime(2026, 10, 15, 23, 59, 59, tzinfo=oa.PARIS)
    assert await _VRAIE_RAISON(user, db, oa.FIN - timedelta(seconds=1)) is None
    assert "pris fin le 15 octobre" in await _VRAIE_RAISON(user, db, oa.FIN + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_code_revele_aux_seuls_eligibles(db):
    ancien = await _user(db)
    res = await sr.offre_anniversaire_du_compte(db, ancien)
    assert res["eligible"] is True and res["code"] == CODE
    assert res["prix"]["expert"] == {"avant": 1900, "apres": 950}

    nouveau = await _user(db, created_at=datetime(2026, 10, 9, tzinfo=timezone.utc))
    res = await sr.offre_anniversaire_du_compte(db, nouveau)
    assert res["eligible"] is False and "code" not in res


def test_le_code_nest_pas_dans_le_depot():
    """Le dépôt est public : aucune valeur par défaut ne doit porter le code."""
    from api.config import Settings
    assert Settings.model_fields["code_anniversaire"].default == ""


def test_coupon_premier_paiement_seulement(monkeypatch):
    """La remise ne vaut QUE pour la première facture : `duration=once`. Les
    mensualités suivantes repartent au prix plein si l'abonné ne résilie pas."""
    import importlib
    import stripe
    vrai = importlib.import_module("services.offre_anniversaire")
    cree: dict = {}

    def _absent(_id):
        raise stripe.error.InvalidRequestError("No such coupon", "id")

    monkeypatch.setattr(stripe.Coupon, "retrieve", _absent)
    monkeypatch.setattr(stripe.Coupon, "create", lambda **kw: cree.update(kw))
    monkeypatch.setattr(stripe.Price, "retrieve", lambda pid: {"product": "prod_" + pid})
    monkeypatch.setattr(vrai.get_settings(), "stripe_price_starter_monthly", "std")
    monkeypatch.setattr(vrai.get_settings(), "stripe_price_pro_monthly", "exp")

    assert _VRAI_COUPON() == vrai.COUPON_ID
    assert cree["duration"] == "once"
    assert "duration_in_months" not in cree
    assert cree["percent_off"] == 50
    assert len(cree["name"]) <= 40  # limite Stripe, sinon le coupon (et le paiement) échoue
    assert cree["redeem_by"] == int(vrai.FIN.timestamp())
    assert cree["applies_to"] == {"products": ["prod_exp", "prod_std"]}
