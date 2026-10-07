"""Offre anniversaire : −50 % sur le premier mois d'un abonnement MENSUEL.

Le code n'est JAMAIS public. Le dépôt l'est : le code n'existe que dans le .env
du serveur (`CODE_ANNIVERSAIRE`). Il n'est remis que de deux façons :
  · par le mail d'anniversaire (scripts/envoyer_mail_anniversaire.py) ;
  · par la fenêtre du site, aux seuls comptes ÉLIGIBLES (`GET /stripe/offre-anniversaire`).
Un code qui fuiterait ne sert à rien à un compte créé pour l'occasion : le
checkout refuse tout compte inscrit après `COMPTES_AVANT`.

Côté Stripe, la remise est un COUPON (jamais un « promotion code ») : un coupon
ne se tape pas sur la page de paiement Stripe, c'est le serveur qui l'applique
après avoir vérifié les règles ci-dessous. Stripe borne en plus la remise au
premier mois (`duration=once`) et à la date de fin (`redeem_by`).
"""
from __future__ import annotations

import hmac
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

import stripe
import structlog
from sqlalchemy import select

from api.config import get_settings

if TYPE_CHECKING:  # import réel différé : le gabarit du mail se rend sans base
    from sqlalchemy.ext.asyncio import AsyncSession
    from db.models import User

log = structlog.get_logger()
PARIS = ZoneInfo("Europe/Paris")

POURCENT = 50
COUPON_ID = "blackturf-anniversaire-2026-10"
# Comptes inscrits AVANT cette date seulement (le jour de l'envoi compris).
COMPTES_AVANT = datetime(2026, 10, 8, 0, 0, tzinfo=PARIS)
# Dernier instant où le checkout accepte le code (heure de Paris) : huit jours,
# offre exceptionnelle (décision de l'exploitant).
FIN = datetime(2026, 10, 15, 23, 59, 59, tzinfo=PARIS)
FIN_TEXTE = "jeudi 15 octobre à minuit"

# Prix mensuels en centimes : avant / après remise (affichage, mail, contrôle).
PRIX = {"standard": (1200, 600), "expert": (1900, 950)}

DEJA_UTILISEE = "Vous avez déjà profité de cette offre."


class OffreRefusee(Exception):
    """Le code est connu mais ne s'applique pas à ce compte : le message le dit."""


def normaliser(code: Optional[str]) -> str:
    return re.sub(r"[\s-]+", "", code or "").upper()


def code_actif() -> Optional[str]:
    """Le code tel que l'exploitant l'a posé dans le .env, ou None (offre fermée)."""
    brut = (get_settings().code_anniversaire or "").strip()
    return brut.upper() or None


def correspond(saisi: Optional[str]) -> bool:
    actif = code_actif()
    return bool(actif) and hmac.compare_digest(normaliser(saisi), normaliser(actif))


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _deja_utilisee(user: User) -> bool:
    """Un abonnement de ce client a déjà porté l'offre (même résilié depuis).
    Lu chez Stripe : la métadonnée `offre` est posée au checkout. Stripe injoignable :
    on laisse passer (la remise vaut quelques euros, bloquer un achat légitime coûte
    plus) et on le note."""
    from api.routes.stripe_routes import _stripe_joignable
    if not user.stripe_customer_id or not _stripe_joignable():
        return False
    try:
        for sub in stripe.Subscription.list(customer=user.stripe_customer_id, status="all",
                                            limit=100).auto_paging_iter():
            if (sub.get("metadata") or {}).get("offre") == COUPON_ID and \
                    sub.get("status") != "incomplete_expired":
                return True
    except Exception as e:  # noqa: BLE001
        log.warning("offre_anniversaire.lecture_stripe_echouee", user_id=user.user_id, error=str(e)[:120])
    return False


async def raison_refus(user: User, db: AsyncSession, now: Optional[datetime] = None) -> Optional[str]:
    """None si le compte peut profiter de l'offre, sinon la phrase à lui montrer."""
    from api.routes.stripe_routes import STATUTS_EN_ATTENTE_PAIEMENT, STATUTS_VIVANTS
    from db.models import Subscription
    from services.parrainage import remise_filleul_due

    now = now or datetime.now(timezone.utc)
    if not code_actif():
        return "Cette offre n'est pas disponible."
    if now > FIN:
        return "Cette offre exceptionnelle a pris fin le 15 octobre."
    if user.created_at is None or _utc(user.created_at) >= COMPTES_AVANT:
        return "Cette offre est réservée aux membres inscrits avant le 8 octobre 2026."
    en_cours = await db.scalar(select(Subscription.sub_id).where(
        Subscription.user_id == user.user_id,
        Subscription.statut.in_(STATUTS_VIVANTS + STATUTS_EN_ATTENTE_PAIEMENT)).limit(1))
    if en_cours:
        return "Cette offre est réservée aux comptes sans abonnement en cours."
    if await remise_filleul_due(user, db) is not None:
        return ("Votre remise de parrainage (5 € offerts) s'applique déjà à votre premier "
                "paiement ; elle ne se cumule pas avec cette offre.")
    if _deja_utilisee(user):
        return DEJA_UTILISEE
    return None


async def verifier(code: Optional[str], periodicite: str, user: User, db: AsyncSession) -> None:
    """Contrôle complet d'un code saisi au checkout. Lève OffreRefusee."""
    if not correspond(code):
        raise OffreRefusee("Ce code promo n'est pas valide.")
    if periodicite != "monthly":
        raise OffreRefusee("Ce code s'applique à l'abonnement mensuel uniquement.")
    raison = await raison_refus(user, db)
    if raison:
        raise OffreRefusee(raison)


def assurer_coupon() -> str:
    """Identifiant du coupon Stripe de l'offre, créé s'il manque (idempotent)."""
    try:
        stripe.Coupon.retrieve(COUPON_ID)
        return COUPON_ID
    except stripe.error.InvalidRequestError:
        pass
    settings = get_settings()
    produits = []
    for price_id in (settings.stripe_price_starter_monthly, settings.stripe_price_pro_monthly):
        if price_id:
            produits.append(stripe.Price.retrieve(price_id)["product"])
    params: dict = {
        "id": COUPON_ID,
        "percent_off": POURCENT,
        "duration": "once",
        "redeem_by": int(FIN.timestamp()),
        "name": f"Anniversaire BlackTurf : −{POURCENT} % le 1er mois",
        "metadata": {"app": "blackturf", "offre": "anniversaire"},
    }
    if produits:
        params["applies_to"] = {"products": sorted(set(produits))}
    stripe.Coupon.create(**params)
    log.info("offre_anniversaire.coupon_cree", coupon=COUPON_ID)
    return COUPON_ID


def offre_publique() -> dict:
    """Ce que le site et le mail affichent (sans le code)."""
    return {
        "pourcent": POURCENT,
        "fin": FIN.isoformat(),
        "fin_texte": FIN_TEXTE,
        "prix": {plan: {"avant": a, "apres": b} for plan, (a, b) in PRIX.items()},
    }
