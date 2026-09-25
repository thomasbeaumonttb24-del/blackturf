"""
Pseudo public d'un compte : affiché au classement du Défi du mois et dans la
Communauté, jamais le prénom ni l'e-mail. Obligatoire à l'inscription ; les
comptes créés avant (ou via Google) le choisissent à leur prochaine visite.

Une seule règle pour tout le site : unicité insensible à la casse (index unique
sur lower(pseudo), cf. migration 0049), 3 à 20 caractères, et aucun mot qui
ferait passer un membre pour l'équipe.
"""
import re
from typing import Optional

from sqlalchemy import func, select

from db.models import User

PSEUDO_RE = re.compile(r"^[A-Za-z0-9À-ÖØ-öø-ÿ_.-]{3,20}$")
# Sous-chaînes qui feraient passer un membre pour l'équipe du site.
MOTS_RESERVES = ("admin", "blackturf", "modera", "modéra", "modo", "support", "staff")

MSG_FORMAT = "Pseudo : 3 à 20 caractères — lettres, chiffres, point, tiret ou soulignement."
MSG_RESERVE = "Ce pseudo est réservé à l'équipe du site."
MSG_PRIS = "Ce pseudo est déjà pris."


class PseudoRefuse(ValueError):
    """Pseudo invalide ou indisponible ; ``code`` = statut HTTP à renvoyer."""

    def __init__(self, message: str, code: int = 422):
        super().__init__(message)
        self.code = code


def normaliser(pseudo: Optional[str], *, admin: bool = False) -> str:
    p = (pseudo or "").strip()
    if not PSEUDO_RE.match(p):
        raise PseudoRefuse(MSG_FORMAT)
    if not admin and any(m in p.lower() for m in MOTS_RESERVES):
        raise PseudoRefuse(MSG_RESERVE)
    return p


async def verifier_disponible(db, pseudo: str, sauf_user_id: Optional[str] = None) -> None:
    q = select(User.user_id).where(func.lower(User.pseudo) == pseudo.lower())
    if sauf_user_id:
        q = q.where(User.user_id != sauf_user_id)
    if await db.scalar(q):
        raise PseudoRefuse(MSG_PRIS, code=409)
