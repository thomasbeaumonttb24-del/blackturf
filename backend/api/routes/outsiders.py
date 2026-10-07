"""
Outsiders du jour — routes (cerveau `ml.outsider_brain`).

Accès (décisions Thomas, 07/10/2026) :
- Standard et Expert (passes comprises, qui donnent le plan Expert) : tout,
  courses à venir et courses courues.
- Sans compte et compte gratuit : les courses COURUES en clair (l'outsider
  détecté et son résultat) ; pour les courses à venir, des cartes verrouillées
  qui ne portent QUE le niveau — rien qui permette de retrouver la course ou le
  cheval. Sur une fiche course à venir : rien du tout (la page désigne déjà la
  course). Le filtre est ici, côté serveur, jamais seulement à l'affichage.
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

router = APIRouter()

# « starter » et « pro » : anciens noms de Standard et d'Expert.
PLANS_OUTSIDERS = ("standard", "starter", "expert", "pro")


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
    return bool(user) and (user.plan in PLANS_OUTSIDERS or bool(getattr(user, "is_admin", False)))


def verrouiller(l: dict) -> dict:
    """Carte d'une course À VENIR pour un non-abonné : son niveau, rien d'autre.

    Ni course, ni hippodrome, ni heure, ni numéro, casaque, jockey ou cote : la
    moindre de ces données suffit à retrouver le cheval sur pmu.fr."""
    return {"verrouille": True, "termine": False, "niveau": l["niveau"]}


def filtrer(lignes: list[dict], complet: bool) -> list[dict]:
    """Abonné : tout. Sinon : courses courues en clair (le résultat est public),
    courses à venir réduites à une carte verrouillée anonyme."""
    if complet:
        return [dict(l, verrouille=False) for l in lignes]
    courus = [dict(l, verrouille=False) for l in lignes if l["termine"]]
    a_venir = [verrouiller(l) for l in lignes if not l["termine"] and not l.get("non_partant")]
    # Ordre neutre (forts d'abord) : l'ordre chronologique trahirait l'horaire.
    a_venir.sort(key=lambda x: x["niveau"] != "fort")
    return a_venir + courus


@router.get("/outsiders/jour", dependencies=[Depends(rate_limit_public)])
async def outsiders_du_jour(
    jour: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    lignes = await outsiders.lister(db, jour=jour)
    complet = acces_complet(user)
    return {"jour": (jour or outsiders.datetime.now(outsiders.PARIS).date()).isoformat(),
            "acces_complet": complet, "outsiders": filtrer(lignes, complet)}


@router.get("/outsiders/course/{course_id}", dependencies=[Depends(rate_limit_public)])
async def outsiders_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    lignes = await outsiders.lister(db, course_id=course_id)
    complet = acces_complet(user)
    # Fiche course : une carte verrouillée y désignerait déjà la course.
    visibles = filtrer(lignes, complet) if complet else [dict(l, verrouille=False) for l in lignes if l["termine"]]
    return {"acces_complet": complet, "outsiders": visibles}


@router.get("/outsiders/bilan", dependencies=[Depends(rate_limit_public)])
async def outsiders_bilan(
    jours: int = Query(default=30, ge=7, le=120),
    db: AsyncSession = Depends(get_db),
):
    b = await outsiders.bilan(db, jours=jours)
    b["validation"] = outsiders.validation_modele()
    return b
