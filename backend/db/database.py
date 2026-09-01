from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from api.config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {
    "echo": settings.environment == "development",
}
if not _is_sqlite:
    # Le pool est un BUDGET PARTAGÉ entre processus, pas un réglage local : voir
    # `api.config.Settings.db_pool_size` pour l'arithmétique complète et la panne
    # qui l'a motivé. Ne PAS remettre de constante en dur ici — la surcharge par
    # service passe par `environment:` dans les deux compose, et un invariant de
    # déploiement vérifie que leur somme reste sous `max_connections`.
    _engine_kwargs.update({
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": settings.db_pool_recycle_s,
    })

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias for convenience
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def desempoisonner(session: AsyncSession) -> None:
    """Annule une transaction avortée par une requête dont on ignore l'échec.

    PostgreSQL/asyncpg marque la transaction ENTIÈRE comme avortée dès qu'une
    requête échoue : toutes les suivantes lèvent `InFailedSQLTransactionError`,
    même parfaitement valides. Un `except Exception: pass` autour d'une sonde
    optionnelle ne « rattrape » donc rien — il déplace juste le 500 sur la
    requête d'après, avec un message qui n'a plus aucun rapport avec la cause.

    Constaté en production le 20/08/2026 : `/admin/api/dashboard` renvoyait
    « current transaction is aborted » sur un simple `count(courses)`, alors que
    la vraie panne était une requête parallèle tuée par un `/dev/shm` de 64 Mo
    dans le conteneur PostgreSQL, avalée quatre appels plus haut.

    À appeler dans TOUT `except` qui décide de continuer après un échec SQL.
    """
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001 — session déjà fermée : rien à désempoisonner
        pass
