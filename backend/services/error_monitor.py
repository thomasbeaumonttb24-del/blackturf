"""Monitoring centralisé des erreurs runtime du site.

Capture les exceptions NON gérées de l'API (vrais 500 + traceback) dans la table
`system_errors`, et agrège les échecs de scrapers (`scrape_log.statut='error'`) pour
les exposer EN LIVE dans le back-office → l'admin identifie une erreur réelle dès
qu'elle survient, au lieu d'un « 0 ✓OK » trompeur.

Best-effort : la journalisation d'une erreur ne lève JAMAIS d'exception propre (sinon
on masquerait l'erreur d'origine). La table est auto-créée (CREATE TABLE IF NOT EXISTS),
pas de migration requise — même mécanique que signal_performance.
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal

log = structlog.get_logger()

_CREATE = """
CREATE TABLE IF NOT EXISTS system_errors (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source     VARCHAR(80)  NOT NULL,
    level      VARCHAR(20)  NOT NULL DEFAULT 'error',
    message    TEXT         NOT NULL,
    detail     TEXT,
    endpoint   VARCHAR(300),
    resolved   BOOLEAN      NOT NULL DEFAULT false
)
"""
_IDX = "CREATE INDEX IF NOT EXISTS ix_system_errors_created ON system_errors (created_at DESC)"


async def _ensure(session: AsyncSession) -> None:
    await session.execute(text(_CREATE))
    await session.execute(text(_IDX))


async def record_error(source: str, message: str, *, detail: str | None = None,
                       endpoint: str | None = None, level: str = "error") -> None:
    """Journalise une erreur runtime en base. Best-effort, ne lève jamais."""
    try:
        async with AsyncSessionLocal() as s:
            await _ensure(s)
            await s.execute(
                text("INSERT INTO system_errors (source, level, message, detail, endpoint) "
                     "VALUES (:s, :l, :m, :d, :e)"),
                {"s": str(source)[:80], "l": str(level)[:20], "m": str(message)[:2000],
                 "d": (str(detail)[:8000] if detail else None),
                 "e": (str(endpoint)[:300] if endpoint else None)},
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("error_monitor.record_failed", err=str(e)[:200])


async def error_count(session: AsyncSession, hours: int = 24) -> int:
    """Nb d'erreurs NON résolues sur la fenêtre = exceptions API + scrapers échoués."""
    n_sys = 0
    n_scrape = 0
    try:
        await _ensure(session)
        n_sys = (await session.execute(text(
            "SELECT COUNT(*) FROM system_errors WHERE resolved = false "
            "AND created_at >= now() - (:h * INTERVAL '1 hour')"), {"h": hours})).scalar() or 0
    except Exception:
        n_sys = 0
    try:
        n_scrape = (await session.execute(text(
            "SELECT COUNT(*) FROM scrape_log WHERE statut = 'error' "
            "AND created_at >= now() - (:h * INTERVAL '1 hour')"), {"h": hours})).scalar() or 0
    except Exception:
        n_scrape = 0
    return int(n_sys) + int(n_scrape)


async def recent_errors(session: AsyncSession, hours: int = 72, limit: int = 50) -> list[dict]:
    """Liste FUSIONNÉE des erreurs récentes (exceptions API + scrapers échoués), récente d'abord."""
    out: list[dict] = []
    try:
        await _ensure(session)
        rows = (await session.execute(text(
            "SELECT id, created_at, source, level, message, detail, endpoint, resolved "
            "FROM system_errors WHERE created_at >= now() - (:h * INTERVAL '1 hour') "
            "ORDER BY created_at DESC LIMIT :lim"), {"h": hours, "lim": limit})).all()
        for r in rows:
            out.append({
                "id": int(r.id), "kind": "api", "created_at": r.created_at, "source": r.source,
                "level": r.level, "message": r.message, "detail": r.detail,
                "endpoint": r.endpoint, "resolved": bool(r.resolved),
            })
    except Exception as e:  # noqa: BLE001
        log.warning("error_monitor.recent_sys_failed", err=str(e)[:200])
    try:
        rows = (await session.execute(text(
            "SELECT source, created_at, erreur FROM scrape_log "
            "WHERE statut = 'error' AND erreur IS NOT NULL "
            "AND created_at >= now() - (:h * INTERVAL '1 hour') "
            "ORDER BY created_at DESC LIMIT :lim"), {"h": hours, "lim": limit})).all()
        for r in rows:
            out.append({
                "id": None, "kind": "scraper", "created_at": r.created_at,
                "source": f"scraper:{r.source}", "level": "error",
                "message": (r.erreur or "")[:300], "detail": r.erreur,
                "endpoint": None, "resolved": False,
            })
    except Exception as e:  # noqa: BLE001
        log.warning("error_monitor.recent_scrape_failed", err=str(e)[:200])
    out.sort(key=lambda x: (x["created_at"] is not None, x["created_at"]), reverse=True)
    return out[:limit]


async def resolve_error(session: AsyncSession, error_id: int) -> bool:
    """Marque une erreur API comme résolue (best-effort)."""
    try:
        await _ensure(session)
        await session.execute(
            text("UPDATE system_errors SET resolved = true WHERE id = :id"), {"id": error_id})
        await session.commit()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("error_monitor.resolve_failed", err=str(e)[:200])
        return False
