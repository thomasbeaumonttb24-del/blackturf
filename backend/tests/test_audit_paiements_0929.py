"""Failles du circuit de paiement trouvées à l'audit du 2026-09-29.

Chaque test rejoue le scénario concret qui coûtait de l'argent au client, en
retirait l'accès à un client à jour, ou donnait l'accès sans paiement.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

import api.routes.stripe_routes as sr
import services.relances_paiement as rp
from db.models import Subscription, SubscriptionEvent, User
from tests.test_stripe_essai_et_changement_plan import _abo, _capture_checkout, _user

pytestmark = pytest.mark.asyncio


def _joignable(monkeypatch):
    """Lève le garde-fou anti-réseau : chaque appel Stripe est simulé par le test.
    Appelé DANS le test : pytest réécrit PYTEST_CURRENT_TEST à chaque phase."""
    monkeypatch.setattr(sr.stripe, "api_key", "sk_test")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


@pytest.fixture(autouse=True)
def sans_email(monkeypatch):
    async def _rien(**kw):
        return None
    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _rien)


async def _journal(db, user):
    return [e.type for e in (await db.execute(
        select(SubscriptionEvent).where(SubscriptionEvent.user_id == user.user_id)
        .order_by(SubscriptionEvent.created_at))).scalars().all()]


# ── 1. Différence d'un passage en Expert refusée : le client garde sa formule payée
async def test_refus_de_la_difference_ne_coupe_pas_la_formule_payee(db, monkeypatch):
    _joignable(monkeypatch)
    user = await _user(db, plan="standard")
    abo = await _abo(db, user, plan="standard", statut="active", stripe_id="sub_std")
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve",
                        lambda sid: {"status": "active", "pending_update": {"subscription_items": []}})
    coupes = []
    monkeypatch.setattr(rp, "couper_collecte_stripe", lambda fid: coupes.append(fid))

    await sr._handle_payment_failed({
        "id": "in_diff", "customer": "cus_test", "billing_reason": "subscription_update",
        "subscription": "sub_std", "amount_due": 461, "attempt_count": 1}, db)

    await db.refresh(abo)
    await db.refresh(user)
    assert abo.statut == "active" and user.plan == "standard"
    assert coupes == []
    assert (await _journal(db, user))[-1] == "changement_formule_refuse"


async def test_fin_d_essai_refusee_reste_un_impaye(db, monkeypatch):
    """Même motif `subscription_update`, mais l'abonnement lui-même est impayé."""
    _joignable(monkeypatch)
    user = await _user(db, plan="expert")
    abo = await _abo(db, user, plan="expert", statut="active", stripe_id="sub_essai")
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid: {"status": "past_due"})
    monkeypatch.setattr(rp, "couper_collecte_stripe", lambda fid: None)

    await sr._handle_payment_failed({
        "id": "in_essai", "customer": "cus_test", "billing_reason": "subscription_update",
        "subscription": "sub_essai", "amount_due": 1900, "attempt_count": 1}, db)

    await db.refresh(abo)
    await db.refresh(user)
    assert abo.statut == "past_due" and user.plan == "free"


# ── 2. Paiement tardif sur un abonnement clos : pas d'accès à vie
async def test_paiement_sur_abonnement_clos_ne_rouvre_pas(db):
    user = await _user(db, plan="free")
    abo = await _abo(db, user, plan="expert", statut="canceled", stripe_id="sub_clos")

    await sr._handle_payment_succeeded({
        "id": "in_tard", "customer": "cus_test", "subscription": "sub_clos",
        "amount_paid": 1900, "billing_reason": "subscription_cycle"}, db)

    await db.refresh(abo)
    await db.refresh(user)
    assert abo.statut == "canceled" and user.plan == "free"
    ev = (await db.execute(select(SubscriptionEvent).where(
        SubscriptionEvent.type == "paiement_recu"))).scalar_one()
    assert ev.detail["a_rembourser"] is True


# ── 3. Résilier pendant un impayé : clos tout de suite, plus aucun prélèvement
async def test_resilier_pendant_un_impaye_clot_et_annule_la_facture(db, monkeypatch):
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test")
    appels = []
    monkeypatch.setattr(sr.stripe.Subscription, "delete", lambda sid: appels.append(("delete", sid)))
    monkeypatch.setattr(sr.stripe.Subscription, "modify", lambda sid, **kw: appels.append(("modify", kw)))
    monkeypatch.setattr(sr.stripe.Invoice, "list", lambda **kw: [{"id": "in_du"}])
    monkeypatch.setattr(sr.stripe.Invoice, "void_invoice", lambda fid: appels.append(("void", fid)))
    user = await _user(db, plan="free")
    abo = await _abo(db, user, plan="expert", statut="past_due", stripe_id="sub_impaye")

    res = await sr.cancel_subscription(db, user)

    assert res["via_stripe"] is True
    assert ("delete", "sub_impaye") in appels and ("void", "in_du") in appels
    assert not any(a[0] == "modify" for a in appels)  # pas de « fin de période »
    await db.refresh(abo)
    assert abo.statut == "canceled"


# ── 4. Checkout : jamais de second abonnement ni de mélange de prix
async def test_impaye_refuse_avant_meme_formule(db, monkeypatch):
    _capture_checkout(monkeypatch)
    user = await _user(db, plan="free")
    await _abo(db, user, plan="expert", statut="past_due")
    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)
    assert exc.value.status_code == 409 and "attente" in exc.value.detail


async def test_premier_paiement_en_cours_bloque_un_second_abonnement(db, monkeypatch):
    captured = _capture_checkout(monkeypatch)
    user = await _user(db, plan="free")
    await _abo(db, user, plan="expert", statut="incomplete")
    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)
    assert exc.value.status_code == 409
    assert captured == {}


async def test_abonnement_connu_de_stripe_seul_bloque_le_checkout(db, monkeypatch):
    captured = _capture_checkout(monkeypatch)
    monkeypatch.setattr(sr, "_abonnements_stripe_vivants", lambda cid: [{"status": "trialing"}])
    user = await _user(db, plan="free")
    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)
    assert exc.value.status_code == 409 and captured == {}


async def test_checkout_expire_les_pages_de_paiement_ouvertes(db, monkeypatch):
    _capture_checkout(monkeypatch)
    _joignable(monkeypatch)
    expirees = []
    monkeypatch.setattr(sr.stripe.Subscription, "list",
                        lambda **kw: type("L", (), {"auto_paging_iter": lambda self: iter([])})())
    monkeypatch.setattr(sr.stripe.checkout.Session, "list", lambda **kw: [{"id": "cs_vieux"}])
    monkeypatch.setattr(sr.stripe.checkout.Session, "expire", lambda sid: expirees.append(sid))
    monkeypatch.setattr(sr, "_empreintes_deja_prises", _faux_async(False))
    monkeypatch.setattr(sr.parrainage, "remise_filleul_due", _faux_async(None))
    user = await _user(db, plan="free")
    await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)
    assert expirees == ["cs_vieux"]


def _faux_async(valeur):
    async def f(*a, **k):
        return valeur
    return f


async def test_passage_mensuel_annuel_refuse(db, monkeypatch):
    _capture_checkout(monkeypatch)
    monkeypatch.setitem(sr.PRICE_MAP, "expert_annual", "price_test_expert_an")
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active")
    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="annual"), db, user)
    assert exc.value.status_code == 409


async def test_changement_garde_la_resiliation_programmee(db, monkeypatch):
    _capture_checkout(monkeypatch)
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve",
                        lambda sid: {"status": "active", "items": {"data": [{"id": "si"}]}})
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda sid, **kw: {"status": "active", "cancel_at_period_end": True})
    user = await _user(db, plan="expert")
    abo = await _abo(db, user, plan="expert", statut="cancel_at_period_end")
    await sr.create_checkout(
        sr.CheckoutRequest(plan="standard", periodicite="monthly", confirmer=True), db, user)
    await db.refresh(abo)
    await db.refresh(user)
    assert abo.statut == "cancel_at_period_end" and user.plan == "standard"


async def test_second_clic_pendant_3ds_renvoie_la_meme_facture(db, monkeypatch):
    _capture_checkout(monkeypatch)
    modifs = []
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid: {
        "status": "active", "items": {"data": [{"id": "si"}]},
        "pending_update": {"x": 1}, "latest_invoice": {"hosted_invoice_url": "https://inv/1"}})
    monkeypatch.setattr(sr.stripe.Subscription, "modify", lambda sid, **kw: modifs.append(kw))
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active")
    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)
    assert res["paiement_requis"] is True and res["url"] == "https://inv/1"
    assert modifs == []


# ── 5. Relances : Stripe fait foi
class _Relances:
    def __init__(self, monkeypatch, statut_live="past_due", resilie=False, factures=None):
        self.appels = []
        f = {"id": "in_x", "status": "open", "attempt_count": 1, "auto_advance": False,
             "amount_due": 1900, "created": 0}
        monkeypatch.setattr(rp.stripe, "api_key", "sk_test")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(rp.stripe.Subscription, "retrieve",
                            lambda sid: {"status": statut_live, "cancel_at_period_end": resilie})
        monkeypatch.setattr(rp.stripe.Invoice, "list",
                            lambda **kw: {"data": factures if factures is not None else [f]})
        monkeypatch.setattr(rp.stripe.Invoice, "retrieve", lambda fid: dict(f))
        monkeypatch.setattr(rp.stripe.Invoice, "pay", lambda fid: self.appels.append("pay"))
        monkeypatch.setattr(rp.stripe.Invoice, "void_invoice", lambda fid: self.appels.append(f"void:{fid}"))
        monkeypatch.setattr(rp.stripe.Subscription, "delete", lambda sid: self.appels.append(f"delete:{sid}"))


async def _impaye(db, jours=3.2):
    user = await _user(db, plan="free")
    abo = await _abo(db, user, plan="expert", statut="past_due", stripe_id=f"sub_{uuid.uuid4().hex[:6]}")
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=user.user_id, email=user.email,
                             type="paiement_echoue", plan="expert",
                             stripe_subscription_id=abo.stripe_subscription_id, montant_cents=1900,
                             detail={"facture": "in_x"},
                             created_at=datetime.now(timezone.utc) - timedelta(days=jours)))
    await db.commit()
    return user, abo


async def test_relance_ne_debite_pas_un_abonnement_clos_chez_stripe(db, monkeypatch):
    s = _Relances(monkeypatch, statut_live="canceled")
    user, abo = await _impaye(db)
    await rp.traiter_impayes(db)
    assert "pay" not in s.appels
    await db.refresh(abo)
    assert abo.statut == "canceled"


async def test_relance_ne_debite_pas_un_client_qui_a_resilie(db, monkeypatch):
    s = _Relances(monkeypatch, resilie=True)
    user, abo = await _impaye(db)
    await rp.traiter_impayes(db)
    assert "pay" not in s.appels
    assert f"delete:{abo.stripe_subscription_id}" in s.appels and "void:in_x" in s.appels


async def test_difference_orpheline_annulee(db, monkeypatch):
    s = _Relances(monkeypatch, statut_live="active",
                  factures=[{"id": "in_diff", "billing_reason": "subscription_update", "amount_due": 461}])
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_ok")
    await rp.traiter_impayes(db)
    assert "void:in_diff" in s.appels and "pay" not in s.appels


# ── 6. Webhook : secret obligatoire, un événement traité une seule fois
async def test_webhook_refuse_sans_secret(client, monkeypatch):
    monkeypatch.setattr(sr.settings, "stripe_webhook_secret", "")
    resp = await client.post("/api/v1/stripe/webhook", content=b"{}",
                             headers={"stripe-signature": "t=1,v1=x"})
    assert resp.status_code == 503


async def test_webhook_meme_evenement_traite_une_fois_et_rejoue_apres_echec(client, db, monkeypatch):
    monkeypatch.setattr(sr.settings, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(sr.stripe.Webhook, "construct_event", lambda p, s, k: {
        "id": "evt_1", "type": "invoice.payment_succeeded", "data": {"object": {"id": "in"}}})
    traites = []

    async def _traiter(t, d, db_):
        traites.append(t)
        if len(traites) == 1:
            raise RuntimeError("panne")

    monkeypatch.setattr(sr, "_traiter_evenement", _traiter)
    h = {"stripe-signature": "t=1,v1=x"}
    with pytest.raises(RuntimeError):
        await client.post("/api/v1/stripe/webhook", content=b"{}", headers=h)
    assert (await client.post("/api/v1/stripe/webhook", content=b"{}", headers=h)).status_code == 200
    assert (await client.post("/api/v1/stripe/webhook", content=b"{}", headers=h)).status_code == 200
    assert len(traites) == 2  # échec, rejeu réussi, puis doublon ignoré


# ── 7. Contenu payant : jamais servi à un compte gratuit
async def test_tableau_de_bord_ne_nomme_aucun_pari_a_un_compte_gratuit(client, auth_headers):
    resp = await client.get("/api/v1/stats/dashboard-summary", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json().get("top_vbs") == []


async def test_dutch_reserve_aux_abonnes(client, auth_headers):
    resp = await client.get("/api/v1/courses/course_x/dutch", headers=auth_headers)
    assert resp.status_code == 403


async def test_plan_inconnu_ne_voit_aucun_pari():
    from services.valuebets_visibilite import PLANS_AVEC_VALUE_BETS, cutoff_detection
    assert "decouverte" not in PLANS_AVEC_VALUE_BETS and "free" not in PLANS_AVEC_VALUE_BETS
    assert cutoff_detection("starter") is not None  # ancien nom de Standard : même délai


# ── 8. Chiffres admin
async def test_mrr_hors_resiliations_programmees(client, admin_headers, db):
    u1 = await _user(db, plan="expert", stripe_customer_id="cus_a")
    u2 = await _user(db, plan="standard", stripe_customer_id="cus_b")
    await _abo(db, u1, plan="expert", statut="cancel_at_period_end")
    await _abo(db, u2, plan="standard", statut="active")
    r = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()["resume"]
    assert r["mrr"] == 12.0 and r["mrr_resiliations"] == 19.0
    assert r["abonnes_payants"] == 2  # il a payé : toujours payant jusqu'à l'échéance


async def test_une_facture_refusee_compte_une_fois_meme_relancee_le_mois_suivant(client, admin_headers, db):
    from api.routes.admin import FUSEAU_REVENUS
    from zoneinfo import ZoneInfo
    u = await _user(db, plan="free")
    maintenant = datetime.now(ZoneInfo(FUSEAU_REVENUS))
    debut_mois = maintenant.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    for d in (debut_mois - timedelta(days=2), debut_mois + timedelta(hours=1)):
        db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email=u.email,
                                 type="paiement_echoue", plan="expert", stripe_subscription_id="sub_r",
                                 montant_cents=1900, detail={"facture": "in_une"},
                                 created_at=d.astimezone(timezone.utc)))
    await db.commit()
    data = (await client.get("/admin/api/revenus?mois=3", headers=admin_headers)).json()
    assert sum(m["nb_echecs"] for m in data["mois"]) == 1
    assert data["totaux"]["echecs_cents"] == 1900
    assert sum(m["nb_tentatives_echouees"] for m in data["mois"]) == 2


async def test_parrain_pas_credite_sur_une_difference_au_prorata(db):
    from services import parrainage as P
    appels = []

    async def _lien(uid, db_):
        appels.append(uid)
        return None

    filleul = await _user(db, plan="standard")
    filleul.parraine_par_id = "parrain"
    orig = P._lien_du_filleul
    P._lien_du_filleul = _lien
    try:
        await P._sur_paiement(filleul, {"amount_paid": 461, "total": 461,
                                        "lines": {"data": [{"amount": 461, "proration": True}]}}, db)
        await P._sur_paiement(filleul, {"amount_paid": 300, "total": 1200, "lines": {"data": []}}, db)
        assert appels == []  # aucun des deux n'atteint la validation
        await P._sur_paiement(filleul, {"amount_paid": 700, "total": 700, "lines": {"data": []}}, db)
        assert appels == [filleul.user_id]
    finally:
        P._lien_du_filleul = orig
