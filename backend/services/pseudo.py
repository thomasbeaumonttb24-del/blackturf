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


# Caractères qui se lisent comme une lettre réservée : « BIackTurf » (i majuscule),
# « 4dmin », « m0do », « àdmin » passaient le contrôle et imitaient l'équipe.
_SOSIES = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t",
                         "8": "b", "_": "", ".": "", "-": ""})


def _squelette(p: str) -> str:
    """Forme ramenée à ses lettres de base, pour comparer aux mots réservés."""
    import unicodedata
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", p)
                           if not unicodedata.combining(c))
    return sans_accents.lower().translate(_SOSIES)


def _reserve(p: str) -> bool:
    s = _squelette(p)
    # « I » majuscule et « l » se confondent à l'écran : on teste les deux lectures.
    variantes = {s, s.replace("i", "l"), s.replace("l", "i")}
    return any(m in v for v in variantes for m in MOTS_RESERVES)


def normaliser(pseudo: Optional[str], *, admin: bool = False) -> str:
    p = (pseudo or "").strip()
    if not PSEUDO_RE.match(p):
        raise PseudoRefuse(MSG_FORMAT)
    if not admin and _reserve(p):
        raise PseudoRefuse(MSG_RESERVE)
    return p


async def verifier_disponible(db, pseudo: str, sauf_user_id: Optional[str] = None) -> None:
    q = select(User.user_id).where(func.lower(User.pseudo) == pseudo.lower())
    if sauf_user_id:
        q = q.where(User.user_id != sauf_user_id)
    if await db.scalar(q):
        raise PseudoRefuse(MSG_PRIS, code=409)
