"""
WebSocket routes — BlackTurf.
- /ws/courses/{course_id}/cotes : cotes live (30s refresh)
- /ws/value-bets : stream value bets actifs
- /ws/user/alertes : alertes in-app personnalisées
"""
import asyncio
import json
import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from jose import JWTError, jwt
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from db.database import get_db, async_session_factory
from db.models import Participation, CoteHistorique, ValueBet, Course, Cheval, User
from db.redis_client import get_redis

settings = get_settings()
log = structlog.get_logger()
router = APIRouter()

# Heartbeat constants
PING_INTERVAL = 30   # seconds between server pings
PONG_TIMEOUT = 45    # seconds to wait for pong before closing


# ─────────────────────────────────────────────
# Connection manager pour les alertes user
# ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}
        self._connected_at: dict[int, datetime] = {}  # id(ws) → datetime
        self._last_pong: dict[int, float] = {}         # id(ws) → monotonic timestamp

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)
        self._connected_at[id(ws)] = datetime.now(timezone.utc)
        self._last_pong[id(ws)] = asyncio.get_event_loop().time()
        log.info("ws.connected", user_id=user_id)

    def disconnect(self, user_id: str, ws: WebSocket):
        conns = self._connections.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        self._connected_at.pop(id(ws), None)
        self._last_pong.pop(id(ws), None)
        log.info("ws.disconnected", user_id=user_id)

    def record_pong(self, ws: WebSocket):
        self._last_pong[id(ws)] = asyncio.get_event_loop().time()

    def is_stale(self, ws: WebSocket) -> bool:
        last = self._last_pong.get(id(ws))
        if last is None:
            return False
        return (asyncio.get_event_loop().time() - last) > PONG_TIMEOUT

    async def send(self, user_id: str, payload: dict):
        conns = self._connections.get(user_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast(self, payload: dict):
        """Envoie à tous les utilisateurs connectés."""
        for user_id in list(self._connections.keys()):
            await self.send(user_id, payload)


manager = ConnectionManager()


async def _get_user_from_token(token: str) -> str | None:
    """Extrait user_id depuis le JWT (pour WS auth)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError:
        return None


# ─────────────────────────────────────────────
# Cotes live
# ─────────────────────────────────────────────
@router.websocket("/courses/{course_id}/cotes")
async def ws_cotes_live(course_id: str, websocket: WebSocket, token: str = Query(default="")):
    """Stream des cotes live pour une course. Refresh 30s + ping/pong heartbeat."""
    user_id = await _get_user_from_token(token)
    if not user_id:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connected_at = datetime.now(timezone.utc)
    last_pong = asyncio.get_event_loop().time()
    log.info("ws.cotes.connect", course_id=course_id, user_id=user_id)

    async def send_cotes():
        async with async_session_factory() as db:
            q = (
                select(Participation, Cheval)
                .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
                .where(Participation.course_id == course_id)
                .order_by(Participation.numero)
            )
            rows = (await db.execute(q)).all()
            partants = [
                {
                    "numero": p.numero,
                    "nom": ch.nom,
                    "cote_pmu": p.cote_pmu,
                    "cote_geny": p.cote_geny,
                    "non_partant": p.non_partant,
                }
                for p, ch in rows
            ]
        await websocket.send_json({
            "type": "cotes_update",
            "course_id": course_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "partants": partants,
        })

    try:
        ping_counter = 0
        while True:
            # Send cotes data
            await send_cotes()

            # Heartbeat every PING_INTERVAL seconds — use small sleep loops to read pong
            elapsed = 0
            while elapsed < 30:
                try:
                    msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    try:
                        msg = json.loads(msg_raw)
                        if msg.get("type") == "pong":
                            last_pong = asyncio.get_event_loop().time()
                    except Exception:
                        pass
                except asyncio.TimeoutError:
                    pass
                elapsed += 1

                # Check pong timeout
                if (asyncio.get_event_loop().time() - last_pong) > PONG_TIMEOUT:
                    log.warning("ws.cotes.pong_timeout", course_id=course_id, user_id=user_id)
                    await websocket.close()
                    return

            # Send ping
            await websocket.send_json({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            ping_counter += 1

    except WebSocketDisconnect:
        log.info("ws.cotes.disconnect", course_id=course_id)
    except Exception as e:
        log.error("ws.cotes.error", error=str(e))
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Value bets stream
# ─────────────────────────────────────────────
@router.websocket("/value-bets")
async def ws_value_bets(websocket: WebSocket, token: str = Query(default="")):
    """Stream des value bets actifs. Refresh 60s + ping/pong heartbeat."""
    user_id = await _get_user_from_token(token)
    if not user_id:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_pong = asyncio.get_event_loop().time()
    log.info("ws.valuebets.connect", user_id=user_id)

    async def send_vbs():
        async with async_session_factory() as db:
            q = (
                select(ValueBet, Participation, Cheval, Course)
                .join(Participation, Participation.participation_id == ValueBet.participation_id)
                .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
                .join(Course, Course.course_id == ValueBet.course_id)
                .where(
                    and_(
                        ValueBet.actif == True,
                        Course.statut.in_(["a_venir", "en_cours"]),
                    )
                )
                .order_by(desc(ValueBet.ev_max))
                .limit(20)
            )
            rows = (await db.execute(q)).all()
            vbs = [
                {
                    "vb_id": vb.vb_id,
                    "course_id": vb.course_id,
                    "hippodrome_nom": course.hippodrome_nom,
                    "hippodrome": course.hippodrome_nom,
                    "date_heure": course.date_heure.isoformat(),
                    "nom_cheval": cheval.nom,
                    "numero": part.numero,
                    "cote_pmu": part.cote_pmu,
                    "ev_max": round(vb.ev_max, 4),
                    "niveau": vb.niveau,
                    "meilleure_source": vb.meilleure_source,
                    "actif": vb.actif,
                    "spi_detected": vb.spi_detected,
                    "spi_score": round(vb.spi_score, 3) if vb.spi_score else None,
                }
                for vb, part, cheval, course in rows
            ]
        await websocket.send_json({
            "type": "value_bets",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": vbs,
        })

    try:
        while True:
            await send_vbs()

            # Wait 60s reading pong responses
            elapsed = 0
            while elapsed < 60:
                try:
                    msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    try:
                        msg = json.loads(msg_raw)
                        if msg.get("type") == "pong":
                            last_pong = asyncio.get_event_loop().time()
                    except Exception:
                        pass
                except asyncio.TimeoutError:
                    pass
                elapsed += 1

                if (asyncio.get_event_loop().time() - last_pong) > PONG_TIMEOUT:
                    log.warning("ws.valuebets.pong_timeout", user_id=user_id)
                    await websocket.close()
                    return

            await websocket.send_json({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    except WebSocketDisconnect:
        log.info("ws.valuebets.disconnect", user_id=user_id)
    except Exception as e:
        log.error("ws.valuebets.error", error=str(e))
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Alertes in-app user
# ─────────────────────────────────────────────
@router.websocket("/user/alertes")
async def ws_user_alertes(websocket: WebSocket, token: str = Query(default="")):
    """Canal d'alertes in-app personnalisées avec ping/pong heartbeat."""
    user_id = await _get_user_from_token(token)
    if not user_id:
        await websocket.close(code=4401)
        return

    await manager.connect(user_id, websocket)
    redis = await get_redis()
    pubsub = redis.pubsub()
    listen_task: asyncio.Task | None = None
    ping_task: asyncio.Task | None = None

    try:
        await pubsub.subscribe(f"alertes:{user_id}", "alertes:broadcast")

        async def listen():
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        await websocket.send_json(data)
                    except Exception:
                        pass

        async def heartbeat():
            """Send ping every PING_INTERVAL seconds; close if no pong in PONG_TIMEOUT."""
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    break
                if manager.is_stale(websocket):
                    log.warning(
                        "ws.alertes.pong_timeout",
                        user_id=user_id,
                        connected_at=manager._connected_at.get(id(websocket)),
                    )
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    break

        listen_task = asyncio.create_task(listen())
        ping_task = asyncio.create_task(heartbeat())

        # Read messages from client (pong + any client-initiated messages)
        while True:
            try:
                msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                try:
                    msg = json.loads(msg_raw)
                    if msg.get("type") == "pong":
                        manager.record_pong(websocket)
                    elif msg_raw == "ping":
                        await websocket.send_json({"type": "pong"})
                except Exception:
                    # Plain text "ping" fallback
                    if msg_raw == "ping":
                        await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # No message received — heartbeat task handles ping sending
                pass

    except WebSocketDisconnect:
        log.info("ws.alertes.disconnect", user_id=user_id)
    except Exception as e:
        log.error("ws.alertes.error", error=str(e))
    finally:
        for task in [listen_task, ping_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass
        manager.disconnect(user_id, websocket)


async def push_alert_to_user(user_id: str, payload: dict):
    """Publier une alerte in-app via Redis → tous les WS de l'utilisateur."""
    try:
        redis = await get_redis()
        await redis.publish(f"alertes:{user_id}", json.dumps(payload))
    except Exception as e:
        log.error("ws.push_alert.failed", user_id=user_id, error=str(e))


async def broadcast_alert(payload: dict):
    """Broadcast à tous les utilisateurs connectés."""
    try:
        redis = await get_redis()
        await redis.publish("alertes:broadcast", json.dumps(payload))
    except Exception as e:
        log.error("ws.broadcast.failed", error=str(e))
