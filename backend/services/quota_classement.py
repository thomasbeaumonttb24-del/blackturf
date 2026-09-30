"""Quota journalier du classement de l'algorithme (et du plan de mise).

Règle (arrêtée par l'exploitant le 2026-09-30) : un compte gratuit ouvre le
classement COMPLET d'UNE course à venir par jour ; sans compte, aucun. Standard
5/jour, Expert illimité.

Ce module est l'unique porte de ce quota. Ce qu'il ferme, et pourquoi :

- COURSE CONCURRENTE. L'ancien contrôle lisait `SCARD` puis écrivait `SADD` en
  deux allers-retours : deux requêtes simultanées sur deux courses passaient
  toutes les deux. Ici, lecture, contrôle et écriture tiennent dans UN script
  Lua, exécuté atomiquement par Redis.
- REDIS INDISPONIBLE. L'ancien contrôle laissait passer (« fail-open ») : une
  panne Redis offrait le classement illimité. Pour un plan gratuit, on refuse
  désormais ; un abonné payant garde l'accès (il a payé, la panne est la nôtre).
- ALIAS D'ADRESSE. `nom+1@gmail.com`, `nom+2@gmail.com`, `n.o.m@gmail.com`
  arrivent dans la MÊME boîte : autant de comptes gratuits confirmables par une
  seule personne. Le quota est donc tenu par l'adresse NORMALISÉE, pas par le
  compte : tous ces comptes partagent la même course du jour.
- JOUR. Le « jour » est celui de Paris (les courses sont françaises) et non plus
  UTC : le quota ne se renouvelle plus à 2 h du matin, heure d'été.

Ce qu'il ne ferme pas : plusieurs boîtes mail RÉELLES et distinctes. Les
adresses jetables sont déjà refusées à l'inscription (services/adresse_email) et
la connexion exige une adresse confirmée ; au-delà, une IP ne serait pas un
critère fiable (le rendu serveur Next et les opérateurs mobiles la partagent).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

log = structlog.get_logger()

PARIS = ZoneInfo("Europe/Paris")

# Courses distinctes par jour. Plan absent = illimité (expert, admin).
LIMITES_CLASSEMENT = {"free": 1, "decouverte": 1, "standard": 5, "starter": 5}
PLANS_GRATUITS = ("free", "decouverte")

TTL_S = 36 * 3600

# Atomique : déjà ouverte → OK sans rien consommer ; sinon refus si plafond
# atteint ; sinon ajout. Renvoie {autorisé (0/1), nb de courses utilisées}.
_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
  return {1, redis.call('SCARD', KEYS[1])}
end
local n = redis.call('SCARD', KEYS[1])
if n >= tonumber(ARGV[2]) then
  return {0, n}
end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return {1, n + 1}
"""

_DOMAINES_SANS_POINTS = {"gmail.com", "googlemail.com"}


def adresse_canonique(email: str | None) -> str:
    """Adresse ramenée à la boîte qui reçoit réellement le courrier.

    - casse ignorée ;
    - sous-adresse `+étiquette` retirée (Gmail, Outlook, iCloud, Proton, Fastmail
      la délivrent toutes à la boîte principale) ;
    - Gmail ignore les points de la partie locale, et `googlemail.com` est le
      même service.
    """
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, _, domaine = e.rpartition("@")
    local = local.split("+", 1)[0]
    if domaine in _DOMAINES_SANS_POINTS:
        local = local.replace(".", "")
        domaine = "gmail.com"
    return f"{local}@{domaine}"


def _identite(user) -> str:
    """Titulaire du quota : l'adresse canonique (hachée — pas d'e-mail en clair
    dans Redis), à défaut l'identifiant du compte."""
    email = getattr(user, "email", None)
    if email:
        return "m:" + hashlib.sha256(adresse_canonique(email).encode()).hexdigest()[:32]
    return "u:" + str(getattr(user, "user_id", ""))


def jour_paris(maintenant: datetime | None = None) -> str:
    return (maintenant or datetime.now(PARIS)).astimezone(PARIS).strftime("%Y-%m-%d")


# Seuls plans illimités. Tout plan INCONNU (valeur inattendue, ancien nom) est
# traité comme gratuit : l'ancien `LIMITES.get(plan)` rendait None — illimité —
# pour n'importe quelle valeur absente de la table.
PLANS_ILLIMITES = ("expert", "pro")


def limite(user) -> int | None:
    """Plafond du compte ; None = illimité."""
    if getattr(user, "is_admin", False):
        return None
    plan = getattr(user, "plan", None)
    if plan in PLANS_ILLIMITES:
        return None
    return LIMITES_CLASSEMENT.get(plan, LIMITES_CLASSEMENT["free"])


def cle(user, prefixe: str = "classement") -> str:
    return f"quota:{prefixe}:{_identite(user)}:{jour_paris()}"


async def _redis():
    from db.redis_client import get_redis
    return await get_redis()


async def consommer(user, course_id: str, prefixe: str = "classement") -> tuple[bool, int]:
    """Ouvre `course_id` pour ce compte. (autorisé, restant ; -1 = illimité).

    Ré-ouvrir une course déjà comptée aujourd'hui ne consomme rien."""
    lim = limite(user)
    if lim is None:
        return True, -1
    try:
        r = await _redis()
        ok, n = await r.eval(_SCRIPT, 1, cle(user, prefixe), course_id, lim, TTL_S)
        return bool(int(ok)), max(0, lim - int(n))
    except Exception:
        gratuit = getattr(user, "plan", None) in PLANS_GRATUITS
        log.warning("quota_classement.redis_indisponible", prefixe=prefixe,
                    user_id=getattr(user, "user_id", None), refuse=gratuit)
        # Gratuit : on refuse (sinon une panne = classement illimité). Payant : on sert.
        return (False, 0) if gratuit else (True, -1)


async def etat(user, prefixe: str = "classement") -> dict:
    """Lecture seule : plafond, restant et courses déjà ouvertes aujourd'hui."""
    lim = limite(user)
    if lim is None:
        return {"limite": None, "restant": -1, "courses": []}
    try:
        r = await _redis()
        membres = await r.smembers(cle(user, prefixe))
        courses = sorted(m.decode() if isinstance(m, bytes) else str(m) for m in membres)
    except Exception:
        log.warning("quota_classement.etat_indisponible", user_id=getattr(user, "user_id", None))
        return {"limite": lim, "restant": 0, "courses": [], "indisponible": True}
    return {"limite": lim, "restant": max(0, lim - len(courses)), "courses": courses}


async def deja_ouverte(user, course_id: str, prefixe: str = "classement") -> bool:
    """La course fait-elle déjà partie des ouvertures du jour ? (sans consommer)"""
    if limite(user) is None:
        return True
    try:
        r = await _redis()
        return bool(await r.sismember(cle(user, prefixe), course_id))
    except Exception:
        return False
