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
from api.routes.auth import get_current_user, require_verified_email
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


# Statuts pour lesquels l'abonnement DONNE ENCORE ACCÈS au produit. `past_due` en
# fait partie : Stripe retente le paiement plusieurs jours, couper l'accès au
# premier échec punirait une carte expirée. `cancel_at_period_end` est notre
# statut maison — résilié, mais payé jusqu'à l'échéance.
STATUTS_VIVANTS = ("active", "trialing", "past_due", "cancel_at_period_end")

# Ordre des plans, pour choisir lequel accorder quand il en reste plusieurs.
RANG_PLAN = {"free": 0, "standard": 1, "expert": 2}


async def _subs_vivantes(user_id: str, db: AsyncSession,
                         sauf_stripe_id: str | None = None) -> list[Subscription]:
    """Abonnements qui donnent encore accès, du plus récent au plus ancien."""
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id,
               Subscription.statut.in_(STATUTS_VIVANTS))
        .order_by(Subscription.created_at.desc())
    )
    subs = list(res.scalars().all())
    if sauf_stripe_id:
        subs = [s for s in subs if s.stripe_subscription_id != sauf_stripe_id]
    return subs


async def _plan_effectif(user_id: str, db: AsyncSession,
                         sauf_stripe_id: str | None = None) -> str:
    """Plan réellement dû à l'utilisateur au vu de TOUS ses abonnements vivants.

    Corrige une rétrogradation prématurée : `_handle_subscription_deleted` posait
    `plan = "free"` dès la fin du PREMIER abonnement, même quand un autre courait
    encore (cas réel du 2026-08-20 : 3 essais simultanés expirant à 24 h d'écart,
    le compte perdait l'accès un jour trop tôt).
    """
    subs = await _subs_vivantes(user_id, db, sauf_stripe_id=sauf_stripe_id)
    if not subs:
        return "free"
    return max((s.plan for s in subs), key=lambda p: RANG_PLAN.get(p, 0))


class CheckoutRequest(BaseModel):
    plan: str         # standard / expert (ou starter / pro compat)
    periodicite: str  # monthly / annual


@router.post("/stripe/checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    # Adresse confirmée exigée : sans elle, l'essai gratuit se multiplie à volonté,
    # une adresse bidon par compte.
    user: User = Depends(require_verified_email),
):
    """Crée une session Stripe Checkout et retourne l'URL de paiement.

    Trois règles, toutes absentes avant le 2026-08-20 :
    1. un compte déjà abonné ne repasse PAS par Checkout — il change de plan sur
       son abonnement existant (sinon il en cumule autant qu'il clique) ;
    2. l'essai gratuit n'est accordé qu'une fois par compte ;
    3. la carte est exigée à l'ouverture de l'essai.
    """
    plan_cible = _normalize_plan(body.plan)
    price_key = f"{body.plan}_{body.periodicite}"
    price_id = PRICE_MAP.get(price_key)
    if not price_id:
        raise HTTPException(status_code=400, detail="Plan invalide")

    # 1) Déjà abonné ? On ne crée JAMAIS un second abonnement.
    vivants = await _subs_vivantes(user.user_id, db)
    if vivants:
        courant = vivants[0]
        if courant.plan == plan_cible and courant.periodicite == body.periodicite:
            raise HTTPException(
                status_code=409,
                detail="Vous êtes déjà abonné à cette formule. "
                       "Gérez votre abonnement depuis votre profil.",
            )
        return await _changer_de_plan(user, vivants, plan_cible, body.periodicite,
                                      price_id, db)

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

    # 2) Essai gratuit : une seule fois par compte.
    #
    # Stripe ne déduplique pas les essais par client : sans ce contrôle, le cycle
    # « essai → annulation → nouveau checkout » rendait le produit gratuit à vie
    # (constaté en production le 2026-08-20, 3 essais ouverts en 24 h sur un même
    # compte). La consommation est enregistrée par le webhook, quand Stripe
    # confirme l'essai — un checkout abandonné ne brûle donc rien.
    droit_a_lessai = user.essai_utilise_at is None

    subscription_data: dict = {
        "metadata": {"user_id": user.user_id, "plan": plan_cible},
    }
    if droit_a_lessai:
        # Essai gratuit 7 jours : Standard ET Expert (alignés, cf. page /tarifs).
        subscription_data["trial_period_days"] = 7
        # Filet de sécurité : si la carte disparaît d'ici la fin de l'essai
        # (supprimée depuis le portail), on annule au lieu de laisser traîner un
        # impayé — le webhook repasse alors l'utilisateur en `free`.
        subscription_data["trial_settings"] = {
            "end_behavior": {"missing_payment_method": "cancel"}
        }

    # Créer la session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/abonnement/succes?session_id={{CHECKOUT_SESSION_ID}}&plan={plan_cible}",
        cancel_url=f"{settings.frontend_url}/tarifs",
        # 3) Carte exigée dès l'ouverture de l'essai (décision produit du
        # 2026-08-20). `if_required` — l'essai sans carte — laissait partir des
        # essais qu'aucun moyen de paiement ne pouvait convertir, et rendait
        # l'abus indétectable côté Stripe. `always` est aussi le défaut Stripe :
        # le paramètre reste explicite pour que le choix soit lisible ici.
        payment_method_collection="always",
        subscription_data=subscription_data,
        allow_promotion_codes=True,
        locale="fr",
    )

    log.info("stripe.checkout_created", user_id=user.user_id, plan=plan_cible,
             essai_accorde=droit_a_lessai)
    return {"url": session.url, "essai": droit_a_lessai}


async def _changer_de_plan(
    user: User,
    vivants: list[Subscription],
    plan_cible: str,
    periodicite: str,
    price_id: str,
    db: AsyncSession,
) -> dict:
    """Standard ↔ Expert : on MODIFIE l'abonnement existant.

    Avant le 2026-08-20, tout passage d'une formule à l'autre repassait par
    Checkout et créait un SECOND abonnement, le premier restant actif : le client
    était facturé deux fois. Ici, une seule ligne Stripe suit le client, la
    différence de prix est proratisée sur la prochaine facture, et l'essai en
    cours est conservé (Stripe garde `trial_end` lors d'un changement d'article).
    """
    courant = vivants[0]
    sub_stripe = stripe.Subscription.retrieve(courant.stripe_subscription_id)
    item_id = sub_stripe["items"]["data"][0]["id"]

    maj = stripe.Subscription.modify(
        courant.stripe_subscription_id,
        items=[{"id": item_id, "price": price_id}],
        # Crédit/débit au prorata reporté sur la prochaine facture : le client
        # obtient son nouveau plan tout de suite sans prélèvement surprise.
        proration_behavior="create_prorations",
        metadata={"user_id": user.user_id, "plan": plan_cible},
    )

    # Doublons hérités de l'ancien tunnel : un compte ne doit porter qu'UN
    # abonnement. Ceux encore en essai n'ont rien coûté, on les ferme sur-le-champ ;
    # ceux déjà payés courent jusqu'à l'échéance déjà réglée.
    for doublon in vivants[1:]:
        try:
            if doublon.statut == "trialing" or doublon.essai_fin is not None:
                stripe.Subscription.delete(doublon.stripe_subscription_id)
                doublon.statut = "canceled"
            else:
                stripe.Subscription.modify(doublon.stripe_subscription_id,
                                           cancel_at_period_end=True)
                doublon.statut = "cancel_at_period_end"
            log.warning("stripe.doublon_ferme", user_id=user.user_id,
                        sub=doublon.stripe_subscription_id, statut=doublon.statut)
        except Exception as e:  # noqa: BLE001
            log.error("stripe.doublon_fermeture_echouee", user_id=user.user_id,
                      sub=doublon.stripe_subscription_id, error=str(e)[:120])

    # Mise à jour immédiate : le webhook `subscription.updated` confirmera, mais
    # l'utilisateur revient sur le site dans la seconde et doit voir son plan.
    courant.plan = plan_cible
    courant.periodicite = periodicite
    statut_stripe = maj.get("status")
    if statut_stripe in ("active", "trialing"):
        courant.statut = "active"
        user.plan = plan_cible
    await db.commit()

    log.info("stripe.plan_change", user_id=user.user_id, plan=plan_cible,
             sub=courant.stripe_subscription_id, doublons_fermes=len(vivants) - 1)
    return {
        "url": f"{settings.frontend_url}/abonnement/succes?plan={plan_cible}&change=1",
        "change_de_plan": True,
        "plan": plan_cible,
        "message": f"Votre abonnement est passé en {plan_cible.capitalize()}. "
                   "La différence est ajustée au prorata sur votre prochaine facture.",
    }


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
    # 1) Essai Stripe si configuré + abonnement connu.
    #
    # On boucle sur TOUS les abonnements vivants. L'ancien `scalar_one_or_none()`
    # levait `MultipleResultsFound` dès qu'un compte en portait plusieurs — cas
    # créé par l'ancien tunnel de changement de plan. L'exception était avalée par
    # le `except` ci-dessous : le client recevait « demande enregistrée » et RIEN
    # n'était résilié chez Stripe (constaté le 2026-08-20).
    if settings.stripe_secret_key and user.stripe_customer_id:
        subs = await _subs_vivantes(user.user_id, db)
        for sub in subs:
            if not sub.stripe_subscription_id:
                continue
            try:
                stripe.Subscription.modify(sub.stripe_subscription_id,
                                           cancel_at_period_end=True)
                sub.statut = "cancel_at_period_end"
                cancelled_via_stripe = True
            except Exception as e:  # noqa: BLE001
                log.warning("stripe.cancel.api_failed", user_id=user.user_id,
                            sub=sub.stripe_subscription_id, error=str(e)[:120])
        if cancelled_via_stripe:
            await db.commit()

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
    retry Stripe en boucle).

    Repli sur l'ARTICLE d'abonnement : les versions récentes de l'API portent
    `current_period_start`/`current_period_end` sur `items.data[0]` et non plus sur
    l'objet abonnement. D'où trois lignes `subscriptions` avec des périodes NULL en
    production (constaté le 2026-08-20).
    """
    v = sub.get(key)
    if v is None:
        try:
            v = sub["items"]["data"][0].get(key)
        except (KeyError, IndexError, TypeError):
            v = None
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
    statut_reel = sub.get("status")
    est_active = statut_reel in ("active", "trialing")
    subscription = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=sub["id"],
        plan=plan,
        periodicite=periodicite,
        statut="active" if est_active else statut_reel,
        periode_debut=_ts(sub, "current_period_start"),
        periode_fin=_ts(sub, "current_period_end"),
        essai_fin=_ts(sub, "trial_end"),
    )
    db.add(subscription)

    # BUG corrigé (2026-08-17) : le plan était accordé ICI même quand `statut_reel`
    # valait "incomplete" (carte non validée / 3-D Secure non terminé / checkout
    # abandonné avant confirmation) — Stripe émet quand même `subscription.created`
    # dès la création de l'objet, avant paiement effectif. Résultat : un compte
    # affiché comme abonné côté site sans paiement réel. On aligne sur
    # _handle_subscription_updated, qui lui vérifiait déjà le statut.
    if est_active:
        user.plan = plan
        # L'essai est consommé ICI, quand Stripe confirme qu'il a bien démarré —
        # pas à l'ouverture du checkout, sinon une session abandonnée brûlerait le
        # droit à l'essai d'un client qui n'a rien obtenu.
        if subscription.essai_fin is not None and user.essai_utilise_at is None:
            user.essai_utilise_at = datetime.now(timezone.utc)
            log.info("stripe.essai_consomme", user_id=user.user_id, plan=plan)
    await db.commit()
    log.info("stripe.subscription_created", user_id=user.user_id, plan=plan,
             statut=statut_reel, plan_accorde=est_active)


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
    subscription.essai_fin = _ts(sub, "trial_end") or subscription.essai_fin

    user = await _find_user_by_customer(sub.get("customer"), db)
    if user:
        if subscription.statut == "active":
            user.plan = plan
            if subscription.essai_fin is not None and user.essai_utilise_at is None:
                user.essai_utilise_at = datetime.now(timezone.utc)
        else:
            # Un autre abonnement peut encore courir : ne pas rétrograder à l'aveugle.
            user.plan = await _plan_effectif(
                user.user_id, db, sauf_stripe_id=subscription.stripe_subscription_id
            )

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
        # `free` seulement s'il ne reste RIEN. Poser `free` inconditionnellement
        # coupait l'accès dès la fin du premier abonnement, même quand un second
        # courait encore (constaté le 2026-08-20 : 3 essais expirant à 24 h d'écart).
        user.plan = await _plan_effectif(user.user_id, db, sauf_stripe_id=sub["id"])

    await db.commit()
    log.info("stripe.subscription_deleted", customer=sub["customer"],
             plan_restant=user.plan if user else None)


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
