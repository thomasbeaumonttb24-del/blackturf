"""Journal et supervision des mouvements d'abonnement — BlackTurf.

`subscriptions` ne garde que l'état courant. Ce module écrit, à côté, le journal
append-only `subscription_events` et prévient l'exploitant à chaque mouvement.

Une règle tient tout le fichier : **journaliser ne doit jamais faire échouer le
traitement Stripe**. Un webhook qui lève renvoie 500, Stripe le rejoue, et le
même mouvement se rejoue avec lui. Les erreurs d'écriture et d'e-mail sont donc
consignées, jamais propagées.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from db.models import Subscription, SubscriptionEvent, User

settings = get_settings()
log = structlog.get_logger()


# Libellés lisibles : l'e-mail de supervision est lu sur un téléphone, pas dans
# une console. L'ordre suit le cycle de vie réel d'un abonné.
LIBELLES = {
    "essai_ouvert": "Essai gratuit ouvert",
    "essai_sans_carte": "Essai ouvert SANS carte — accès bloqué",
    "carte_ajoutee": "Carte enregistrée — accès débloqué",
    "abonnement_actif": "Abonnement actif",
    "changement_plan": "Changement de formule",
    "essai_bientot_fini": "Essai bientôt terminé",
    "essai_termine_sans_carte": "Essai terminé sans carte — abonnement annulé",
    "resiliation_demandee": "Résiliation demandée",
    "resilie": "Abonnement résilié",
    "paiement_echoue": "Paiement en échec — accès coupé",
    "paiement_recu": "Paiement encaissé — accès rétabli",
    "essai_refuse_carte_reutilisee": "Essai refusé — carte déjà vue sur un autre compte",
    "carte_refusee_autre_compte": "Abonnement refusé — carte rattachée à un autre compte",
}

# Mouvements qui coûtent ou rapportent de l'argent, ou qui demandent une action.
# Les autres sont journalisés sans réveiller personne.
TYPES_NOTIFIES = set(LIBELLES)


def _euros(cents: Optional[int]) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",") if cents else "—"


def _jour(d: Optional[datetime]) -> str:
    return d.strftime("%d/%m/%Y à %H:%M") if d else "—"


async def journaliser(
    db: AsyncSession,
    type_: str,
    user: Optional[User] = None,
    sub: Optional[Subscription] = None,
    *,
    plan: Optional[str] = None,
    plan_precedent: Optional[str] = None,
    montant_cents: Optional[int] = None,
    essai_fin: Optional[datetime] = None,
    periode_fin: Optional[datetime] = None,
    stripe_subscription_id: Optional[str] = None,
    detail: Optional[dict] = None,
    notifier: bool = True,
) -> Optional[SubscriptionEvent]:
    """Enregistre un mouvement et prévient l'exploitant.

    N'appelle PAS `commit` : l'écriture rejoint la transaction du webhook, pour
    que le journal et l'état de l'abonnement soient vrais ensemble ou pas du tout.
    """
    try:
        essai = essai_fin if essai_fin is not None else (sub.essai_fin if sub else None)
        maintenant = datetime.now(timezone.utc)
        # « Pendant l'essai » n'a de sens que si un essai est connu. Sinon NULL —
        # un faux `False` laisserait croire que le client avait dépassé sa période
        # d'essai alors qu'il n'en a jamais eu.
        pendant_essai = None
        if essai is not None:
            # Comparaison tolérante aux dates naïves (SQLite en test).
            ref = essai if essai.tzinfo else essai.replace(tzinfo=timezone.utc)
            pendant_essai = maintenant < ref

        event = SubscriptionEvent(
            event_id=str(uuid.uuid4()),
            user_id=user.user_id if user else None,
            email=user.email if user else None,
            type=type_,
            plan=plan or (sub.plan if sub else None),
            plan_precedent=plan_precedent,
            stripe_subscription_id=stripe_subscription_id
            or (sub.stripe_subscription_id if sub else None),
            montant_cents=montant_cents,
            essai_fin=essai,
            periode_fin=periode_fin if periode_fin is not None else (sub.periode_fin if sub else None),
            pendant_essai=pendant_essai,
            detail=detail,
        )
        db.add(event)
        await db.flush()
    except Exception as e:  # noqa: BLE001
        # Un journal qui casse le webhook coûterait plus cher que le journal.
        log.error("abonnements.journal_echoue", type=type_, error=str(e)[:200])
        return None

    log.info("abonnements.mouvement", type=type_,
             email=event.email, plan=event.plan,
             pendant_essai=event.pendant_essai)

    if notifier and type_ in TYPES_NOTIFIES:
        await _notifier_admin(event)
    return event


async def _notifier_admin(event: SubscriptionEvent) -> None:
    """E-mail de supervision à l'exploitant. Jamais bloquant."""
    try:
        from services.alerts import send_email

        libelle = LIBELLES.get(event.type, event.type)
        lignes = [
            ("Compte", event.email or "—"),
            ("Mouvement", libelle),
            ("Formule", (event.plan or "—").capitalize()),
        ]
        if event.plan_precedent:
            lignes.append(("Formule précédente", event.plan_precedent.capitalize()))
        if event.montant_cents:
            lignes.append(("Montant", _euros(event.montant_cents)))
        if event.essai_fin:
            lignes.append(("Fin d'essai", _jour(event.essai_fin)))
        if event.periode_fin:
            lignes.append(("Fin de période", _jour(event.periode_fin)))
        if event.pendant_essai is not None:
            lignes.append(("Survenu pendant l'essai",
                           "oui" if event.pendant_essai else "non"))
        if event.stripe_subscription_id:
            lignes.append(("Abonnement Stripe", event.stripe_subscription_id))

        corps = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#666;'>{k}</td>"
            f"<td style='padding:4px 0;'><strong>{v}</strong></td></tr>"
            for k, v in lignes
        )
        await send_email(
            to=settings.admin_email,
            subject=f"[BlackTurf] {libelle} — {event.email or 'compte inconnu'}",
            html=f"<p>{libelle}</p><table>{corps}</table>"
                 f"<p style='color:#666;font-size:11px;'>"
                 f"Suivi complet : {settings.frontend_url}/admin</p>",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("abonnements.notif_admin_echouee", type=event.type,
                    error=str(e)[:200])
