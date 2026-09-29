"""Accès offert à la main (gagnant du jeu concours, geste commercial, test).

Avant le 2026-09-29, offrir un accès écrivait seulement `users.plan`. Le moindre
événement Stripe du compte (fin d'un essai, paiement, impayé) recalculait le
plan d'après les SEULS abonnements et effaçait le cadeau — un gagnant qui
prenait ensuite un abonnement Standard perdait son Expert offert au premier
paiement.

L'accès offert est désormais un fait daté du journal des abonnements
(`acces_offert` / `acces_offert_retire`, jamais modifiés) :
  · `plan_offert_actif` le relit ; `stripe_routes._plan_effectif` en tient
    compte partout où le plan est recalculé (formule la plus haute des deux) ;
  · une date de fin est possible (« 1 mois Expert offert ») ; à l'échéance, la
    tâche `expirer_acces_offerts` rend au compte le plan que ses abonnements
    justifient, sans toucher à rien d'autre ;
  · le journal garde qui a offert quoi, quand, pour quelle raison.

Pas de nouvelle colonne : une migration aurait croisé celles de la branche du
défi du mois (0056-0057), en attente de déploiement.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SubscriptionEvent, User

log = structlog.get_logger()

PLANS_OFFRABLES = ("standard", "expert")
TYPES = ("acces_offert", "acces_offert_retire")


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


async def dernier_acces_offert(db: AsyncSession, user_id: str) -> Optional[dict]:
    """Dernier don ENCORE EN VIGUEUR ou non : {plan, jusqu_au, motif, depuis, actif}."""
    evs = (await db.execute(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.user_id == user_id, SubscriptionEvent.type.in_(TYPES))
    )).scalars().all()
    # Ordre par horodatage fin (`t`, ns) : deux gestes dans la même seconde
    # (offrir puis retirer) restent départagés — le dernier gagne.
    def _cle(e):
        d = e.detail if isinstance(e.detail, dict) else {}
        return (d.get("t") or 0, _aware(e.created_at) or datetime.min.replace(tzinfo=timezone.utc))
    ev = max(evs, key=_cle, default=None)
    if ev is None or ev.type != "acces_offert":
        return None
    detail = ev.detail if isinstance(ev.detail, dict) else {}
    jusqu_au = detail.get("jusqu_au")
    fin = datetime.fromisoformat(jusqu_au) if jusqu_au else None
    fin = _aware(fin)
    return {
        "plan": ev.plan,
        "jusqu_au": fin,
        "motif": detail.get("motif"),
        "par": detail.get("par"),
        "depuis": _aware(ev.created_at),
        "actif": fin is None or fin > datetime.now(timezone.utc),
    }


async def plan_offert_actif(db: AsyncSession, user_id: str) -> Optional[str]:
    don = await dernier_acces_offert(db, user_id)
    return don["plan"] if don and don["actif"] else None


async def offrir(db: AsyncSession, user: User, plan: str, jours: Optional[int],
                 motif: str, par: Optional[str]) -> dict:
    from api.routes.stripe_routes import _plan_effectif
    from services.abonnements import journaliser

    if plan not in PLANS_OFFRABLES:
        raise ValueError("Formule invalide (standard ou expert)")
    fin = datetime.now(timezone.utc) + timedelta(days=jours) if jours else None
    await journaliser(db, "acces_offert", user, None, plan=plan, notifier=False,
                      detail={"t": time.time_ns(), "jusqu_au": fin.isoformat() if fin else None,
                              "motif": (motif or "").strip()[:200] or None, "par": par})
    await db.flush()
    user.plan = await _plan_effectif(user.user_id, db)
    await db.commit()
    log.info("acces_offert.accorde", user_id=user.user_id, plan=plan, jusqu_au=fin, motif=motif)
    return {"plan_offert": plan, "jusqu_au": fin, "plan": user.plan}


async def retirer(db: AsyncSession, user: User, par: Optional[str], raison: str = "retire") -> str:
    from api.routes.stripe_routes import _plan_effectif
    from services.abonnements import journaliser

    await journaliser(db, "acces_offert_retire", user, None, notifier=False,
                      detail={"t": time.time_ns(), "par": par, "raison": raison})
    await db.flush()
    user.plan = await _plan_effectif(user.user_id, db)
    await db.commit()
    log.info("acces_offert.retire", user_id=user.user_id, plan_restant=user.plan, raison=raison)
    return user.plan


async def expirer_acces_offerts(db: AsyncSession) -> int:
    """Clôt les dons arrivés à échéance : le compte retrouve le plan que ses
    abonnements justifient (souvent « free », ou sa formule payante)."""
    n = 0
    ids = {uid for (uid,) in (await db.execute(
        select(SubscriptionEvent.user_id).where(SubscriptionEvent.type == "acces_offert")
    )).all() if uid}
    for uid in ids:
        don = await dernier_acces_offert(db, uid)
        if don is None or don["actif"]:
            continue
        user = await db.get(User, uid)
        if user is None:
            continue
        await retirer(db, user, par="systeme", raison="echeance")
        n += 1
    return n
