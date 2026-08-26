"""
Rate limiting Redis-based pour les endpoints coûteux.
Usage:
    @router.post("/chat")
    async def chat(..., _=Depends(rate_limit_assistant)):

    @router.get("/programme")
    async def programme(..., _=Depends(rate_limit_public)):
"""
from fastapi import Depends, HTTPException, Request, status
from db.redis_client import get_redis
from api.routes.auth import get_current_user
from db.models import User
import redis.asyncio as aioredis

# Limites par plan (par minute / par jour)
LIMITS: dict[str, tuple[int, int]] = {
    "expert": (15, 200),
}
DEFAULT_LIMIT = (5, 30)  # free / standard — ne devrait pas accéder


async def _check(
    user: User,
    prefix: str,
    per_min: int,
    per_day: int,
    redis: aioredis.Redis,
) -> None:
    # Admin exempté : compte d'exploitation (monitoring, audits, onglets ouverts
    # toute la journée) — le quota journalier le bloquait en 429 silencieux
    # (analyse/outsiders/signaux absents de la page course, constaté 2026-07-03).
    if getattr(user, "is_admin", False):
        return
    uid = str(user.user_id)
    key_min = f"rl:{prefix}:min:{uid}"
    key_day = f"rl:{prefix}:day:{uid}"

    pipe = redis.pipeline()
    pipe.incr(key_min)
    pipe.expire(key_min, 60)
    pipe.incr(key_day)
    pipe.expire(key_day, 86400)
    results = await pipe.execute()

    count_min = results[0]
    count_day = results[2]

    if count_min > per_min:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite atteinte : {per_min} requêtes/minute. Réessayez dans quelques secondes.",
            headers={"Retry-After": "60"},
        )
    if count_day > per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite journalière atteinte ({per_day} requêtes). Revenez demain.",
            headers={"Retry-After": "86400"},
        )


async def rate_limit_assistant(
    user: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """10 req/min, 100 req/jour pour Expert — protège le budget Claude."""
    per_min, per_day = LIMITS.get(user.plan, DEFAULT_LIMIT)
    await _check(user, "assistant", per_min, per_day, redis)


async def rate_limit_predictions(
    user: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """30 req/min pour trigger IA — évite les abus de calcul."""
    await _check(user, "predictions", 30, 500, redis)


# Plafond par IP des endpoints publics, par minute.
#
# Il valait 60. Deux situations réelles le faisaient tomber sur des lectures
# parfaitement normales :
#   - le PARTAGE D'IP. Derrière une sortie d'entreprise ou un opérateur mobile,
#     tous les lecteurs additionnent leurs requêtes dans le même seau ;
#   - le RENDU SERVEUR. `NEXT_PUBLIC_API_URL` pointe sur le domaine public, donc
#     les fetch SSR du conteneur Next repassent par nginx, qui pose un `X-Real-IP`
#     unique — celui du conteneur. Toutes les pages rendues côté serveur, pour
#     tous les visiteurs et tous les robots, partagent alors UNE seule IP.
#
# Ces endpoints sont en lecture seule et servis depuis un cache Redis (120 s à
# 10 min) : un appel de plus coûte presque rien, alors qu'un 429 sur une page
# publique se lit comme un site en panne. Le garde-fou reste là pour l'aspiration
# massive, pas pour la lecture.
PUBLIC_PAR_MINUTE = 240


async def rate_limit_public(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Rate limit par IP des endpoints publics (cf. PUBLIC_PAR_MINUTE)."""
    from api.middleware.throttle import _client_ip
    ip = _client_ip(request)
    key = f"rl:public:min:{ip}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)
    results = await pipe.execute()
    if results[0] > PUBLIC_PAR_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requêtes — réessayez dans 1 minute",
            headers={"Retry-After": "60"},
        )
