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
from zoneinfo import ZoneInfo

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
    "resiliation_annulee": "Résiliation annulée — abonnement repris",
    "resilie": "Abonnement résilié",
    "paiement_echoue": "Paiement en échec — accès coupé",
    "paiement_recu": "Paiement encaissé — accès rétabli",
    "relance_paiement": "Relance du prélèvement refusé",
    "impaye_perdu": "Impayé après 2 relances — abonnement clos, compte perdu",
    "essai_refuse_carte_reutilisee": "Essai refusé — carte déjà vue sur un autre compte",
    "carte_refusee_autre_compte": "Abonnement refusé — carte rattachée à un autre compte",
    "parrainage_valide": "Parrainage validé — 5 € de crédit au parrain",
    "parrainage_refuse": "Parrainage refusé — carte du filleul déjà vue ailleurs",
    "parrainage_annule": "Parrainage annulé — paiement du filleul remboursé ou contesté",
    "pass_achete": "Pass sans renouvellement acheté",
    "pass_retire": "Pass retiré — paiement remboursé ou contesté",
    "pass_termine": "Pass arrivé à échéance",

    # Statuts Stripe bruts. `_handle_subscription_updated` journalise le STATUT
    # lui-même quand il change sans correspondre à un mouvement métier nommé :
    # sans ces entrées, le suivi admin affichait la clé technique telle quelle
    # (« past_due » en toutes lettres, constaté sur le premier impayé réel du
    # 2026-08-27). Ils sont libellés mais NON notifiés, cf. TYPES_NOTIFIES.
    "past_due": "Impayé — accès coupé, relances Stripe en cours",
    "canceled": "Abonnement clos chez Stripe",
    "unpaid": "Impayé définitif — relances Stripe épuisées",
    "incomplete": "Paiement jamais finalisé",
    "incomplete_expired": "Paiement abandonné — abonnement expiré",
    "paused": "Abonnement suspendu",
}

# Mouvements qui réveillent l'exploitant par e-mail : ceux qui coûtent ou
# rapportent de l'argent, ou qui demandent une action.
#
# La liste est EXPLICITE et non plus `set(LIBELLES)` : depuis qu'on libelle aussi
# les statuts Stripe bruts, tout libellé ajouté déclencherait sinon un e-mail de
# plus. Or un échec de paiement produit DEUX mouvements à 4 secondes d'écart
# (`past_due` puis `paiement_echoue`) — deux e-mails pour un seul événement.
TYPES_NOTIFIES = {
    "essai_ouvert", "essai_sans_carte", "carte_ajoutee", "abonnement_actif",
    "changement_plan", "essai_bientot_fini", "essai_termine_sans_carte",
    "resiliation_demandee", "resiliation_annulee", "resilie", "paiement_echoue", "paiement_recu",
    "essai_refuse_carte_reutilisee", "carte_refusee_autre_compte",
    "unpaid", "impaye_perdu",
    "parrainage_valide", "parrainage_refuse", "parrainage_annule",
    "pass_achete", "pass_retire",
}


def _euros(cents: Optional[int]) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",") if cents else "—"


PARIS = ZoneInfo("Europe/Paris")


def _jour(d: Optional[datetime]) -> str:
    # Heure de Paris : l'exploitant lisait « 17:57 » (UTC) sur un mail reçu à 19:57.
    if not d:
        return "—"
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(PARIS) \
        .strftime("%d/%m/%Y à %H:%M")


def _paiement_echoue_explique(event: SubscriptionEvent) -> tuple[str, str, list[tuple[str, str]]]:
    """Libellé, explication et lignes propres à un paiement refusé.

    Un seul libellé « Paiement en échec — accès coupé » couvrait deux situations
    opposées (2026-10-07) : le prospect dont la carte est refusée À L'INSCRIPTION
    (il n'a jamais eu accès, rien n'est « coupé ») et l'abonné dont le
    renouvellement est refusé. La « fin de période » affichée pour le premier était
    celle d'un mois jamais payé, ce qui ajoutait à la confusion.
    """
    from services.relances_paiement import TENTATIVES_MAX

    d = event.detail or {}
    tentative = int(d.get("tentative") or 1)
    premier = d.get("motif") == "subscription_create"
    lignes: list[tuple[str, str]] = []

    if d.get("acces_ouvert"):
        libelle = "Paiement refusé — accès maintenu par un autre abonnement"
        explication = ("Une facture a été refusée, mais le compte garde son accès "
                       "grâce à un autre abonnement encore payé.")
    elif premier and tentative <= 1:
        libelle = "Carte refusée à l'inscription — abonnement non ouvert"
        explication = ("Le client a voulu s'abonner mais sa banque a refusé le paiement. "
                       "Il n'a jamais eu accès à la formule et reste en Gratuit : "
                       "aucun accès n'a été retiré.")
    elif tentative > 1:
        libelle = "Relance refusée — toujours impayé"
        explication = ("La nouvelle tentative de prélèvement a encore été refusée. "
                       "Le compte reste en Gratuit.")
    else:
        libelle = "Renouvellement refusé — accès coupé"
        explication = ("L'abonné payait, mais le prélèvement de la nouvelle période a été "
                       "refusé. Il repasse en Gratuit jusqu'à ce qu'un paiement passe.")

    lignes.append(("Tentative", f"{tentative} sur {TENTATIVES_MAX}"))
    relance = d.get("prochaine_relance")
    lignes.append(("Prochaine relance",
                   _jour(datetime.fromtimestamp(relance, timezone.utc)) if relance
                   else "aucune — abonnement clos au prochain passage des relances"))
    if d.get("acces_ouvert"):
        a_faire = "Rien."
    elif premier and tentative <= 1:
        a_faire = ("Rien d'obligatoire. Un mot au client (« ta carte a été refusée, "
                   "réessaie avec une autre ») peut sauver la vente.")
    else:
        a_faire = "Rien : relance automatique, accès rendu dès qu'un paiement passe."
    lignes.append(("À faire", a_faire))
    return libelle, explication, lignes


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
        # Point de sauvegarde : un échec d'écriture du journal n'empoisonne pas la
        # transaction du webhook (sinon son `commit` final levait → 500 → Stripe
        # relivrait en boucle).
        async with db.begin_nested():
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
        from html import escape

        from services.alerts import alerter_admin

        libelle = LIBELLES.get(event.type, event.type)
        explication, lignes_propres = "", []
        if event.type == "paiement_echoue":
            libelle, explication, lignes_propres = _paiement_echoue_explique(event)
        premier_refus = (event.type == "paiement_echoue"
                         and (event.detail or {}).get("motif") == "subscription_create")
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
        # Après une carte refusée à l'inscription, la « fin de période » est celle
        # d'un mois jamais payé : la montrer laissait croire à un accès en cours.
        if event.periode_fin and not premier_refus:
            lignes.append(("Fin de période", _jour(event.periode_fin)))
        if event.pendant_essai is not None:
            lignes.append(("Survenu pendant l'essai",
                           "oui" if event.pendant_essai else "non"))
        if event.stripe_subscription_id:
            lignes.append(("Abonnement Stripe", event.stripe_subscription_id))
        lignes.extend(lignes_propres)

        corps = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#666;'>{k}</td>"
            f"<td style='padding:4px 0;'><strong>{escape(str(v))}</strong></td></tr>"
            for k, v in lignes
        )
        await alerter_admin(
            f"[BlackTurf] {libelle} — {event.email or 'compte inconnu'}",
            f"<p>{escape(libelle)}</p>"
            + (f"<p style='color:#444;'>{escape(explication)}</p>" if explication else "")
            + f"<table>{corps}</table>"
            f"<p style='color:#666;font-size:11px;'>"
            f"Suivi complet : {settings.frontend_url}/admin</p>",
            transactionnel=True, contexte=f"mouvement.{event.type}",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("abonnements.notif_admin_echouee", type=event.type,
                    error=str(e)[:200])
