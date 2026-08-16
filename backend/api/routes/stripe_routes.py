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
from sqlalchemy import select, text

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
    """Anciens noms de plans -> noms canoniques.

    "pro" a été supprimé du produit le 2026-08-16 (aucun compte, aucun prix
    Stripe) : il ne reste QUE ce point de normalisation, volontairement, pour
    qu'un client ou un lien de checkout périmé qui enverrait encore "pro"
    aboutisse sur "expert" au lieu d'échouer. Ne pas réintroduire "pro" dans les
    contrôles d'accès — le plan stocké doit toujours être canonique.
    """
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
            # Essai gratuit 7 jours : Standard uniquement (Expert/Pro = paiement direct).
            **({"trial_period_days": 7} if _normalize_plan(body.plan) == "standard" else {}),
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


@router.post("/stripe/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Résiliation de l'abonnement en self-service (honore L215-1-1 « résiliation en
    quelques clics »). Fonctionne AVEC ou SANS Stripe configuré :
    - Stripe + abonnement actif → annulation à la fin de la période (cancel_at_period_end).
    - Sinon (plan accordé manuellement / Stripe non configuré) → la demande est
      enregistrée et notifiée par email ; l'accès reste ouvert jusqu'à traitement.
    """
    cancelled_via_stripe = False
    # 1) Essai Stripe si configuré + abonnement connu
    if settings.stripe_secret_key and user.stripe_customer_id:
        try:
            res = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.user_id,
                    Subscription.statut == "active",
                )
            )
            sub = res.scalar_one_or_none()
            if sub and sub.stripe_subscription_id:
                stripe.Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=True)
                sub.statut = "cancel_at_period_end"
                await db.commit()
                cancelled_via_stripe = True
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.cancel.api_failed", user_id=user.user_id, error=str(e)[:120])

    # 2) Toujours notifier (preuve de la demande) — sans dépendre de Stripe
    try:
        from services.alerts import send_email
        await send_email(
            to="contact@blackturf.fr",
            subject=f"[BlackTurf] Demande de résiliation — {user.email}",
            html=f"<p>Demande de résiliation.</p><p>User: {user.email} ({user.user_id})</p>"
                 f"<p>Plan: {user.plan} — via Stripe: {cancelled_via_stripe}</p>",
        )
        await send_email(
            to=user.email,
            subject="BlackTurf — Votre demande de résiliation",
            html="<p>Votre demande de résiliation a bien été enregistrée.</p>"
                 + ("<p>Votre abonnement prendra fin à l'échéance de la période en cours ; "
                    "vous gardez l'accès jusque-là.</p>" if cancelled_via_stripe else
                    "<p>Elle sera traitée sous 72h. Vous conservez l'accès jusqu'au traitement. "
                    "Pour toute question : contact@blackturf.fr</p>")
                 + "<hr/><p style='color:#666;font-size:11px;'>Jeu responsable — "
                   "joueurs-info-service.fr — 09 74 75 13 13</p>",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.cancel.email_failed", user_id=user.user_id, error=str(e)[:120])

    log.info("stripe.cancel.requested", user_id=user.user_id, via_stripe=cancelled_via_stripe)
    return {
        "ok": True,
        "via_stripe": cancelled_via_stripe,
        "message": ("Résiliation enregistrée : effective à la fin de la période en cours."
                    if cancelled_via_stripe else
                    "Demande de résiliation enregistrée. Traitée sous 72h, accès maintenu jusque-là."),
    }


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
    event_id = event.get("id", "")

    # Idempotence / anti-replay : Stripe redélivre les webhooks (at-least-once) et un
    # payload+signature capturé peut être rejoué dans la fenêtre de 5 min. On ignore
    # tout event_id déjà traité. Table créée à la volée (pattern maison, cf. profil_run_log).
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS stripe_events ("
        "event_id TEXT PRIMARY KEY, event_type TEXT, "
        "processed_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    ))
    if event_id:
        seen = await db.execute(text("SELECT 1 FROM stripe_events WHERE event_id = :e"),
                                {"e": event_id})
        if seen.first() is not None:
            log.info("stripe.webhook.duplicate_ignored", event_id=event_id)
            return {"ok": True}

    log.info("stripe.webhook", event_type=event_type, event_id=event_id)

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

    # Marque l'event traité APRÈS le traitement métier (at-least-once + handlers
    # idempotents → aucun event perdu, aucun double-effet).
    if event_id:
        await db.execute(text(
            "INSERT INTO stripe_events (event_id, event_type) VALUES (:e, :t) "
            "ON CONFLICT (event_id) DO NOTHING"
        ), {"e": event_id, "t": event_type})
        await db.commit()

    return {"ok": True}


async def _find_user_by_customer(customer_id: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    return result.scalar_one_or_none()


def _ts(sub: dict, key: str):
    """Convertit un timestamp Stripe en datetime UTC, None si absent (gardes .get :
    selon l'event/la version d'API la clé peut manquer → éviter un KeyError → 500 →
    retry Stripe en boucle)."""
    v = sub.get(key)
    return datetime.fromtimestamp(v, tz=timezone.utc) if v else None


def _plan_from_sub(sub: dict) -> Optional[str]:
    """Plan dérivé du price_id réel. None si price inconnu → on N'ACCORDE PAS de plan
    par défaut (l'ancien fallback 'standard' donnait un accès payant gratuitement)."""
    try:
        price_id = sub["items"]["data"][0]["price"]["id"]
    except (KeyError, IndexError, TypeError):
        return None
    return PLAN_FROM_PRICE.get(price_id)


async def _handle_subscription_created(sub: dict, db: AsyncSession):
    user = await _find_user_by_customer(sub.get("customer"), db)
    if not user:
        log.warning("stripe.webhook.user_not_found", customer=sub.get("customer"))
        return

    # Idempotence : si l'abonnement existe déjà (re-livraison/retry), on délègue à
    # l'update plutôt que de créer un doublon (qui faussait MRR/ARR).
    existing = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub.get("id"))
    )
    if existing.scalar_one_or_none() is not None:
        await _handle_subscription_updated(sub, db)
        return

    plan = _plan_from_sub(sub)
    if plan is None:
        log.error("stripe.unknown_price", sub=sub.get("id"))
        return  # ne PAS accorder de plan sur un price non mappé

    price_id = sub["items"]["data"][0]["price"]["id"]
    recurring = (sub["items"]["data"][0]["price"].get("recurring") or {})
    periodicite = "annual" if recurring.get("interval") == "year" or "annual" in price_id else "monthly"

    import uuid
    subscription = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=sub["id"],
        plan=plan,
        periodicite=periodicite,
        statut="active" if sub.get("status") in ("active", "trialing") else sub.get("status"),
        periode_debut=_ts(sub, "current_period_start"),
        periode_fin=_ts(sub, "current_period_end"),
        essai_fin=_ts(sub, "trial_end"),
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

    plan = _plan_from_sub(sub)
    if plan is None:
        log.error("stripe.unknown_price", sub=sub.get("id"))
        return

    subscription.plan = plan
    subscription.statut = "active" if sub.get("status") in ("active", "trialing") else sub.get("status")
    subscription.periode_debut = _ts(sub, "current_period_start") or subscription.periode_debut
    subscription.periode_fin = _ts(sub, "current_period_end") or subscription.periode_fin

    user = await _find_user_by_customer(sub.get("customer"), db)
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
