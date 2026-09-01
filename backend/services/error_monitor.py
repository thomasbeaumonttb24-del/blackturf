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

from db.database import AsyncSessionLocal, desempoisonner

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
    resolved   BOOLEAN      NOT NULL DEFAULT false,
    cle        VARCHAR(160),
    occurrences INTEGER     NOT NULL DEFAULT 1,
    derniere_occurrence TIMESTAMPTZ
)
"""
# Colonnes ajoutées après coup : la table a pu être créée par une version
# antérieure de ce module (elle n'appartient pas au modèle SQLAlchemy, cf.
# docstring). La migration 0044 fait le même travail pour les bases suivies par
# alembic ; les deux chemins doivent converger, sinon une base créée par le code
# seul n'aurait jamais l'index unique et la déduplication serait un no-op muet.
_ALTERS = (
    "ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS cle VARCHAR(160)",
    "ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS occurrences INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS derniere_occurrence TIMESTAMPTZ",
)
_IDX = "CREATE INDEX IF NOT EXISTS ix_system_errors_created ON system_errors (created_at DESC)"
# Index PARTIEL : seules les lignes OUVERTES se dédupliquent. Une fois « marquée
# résolue », une anomalie qui revient rouvre une ligne neuve, datée d'après la
# résolution — c'est ce qui rend le geste de l'admin observable.
_IDX_CLE = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_system_errors_cle_ouverte "
            "ON system_errors (source, cle) WHERE resolved = false")


async def _ensure(session: AsyncSession) -> None:
    await session.execute(text(_CREATE))
    for alter in _ALTERS:
        await session.execute(text(alter))
    await session.execute(text(_IDX))
    await session.execute(text(_IDX_CLE))


async def record_error(source: str, message: str, *, detail: str | None = None,
                       endpoint: str | None = None, level: str = "error",
                       cle: str | None = None) -> None:
    """Journalise une erreur runtime en base. Best-effort, ne lève jamais.

    ``cle`` identifie le PROBLÈME, pas l'occurrence. Deux appels de même
    ``(source, cle)`` tant que la ligne est ouverte fusionnent : ``occurrences``
    monte, ``derniere_occurrence`` avance, et ``created_at`` reste à la première
    apparition — la durée du problème est l'information utile, son dernier écho
    ne l'est pas.

    Sans ``cle``, comportement inchangé (une ligne par appel) : ``NULL`` n'entre
    pas en conflit avec ``NULL``, donc l'index unique partiel ne s'applique pas.
    C'est le bon défaut pour un événement réellement ponctuel.

    Le défaut que cela ferme (2026-09-01) : ``job_data_quality_check`` tourne
    toutes les heures et réinsérait ses anomalies telles quelles. Deux faits
    persistants — la dérive de calibration 0,40-0,50 et les features à variance
    nulle — s'affichaient en 40 lignes « ouvertes » sur 72 h, repoussant hors des
    huit lignes visibles toute anomalie réellement nouvelle et rendant
    « marquer résolu » sans effet.
    """
    try:
        async with AsyncSessionLocal() as s:
            await _ensure(s)
            await s.execute(
                text("""
                    INSERT INTO system_errors
                        (source, level, message, detail, endpoint, cle,
                         occurrences, derniere_occurrence)
                    VALUES (:s, :l, :m, :d, :e, :k, 1, now())
                    ON CONFLICT (source, cle) WHERE resolved = false
                    DO UPDATE SET
                        level   = EXCLUDED.level,
                        message = EXCLUDED.message,
                        detail  = EXCLUDED.detail,
                        endpoint = EXCLUDED.endpoint,
                        occurrences = system_errors.occurrences + 1,
                        derniere_occurrence = now()
                """),
                {"s": str(source)[:80], "l": str(level)[:20], "m": str(message)[:2000],
                 "d": (str(detail)[:8000] if detail else None),
                 "e": (str(endpoint)[:300] if endpoint else None),
                 "k": (str(cle)[:160] if cle else None)},
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
        # Fenêtre lue sur la dernière occurrence (cf. `recent_errors`) : une
        # anomalie encore active mais ouverte avant la fenêtre reste comptée.
        n_sys = (await session.execute(text(
            "SELECT COUNT(*) FROM system_errors WHERE resolved = false "
            "AND coalesce(derniere_occurrence, created_at) >= now() - (:h * INTERVAL '1 hour')"),
            {"h": hours})).scalar() or 0
    except Exception:
        # Requête ratée ⇒ transaction avortée : sans rollback, l'appelant se
        # prend « current transaction is aborted » sur ses requêtes SUIVANTES.
        await desempoisonner(session)
        n_sys = 0
    try:
        n_scrape = (await session.execute(text(
            "SELECT COUNT(*) FROM scrape_log WHERE statut = 'error' "
            "AND created_at >= now() - (:h * INTERVAL '1 hour')"), {"h": hours})).scalar() or 0
    except Exception:
        await desempoisonner(session)
        n_scrape = 0
    return int(n_sys) + int(n_scrape)


async def recent_errors(session: AsyncSession, hours: int = 72, limit: int = 50) -> list[dict]:
    """Liste FUSIONNÉE des erreurs récentes (exceptions API + scrapers échoués), récente d'abord."""
    out: list[dict] = []
    try:
        await _ensure(session)
        # Fenêtre lue sur la DERNIÈRE occurrence, pas sur la première : une
        # anomalie ouverte depuis quatre jours et toujours active doit rester
        # affichée. La borner sur `created_at` la ferait disparaître de la liste
        # précisément parce qu'elle dure — l'inverse de ce qu'on veut voir.
        rows = (await session.execute(text(
            "SELECT id, created_at, source, level, message, detail, endpoint, resolved, "
            "       occurrences, coalesce(derniere_occurrence, created_at) AS derniere "
            "FROM system_errors "
            "WHERE coalesce(derniere_occurrence, created_at) >= now() - (:h * INTERVAL '1 hour') "
            "ORDER BY coalesce(derniere_occurrence, created_at) DESC LIMIT :lim"),
            {"h": hours, "lim": limit})).all()
        for r in rows:
            out.append({
                "id": int(r.id), "kind": "api", "created_at": r.created_at, "source": r.source,
                "level": r.level, "message": r.message, "detail": r.detail,
                "endpoint": r.endpoint, "resolved": bool(r.resolved),
                "occurrences": int(r.occurrences or 1), "derniere_occurrence": r.derniere,
            })
    except Exception as e:  # noqa: BLE001
        await desempoisonner(session)
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
                "occurrences": 1, "derniere_occurrence": r.created_at,
            })
    except Exception as e:  # noqa: BLE001
        await desempoisonner(session)
        log.warning("error_monitor.recent_scrape_failed", err=str(e)[:200])
    # Tri sur la dernière occurrence, jamais sur la première : une anomalie
    # dédupliquée garde `created_at` au jour où elle a commencé, et trier
    # là-dessus la ferait descendre au fond de la liste — puis sortir par le
    # `limit` — à mesure qu'elle s'aggrave.
    def _quand(e: dict):
        return e.get("derniere_occurrence") or e.get("created_at")
    out.sort(key=lambda x: (_quand(x) is not None, _quand(x)), reverse=True)
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
        await desempoisonner(session)
        log.warning("error_monitor.resolve_failed", err=str(e)[:200])
        return False
