"""Relances d'un prélèvement refusé : J+3, J+7, puis compte perdu (2026-09-16).

Stripe relançait selon son propre calendrier — 8 refus en 13 jours sur un compte
réel. L'exploitant : « ça donne l'impression que c'est un site arnaque ».
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import stripe
from sqlalchemy import select, update

import api.routes.stripe_routes as sr
import services.relances_paiement as rp
from db.models import Subscription, SubscriptionEvent, User

pytestmark = pytest.mark.asyncio

MAINTENANT = datetime.now(timezone.utc)


class FauxStripe:
    """Une facture ouverte et ce qu'on en fait."""

    def __init__(self, tentatives: int, paiement_passe: bool = False,
                 erreur_pay: Exception | None = None):
        self.facture = {"id": "in_test", "status": "open", "attempt_count": tentatives,
                        "auto_advance": True, "amount_due": 1900, "created": 0}
        self.paiement_passe = paiement_passe
        self.erreur_pay = erreur_pay
        self.appels: list[str] = []

    def installer(self, monkeypatch):
        f = self

        def retrieve(fid):
            return dict(f.facture)

        def pay(fid):
            f.appels.append("pay")
            # Comme le vrai Stripe : un `pay` lancé par l'API n'incrémente PAS
            # `attempt_count` (seules ses relances automatiques le font).
            if f.erreur_pay is not None:
                raise f.erreur_pay
            if f.paiement_passe:
                f.facture["status"] = "paid"
                return dict(f.facture)
            raise stripe.error.CardError("Votre carte a été refusée.", None, "card_declined")

        def modify(fid, **kw):
            f.appels.append(f"modify:{kw}")
            f.facture.update(kw)

        def void_invoice(fid):
            f.appels.append("void")
            f.facture["status"] = "void"

        def delete(sid):
            f.appels.append(f"delete:{sid}")

        monkeypatch.setattr(stripe, "api_key", "sk_test")
        # Le garde-fou anti-réseau de `couper_collecte_stripe` est levé : Stripe est simulé.
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(stripe.Invoice, "retrieve", retrieve)
        monkeypatch.setattr(stripe.Invoice, "pay", pay)
        monkeypatch.setattr(stripe.Invoice, "modify", modify)
        monkeypatch.setattr(stripe.Invoice, "void_invoice", void_invoice)
        monkeypatch.setattr(stripe.Subscription, "delete", delete)
        # État live de l'abonnement et factures ouvertes, relus chez Stripe.
        f.statut_live = "past_due"
        f.resilie = False
        monkeypatch.setattr(stripe.Subscription, "retrieve",
                            lambda sid: {"status": f.statut_live, "cancel_at_period_end": f.resilie})
        monkeypatch.setattr(stripe.Invoice, "list",
                            lambda **kw: {"data": [dict(f.facture)] if f.facture.get("status") == "open"
                                          and kw.get("status") == "open" else []})
        return self


@pytest.fixture(autouse=True)
def sans_email(monkeypatch):
    async def _rien(**kw):
        return None

    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _rien)


async def _impaye(db, premier_refus_il_y_a_j: float,
                  stripe_sub_id: str = "sub_impaye") -> tuple[User, Subscription]:
    u = User(user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:6]}@x.fr", plan="free",
             stripe_customer_id=f"cus_{stripe_sub_id}")
    s = Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id=stripe_sub_id,
                     plan="expert", periodicite="monthly", statut="past_due",
                     periode_debut=MAINTENANT, periode_fin=MAINTENANT + timedelta(days=30))
    db.add_all([u, s])
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email=u.email,
                             type="paiement_echoue", stripe_subscription_id=stripe_sub_id,
                             detail={"facture": "in_test", "tentative": 1},
                             created_at=MAINTENANT - timedelta(days=premier_refus_il_y_a_j)))
    await db.commit()
    return u, s


async def _journal(db, u: User) -> list[str]:
    return [e.type for e in (await db.execute(
        select(SubscriptionEvent).where(SubscriptionEvent.user_id == u.user_id)
        .order_by(SubscriptionEvent.created_at)
    )).scalars().all()]


async def test_calendrier_deux_relances_puis_plus_rien():
    t0 = MAINTENANT
    assert rp.prochaine_relance(t0, 1) == t0 + timedelta(days=3)
    assert rp.prochaine_relance(t0, 2) == t0 + timedelta(days=7)
    assert rp.prochaine_relance(t0, 3) is None
    # Rattrapage : relance 1 faite en retard à J+8 → relance 2 pas avant J+12.
    assert rp.prochaine_relance(t0, 2, t0 + timedelta(days=8)) == t0 + timedelta(days=12)


async def test_rien_avant_j3(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    await _impaye(db, premier_refus_il_y_a_j=2)

    bilan = await rp.traiter_impayes(db)

    assert "pay" not in stripe_.appels
    assert bilan["attente"] == 1
    assert "modify:{'auto_advance': False}" in stripe_.appels, "Stripe ne doit pas relancer seul"


async def test_premiere_relance_a_j3_sans_cloturer(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=3.1)

    await rp.traiter_impayes(db)
    await rp.traiter_impayes(db)  # la tâche repasse une heure plus tard : pas de 2e prélèvement

    assert stripe_.appels.count("pay") == 1
    await db.refresh(s)
    assert s.statut == "past_due"
    assert (await _journal(db, u))[-1] == "relance_paiement"


async def test_seconde_relance_refusee_a_j7_clot_le_compte(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=2).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=7.2)

    bilan = await rp.traiter_impayes(db)

    assert bilan["clos"] == 1
    assert stripe_.appels.count("pay") == 1
    assert "void" in stripe_.appels and "delete:sub_impaye" in stripe_.appels
    await db.refresh(s)
    await db.refresh(u)
    assert (s.statut, u.plan) == ("canceled", "free")
    assert (await _journal(db, u))[-1] == "impaye_perdu"

    # Stripe clôt l'abonnement AVANT d'annuler la facture (l'inverse le rendait `active`).
    assert stripe_.appels.index("delete:sub_impaye") < stripe_.appels.index("void")

    # Un `updated` arrivé en retard ne rouvre rien.
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_x": "expert"})
    await sr._handle_subscription_updated({
        "id": "sub_impaye", "customer": "cus_impaye", "status": "active",
        "items": {"data": [{"price": {"id": "price_x", "recurring": {"interval": "month"}}}]},
    }, db)
    await db.refresh(s)
    await db.refresh(u)
    assert (s.statut, u.plan) == ("canceled", "free")
    assert "abonnement_actif" not in await _journal(db, u)

    # Le webhook de Stripe qui confirme la suppression n'ajoute pas de « résiliation ».
    await sr._handle_subscription_deleted({"id": "sub_impaye", "customer": "cus_impaye"}, db)
    assert "resilie" not in await _journal(db, u)

    # Et plus jamais de relance.
    await rp.traiter_impayes(db)
    assert stripe_.appels.count("pay") == 1


async def test_ancien_impaye_deja_trop_relance_est_clos_sans_nouveau_prelevement(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=8).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=13)

    await rp.traiter_impayes(db)

    assert "pay" not in stripe_.appels
    await db.refresh(s)
    assert s.statut == "canceled"


async def test_relance_qui_passe_ne_clot_rien(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=2, paiement_passe=True).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=8)

    bilan = await rp.traiter_impayes(db)

    assert bilan["payes"] == 1 and bilan["clos"] == 0
    assert "delete:sub_impaye" not in stripe_.appels


async def test_le_webhook_du_premier_refus_coupe_les_relances_stripe(db, monkeypatch):
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    u = User(user_id=str(uuid.uuid4()), email="refus@x.fr", plan="expert", stripe_customer_id="cus_refus")
    db.add(u)
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id="sub_refus",
                        plan="expert", periodicite="monthly", statut="active",
                        periode_debut=MAINTENANT, periode_fin=MAINTENANT + timedelta(days=30)))
    await db.commit()

    avant_webhook = datetime.now(timezone.utc)
    await sr._handle_payment_failed({
        "id": "in_test", "customer": "cus_refus", "subscription": "sub_refus",
        "attempt_count": 1, "auto_advance": True, "amount_due": 1900,
    }, db)

    assert "modify:{'auto_advance': False}" in stripe_.appels
    evt = (await db.execute(select(SubscriptionEvent).where(
        SubscriptionEvent.type == "paiement_echoue"))).scalar_one()
    relance = datetime.fromtimestamp(evt.detail["prochaine_relance"], tz=timezone.utc)
    assert abs((relance - avant_webhook) - timedelta(days=3)) < timedelta(minutes=5)


async def _relance_journalisee(db, u: User, s: Subscription, il_y_a_h: float) -> None:
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email=u.email,
                             type="relance_paiement", stripe_subscription_id=s.stripe_subscription_id,
                             detail={"facture": "in_test", "numero": 1, "resultat": "open"},
                             created_at=MAINTENANT - timedelta(hours=il_y_a_h)))
    await db.commit()


async def test_relances_comptees_au_journal_pas_par_attempt_count(db, monkeypatch):
    """Cas réel du 21-22/09 : Stripe laisse `attempt_count` à 1 après un `pay` manuel,
    la relance J+3 repartait chaque heure (10 refus sur une carte). Deux relances
    au journal suffisent à clore, sans nouveau prélèvement."""
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=11)
    await _relance_journalisee(db, u, s, il_y_a_h=26)
    await _relance_journalisee(db, u, s, il_y_a_h=25)

    bilan = await rp.traiter_impayes(db)

    assert "pay" not in stripe_.appels
    assert bilan["clos"] == 1
    await db.refresh(s)
    assert s.statut == "canceled"


async def test_facture_non_prelevable_comptee_comme_tentative(db, monkeypatch):
    """PaymentIntent annulé par Stripe (22/09 15:35) : `pay` lève une erreur non
    bancaire. La tentative est journalisée, et ne repart pas à l'heure suivante."""
    erreur = stripe.error.InvalidRequestError("PaymentIntent annulé.", None,
                                              code="payment_intent_unexpected_state")
    stripe_ = FauxStripe(tentatives=1, erreur_pay=erreur).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=3.1)

    bilan = await rp.traiter_impayes(db)
    await rp.traiter_impayes(db)

    assert bilan["erreurs"] == 0
    assert stripe_.appels.count("pay") == 1
    relance = (await db.execute(select(SubscriptionEvent).where(
        SubscriptionEvent.type == "relance_paiement"))).scalar_one()
    assert relance.detail["erreur"] == "payment_intent_unexpected_state"


async def test_une_erreur_n_arrete_pas_la_boucle(db, monkeypatch):
    """Du 22/09 au 29/09 : l'erreur d'un impayé faisait `rollback`, le `log` relisait
    `sub.stripe_subscription_id` expiré → MissingGreenlet sorti de la boucle, et les
    autres impayés n'étaient plus jamais traités."""
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    u1, s1 = await _impaye(db, premier_refus_il_y_a_j=3.1, stripe_sub_id="sub_casse")
    u2, s2 = await _impaye(db, premier_refus_il_y_a_j=3.1, stripe_sub_id="sub_sain")
    await db.execute(update(SubscriptionEvent)
                     .where(SubscriptionEvent.stripe_subscription_id == "sub_casse")
                     .values(detail={"facture": "in_casse", "tentative": 1}))
    await db.commit()

    retrieve_sain = stripe.Invoice.retrieve

    def retrieve(fid):
        if fid == "in_casse":
            raise RuntimeError("panne réseau")
        return retrieve_sain(fid)

    monkeypatch.setattr(stripe.Invoice, "retrieve", retrieve)
    liste_saine = stripe.Invoice.list
    monkeypatch.setattr(stripe.Invoice, "list", lambda **kw: (
        {"data": [{"id": "in_casse", "status": "open"}]} if kw.get("subscription") == "sub_casse"
        else liste_saine(**kw)))

    bilan = await rp.traiter_impayes(db)

    assert bilan["erreurs"] == 1
    assert bilan["relances"] == 1 and stripe_.appels.count("pay") == 1
    assert (await _journal(db, u2))[-1] == "relance_paiement"


async def test_impaye_decouvert_apres_j7_pas_deux_prelevements_dans_l_heure(db, monkeypatch):
    """Cas de sub_1UIPDFF… (1er refus le 22/09, jamais relancé avant le 29/09) :
    la relance 1 part, la relance 2 attend quatre jours au lieu d'une heure."""
    stripe_ = FauxStripe(tentatives=1).installer(monkeypatch)
    u, s = await _impaye(db, premier_refus_il_y_a_j=7.3)

    await rp.traiter_impayes(db)
    bilan = await rp.traiter_impayes(db, maintenant=MAINTENANT + timedelta(hours=1))

    assert stripe_.appels.count("pay") == 1
    assert bilan["attente"] == 1
    await db.refresh(s)
    assert s.statut == "past_due"
