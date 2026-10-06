"""
Throttling sans dépendance sur les routes (évite l'import circulaire avec auth).
Contient le rate-limit anti-brute-force des endpoints d'authentification et le
helper d'IP cliente réelle (derrière nginx).
"""
import hmac

from fastapi import Depends, HTTPException, Request, status
import redis.asyncio as aioredis

from api.config import get_settings
from db.redis_client import get_redis


def _client_ip(request: Request) -> str:
    """IP cliente RÉELLE derrière nginx. nginx pose X-Real-IP = $remote_addr (le
    pair TCP réel, non spoofable par le client). On NE lit PAS X-Forwarded-For brut
    (appendé → un client peut y injecter des valeurs). Fallback sur l'IP de socket.

    Le fallback n'est pas théorique : le rendu serveur du frontend appelle l'API
    en direct sur `http://api:8000` (réseau Docker), SANS passer par nginx — il n'y
    a donc pas de X-Real-IP, et c'est l'adresse du conteneur qui fait foi. Un
    en-tête présent mais vide est traité comme absent : sinon tous ces appels se
    retrouveraient dans le même compteur `rl:...:` à clé vide."""
    xri = (request.headers.get("x-real-ip") or "").strip()
    if xri:
        return xri
    return request.client.host if request.client else "unknown"


def est_appel_interne(request: Request) -> bool:
    """Vrai si la requête vient du rendu serveur du frontend (en-tête X-BT-Interne).

    Pourquoi une exemption : le rendu serveur de TOUTES les pages publiques sort
    d'une seule adresse. Un visiteur malveillant qui boucle sur une route rendue
    côté serveur (par exemple /visuels/mosaique/legendes.json, lue sans cache)
    vidait ce seau commun ; chaque lecture SSR prenait alors un 429 et les pages
    sortaient vides pour tout le monde — puis restaient vides en cache ISR.

    Pourquoi c'est sûr : nginx EFFACE cet en-tête sur toutes ses locations
    (`proxy_set_header X-BT-Interne ""`), donc il ne peut arriver que par le réseau
    Docker, et il doit en plus égaler le secret. `compare_digest` : comparaison à
    temps constant, pour ne pas laisser deviner le secret octet par octet.
    Secret vide côté réglages = exemption coupée, quel que soit l'en-tête reçu."""
    secret = get_settings().bt_secret_interne
    if not secret:
        return False
    recu = request.headers.get("x-bt-interne")
    if not recu:
        return False
    return hmac.compare_digest(recu.encode("utf-8"), secret.encode("utf-8"))


async def rate_limit_auth(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Anti-brute-force sur les endpoints d'authentification (login/register/reset).
    10 tentatives / 5 min / IP, puis 429. Protège contre le credential-stuffing et
    le spam d'emails (forgot-password). Fail-open si Redis est indisponible (ne pas
    bloquer l'auth légitime sur panne cache).

    PAS d'exemption `est_appel_interne` ici, volontairement : le rendu serveur ne
    se connecte jamais, ne crée aucun compte et ne réinitialise aucun mot de passe.
    L'exemption n'y apporterait rien, et un secret qui fuiterait deviendrait un
    passe-droit de credential-stuffing illimité."""
    ip = _client_ip(request)
    key = f"rl:auth:{ip}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        # TTL posé UNIQUEMENT à la création : réarmé à chaque tentative, il donnait
        # une fenêtre GLISSANTE, et un utilisateur légitime qui se trompe puis
        # réessaie toutes les minutes restait bloqué INDÉFINIMENT — chaque essai
        # repoussait sa propre libération. La protection ne faiblit pas pour autant :
        # 10 tentatives par tranche de 5 minutes plafonnent un attaquant à 120
        # essais/heure, et le compteur repart de zéro seulement une fois la fenêtre
        # réellement écoulée.
        pipe.expire(key, 300, nx=True)
        n = (await pipe.execute())[0]
    except Exception:
        return  # fail-open : panne Redis ne doit pas verrouiller l'auth
    if n > 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessayez dans quelques minutes.",
            headers={"Retry-After": "300"},
        )
