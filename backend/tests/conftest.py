"""
Fixtures de test — BlackTurf.
SQLite en mémoire pour isolation, pas de dépendance externe.
Lifespan patché pour éviter connexions PostgreSQL/Redis en CI.
"""
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# ─── Env vars avant tout import de l'app ───────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-change-in-production-must-be-64-chars-min-ok")
os.environ.setdefault("ENVIRONMENT", "test")

from db.database import Base, get_db  # noqa: E402
from api.main import app              # noqa: E402

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    """
    Engine function-scoped : chaque test reçoit une base SQLite en mémoire neuve.
    Garantit l'isolation totale sans dépendre des savepoints SQLite.
    """
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db):
    """
    Client HTTP de test avec :
    - get_db surchargé → SQLite en mémoire
    - Redis + scheduler mockés → pas de connexion externe
    """
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.publish = AsyncMock(return_value=0)

    # pipeline() est SYNCHRONE côté redis-py : renvoie un pipe dont incr/expire
    # sont synchrones (mise en file) et execute() est async. Compteur=1 → pas de 429.
    _pipe = MagicMock()
    _pipe.incr = MagicMock(return_value=_pipe)
    _pipe.expire = MagicMock(return_value=_pipe)
    _pipe.execute = AsyncMock(return_value=[1, True])
    mock_redis.pipeline = MagicMock(return_value=_pipe)

    with (
        patch("db.redis_client.get_redis", return_value=mock_redis),
        patch("db.redis_client.close_redis", new_callable=AsyncMock),
        patch("services.jobs.start_scheduler", return_value=None),
        patch("services.jobs.stop_scheduler", return_value=None),
        # Auth routes appellent aioredis.from_url() directement
        patch("redis.asyncio.from_url", return_value=mock_redis),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client):
    """Crée un utilisateur et retourne les headers JWT."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@blackturf.fr",
        "password": "TestPassword123!",
        "nom": "Test",
        "prenom": "User",
    })
    assert resp.status_code == 200, f"register failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client, db):
    """Crée un admin et retourne les headers JWT."""
    from api.routes.auth import _hash
    from db.models import User
    import uuid

    admin = User(
        user_id=str(uuid.uuid4()),
        email="admin@blackturf.fr",
        hashed_password=_hash("AdminPass123!"),
        plan="expert",
        is_admin=True,
    )
    db.add(admin)
    await db.commit()

    resp = await client.post("/api/v1/auth/login", data={
        "username": "admin@blackturf.fr",
        "password": "AdminPass123!",
    })
    assert resp.status_code == 200, f"admin login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
