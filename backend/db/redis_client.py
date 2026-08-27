import redis.asyncio as aioredis
from api.config import get_settings

settings = get_settings()

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Client Redis partagé, résistant aux connexions mortes par inactivité.

    Le pool était créé sans contrôle de santé : après une longue période sans
    trafic (aucune course entre 23 h et 06 h UTC, soit ~10 h d'inactivité), la
    socket TCP était fermée côté réseau et la PREMIÈRE publication suivante
    échouait — les suivantes passaient, redis-py ayant remplacé la connexion
    cassée entre-temps. En production, c'est exactement le seul échec d'envoi
    in-app du 27/08 (06:10:00, 1er des 9 destinataires du lot) et celui du 18/08.

    `health_check_interval` fait envoyer un PING avant réutilisation d'une
    connexion restée inactive, et `retry` rejoue l'appel une fois si la socket
    lâche malgré tout.
    """
    global _redis
    if _redis is None:
        from redis.asyncio.retry import Retry
        from redis.backoff import ExponentialBackoff
        from redis.exceptions import ConnectionError as RedisConnectionError
        from redis.exceptions import TimeoutError as RedisTimeoutError

        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            health_check_interval=30,
            socket_keepalive=True,
            retry=Retry(ExponentialBackoff(cap=1.0, base=0.05), 2),
            retry_on_error=[RedisConnectionError, RedisTimeoutError],
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
