"""
Garde-fou contre l'usage du site comme canon à e-mails.

Le quota par IP ne protège ni la boîte visée (dix machines suffisent à l'inonder) ni
le compte Resend : tous les e-mails du site — confirmation d'inscription, mot de passe
oublié, confirmations de passe — partent du même compte. Un formulaire public qui
expédie à volonté peut donc épuiser le quota et couper les envois qui comptent, ou
faire suspendre le domaine sur plaintes pour spam.

Deux verrous, dans Redis :
  - un délai par destinataire (clé = empreinte de l'adresse, jamais l'adresse en clair) ;
  - un plafond horaire global par catégorie d'envoi.

Panne Redis → on laisse passer : le quota par IP tient encore la porte, et un
formulaire qui cesse d'envoyer quand Redis tousse se lirait comme un site cassé.
"""
import hashlib
from datetime import datetime, timezone

import structlog

log = structlog.get_logger()


def _empreinte(destinataire: str) -> str:
    return hashlib.sha256(destinataire.strip().lower().encode()).hexdigest()[:32]


async def envoi_autorise(
    categorie: str,
    destinataire: str,
    delai_s: int,
    plafond_heure: int | None = None,
) -> bool:
    """True si on peut envoyer `categorie` à `destinataire` maintenant.

    Pose le verrou par destinataire au passage : deux appels rapprochés ne
    passent pas tous les deux.
    """
    from db.redis_client import get_redis
    try:
        r = await get_redis()
        if plafond_heure is not None:
            heure = datetime.now(timezone.utc).strftime("%Y%m%d%H")
            cle_globale = f"garde_envoi:{categorie}:h:{heure}"
            n = await r.incr(cle_globale)
            if n == 1:
                await r.expire(cle_globale, 3700)
            if n > plafond_heure:
                log.warning("garde_envoi.plafond_global", categorie=categorie, n=n)
                return False
        cle = f"garde_envoi:{categorie}:{_empreinte(destinataire)}"
        ok = bool(await r.set(cle, "1", ex=delai_s, nx=True))
        if not ok:
            log.info("garde_envoi.delai", categorie=categorie)
        return ok
    except Exception as exc:  # pragma: no cover — dépend de Redis
        log.warning("garde_envoi.redis_indisponible", erreur=str(exc))
        return True
