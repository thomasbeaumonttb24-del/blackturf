"""Audit sécurité du 2026-10-06 : envois d'e-mails rejouables, litiges, stats publiques.

1. Le popup « pronostic par e-mail » (anonyme) servait de relais : quota par IP,
   par BOÎTE (alias `+…` compris) et plafond global.
2. `/stripe/cancel` envoyait deux e-mails à CHAQUE appel, même sans rien résilier.
3. Un paiement d'abonnement contesté (ou remboursé en entier) gardait l'accès.
4. Dates fantaisistes refusées sur les stats publiques à paramètre de date.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import api.routes.stripe_routes as sr
from api.routes import pronostic_email as pe
from db.models import SubscriptionEvent
from tests.test_pronostic_email_quota import _course, _demander, _patches
from tests.test_stripe_essai_et_changement_plan import _abo, _user

pytestmark = pytest.mark.asyncio


# ── 1. Pronostic par e-mail ──────────────────────────────────────────────────
def test_les_alias_arrivent_dans_la_meme_boite():
    assert pe._boite("nom+1@x.fr") == pe._boite("nom+zz@x.fr") == "nom@x.fr"
    assert pe._boite("nom@x.fr") == "nom@x.fr"


async def test_limite_ip_au_dela_de_cinq_par_heure():
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[pe.DEMANDES_PAR_HEURE_IP + 1, True])
    redis = MagicMock(pipeline=MagicMock(return_value=pipe))
    req = SimpleNamespace(headers={"x-real-ip": "1.2.3.4"}, client=None)
    with patch("db.redis_client.get_redis", AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc:
            await pe._limite_ip(req)
    assert exc.value.status_code == 429
    pipe.incr.assert_called_with("rl:pronoemail:ip:1.2.3.4")


async def test_limite_ip_laisse_passer_si_redis_tombe():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="5.6.7.8"))
    with patch("db.redis_client.get_redis", AsyncMock(side_effect=RuntimeError("panne"))):
        await pe._limite_ip(req)  # ne lève pas


async def test_garde_refuse_rien_ne_part_et_la_reponse_reste_generique(client, db):
    await _course(db, "C-SECU-GARDE")
    p1, p2, p3, p4 = _patches()
    with p1, p2, p3, p4 as envoi, patch.object(pe, "envoi_autorise", AsyncMock(return_value=False)):
        r = await _demander(client, "C-SECU-GARDE")
    assert r.status_code == 200 and r.json()["ok"] is True
    envoi.assert_not_called()


# ── 2. /stripe/cancel ────────────────────────────────────────────────────────
@pytest.fixture
def mails(monkeypatch):
    envoyes: list[str] = []

    async def _capture(**kw):
        envoyes.append(kw["to"])
    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _capture)
    monkeypatch.setattr(sr, "envoi_autorise", AsyncMock(return_value=True))
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test", raising=False)
    monkeypatch.setattr(sr.stripe.Subscription, "modify", lambda sid, **kw: None)
    return envoyes


async def test_sans_abonnement_ni_formule_400_et_aucun_mail(db, mails):
    user = await _user(db, plan="free")
    with pytest.raises(HTTPException) as exc:
        await sr.cancel_subscription(db, user)
    assert exc.value.status_code == 400
    assert mails == []


async def test_double_clic_un_seul_jeu_de_mails(db, mails):
    user = await _user(db, plan="expert")
    await _abo(db, user, plan="expert", statut="active", stripe_id="sub_cancel_1")
    assert (await sr.cancel_subscription(db, user))["via_stripe"] is True
    assert (await sr.cancel_subscription(db, user))["via_stripe"] is True
    # L'exploitant est prévenu UNE fois, par le journal des mouvements (admin@) :
    # le second mail à contact@ faisait doublon (audit mails 10/10/2026).
    assert sorted(mails) == sorted(["admin@blackturf.fr", user.email])


async def test_formule_hors_stripe_garde_la_demande_manuelle(db, mails):
    user = await _user(db, plan="expert", stripe_customer_id=None)
    res = await sr.cancel_subscription(db, user)
    assert res["via_stripe"] is False
    # Rien n'a été résilié chez Stripe : la demande à traiter à la main part bien.
    assert sorted(mails) == sorted(["contact@blackturf.fr", user.email])


# ── 3. Contestation / remboursement d'un abonnement ─────────────────────────
@pytest.fixture
def stripe_litige(monkeypatch):
    supprimes: list[str] = []
    monkeypatch.setattr(sr, "_stripe_joignable", lambda: True)
    monkeypatch.setattr(sr.stripe.Charge, "retrieve", lambda cid: {"id": cid, "invoice": "in_litige"})
    monkeypatch.setattr(sr.stripe.Invoice, "retrieve",
                        lambda fid: {"id": fid, "subscription": "sub_litige"})
    monkeypatch.setattr(sr.stripe.Subscription, "delete", lambda sid: supprimes.append(sid))
    return supprimes


async def test_contestation_clot_l_abonnement_une_seule_fois(db, stripe_litige):
    user = await _user(db, plan="expert")
    abo = await _abo(db, user, plan="expert", statut="active", stripe_id="sub_litige")
    litige = {"object": "dispute", "id": "dp_1", "charge": "ch_1"}

    await sr._clore_abonnement_du_paiement(litige, db, "paiement_conteste")
    await sr._clore_abonnement_du_paiement(litige, db, "paiement_conteste")  # relivraison

    await db.refresh(abo)
    await db.refresh(user)
    assert abo.statut == "canceled" and user.plan == "free"
    assert stripe_litige == ["sub_litige"]
    types = (await db.execute(select(SubscriptionEvent.type).where(
        SubscriptionEvent.user_id == user.user_id))).scalars().all()
    assert list(types) == ["resilie"]


async def test_remboursement_partiel_laisse_l_abonnement(db, stripe_litige):
    assert not sr._remboursement_total({"amount": 1900, "amount_refunded": 500, "refunded": False})
    assert sr._remboursement_total({"amount": 1900, "amount_refunded": 1900})
    user = await _user(db, plan="expert")
    abo = await _abo(db, user, plan="expert", statut="active", stripe_id="sub_litige")
    await sr._traiter_evenement("charge.refunded", {
        "object": "charge", "id": "ch_2", "amount": 1900, "amount_refunded": 500,
        "refunded": False, "payment_intent": "pi_x"}, db)
    await db.refresh(abo)
    assert abo.statut == "active" and stripe_litige == []


async def test_panne_stripe_ne_casse_pas_le_webhook(db, monkeypatch):
    monkeypatch.setattr(sr, "_stripe_joignable", lambda: True)

    def _panne(cid):
        raise RuntimeError("réseau")
    monkeypatch.setattr(sr.stripe.Charge, "retrieve", _panne)
    await sr._clore_abonnement_du_paiement({"object": "dispute", "charge": "ch_3"}, db,
                                           "paiement_conteste")


# ── 4. Stats publiques : bornes de date ──────────────────────────────────────
@pytest.mark.parametrize("route", ["meilleurs-plans-jour?jour=", "bilan-semaine?fin="])
@pytest.mark.parametrize("valeur", ["2025-12-31", "2099-01-01"])
async def test_dates_hors_periode_refusees(client, route, valeur):
    r = await client.get(f"/api/v1/stats/{route}{valeur}")
    assert r.status_code == 400
