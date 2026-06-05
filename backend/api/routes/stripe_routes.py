"""
Stripe routes — BlackTurf.
Checkout, webhooks, portail client.
"""
import structlog
import stripe
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.config import get_settings
from api.routes.auth import get_current_user
from db.database import get_db
from db.models import User, Subscription

settings = get_settings()
log = structlog.get_logger()
router = APIRouter()

stripe.api_key = settings.stripe_secret_key

PRICE_MAP = {
    # v3 names (standard/expert) + backwards compat (starter/pro)
    "standard_monthly": settings.stripe_price_starter_monthly,
    "standard_annual":  settings.stripe_price_starter_annual,
    "expert_monthly":   settings.stripe_price_pro_monthly,
    "expert_annual":    settings.stripe_price_pro_annual,
    # backwards compat
    "starter_monthly": settings.stripe_price_starter_monthly,
    "starter_annual":  settings.stripe_price_starter_annual,
    "pro_monthly":     settings.stripe_price_pro_monthly,
    "pro_annual":      settings.stripe_price_pro_annual,
}

# Normalize plan names from Stripe price_id
PLAN_FROM_PRICE = {
    settings.stripe_price_starter_monthly: "standard",
    settings.stripe_price_starter_annual:  "standard",
    settings.stripe_price_pro_monthly:     "expert",
    settings.stripe_price_pro_annual:      "expert",
}

def _normalize_plan(plan: str) -> str:
    return {"starter": "standard", "pro": "expert"}.get(plan, plan)


class CheckoutRequest(BaseModel):
    plan: str         # standard / expert (ou starter / pro compat)
    periodicite: str  # monthly / annual


@router.post("/stripe/checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Crée une session Stripe Checkout et retourne l'URL de paiement."""
    price_key = f"{body.plan}_{body.periodicite}"
    price_id = PRICE_MAP.get(price_key)
    if not price_id:
        raise HTTPException(status_code=400, detail="Plan invalide")

    # Récupérer ou créer le customer Stripe
    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=f"{user.prenom or ''} {user.nom or ''}".strip() or user.email,
            metadata={"user_id": user.user_id},
        )
        customer_id = customer.id
        user.stripe_customer_id = customer_id
        await db.commit()

    # Créer la session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/abonnement/succes?session_id={{CHECKOUT_SESSION_ID}}&plan={_normalize_plan(body.plan)}",
        cancel_url=f"{settings.frontend_url}/tarifs",
        subscription_data={
            "trial_period_days": 7,
            "metadata": {"user_id": user.user_id, "plan": _normalize_plan(body.plan)},
        },
        allow_promotion_codes=True,
        locale="fr",
    )

    log.info("stripe.checkout_created", user_id=user.user_id, plan=body.plan)
    return {"url": session.url}


@router.post("/stripe/portal")
async def customer_portal(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accès au portail client Stripe (gérer/annuler abonnement)."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Aucun abonnement Stripe")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/profil",
    )
    return {"url": session.url}


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Traite les événements Stripe (subscription lifecycle)."""
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        log.warning("stripe.webhook.invalid_signature")
        raise HTTPException(status_code=400, detail="Signature invalide")

    event_type = event["type"]
    data = event["data"]["object"]

    log.info("stripe.webhook", event_type=event_type)

    if event_type == "customer.subscription.created":
        await _handle_subscription_created(data, db)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data, db)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        await _handle_subscription_deleted(data, db)
    elif event_type in ("invoice.payment_succeeded",):
        await _handle_payment_succeeded(data, db)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data, db)

    return {"ok": True}


async def _find_user_by_customer(customer_id: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    return result.scalar_one_or_none()


async def _handle_subscription_created(sub: dict, db: AsyncSession):
    user = await _find_user_by_customer(sub["customer"], db)
    if not user:
        log.warning("stripe.webhook.user_not_found", customer=sub["customer"])
        return

    price_id = sub["items"]["data"][0]["price"]["id"]
    plan = PLAN_FROM_PRICE.get(price_id, "standard")
    periodicite = "annual" if "annual" in price_id else "monthly"

    import uuid
    subscription = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=sub["id"],
        plan=plan,
        periodicite=periodicite,
        statut="active" if sub["status"] in ("active", "trialing") else sub["status"],
        periode_debut=datetime.fromtimestamp(sub["current_period_start"], tz=timezone.utc),
        periode_fin=datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc),
        essai_fin=datetime.fromtimestamp(sub["trial_end"], tz=timezone.utc) if sub.get("trial_end") else None,
    )
    db.add(subscription)

    user.plan = plan
    await db.commit()
    log.info("stripe.subscription_created", user_id=user.user_id, plan=plan)


async def _handle_subscription_updated(sub: dict, db: AsyncSession):
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await _handle_subscription_created(sub, db)
        return

    price_id = sub["items"]["data"][0]["price"]["id"]
    plan = PLAN_FROM_PRICE.get(price_id, "standard")

    subscription.plan = plan
    subscription.statut = "active" if sub["status"] in ("active", "trialing") else sub["status"]
    subscription.periode_debut = datetime.fromtimestamp(sub["current_period_start"], tz=timezone.utc)
    subscription.periode_fin = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc)

    user = await _find_user_by_customer(sub["customer"], db)
    if user:
        user.plan = plan if subscription.statut == "active" else "free"

    await db.commit()
    log.info("stripe.subscription_updated", plan=plan, statut=subscription.statut)


async def _handle_subscription_deleted(sub: dict, db: AsyncSession):
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.statut = "canceled"

    user = await _find_user_by_customer(sub["customer"], db)
    if user:
        user.plan = "free"

    await db.commit()
    log.info("stripe.subscription_deleted", customer=sub["customer"])


async def _handle_payment_succeeded(invoice: dict, db: AsyncSession):
    log.info("stripe.payment_succeeded", invoice_id=invoice["id"])


async def _handle_payment_failed(invoice: dict, db: AsyncSession):
    user = await _find_user_by_customer(invoice["customer"], db)
    if user:
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == invoice.get("subscription"))
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.statut = "past_due"
        await db.commit()

    log.warning("stripe.payment_failed", customer=invoice["customer"])
