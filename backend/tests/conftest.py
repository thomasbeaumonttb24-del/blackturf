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

# Variables d'environnement de PRODUCTION qui changent le VERDICT d'un test sans
# rien changer au code testé. La suite est exécutée dans l'image de prod, avec le
# `.env` de prod : `SCRAPER_DISABLED_SOURCES` y liste 8 sources volontairement
# éteintes, et `sante_scrapers()` renvoyait donc `disabled` / `silent_disabled`
# là où les tests attendaient `ok_but_empty` / `silent` — 4 échecs qui n'étaient
# le symptôme d'aucun bug (constaté le 2026-08-19, gate à 5 rouges).
# Un test qui dépend d'une de ces variables doit la poser LUI-MÊME
# (`monkeypatch.setenv`), ce que font déjà test_data_quality et
# test_orchestrator_*. On neutralise donc l'ambiant, jamais l'explicite.
ENV_AMBIANTES_NEUTRALISEES = (
    "SCRAPER_DISABLED_SOURCES",
    "SCRAPER_INTERVAL_MULTIPLIER",
)


@pytest.fixture(autouse=True)
def _env_ambiant_neutralise(monkeypatch):
    """Retire l'environnement de prod qui fausse les tests. Autouse : la règle ne
    vaut rien si chaque test doit penser à l'appliquer. `monkeypatch` restaure
    tout après le test, donc l'ambiant reste intact pour le reste du processus."""
    for nom in ENV_AMBIANTES_NEUTRALISEES:
        monkeypatch.delenv(nom, raising=False)


@pytest_asyncio.fixture
async def engine():
    """
    Engine function-scoped : chaque test reçoit une base SQLite en mémoire neuve.
    Garantit l'isolation totale sans dépendre des savepoints SQLite.
    """
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # En production ``prediction_evaluation`` est une VUE PostgreSQL (migration
        # 0030). Base.metadata doit déclarer sa forme pour l'ORM, donc create_all la
        # crée comme table sous SQLite. On la remplace ici par l'équivalent dynamique
        # SQLite afin que les tests legacy et snapshot exercent le vrai read-model.
        await conn.exec_driver_sql("DROP TABLE prediction_evaluation")
        await conn.exec_driver_sql("""
            CREATE VIEW prediction_evaluation AS
            WITH ranked_snapshot AS (
                SELECT ps.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY ps.participation_id
                           ORDER BY ps.observed_at DESC, ps.snapshot_id DESC
                       ) AS snapshot_rank
                FROM prediction_snapshots ps
                LEFT JOIN participations pa_snap
                  ON pa_snap.participation_id = ps.participation_id
                WHERE ps.is_pre_course = 1 AND ps.is_replayable = 1
                  AND COALESCE(pa_snap.non_partant, 0) = 0
            ),
            latest_snapshot AS (
                SELECT
                    snapshot_id AS evaluation_id, prediction_id,
                    participation_id, course_id, model_version_id,
                    proba_top1, proba_top3, proba_top1_raw, proba_top3_raw,
                    proba_top1_low, proba_top1_high, rang_predit,
                    NULL AS score_borda, confidence_score, cote_figee,
                    observed_at AS created_at, features, features_hash,
                    feature_schema_hash, origin AS source_origin,
                    1 AS is_snapshot, is_replayable
                FROM ranked_snapshot WHERE snapshot_rank = 1
            )
            SELECT * FROM latest_snapshot
            UNION ALL
            SELECT
                p.prediction_id AS evaluation_id, p.prediction_id,
                p.participation_id, p.course_id, p.model_version_id,
                p.proba_top1, p.proba_top3, p.proba_top1_raw, p.proba_top3_raw,
                p.proba_top1_low, p.proba_top1_high, p.rang_predit,
                p.score_borda, p.confidence_score, p.cote_figee, p.created_at,
                NULL AS features, NULL AS features_hash,
                NULL AS feature_schema_hash, 'legacy_mutable_row' AS source_origin,
                0 AS is_snapshot, 0 AS is_replayable
            FROM predictions p
            LEFT JOIN participations pa_legacy
              ON pa_legacy.participation_id = p.participation_id
            WHERE NOT EXISTS (
                SELECT 1 FROM latest_snapshot s
                WHERE s.participation_id = p.participation_id
            )
              AND COALESCE(pa_legacy.non_partant, 0) = 0
        """)
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
