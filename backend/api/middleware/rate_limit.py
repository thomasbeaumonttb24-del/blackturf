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
    "pro":    (15, 200),
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


async def rate_limit_public(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Rate limit by IP for public endpoints — 60 req/min."""
    ip = request.client.host if request.client else "unknown"
    key = f"rl:public:min:{ip}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)
    results = await pipe.execute()
    if results[0] > 60:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requêtes — réessayez dans 1 minute",
            headers={"Retry-After": "60"},
        )
