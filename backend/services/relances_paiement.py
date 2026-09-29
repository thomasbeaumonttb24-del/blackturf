"""Relances d'un prélèvement refusé — politique de l'exploitant du 2026-09-16.

Avant, Stripe relançait la carte selon son propre calendrier, jusqu'à trois
semaines : 8 prélèvements refusés en 13 jours sur un seul compte (constaté le
2026-09-16). Pour le client, c'est la signature d'un site arnaque.

Désormais :
    refus initial (échéance ou fin d'essai)
    → relance à J+3
    → relance à J+7
    → plus rien : la facture est annulée (void), l'abonnement clos, le compte
      marqué perdu (`impaye_perdu` au journal).

Stripe ne permet pas de fixer ce calendrier par l'API. On coupe donc sa
collecte automatique dès le premier refus (`auto_advance=False`, cf.
`stripe_routes._handle_payment_failed`) et c'est `job_relances_paiement` qui
retente, à heure ouvrée. L'accès reste coupé pendant tout ce temps ; un
prélèvement qui passe le rend dans la seconde (`_handle_payment_succeeded`).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Subscription, SubscriptionEvent, User
from services.abonnements import journaliser

log = structlog.get_logger()

# Jours après le PREMIER refus. Deux relances, pas une de plus.
RELANCES_JOURS = (3, 7)
# Tentatives Stripe au total : le prélèvement initial + les relances.
TENTATIVES_MAX = 1 + len(RELANCES_JOURS)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def prochaine_relance(premier_refus: datetime, tentatives: int,
                      derniere_relance: Optional[datetime] = None) -> Optional[datetime]:
    """Date de la relance suivante, `None` quand il n'y en a plus.

    `tentatives` = prélèvements déjà tentés sur la facture (1 après le refus initial).
    `derniere_relance` garde l'écart du calendrier (4 jours entre J+3 et J+7) quand
    la tâche rattrape un retard : sans lui, un impayé vu pour la première fois
    après J+7 était prélevé deux fois à une heure d'écart.
    """
    if tentatives < 1 or tentatives >= TENTATIVES_MAX:
        return None
    echeance = _aware(premier_refus) + timedelta(days=RELANCES_JOURS[tentatives - 1])
    if derniere_relance is not None and tentatives >= 2:
        ecart = RELANCES_JOURS[tentatives - 1] - RELANCES_JOURS[tentatives - 2]
        echeance = max(echeance, _aware(derniere_relance) + timedelta(days=ecart))
    return echeance


async def premier_refus(db: AsyncSession, facture_id: str) -> Optional[datetime]:
    """Date du premier refus connu pour cette facture, lue au journal."""
    for e in (await db.execute(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.type == "paiement_echoue")
        .order_by(SubscriptionEvent.created_at)
    )).scalars().all():
        if (e.detail or {}).get("facture") == facture_id:
            return _aware(e.created_at)
    return None


def couper_collecte_stripe(facture_id: str) -> None:
    """Empêche Stripe de relancer de lui-même. Jamais bloquant.

    Appelé depuis le webhook, donc depuis des tests : la suite tourne avec une clé
    réelle (sk_test en local, sk_live dans l'image de prod) — rien ne part sous pytest.
    """
    if not stripe.api_key or "PYTEST_CURRENT_TEST" in os.environ:
        return
    try:
        stripe.Invoice.modify(facture_id, auto_advance=False)
    except Exception as e:  # noqa: BLE001
        log.warning("relances.coupure_stripe_echouee", facture=facture_id, error=str(e)[:150])


async def relances_faites(db: AsyncSession, facture_id: str) -> tuple[int, Optional[datetime]]:
    """Relances déjà tentées par cette tâche sur la facture, et la date de la
    dernière, lues au journal.

    On ne peut PAS se fier à `attempt_count` de Stripe : un `Invoice.pay` lancé
    par l'API ne l'incrémente pas (seules ses propres relances automatiques
    comptent). Le 21-22/09, la relance « J+3 » est ainsi repartie toutes les
    heures : 10 prélèvements refusés sur une même carte, jusqu'à ce que Stripe
    annule lui-même le PaymentIntent.
    """
    dates = [_aware(e.created_at) for e in (await db.execute(
        select(SubscriptionEvent).where(SubscriptionEvent.type == "relance_paiement")
    )).scalars().all() if (e.detail or {}).get("facture") == facture_id]
    return len(dates), max(dates, default=None)


async def _facture_ouverte(db: AsyncSession, sub: Subscription) -> Optional[str]:
    derniers = (await db.execute(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.type == "paiement_echoue",
               SubscriptionEvent.stripe_subscription_id == sub.stripe_subscription_id)
        .order_by(SubscriptionEvent.created_at.desc())
    )).scalars().all()
    for e in derniers:
        facture = (e.detail or {}).get("facture")
        if facture:
            return facture
    ouvertes = stripe.Invoice.list(subscription=sub.stripe_subscription_id, status="open", limit=1)
    data = ouvertes.get("data") or []
    return data[0]["id"] if data else None


async def _clore(db: AsyncSession, sub: Subscription, user: Optional[User],
                 facture: dict, motif: str) -> bool:
    """Facture annulée, abonnement clos, compte perdu. Faux si Stripe a refusé."""
    from api.routes.stripe_routes import _plan_effectif

    # 1. `canceled` écrit AVANT tout appel Stripe : les webhooks que ces appels
    #    déclenchent arrivent pendant ce traitement, et c'est ce statut qui les
    #    empêche de journaliser une « résiliation » ou de rouvrir l'accès.
    statut_avant = sub.statut
    sub.statut = "canceled"
    await db.commit()
    # 2. L'abonnement d'abord. Annuler la facture en premier faisait repasser
    #    l'abonnement `active` chez Stripe (sa seule facture impayée disparue) :
    #    le webhook rouvrait le plan Expert une seconde (constaté le 2026-09-16).
    try:
        stripe.Subscription.delete(sub.stripe_subscription_id)
    except stripe.error.InvalidRequestError as e:
        # Déjà clos chez Stripe : on aligne la base.
        log.info("relances.abonnement_deja_clos", sub=sub.stripe_subscription_id, error=str(e)[:120])
    except Exception as e:  # noqa: BLE001
        log.error("relances.cloture_echouee", sub=sub.stripe_subscription_id, error=str(e)[:150])
        sub.statut = statut_avant
        await db.commit()
        return False
    # 3. La facture ensuite : le client ne doit plus rien pour un service coupé.
    if facture.get("status") == "open":
        try:
            stripe.Invoice.void_invoice(facture["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("relances.annulation_facture_echouee", facture=facture["id"],
                        error=str(e)[:150])

    if user is not None:
        user.plan = await _plan_effectif(user.user_id, db, sauf_stripe_id=sub.stripe_subscription_id)
    await journaliser(db, "impaye_perdu", user, sub,
                      montant_cents=facture.get("amount_due"),
                      detail={"facture": facture.get("id"),
                              "tentatives": facture.get("attempt_count"),
                              "motif": motif})
    await db.commit()
    log.warning("relances.compte_perdu", sub=sub.stripe_subscription_id,
                email=user.email if user else None, motif=motif)
    return True


async def traiter_impayes(db: AsyncSession, maintenant: Optional[datetime] = None) -> dict:
    """Relance ce qui est dû, clôt ce qui a épuisé ses relances."""
    maintenant = maintenant or datetime.now(timezone.utc)
    bilan = {"relances": 0, "payes": 0, "clos": 0, "attente": 0, "erreurs": 0}

    impayes = (await db.execute(
        select(Subscription, User)
        .join(User, User.user_id == Subscription.user_id, isouter=True)
        .where(Subscription.statut.in_(("past_due", "unpaid")),
               Subscription.stripe_subscription_id.isnot(None))
    )).all()

    # Clés relevées d'avance : un `rollback` sur une erreur expire tous les objets de
    # la session, et relire un attribut expiré hors `await` lève MissingGreenlet.
    # C'est ce qui masquait la vraie erreur et arrêtait toute la boucle au premier
    # impayé en échec (facture au PaymentIntent annulé, du 22/09 au 29/09).
    cles = [(sub.sub_id, sub.stripe_subscription_id, user.user_id if user else None)
            for sub, user in impayes]

    for sub_id, stripe_sub_id, user_id in cles:
        try:
            # `get` recharge sous `await` ce qu'un rollback précédent a expiré.
            sub = await db.get(Subscription, sub_id)
            user = await db.get(User, user_id) if user_id else None
            facture_id = await _facture_ouverte(db, sub)
            if not facture_id:
                continue
            facture = stripe.Invoice.retrieve(facture_id)
            if facture.get("status") == "paid":
                continue  # le webhook de paiement rend l'accès
            n_relances, derniere = await relances_faites(db, facture_id)
            tentatives = max(facture.get("attempt_count") or 1, 1 + n_relances)

            if facture.get("status") != "open" or tentatives >= TENTATIVES_MAX:
                if await _clore(db, sub, user, facture, "relances_epuisees"):
                    bilan["clos"] += 1
                continue

            if facture.get("auto_advance"):
                couper_collecte_stripe(facture_id)

            debut = await premier_refus(db, facture_id) or datetime.fromtimestamp(
                facture.get("created") or maintenant.timestamp(), tz=timezone.utc)
            echeance = prochaine_relance(debut, tentatives, derniere)
            if echeance is None or maintenant < echeance:
                bilan["attente"] += 1
                continue

            refus_stripe = None
            try:
                stripe.Invoice.pay(facture_id)
            except stripe.error.CardError:
                pass  # refus bancaire : le webhook `invoice.payment_failed` le journalise
            except stripe.error.StripeError as e:
                # Facture non prélevable (ex. PaymentIntent annulé par Stripe) : la
                # tentative compte quand même, sinon elle repartirait à chaque heure.
                refus_stripe = getattr(e, "code", None) or type(e).__name__
                log.warning("relances.prelevement_impossible", sub=stripe_sub_id,
                            facture=facture_id, error=str(e)[:150])
            bilan["relances"] += 1

            facture = stripe.Invoice.retrieve(facture_id)
            detail = {"facture": facture_id, "numero": tentatives,
                      "resultat": facture.get("status")}
            if refus_stripe:
                detail["erreur"] = refus_stripe
            await journaliser(db, "relance_paiement", user, sub, notifier=False,
                              montant_cents=facture.get("amount_due"), detail=detail)
            await db.commit()
            if facture.get("status") == "paid":
                bilan["payes"] += 1
            elif max(tentatives + 1, facture.get("attempt_count") or 0) >= TENTATIVES_MAX:
                if await _clore(db, sub, user, facture, "derniere_relance_refusee"):
                    bilan["clos"] += 1
        except Exception as e:  # noqa: BLE001
            bilan["erreurs"] += 1
            await db.rollback()
            log.error("relances.erreur", sub=stripe_sub_id,
                      error=f"{type(e).__name__}: {str(e)[:200]}")

    log.info("relances.bilan", **bilan)
    return bilan
