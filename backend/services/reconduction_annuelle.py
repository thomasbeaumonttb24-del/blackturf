"""Rappel de reconduction des abonnements ANNUELS (code de la consommation, L215-1).

Un contrat reconduit tacitement doit faire l'objet d'une information écrite du
consommateur, au plus tôt trois mois et au plus tard un mois avant le terme,
sur sa faculté de ne pas le reconduire. Sans cet avis, il peut résilier à tout
moment après la reconduction — et un prélèvement annuel « surprise » est la
première cause de litige bancaire.

La tâche passe chaque jour ; chaque abonnement annuel reçoit UN rappel par
échéance, entre J-45 et J-31 (la fenêtre laisse deux semaines de marge si un
envoi échoue). L'envoi est journalisé (`rappel_reconduction`) : c'est la preuve.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Subscription, SubscriptionEvent, User
from services.abonnements import journaliser
from services.journal import masquer_email

log = structlog.get_logger()

FENETRE_DEBUT = timedelta(days=45)
FENETRE_FIN = timedelta(days=31)
PRIX_ANNUEL_CENTS = {"standard": 11520, "expert": 18240}


def _aware(d):
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


async def envoyer_rappels(db: AsyncSession, maintenant: datetime | None = None) -> int:
    from services.alerts import send_email
    from services.email_compte import rappel_reconduction

    maintenant = maintenant or datetime.now(timezone.utc)
    envoyes = 0
    lignes = (await db.execute(
        select(Subscription, User)
        .join(User, User.user_id == Subscription.user_id)
        .where(Subscription.periodicite == "annual", Subscription.statut == "active")
    )).all()
    for sub, user in lignes:
        fin = _aware(sub.periode_fin)
        if fin is None or not (maintenant + FENETRE_FIN <= fin <= maintenant + FENETRE_DEBUT):
            continue
        # Un seul rappel par échéance.
        deja = (await db.execute(
            select(SubscriptionEvent).where(
                SubscriptionEvent.type == "rappel_reconduction",
                SubscriptionEvent.stripe_subscription_id == sub.stripe_subscription_id,
            )
        )).scalars().all()
        if any((e.detail or {}).get("echeance") == fin.date().isoformat() for e in deja):
            continue
        montant = PRIX_ANNUEL_CENTS.get(sub.plan, 0)
        html, texte = rappel_reconduction(user.prenom, sub.plan, fin, montant)
        try:
            await send_email(to=user.email,
                             subject="BlackTurf — Votre abonnement annuel arrive à échéance",
                             html=html, text=texte)
        except Exception as e:  # noqa: BLE001 — retenté le lendemain (fenêtre de 14 jours)
            log.error("reconduction.envoi_echoue", email=masquer_email(user.email), error=str(e)[:150])
            continue
        await journaliser(db, "rappel_reconduction", user, sub, notifier=False,
                          montant_cents=montant,
                          detail={"echeance": fin.date().isoformat()})
        await db.commit()
        envoyes += 1
        log.info("reconduction.rappel_envoye", email=masquer_email(user.email), echeance=fin.date().isoformat())
    return envoyes
