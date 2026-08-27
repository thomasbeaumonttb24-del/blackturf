"""Deux fuites d'argent fermées le 2026-08-27, sur un compte Stripe qui n'avait
encore jamais encaissé un centime.

1. **L'essai gratuit se rouvrait indéfiniment.** Le verrou portait sur le COMPTE
   (`users.essai_utilise_at`) : une nouvelle adresse e-mail et la même carte
   suffisaient à repartir pour 7 jours. Une carte prépayée vidée rend l'opération
   gratuite et indétectable — Stripe valide l'enregistrement du moyen de paiement
   sans jamais vérifier le solde, et l'échec n'arrive qu'à la fin de l'essai.
   Le verrou porte désormais sur l'empreinte Stripe de la carte.

2. **Un paiement en échec continuait de livrer le produit.** `past_due` figurait
   parmi les statuts qui donnent accès, et Stripe relance une carte jusqu'à trois
   semaines : trois semaines de produit livré, zéro euro encaissé. Pire,
   `_handle_payment_failed` cherchait l'abonnement dans `invoice.subscription`,
   champ SUPPRIMÉ de la version d'API du compte (2026-05-27.dahlia) — il ne
   trouvait donc jamais l'abonnement et ne coupait rien du tout.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import CarteConnue, Subscription, SubscriptionEvent, User
import api.routes.stripe_routes as sr


CARTE = {"id": "pm_test", "card": {"fingerprint": "fp_carte_1", "brand": "visa",
                                   "last4": "4242", "funding": "prepaid"}}


def _sub(status: str = "trialing", sub_id: str | None = None,
         trial_end: int | None = None, customer: str = "cus_test") -> dict:
    now = int(time.time())
    return {
        "id": sub_id or f"sub_{uuid.uuid4().hex[:12]}",
        "customer": customer,
        "status": status,
        "items": {"data": [{"id": "si_test",
                            "price": {"id": "price_test_standard",
                                      "unit_amount": 1200,
                                      "recurring": {"interval": "month"}}}]},
        "current_period_start": now,
        "current_period_end": now + 30 * 86400,
        "trial_end": trial_end,
        "default_payment_method": "pm_test",
    }


def _facture(sub_id: str | None, *, paye: int = 0, du: int = 1200,
             forme: str = "parent", customer: str = "cus_test") -> dict:
    """Facture Stripe. `forme` choisit OÙ est rangé l'identifiant d'abonnement."""
    invoice: dict = {
        "id": f"in_{uuid.uuid4().hex[:12]}",
        "customer": customer,
        "amount_due": du,
        "amount_paid": paye,
        "attempt_count": 1,
        "billing_reason": "subscription_cycle",
        "lines": {"data": [{}]},
    }
    if sub_id is None:
        return invoice
    if forme == "parent":       # API >= 2025 : le compte est dans cette forme
        invoice["parent"] = {"type": "subscription_details",
                             "subscription_details": {"subscription": sub_id}}
    elif forme == "plat":       # ancienne API
        invoice["subscription"] = sub_id
    elif forme == "ligne":      # dernier recours
        invoice["lines"] = {"data": [
            {"parent": {"subscription_item_details": {"subscription": sub_id}}}]}
    return invoice


def _periodes() -> dict:
    """Colonnes de période, non nulles en base."""
    debut = datetime.now(timezone.utc)
    return {"periode_debut": debut, "periode_fin": debut + timedelta(days=30)}


async def _user(db, email: str | None = None, plan: str = "free",
                customer: str = "cus_test") -> User:
    user = User(user_id=str(uuid.uuid4()),
                email=email or f"{uuid.uuid4().hex[:8]}@blackturf.fr",
                plan=plan, stripe_customer_id=customer)
    db.add(user)
    await db.commit()
    return user


def _stripe_muet(monkeypatch, cartes: list[dict] | None = None) -> dict:
    """Neutralise les appels réseau et capture ce qu'on demande à Stripe."""
    appels: dict = {"modify": [], "delete": []}

    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(sr.stripe.PaymentMethod, "list",
                        lambda **kw: {"data": list(cartes or [])})
    monkeypatch.setattr(sr, "_a_moyen_de_paiement", lambda sub: True)

    def _modify(sub_id, **kw):
        appels["modify"].append((sub_id, kw))
        return {"id": sub_id, "status": "active",
                "items": {"data": [{"price": {"id": "price_test_standard",
                                              "unit_amount": 1200,
                                              "recurring": {"interval": "month"}}}]}}

    def _delete(sub_id, **kw):
        appels["delete"].append(sub_id)
        return {"id": sub_id, "status": "canceled"}

    monkeypatch.setattr(sr.stripe.Subscription, "modify", _modify)
    monkeypatch.setattr(sr.stripe.Subscription, "delete", _delete)
    return appels


async def _types_journal(db, user: User) -> list[str]:
    return list((await db.execute(
        select(SubscriptionEvent.type).where(SubscriptionEvent.user_id == user.user_id)
    )).scalars().all())


# ─────────────────────────────────────────────
# 1. Une carte = un seul essai gratuit
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_carte_deja_vue_ailleurs_refuse_lessai_et_facture_tout_de_suite(db, monkeypatch):
    appels = _stripe_muet(monkeypatch, [CARTE])
    premier = await _user(db, email="premier@blackturf.fr", customer="cus_1")
    db.add(CarteConnue(empreinte="fp_carte_1", user_id=premier.user_id,
                       email=premier.email, marque="visa", dernier4="4242"))
    await db.commit()

    fraudeur = await _user(db, email="bis@blackturf.fr", customer="cus_2")
    sub = _sub(trial_end=int(time.time()) + 7 * 86400, customer="cus_2")
    await sr._handle_subscription_created(sub, db)

    # L'essai est coupé chez Stripe : facturation immédiate.
    assert appels["modify"] == [(sub["id"], {"trial_end": "now"})]

    await db.refresh(fraudeur)
    assert fraudeur.plan == "free", "aucun accès tant que le paiement n'a pas abouti"
    ligne = (await db.execute(select(Subscription).where(
        Subscription.stripe_subscription_id == sub["id"]))).scalar_one()
    assert ligne.statut == "incomplete"
    assert ligne.essai_fin is None, "un essai refusé ne doit pas figurer comme en cours"
    assert "essai_refuse_carte_reutilisee" in await _types_journal(db, fraudeur)

    connue = await db.get(CarteConnue, "fp_carte_1")
    assert connue.user_id == premier.user_id, "la carte reste au compte d'origine"
    assert connue.tentatives_autres_comptes == 1


@pytest.mark.asyncio
async def test_sa_propre_carte_ne_bloque_pas_son_propre_essai(db, monkeypatch):
    appels = _stripe_muet(monkeypatch, [CARTE])
    user = await _user(db)
    db.add(CarteConnue(empreinte="fp_carte_1", user_id=user.user_id, email=user.email))
    await db.commit()

    sub = _sub(trial_end=int(time.time()) + 7 * 86400)
    await sr._handle_subscription_created(sub, db)

    assert appels["modify"] == []
    await db.refresh(user)
    assert user.plan == "standard"
    assert user.essai_utilise_at is not None


@pytest.mark.asyncio
async def test_carte_inconnue_est_memorisee_pour_la_prochaine_fois(db, monkeypatch):
    _stripe_muet(monkeypatch, [CARTE])
    user = await _user(db)

    await sr._handle_subscription_created(_sub(trial_end=int(time.time()) + 7 * 86400), db)

    connue = await db.get(CarteConnue, "fp_carte_1")
    assert connue is not None and connue.user_id == user.user_id
    assert connue.financement == "prepaid" and connue.dernier4 == "4242"


@pytest.mark.asyncio
async def test_politique_blocage_annule_labonnement_du_second_compte(db, monkeypatch):
    appels = _stripe_muet(monkeypatch, [CARTE])
    monkeypatch.setattr(sr.settings, "carte_reutilisee_politique", "blocage")
    premier = await _user(db, email="proprio@blackturf.fr", customer="cus_1")
    db.add(CarteConnue(empreinte="fp_carte_1", user_id=premier.user_id, email=premier.email))
    await db.commit()

    second = await _user(db, email="second@blackturf.fr", customer="cus_2")
    sub = _sub(trial_end=int(time.time()) + 7 * 86400, customer="cus_2")
    await sr._handle_subscription_created(sub, db)

    assert appels["delete"] == [sub["id"]]
    await db.refresh(second)
    assert second.plan == "free"
    assert (await db.execute(select(Subscription).where(
        Subscription.stripe_subscription_id == sub["id"]))).scalar_one_or_none() is None
    assert "carte_refusee_autre_compte" in await _types_journal(db, second)


@pytest.mark.asyncio
async def test_politique_ignorer_retablit_lancien_comportement(db, monkeypatch):
    appels = _stripe_muet(monkeypatch, [CARTE])
    monkeypatch.setattr(sr.settings, "carte_reutilisee_politique", "ignorer")
    premier = await _user(db, email="proprio2@blackturf.fr", customer="cus_1")
    db.add(CarteConnue(empreinte="fp_carte_1", user_id=premier.user_id, email=premier.email))
    await db.commit()

    second = await _user(db, email="second2@blackturf.fr", customer="cus_2")
    await sr._handle_subscription_created(
        _sub(trial_end=int(time.time()) + 7 * 86400, customer="cus_2"), db)

    assert appels["modify"] == [] and appels["delete"] == []
    await db.refresh(second)
    assert second.plan == "standard"


# ─────────────────────────────────────────────
# 2. Impayé : accès coupé, puis rendu au paiement
# ─────────────────────────────────────────────
def test_identifiant_dabonnement_lu_dans_les_trois_formes_de_facture():
    for forme in ("parent", "plat", "ligne"):
        assert sr._sub_id_facture(_facture("sub_x", forme=forme)) == "sub_x", forme
    assert sr._sub_id_facture(_facture(None)) is None


@pytest.mark.asyncio
async def test_paiement_echoue_coupe_lacces_et_retrograde_en_free(db, monkeypatch):
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="standard")
    abo = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                       stripe_subscription_id="sub_impaye", plan="standard",
                       periodicite="monthly", **_periodes(), statut="active")
    db.add(abo)
    await db.commit()

    await sr._handle_payment_failed(_facture("sub_impaye", paye=0), db)

    await db.refresh(user)
    await db.refresh(abo)
    assert abo.statut == "past_due"
    assert user.plan == "free", "past_due ne donne plus accès au produit"
    assert "paiement_echoue" in await _types_journal(db, user)


@pytest.mark.asyncio
async def test_le_journal_dit_letat_constate_et_non_une_comparaison(db, monkeypatch):
    """Regression du 2026-08-27, premier impaye reel.

    `customer.subscription.updated` arrive 4 s AVANT `invoice.payment_failed` et a
    deja retrograde le compte : la comparaison avant/apres ne voyait plus aucun
    changement et le journal annoncait << acces coupe : non >> alors que l'acces
    etait coupe. Le detail doit porter l'ETAT CONSTATE.
    """
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="free")   # deja retrograde par l'autre webhook
    abo = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                       stripe_subscription_id="sub_deja_past_due", plan="expert",
                       periodicite="monthly", **_periodes(), statut="past_due")
    db.add(abo)
    await db.commit()

    await sr._handle_payment_failed(_facture("sub_deja_past_due"), db)

    evt = (await db.execute(select(SubscriptionEvent).where(
        SubscriptionEvent.user_id == user.user_id,
        SubscriptionEvent.type == "paiement_echoue"))).scalar_one()
    assert evt.detail["acces_ouvert"] is False
    assert evt.detail["plan_apres"] == "free"


@pytest.mark.asyncio
async def test_paiement_encaisse_retablit_lacces(db, monkeypatch):
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="free")
    abo = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                       stripe_subscription_id="sub_repris", plan="expert",
                       periodicite="monthly", **_periodes(), statut="past_due")
    db.add(abo)
    await db.commit()

    await sr._handle_payment_succeeded(_facture("sub_repris", paye=1900), db)

    await db.refresh(user)
    await db.refresh(abo)
    assert abo.statut == "active"
    assert user.plan == "expert"
    assert "paiement_recu" in await _types_journal(db, user)


@pytest.mark.asyncio
async def test_fin_dessai_facturee_est_journalisee_meme_sans_changement_de_statut(db, monkeypatch):
    """Le tout premier euro encaisse doit laisser une trace.

    L'abonnement est deja `active` pendant l'essai : la bascule essai -> paye ne
    change AUCUN statut. Sans journalisation inconditionnelle, le premier
    paiement reel passait sans un mot, ni journal admin ni e-mail.
    """
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="expert")
    abo = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                       stripe_subscription_id="sub_essai_fini", plan="expert",
                       periodicite="monthly", **_periodes(), statut="active",
                       essai_fin=datetime.now(timezone.utc))
    db.add(abo)
    await db.commit()

    await sr._handle_payment_succeeded(_facture("sub_essai_fini", paye=1900), db)

    await db.refresh(user)
    await db.refresh(abo)
    assert user.plan == "expert"
    assert abo.essai_fin is None, "un essai facture n'est plus un essai en cours"
    assert "paiement_recu" in await _types_journal(db, user)


@pytest.mark.asyncio
async def test_facture_a_zero_euro_nouvre_aucun_acces(db, monkeypatch):
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="free")
    abo = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                       stripe_subscription_id="sub_essai", plan="expert",
                       periodicite="monthly", **_periodes(), statut="incomplete")
    db.add(abo)
    await db.commit()

    # C'est la facture d'OUVERTURE d'essai : 0 € encaissé, rien n'est prouvé.
    await sr._handle_payment_succeeded(_facture("sub_essai", paye=0, du=0), db)

    await db.refresh(user)
    await db.refresh(abo)
    assert abo.statut == "incomplete"
    assert user.plan == "free"


@pytest.mark.asyncio
async def test_un_impaye_ne_retrograde_pas_un_compte_qui_a_un_autre_abonnement(db, monkeypatch):
    _stripe_muet(monkeypatch)
    user = await _user(db, plan="expert")
    db.add_all([
        Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                     stripe_subscription_id="sub_ko", plan="standard",
                     periodicite="monthly", **_periodes(), statut="active"),
        Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                     stripe_subscription_id="sub_ok", plan="expert",
                     periodicite="monthly", **_periodes(), statut="active"),
    ])
    await db.commit()

    await sr._handle_payment_failed(_facture("sub_ko"), db)

    await db.refresh(user)
    assert user.plan == "expert"
