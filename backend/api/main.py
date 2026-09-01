import structlog
import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from api.config import get_settings
from api.routes import auth, courses, predictions, bankroll, admin, ws
from api.routes import assistant, stripe_routes, strategies, stats, notifications
from api.routes import telegram, newsletter, integrations
from db.database import engine, Base
from db.redis_client import get_redis, close_redis

settings = get_settings()
log = structlog.get_logger()

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("blackturf.startup", env=settings.environment)
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await get_redis()

    # Initialiser le moteur d'apprentissage adaptatif + drift detector
    try:
        from db.database import AsyncSessionLocal
        from ml.adaptive_learning import initialize_adaptive_learning
        from ml.drift_detector import initialize_drift_detector
        from ml.meta_learner import initialize_meta_learner
        async with AsyncSessionLocal() as al_session:
            al = await initialize_adaptive_learning(al_session)
            dd = await initialize_drift_detector(al_session)
            ml_meta = await initialize_meta_learner(al_session)
            log.info(
                "adaptive_learning.initialized",
                temperature=round(al.temperature, 4),
                n_races=al.n_races_processed,
                drift_status=dd.get_drift_report().get("status", "healthy"),
                meta_learner_trained=ml_meta.is_trained,
            )
    except Exception as e:
        log.warning("adaptive_learning.init_failed", err=str(e))

    import os as _os
    from services.jobs import start_scheduler, stop_scheduler
    _run_sched = _os.getenv("RUN_SCHEDULER", "1") == "1"
    if _run_sched:
        start_scheduler()

    yield

    if _run_sched:
        stop_scheduler()
    await close_redis()
    log.info("blackturf.shutdown")


app = FastAPI(
    title="BlackTurf API",
    description="Le Terminal IA des Parieurs Gagnants",
    version="1.0.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
    lifespan=lifespan,
)

# CORS strict : méthodes/headers explicites (pas de wildcard avec credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

if settings.environment == "production":
    # localhost/127.0.0.1 requis pour le healthcheck Docker (curl interne) + sondes.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "api.blackturf.fr", "blackturf.fr", "www.blackturf.fr",
            "localhost", "127.0.0.1",
        ],
    )

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Capture toute exception NON gérée (vrai 500) → la journalise dans `system_errors`
    (visible EN LIVE au back-office, carte « Alertes en erreur ») puis renvoie une 500
    propre. Les HTTPException (401/403/404/422…) ont leur propre handler et NE passent
    PAS ici — on ne capture que les vraies erreurs serveur."""
    import traceback
    from services.error_monitor import record_error
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        await record_error(
            "api", f"{type(exc).__name__}: {exc}", detail=tb,
            endpoint=f"{request.method} {request.url.path}",
            # Une panne qui touche un endpoint le touche à CHAQUE appel : sans
            # clé, un rafraîchissement du back-office suffit à écrire dix lignes
            # identiques (deux `TooManyConnectionsError` à une seconde d'écart
            # le 31/08). L'identité est le couple endpoint + type d'exception ;
            # le message, lui, porte des valeurs variables. Le chemin BRUT est
            # volontairement gardé — deux courses différentes qui plantent au
            # même endroit sont deux faits distincts tant que rien ne prouve le
            # contraire.
            cle=f"{request.method} {request.url.path}|{type(exc).__name__}",
        )
    except Exception:  # noqa: BLE001
        pass
    log.error("api.unhandled_exception", path=str(request.url.path), err=str(exc)[:300])
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


# Routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(courses.router, prefix="/api/v1", tags=["courses"])
app.include_router(predictions.router, prefix="/api/v1", tags=["predictions"])
app.include_router(bankroll.router, prefix="/api/v1", tags=["bankroll"])
app.include_router(admin.router, prefix="/admin/api", tags=["admin"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])
app.include_router(assistant.router, prefix="/api/v1", tags=["assistant"])
app.include_router(stripe_routes.router, prefix="/api/v1", tags=["stripe"])
app.include_router(strategies.router, prefix="/api/v1", tags=["strategies"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(telegram.router, prefix="/api/v1/telegram", tags=["telegram"])
app.include_router(newsletter.router, prefix="/api/v1", tags=["newsletter"])
app.include_router(integrations.router, prefix="/admin/api", tags=["integrations"])


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": settings.environment,
    }
