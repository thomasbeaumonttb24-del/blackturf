"""Runner standalone du scheduler BlackTurf (conteneur dedie).

Sort les jobs planifies (APScheduler) du process API pour que uvicorn
puisse tourner en plusieurs workers sans dupliquer les jobs ni bloquer
l'event loop HTTP. Delivery des notifs = redis pubsub (deja decouple).
"""
import asyncio
import structlog
from services.jobs import start_scheduler, stop_scheduler

log = structlog.get_logger()


async def main() -> None:
    start_scheduler()
    log.info("scheduler.standalone.started")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop_scheduler()
        log.info("scheduler.standalone.stopped")


if __name__ == "__main__":
    asyncio.run(main())
