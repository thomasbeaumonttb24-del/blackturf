"""
Publication automatique sur Instagram (Graph API de publication de contenu).

FONCTIONNEMENT EN DEUX TEMPS, imposé par Meta :
1. `POST /{ig_user_id}/media` avec l'URL de l'image et la légende → renvoie un
   « conteneur », que Meta va chercher et prépare de son côté ;
2. `POST /{ig_user_id}/media_publish` avec l'identifiant du conteneur → publie.

L'image doit être en **JPEG** et servie par une URL publique : Meta la télécharge
lui-même, il ne reçoit aucun fichier. D'où `/visuels/*.jpg` côté site.

────────────────────────── L'INTERRUPTEUR EST FERMÉ PAR DÉFAUT ──────────────────────────
`INSTAGRAM_PUBLICATION_ACTIVE` vaut 0 tant que personne ne l'a explicitement mis à 1.
Dans cet état, le service fait tout — construction, vérifications, journalisation — SAUF
l'appel qui publie. Publier au nom d'une marque est irréversible et public : ça ne doit
jamais démarrer parce qu'un jeton s'est trouvé présent dans l'environnement.
"""
from typing import Optional

import httpx
import structlog

from api.config import get_settings

log = structlog.get_logger()
settings = get_settings()

VERSION = "v21.0"
BASE = f"https://graph.facebook.com/{VERSION}"

# Une légende Instagram est plafonnée à 2 200 caractères. Au-delà, l'API rejette la
# publication entière : on tronque proprement plutôt que de perdre le post.
MAX_LEGENDE = 2200


class ResultatPublication:
    """Sortie explicite : un booléen seul ne dit pas POURQUOI un envoi n'est pas parti."""

    def __init__(self, publie: bool, media_id: Optional[str] = None, raison: Optional[str] = None):
        self.publie = publie
        self.media_id = media_id
        self.raison = raison

    def __bool__(self) -> bool:
        return self.publie

    def __repr__(self) -> str:
        return f"ResultatPublication(publie={self.publie}, media_id={self.media_id}, raison={self.raison})"


def _configure() -> tuple[Optional[str], Optional[str]]:
    jeton = getattr(settings, "meta_access_token", "") or None
    compte = getattr(settings, "instagram_user_id", "") or None
    return jeton, compte


def publication_active() -> bool:
    return bool(getattr(settings, "instagram_publication_active", False))


def _tronquer(legende: str) -> str:
    if len(legende) <= MAX_LEGENDE:
        return legende
    return legende[: MAX_LEGENDE - 1].rstrip() + "…"


async def publier_image(url_image: str, legende: str) -> ResultatPublication:
    """
    Publie une image sur le compte Instagram configuré.

    Best-effort : ne lève jamais. Le poste est appelé depuis un job programmé, et une
    exception non rattrapée y arrêterait les tâches suivantes.
    """
    jeton, compte = _configure()
    if not jeton or not compte:
        return ResultatPublication(False, raison="jeton ou identifiant de compte absent")

    if not url_image.startswith("https://"):
        # Meta refuse une URL non https, et un lien local ne lui serait de toute façon
        # pas accessible : autant le dire ici, avec la vraie raison.
        return ResultatPublication(False, raison="l'image doit être servie en https")

    if not publication_active():
        log.info(
            "instagram.simulation",
            url_image=url_image,
            taille_legende=len(legende),
            detail="INSTAGRAM_PUBLICATION_ACTIVE=0 — rien n'a été publié",
        )
        return ResultatPublication(False, raison="publication désactivée (mode simulation)")

    legende = _tronquer(legende)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            conteneur = await client.post(
                f"{BASE}/{compte}/media",
                data={"image_url": url_image, "caption": legende, "access_token": jeton},
            )
            if conteneur.status_code != 200:
                log.warning(
                    "instagram.conteneur.refuse",
                    status=conteneur.status_code,
                    corps=conteneur.text[:300],
                )
                return ResultatPublication(
                    False, raison=f"création du conteneur refusée ({conteneur.status_code})"
                )

            creation_id = conteneur.json().get("id")
            if not creation_id:
                return ResultatPublication(False, raison="conteneur sans identifiant")

            publication = await client.post(
                f"{BASE}/{compte}/media_publish",
                data={"creation_id": creation_id, "access_token": jeton},
            )
            if publication.status_code != 200:
                log.warning(
                    "instagram.publication.refusee",
                    status=publication.status_code,
                    corps=publication.text[:300],
                )
                return ResultatPublication(
                    False, raison=f"publication refusée ({publication.status_code})"
                )

            media_id = publication.json().get("id")
            log.info("instagram.publie", media_id=media_id, url_image=url_image)
            return ResultatPublication(True, media_id=media_id)

    except Exception as e:  # noqa: BLE001
        log.warning("instagram.echec", err=f"{type(e).__name__}: {e}"[:300])
        return ResultatPublication(False, raison=f"{type(e).__name__}: {e}"[:200])


async def quota_restant() -> Optional[int]:
    """
    Publications encore possibles sur la fenêtre glissante de 24 h (plafond Meta : 100).

    None = information indisponible. Utile en journal : dépasser le quota fait échouer
    toutes les publications suivantes sans autre explication qu'un code d'erreur.
    """
    jeton, compte = _configure()
    if not jeton or not compte:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{BASE}/{compte}/content_publishing_limit",
                params={"access_token": jeton},
            )
        if resp.status_code != 200:
            return None
        data = (resp.json().get("data") or [{}])[0]
        return max(0, 100 - int(data.get("quota_usage", 0)))
    except Exception:  # noqa: BLE001
        return None
