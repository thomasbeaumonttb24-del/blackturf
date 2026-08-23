"""
IndexNow — signalement immédiat des URLs nouvelles ou modifiées.

Un seul appel prévient Bing, Yandex, Naver et Seznam qu'une URL vient d'apparaître ou de
changer, au lieu d'attendre qu'un robot repasse de lui-même. Sur un site dont l'essentiel
du contenu vit une journée — le programme du matin, les arrivées du soir — attendre le
prochain passage revient à publier pour personne.

**Google n'utilise PAS IndexNow.** Rien ici n'accélère l'indexation Google, qui passe par
le sitemap et Search Console. Ne jamais présenter ce module comme un levier Google.

Le protocole tient en deux pièces :
1. une clé, publiée en clair à `https://blackturf.fr/<clé>.txt`, dont le contenu est la
   clé elle-même — c'est ce qui prouve qu'on possède le domaine ;
2. un POST JSON vers `api.indexnow.org` listant les URLs.

La clé n'est pas un secret : elle est publiée sur le site par construction. Elle
n'autorise qu'une chose, signaler des URLs de CE domaine.
"""
from typing import Iterable, Optional

import httpx
import structlog

from api.config import get_settings

log = structlog.get_logger()
settings = get_settings()

ENDPOINT = "https://api.indexnow.org/indexnow"
HOTE = "blackturf.fr"

# Le protocole plafonne à 10 000 URLs par requête. On reste très en dessous : une journée
# de courses, c'est environ 250 URLs.
MAX_URLS = 10_000


def _cle() -> Optional[str]:
    return getattr(settings, "indexnow_key", None) or None


async def signaler(urls: Iterable[str]) -> int:
    """
    Signale une liste d'URLs. Renvoie le nombre d'URLs effectivement envoyées.

    Best-effort de bout en bout : ce module ne doit JAMAIS faire échouer l'appelant.
    Un signalement raté ne coûte qu'un délai d'indexation, alors qu'une exception
    remontée depuis un job de scraping ferait perdre des données de course.
    """
    cle = _cle()
    if not cle:
        log.info("indexnow.desactive")  # clé absente = fonction simplement inactive
        return 0

    liste = [u for u in dict.fromkeys(urls) if u.startswith(f"https://{HOTE}/")][:MAX_URLS]
    if not liste:
        return 0

    payload = {
        "host": HOTE,
        "key": cle,
        "keyLocation": f"https://{HOTE}/{cle}.txt",
        "urlList": liste,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(ENDPOINT, json=payload)
        # 200 = accepté, 202 = accepté mais clé encore en cours de validation.
        if resp.status_code in (200, 202):
            log.info("indexnow.ok", nb=len(liste), status=resp.status_code)
            return len(liste)
        log.warning("indexnow.refuse", status=resp.status_code, corps=resp.text[:200])
    except Exception as e:  # noqa: BLE001
        log.warning("indexnow.echec", err=f"{type(e).__name__}: {e}"[:200])
    return 0


def urls_du_jour(course_ids: Iterable[str], jour_iso: str) -> list[str]:
    """
    Les URLs qui changent une fois par jour : les pages du jour, l'archive de la veille,
    et la fiche de chaque course.

    On ne signale pas l'accueil ni les pages éditoriales : leur contenu ne bouge pas, et
    signaler sans cesse des URLs inchangées est le meilleur moyen de se faire ignorer.
    """
    base = f"https://{HOTE}"
    urls = [
        f"{base}/programme",
        f"{base}/quinte-du-jour",
        f"{base}/resultats",
        f"{base}/resultats/{jour_iso}",
    ]
    urls += [f"{base}/courses/{cid}" for cid in course_ids]
    return urls
