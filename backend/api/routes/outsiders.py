"""
Outsiders du jour — routes publiques (cerveau `ml.outsider_brain`).

Tout le monde voit QUELLES courses ont un outsider repéré et le bilan réel ;
le nom, la cote et les raisons d'un outsider de course À VENIR sont réservés aux
abonnés (même liste blanche que les paris de valeur). Une course terminée est
publique : le résultat ne se vend plus, il prouve.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import rate_limit_public
from api.routes.auth import _access_token, get_current_user
from db.database import get_db
from db.models import User
from services import outsiders
from services.valuebets_visibilite import PLANS_AVEC_VALUE_BETS

router = APIRouter()

# La casaque et le jockey identifient le cheval autant que son nom : masqués aussi.
_MASQUES = ("numero", "nom_cheval", "casaque_image_url", "jockey", "cote_signal", "cote_actuelle",
            "chance_place", "raisons")


async def _utilisateur_optionnel(
    token: Optional[str] = Depends(_access_token),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


def acces_complet(user: Optional[User]) -> bool:
    return bool(user) and (user.plan in PLANS_AVEC_VALUE_BETS or bool(getattr(user, "is_admin", False)))


def masquer(lignes: list[dict], complet: bool) -> list[dict]:
    if complet:
        return [dict(l, verrouille=False) for l in lignes]
    out = []
    for l in lignes:
        if l["termine"]:
            out.append(dict(l, verrouille=False))
        else:
            masque = {k: v for k, v in l.items() if k not in _MASQUES}
            masque.update({k: None for k in _MASQUES}, raisons=[], verrouille=True)
            out.append(masque)
    return out


@router.get("/outsiders/jour", dependencies=[Depends(rate_limit_public)])
async def outsiders_du_jour(
    jour: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    lignes = await outsiders.lister(db, jour=jour)
    complet = acces_complet(user)
    return {"jour": (jour or outsiders.datetime.now(outsiders.PARIS).date()).isoformat(),
            "acces_complet": complet, "outsiders": masquer(lignes, complet)}


@router.get("/outsiders/course/{course_id}", dependencies=[Depends(rate_limit_public)])
async def outsiders_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    lignes = await outsiders.lister(db, course_id=course_id)
    complet = acces_complet(user)
    return {"acces_complet": complet, "outsiders": masquer(lignes, complet)}


@router.get("/outsiders/bilan", dependencies=[Depends(rate_limit_public)])
async def outsiders_bilan(
    jours: int = Query(default=30, ge=7, le=120),
    db: AsyncSession = Depends(get_db),
):
    b = await outsiders.bilan(db, jours=jours)
    b["validation"] = outsiders.validation_modele()
    return b
