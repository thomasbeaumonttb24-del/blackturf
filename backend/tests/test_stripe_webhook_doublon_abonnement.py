"""Webhooks concurrents sur un même abonnement Stripe : jamais de doublon, jamais de 500.

Erreurs « API » du panneau admin (POST /api/v1/stripe/webhook) :
  · `IntegrityError … subscriptions_stripe_subscription_id_key` (2 fois, octobre) ;
  · `PendingRollbackError … Original exception: IntegrityError` (septembre).

Cause : au checkout, Stripe livre `customer.subscription.created` et
`customer.subscription.updated` (identifiants d'événement DIFFÉRENTS, donc
l'anti-rejeu `stripe_events` les laisse passer tous les deux) dans la même
seconde. `_handle_subscription_updated` ne trouvant pas la ligne délègue à
`_handle_subscription_created` : les deux webhooks lisaient « abonnement
inconnu », puis insèrent chacun la même ligne. Le second lève à son flush :
  · directement (`IntegrityError`) quand l'autoflush part d'une requête
    (`_avec_offert`, abonnement actif) ;
  · en `PendingRollbackError` quand le flush part du point de sauvegarde de
    `journaliser` (abonnement non actif) : l'erreur y était AVALÉE, la session
    restait empoisonnée et le `commit` final levait.
Le webhook répondait 500, Stripe relivrait.

La course est rejouée de façon déterministe : l'autre webhook écrit sa ligne
(dans sa propre session, validée) entre la lecture « abonnement inconnu » et
l'insertion — exactement là où `_controler_carte` interroge Stripe.
"""
import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import api.routes.stripe_routes as sr
from db.models import Subscription, SubscriptionEvent, User
from services import abonnements

SECRET = "whsec_test_doublon"
SUB_ID = "sub_1UPAVJFiAG0jVlcjyneTX91s"


def _sub(status: str = "active", *, cancel_at_period_end: bool = False) -> dict:
    now = int(time.time())
    return {
        "id": SUB_ID,
        "object": "subscription",
        "customer": "cus_doublon",
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {"data": [{"id": "si_1",
                            "price": {"id": "price_test_standard", "unit_amount": 1200,
                                      "recurring": {"interval": "month"}}}]},
        "current_period_start": now,
        "current_period_end": now + 30 * 86400,
        "trial_end": None,
        "default_payment_method": "pm_test",
    }


@pytest.fixture
def stripe_hors_ligne(monkeypatch):
    """Aucun appel réseau : Stripe « injoignable », plan connu, carte présente."""
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    monkeypatch.setattr(sr, "_stripe_joignable", lambda: False)
    monkeypatch.setattr(sr, "_a_moyen_de_paiement", lambda sub: True)
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [])
    monkeypatch.setattr(sr.settings, "stripe_webhook_secret", SECRET)
    # Pas d'e-mail de supervision pendant les tests.
    monkeypatch.setattr(abonnements, "_notifier_admin", _rien)


async def _rien(*a, **kw):
    return None


async def _user(db) -> User:
    user = User(user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@blackturf.fr",
                plan="free", stripe_customer_id="cus_doublon")
    db.add(user)
    await db.commit()
    return user


def _course_concurrente(monkeypatch, engine, user_id: str, statut: str = "active"):
    """L'autre webhook insère SA ligne pendant que celui-ci interroge Stripe."""
    vrai = sr._controler_carte
    fait = {"n": 0}

    async def _controler(user, sub, db):
        if not fait["n"]:
            fait["n"] += 1
            async with async_sessionmaker(engine, expire_on_commit=False)() as autre:
                autre.add(Subscription(
                    sub_id=str(uuid.uuid4()), user_id=user_id,
                    stripe_subscription_id=sub["id"], plan="standard",
                    periodicite="monthly", statut=statut,
                    periode_debut=sr._ts(sub, "current_period_start"),
                    periode_fin=sr._ts(sub, "current_period_end"),
                ))
                await autre.commit()
        return await vrai(user, sub, db)

    monkeypatch.setattr(sr, "_controler_carte", _controler)
    return fait


async def _lignes(db) -> list[Subscription]:
    return list((await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == SUB_ID)
        .execution_options(populate_existing=True)
    )).scalars().all())


# ─────────────────────────────────────────────
# 1. La course, rejouée sur le gestionnaire
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_course_abonnement_actif_ni_integrity_error_ni_doublon(engine, db, stripe_hors_ligne, monkeypatch):
    """Chemin de l'`IntegrityError` : abonnement actif, autoflush dans `_avec_offert`."""
    user = await _user(db)
    course = _course_concurrente(monkeypatch, engine, user.user_id)

    await sr._handle_subscription_created(_sub("active"), db)

    assert course["n"] == 1, "la course doit avoir été rejouée"
    lignes = await _lignes(db)
    assert len(lignes) == 1
    assert lignes[0].statut == "active"
    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_course_abonnement_non_actif_ni_pending_rollback_ni_doublon(engine, db, stripe_hors_ligne, monkeypatch):
    """Chemin de la `PendingRollbackError` : statut non actif, premier flush dans
    le point de sauvegarde de `journaliser` (qui avalait l'erreur)."""
    user = await _user(db)
    _course_concurrente(monkeypatch, engine, user.user_id, statut="incomplete")
    # Essai ouvert sans carte : aucun accès, donc pas d'autoflush par `_avec_offert` ;
    # le premier flush est celui du point de sauvegarde de `journaliser`.
    monkeypatch.setattr(sr, "_a_moyen_de_paiement", lambda sub: False)
    sub = _sub("trialing")
    sub["trial_end"] = int(time.time()) + 7 * 86400

    await sr._handle_subscription_created(sub, db)

    # La session reste utilisable (aucune transaction empoisonnée).
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() >= 1
    lignes = await _lignes(db)
    assert len(lignes) == 1
    # L'état de l'événement perdant n'est PAS perdu : il est appliqué à la ligne gagnante.
    assert lignes[0].statut == sr.STATUT_SANS_CARTE
    assert lignes[0].essai_fin is not None


@pytest.mark.asyncio
async def test_journaliser_ne_masque_pas_une_erreur_de_l_appelant(db, stripe_hors_ligne):
    """Un flush en échec dû aux écritures de l'APPELANT ne doit pas être avalé par
    `journaliser` : sinon la session reste empoisonnée et le `commit` suivant lève
    `PendingRollbackError`, qui masque la vraie cause."""
    from sqlalchemy.exc import IntegrityError

    user = await _user(db)
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                        stripe_subscription_id=SUB_ID, plan="standard",
                        periodicite="monthly", statut="active",
                        periode_debut=sr._ts(_sub(), "current_period_start"),
                        periode_fin=sr._ts(_sub(), "current_period_end")))
    await db.commit()
    doublon = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                           stripe_subscription_id=SUB_ID, plan="standard",
                           periodicite="monthly", statut="active",
                           periode_debut=sr._ts(_sub(), "current_period_start"),
                           periode_fin=sr._ts(_sub(), "current_period_end"))
    db.add(doublon)
    with pytest.raises(IntegrityError):
        await abonnements.journaliser(db, "abonnement_actif", user, doublon)
    await db.rollback()
    assert len(await _lignes(db)) == 1


# ─────────────────────────────────────────────
# 2. Par la vraie route signée
# ─────────────────────────────────────────────
def _signe(evenement: dict) -> tuple[bytes, dict]:
    corps = json.dumps(evenement).encode()
    t = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    return corps, {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def _evenement(type_: str, objet: dict, eid: str | None = None) -> dict:
    return {"id": eid or f"evt_{uuid.uuid4().hex[:10]}", "object": "event", "type": type_,
            "data": {"object": objet}}


@pytest.mark.asyncio
async def test_meme_evenement_rejoue_deux_fois(client, db, stripe_hors_ligne):
    user = await _user(db)
    evt = _evenement("customer.subscription.created", _sub("active"), eid="evt_rejeu")
    for _ in range(2):
        corps, entetes = _signe(evt)
        r = await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)
        assert r.status_code == 200, r.text
    assert len(await _lignes(db)) == 1
    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_created_puis_updated_meme_abonnement_etat_final(client, db, stripe_hors_ligne):
    """Deux événements différents : une seule ligne, l'état du second appliqué."""
    user = await _user(db)
    for evt in (_evenement("customer.subscription.created", _sub("active")),
                _evenement("customer.subscription.updated", _sub("active", cancel_at_period_end=True))):
        corps, entetes = _signe(evt)
        r = await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)
        assert r.status_code == 200, r.text
    lignes = await _lignes(db)
    assert len(lignes) == 1 and lignes[0].statut == "cancel_at_period_end"
    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_updated_en_course_avec_created_par_la_route(client, engine, db, stripe_hors_ligne, monkeypatch):
    """`updated` arrive le premier (Stripe ne garantit pas l'ordre), délègue à la
    création, et un `created` concurrent écrit la ligne pendant ce temps : 200,
    une seule ligne, et la résiliation programmée portée par `updated` appliquée."""
    user = await _user(db)
    course = _course_concurrente(monkeypatch, engine, user.user_id)
    corps, entetes = _signe(_evenement("customer.subscription.updated",
                                       _sub("active", cancel_at_period_end=True)))
    r = await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)
    assert r.status_code == 200, r.text
    assert course["n"] == 1

    lignes = await _lignes(db)
    assert len(lignes) == 1 and lignes[0].statut == "cancel_at_period_end"
    await db.refresh(user)
    assert user.plan == "standard"
    types = (await db.execute(select(SubscriptionEvent.type)
                              .where(SubscriptionEvent.user_id == user.user_id))).scalars().all()
    assert "resiliation_demandee" in types
