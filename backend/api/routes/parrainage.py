"""Parrainage — BlackTurf.

Toute la mécanique est dans `services/parrainage.py` ; ces routes ne font
qu'afficher. Il n'existe volontairement AUCUNE route pour rattacher un parrain
après coup ni pour déclencher une récompense : le parrain se fixe à
l'inscription, la récompense au paiement confirmé par Stripe.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_verified_email
from db.database import get_db
from db.models import User
from services import parrainage

router = APIRouter()


@router.get("/parrainage")
async def mon_parrainage(db: AsyncSession = Depends(get_db),
                         user: User = Depends(require_verified_email)):
    """Lien d'invitation, filleuls et crédit restant du compte connecté."""
    return await parrainage.resume(user, db)


@router.get("/parrainage/code/{code}")
async def verifier_code(code: str, db: AsyncSession = Depends(get_db)):
    """Page d'inscription : le code du lien est-il valable ? Ne renvoie que le
    prénom du parrain, pour afficher « invité par … ». L'espace des codes
    (27^8) rend l'énumération sans intérêt."""
    parrain = await parrainage.parrain_du_code(code, db)
    if parrain is None:
        return {"valide": False}
    return {
        "valide": True,
        "code": parrain.code_parrain,
        "prenom": (parrain.prenom or "").split(" ")[0][:20] or None,
        "remise_cents": parrainage.REMISE_CENTS,
    }
