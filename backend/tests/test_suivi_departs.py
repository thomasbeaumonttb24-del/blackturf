"""Suivi des départs : résiliations, impayés de fin d'essai, paiements abandonnés.

Demande de l'exploitant (2026-09-16) : la console ne disait pas QUI avait résilié,
QUI n'avait pas payé à la fin de son essai de 7 jours (compte repassé gratuit), ni
QUI s'était arrêté à l'écran de carte bancaire.

En le construisant, un défaut du webhook est apparu sur 3 comptes réels : le
`customer.subscription.updated` qui suit `/stripe/cancel` d'une seconde réécrivait
`cancel_at_period_end` en `active` et journalisait « Abonnement actif ». La
résiliation disparaissait donc de la base comme de l'écran.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import api.routes.stripe_routes as sr
from db.models import Subscription, SubscriptionEvent, User

pytestmark = pytest.mark.asyncio

MAINTENANT = datetime.now(timezone.utc)


def _sub_stripe(sub_id: str, status: str = "trialing", **extra) -> dict:
    now = int(time.time())
    return {
        "id": sub_id,
        "customer": "cus_depart",
        "status": status,
        "items": {"data": [{"id": "si", "price": {"id": "price_test_expert",
                                                 "recurring": {"interval": "month"}}}]},
        "trial_end": now + 5 * 86400,
        "current_period_start": now,
        "current_period_end": now + 5 * 86400,
        "default_payment_method": "pm_test",
        **extra,
    }


async def _compte(db, email: str, plan: str = "free", customer: str | None = None) -> User:
    u = User(user_id=str(uuid.uuid4()), email=email, plan=plan, stripe_customer_id=customer)
    db.add(u)
    await db.commit()
    return u


async def _abo(db, u: User, statut: str, stripe_id: str, plan: str = "expert",
               essai_fin=None) -> Subscription:
    s = Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id=stripe_id,
                     plan=plan, periodicite="monthly", statut=statut,
                     periode_debut=MAINTENANT - timedelta(days=10),
                     periode_fin=MAINTENANT + timedelta(days=20), essai_fin=essai_fin)
    db.add(s)
    await db.commit()
    return s


async def _evt(db, u: User, type_: str, stripe_id: str, il_y_a_h: float, **kw) -> None:
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email=u.email,
                             type=type_, plan="expert", stripe_subscription_id=stripe_id,
                             created_at=MAINTENANT - timedelta(hours=il_y_a_h), **kw))
    await db.commit()


async def _types_journal(db, email: str) -> list[str]:
    return [e.type for e in (await db.execute(
        select(SubscriptionEvent).where(SubscriptionEvent.email == email)
    )).scalars().all()]


@pytest.fixture
def stripe_muet(monkeypatch):
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_expert": "expert"})

    async def _pas_demail(**kw):
        return None

    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _pas_demail)


# ─────────────────────────────────────────────
# 1. Le webhook ne doit plus effacer une résiliation
# ─────────────────────────────────────────────
async def test_le_webhook_qui_suit_la_resiliation_ne_la_defait_pas(db, stripe_muet, monkeypatch):
    monkeypatch.setattr(sr.stripe.Subscription, "modify", lambda sid, **kw: None)
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test", raising=False)
    u = await _compte(db, "part@x.fr", plan="expert", customer="cus_depart")
    abo = await _abo(db, u, "active", "sub_part", essai_fin=MAINTENANT + timedelta(days=5))

    await sr.cancel_subscription(db, u)
    # Stripe renvoie l'abonnement, toujours `trialing`, avec le drapeau posé.
    await sr._handle_subscription_updated(
        _sub_stripe("sub_part", cancel_at_period_end=True), db)

    await db.refresh(abo)
    await db.refresh(u)
    assert abo.statut == "cancel_at_period_end"
    assert u.plan == "expert", "l'accès court jusqu'à la fin de l'essai"
    assert await _types_journal(db, "part@x.fr") == ["resiliation_demandee"]


async def test_un_double_clic_ne_journalise_quune_resiliation(db, stripe_muet, monkeypatch):
    appels: list[str] = []
    monkeypatch.setattr(sr.stripe.Subscription, "modify", lambda sid, **kw: appels.append(sid))
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test", raising=False)
    u = await _compte(db, "double@x.fr", plan="expert", customer="cus_depart")
    await _abo(db, u, "active", "sub_double")

    assert (await sr.cancel_subscription(db, u))["via_stripe"] is True
    assert (await sr.cancel_subscription(db, u))["via_stripe"] is True
    assert appels == ["sub_double"]
    assert await _types_journal(db, "double@x.fr") == ["resiliation_demandee"]


async def test_resiliation_faite_depuis_le_portail_stripe(db, stripe_muet):
    """Le portail récent pose `cancel_at` et non `cancel_at_period_end`."""
    u = await _compte(db, "portail@x.fr", plan="expert", customer="cus_depart")
    abo = await _abo(db, u, "active", "sub_portail")

    await sr._handle_subscription_updated(
        _sub_stripe("sub_portail", status="active", cancel_at=int(time.time()) + 86400), db)

    await db.refresh(abo)
    assert abo.statut == "cancel_at_period_end"
    assert await _types_journal(db, "portail@x.fr") == ["resiliation_demandee"]


async def test_resiliation_annulee_est_nommee(db, stripe_muet):
    u = await _compte(db, "reprise@x.fr", plan="expert", customer="cus_depart")
    abo = await _abo(db, u, "cancel_at_period_end", "sub_reprise")

    await sr._handle_subscription_updated(
        _sub_stripe("sub_reprise", status="active", cancel_at_period_end=False), db)

    await db.refresh(abo)
    assert abo.statut == "active"
    assert await _types_journal(db, "reprise@x.fr") == ["resiliation_annulee"]


# ─────────────────────────────────────────────
# 2. Le suivi admin range chaque compte dans UNE issue
# ─────────────────────────────────────────────
async def test_suivi_range_chaque_parcours(client: AsyncClient, admin_headers, db):
    # Essai fini, prélèvement refusé deux fois : compte repassé gratuit.
    impaye = await _compte(db, "impaye@x.fr")
    await _abo(db, impaye, "past_due", "sub_imp", essai_fin=MAINTENANT - timedelta(days=3))
    await _evt(db, impaye, "essai_ouvert", "sub_imp", 240)
    await _evt(db, impaye, "paiement_echoue", "sub_imp", 70, detail={"tentative": 1})
    await _evt(db, impaye, "paiement_echoue", "sub_imp", 20,
               detail={"tentative": 2, "prochaine_relance": int(time.time()) + 86400})

    # Résilié pendant l'essai, garde l'accès jusqu'à la fin.
    programme = await _compte(db, "programme@x.fr", plan="expert")
    await _abo(db, programme, "cancel_at_period_end", "sub_prog",
               essai_fin=MAINTENANT + timedelta(days=4))
    await _evt(db, programme, "essai_ouvert", "sub_prog", 50)
    await _evt(db, programme, "resiliation_demandee", "sub_prog", 49, pendant_essai=True)

    # Ligne écrite avant le correctif : `active` en base, la demande au journal.
    ancien = await _compte(db, "ancien-bug@x.fr", plan="expert")
    await _abo(db, ancien, "active", "sub_ancien", essai_fin=MAINTENANT + timedelta(days=6))
    await _evt(db, ancien, "essai_ouvert", "sub_ancien", 30)
    await _evt(db, ancien, "resiliation_demandee", "sub_ancien", 29, pendant_essai=True)
    await _evt(db, ancien, "abonnement_actif", "sub_ancien", 28.99)

    essai = await _compte(db, "essai@x.fr", plan="expert")
    await _abo(db, essai, "active", "sub_essai", essai_fin=MAINTENANT + timedelta(days=2))
    await _evt(db, essai, "essai_ouvert", "sub_essai", 120)

    paye = await _compte(db, "paye@x.fr", plan="expert")
    await _abo(db, paye, "active", "sub_paye")
    await _evt(db, paye, "essai_ouvert", "sub_paye", 400)
    await _evt(db, paye, "paiement_recu", "sub_paye", 230, montant_cents=1900)

    parti = await _compte(db, "parti-essai@x.fr")
    await _abo(db, parti, "canceled", "sub_parti", essai_fin=MAINTENANT - timedelta(days=1))
    await _evt(db, parti, "essai_ouvert", "sub_parti", 200)
    await _evt(db, parti, "resiliation_demandee", "sub_parti", 190, pendant_essai=True)
    await _evt(db, parti, "resilie", "sub_parti", 24)

    perdu = await _compte(db, "client-perdu@x.fr")
    await _abo(db, perdu, "canceled", "sub_perdu")
    await _evt(db, perdu, "paiement_recu", "sub_perdu", 900, montant_cents=1200)
    await _evt(db, perdu, "resilie", "sub_perdu", 10)

    # Relances Stripe épuisées : l'abonnement est clos, mais c'est un impayé.
    epuise = await _compte(db, "epuise@x.fr")
    await _abo(db, epuise, "canceled", "sub_epuise", essai_fin=MAINTENANT - timedelta(days=25))
    await _evt(db, epuise, "essai_ouvert", "sub_epuise", 32 * 24)
    await _evt(db, epuise, "paiement_echoue", "sub_epuise", 25 * 24)
    await _evt(db, epuise, "resilie", "sub_epuise", 2)

    await _compte(db, "abandon@x.fr", customer="cus_abandon")
    await _compte(db, "jamais-venu@x.fr")

    data = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    suivi = data["suivi"]
    issues = {c["email"]: c["issue"] for c in suivi["comptes"]}
    assert issues == {
        "impaye@x.fr": "impaye",
        "programme@x.fr": "resiliation_programmee",
        "ancien-bug@x.fr": "resiliation_programmee",
        "essai@x.fr": "en_essai",
        "paye@x.fr": "converti",
        "parti-essai@x.fr": "resilie_pendant_essai",
        "client-perdu@x.fr": "resilie_apres_paiement",
        "epuise@x.fr": "impaye",
    }
    par_email = {c["email"]: c for c in suivi["comptes"]}
    assert par_email["impaye@x.fr"]["echecs_paiement"] == 2
    assert par_email["impaye@x.fr"]["prochaine_relance"] is not None
    assert par_email["impaye@x.fr"]["plan_compte"] == "free"
    assert par_email["epuise@x.fr"]["relances_terminees"] is True
    assert par_email["programme@x.fr"]["resiliation_pendant_essai"] is True
    assert [a["email"] for a in suivi["checkouts_abandonnes"]] == ["abandon@x.fr"]

    r = suivi["resume"]
    assert (r["impaye"], r["resiliation_programmee"], r["en_essai"], r["converti"],
            r["resilie_pendant_essai"], r["resilie_apres_paiement"],
            r["checkouts_abandonnes"]) == (2, 2, 1, 1, 1, 1, 1)
    # Essais arrivés au bout : impayé, payé, parti pendant l'essai, épuisé → 1 sur 4.
    assert (r["essais_termines"], r["essais_convertis"]) == (4, 1)
    assert r["taux_conversion_essai"] == 25.0


async def test_un_impaye_regularise_redevient_converti(client: AsyncClient, admin_headers, db):
    u = await _compte(db, "regularise@x.fr", plan="expert")
    await _abo(db, u, "active", "sub_reg")
    await _evt(db, u, "essai_ouvert", "sub_reg", 300)
    await _evt(db, u, "paiement_echoue", "sub_reg", 150)
    await _evt(db, u, "paiement_recu", "sub_reg", 10, montant_cents=1900)

    ligne = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()["suivi"]["comptes"][0]
    assert (ligne["issue"], ligne["impaye_regularise"], ligne["echecs_paiement"]) == ("converti", True, 0)
