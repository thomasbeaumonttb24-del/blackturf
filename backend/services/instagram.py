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

# DEUX VOIES D'ACCES EXISTENT, et elles n'ont pas les memes prerequis :
#
#   - « Instagram API with Facebook Login » -> hote graph.facebook.com, et le compte
#     Instagram DOIT etre lie a une Page Facebook ;
#   - « Instagram API with Instagram Login » -> hote graph.instagram.com, et un simple
#     compte Instagram professionnel suffit, SANS Page.
#
# On prend la seconde : la liaison a une Page passe par une interface Meta defaillante
# (bouton inerte au clic comme au clavier) et n'apporte rien de plus ici. L'hote reste
# configurable pour pouvoir basculer sans redeployer si Meta ferme cette voie.
def _base() -> str:
    hote = getattr(settings, "instagram_api_host", "") or "graph.instagram.com"
    return f"https://{hote}/{VERSION}"


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


async def _configure() -> tuple[Optional[str], Optional[str]]:
    """
    (jeton, identifiant de compte).

    Le jeton est lu EN BASE en priorite : il y est depose depuis l'administration et
    renouvele automatiquement tous les deux mois. La variable d'environnement ne sert
    que de repli, pour un depannage ou un environnement de test — un secret pose dans un
    fichier ne se renouvelle pas tout seul et finit par expirer sans prevenir.
    """
    compte = getattr(settings, "instagram_user_id", "") or None

    try:
        from db.database import AsyncSessionLocal
        from services.jetons import lire

        async with AsyncSessionLocal() as session:
            enregistre = await lire(session)
            if enregistre and enregistre.valeur:
                return enregistre.valeur, (enregistre.compte_id or compte)
    except Exception as e:  # noqa: BLE001
        # Base indisponible : on retombe sur l'environnement plutot que d'echouer.
        log.warning("instagram.jeton.lecture_base_impossible", err=str(e)[:160])

    return (getattr(settings, "meta_access_token", "") or None), compte


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
    jeton, compte = await _configure()
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
                f"{_base()}/{compte}/media",
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
                f"{_base()}/{compte}/media_publish",
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
    jeton, compte = await _configure()
    if not jeton or not compte:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_base()}/{compte}/content_publishing_limit",
                params={"access_token": jeton},
            )
        if resp.status_code != 200:
            return None
        data = (resp.json().get("data") or [{}])[0]
        return max(0, 100 - int(data.get("quota_usage", 0)))
    except Exception:  # noqa: BLE001
        return None
