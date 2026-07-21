"""
Throttling sans dépendance sur les routes (évite l'import circulaire avec auth).
Contient le rate-limit anti-brute-force des endpoints d'authentification et le
helper d'IP cliente réelle (derrière nginx).
"""
from fastapi import Depends, HTTPException, Request, status
import redis.asyncio as aioredis

from db.redis_client import get_redis


def _client_ip(request: Request) -> str:
    """IP cliente RÉELLE derrière nginx. nginx pose X-Real-IP = $remote_addr (le
    pair TCP réel, non spoofable par le client). On NE lit PAS X-Forwarded-For brut
    (appendé → un client peut y injecter des valeurs). Fallback sur l'IP de socket."""
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_auth(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Anti-brute-force sur les endpoints d'authentification (login/register/reset).
    10 tentatives / 5 min / IP, puis 429. Protège contre le credential-stuffing et
    le spam d'emails (forgot-password). Fail-open si Redis est indisponible (ne pas
    bloquer l'auth légitime sur panne cache)."""
    ip = _client_ip(request)
    key = f"rl:auth:{ip}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 300)
        n = (await pipe.execute())[0]
    except Exception:
        return  # fail-open : panne Redis ne doit pas verrouiller l'auth
    if n > 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessayez dans quelques minutes.",
            headers={"Retry-After": "300"},
        )
