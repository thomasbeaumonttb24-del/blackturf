"""
Telegram bot — BlackTurf.
Webhook mode (pas de polling).
Commandes : /start /vb /programme /alerte
Alertes push : broadcast VB aux abonnés.

Stockage abonnés dans Redis : HSET telegram:subscribers {chat_id} {json_prefs}
"""
import json
import structlog
import httpx
from typing import Optional
from api.config import get_settings

log = structlog.get_logger()
settings = get_settings()

TELEGRAM_API = "https://api.telegram.org/bot"


async def _send(chat_id: int | str, text: str, parse_mode: str = "HTML") -> bool:
    """Envoie un message Telegram."""
    if not settings.telegram_bot_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{TELEGRAM_API}{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            )
            return resp.status_code == 200
    except Exception as e:
        log.error("telegram.send_failed", chat_id=chat_id, error=str(e))
        return False


async def set_webhook(webhook_url: str) -> bool:
    """Configure le webhook Telegram."""
    if not settings.telegram_bot_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{TELEGRAM_API}{settings.telegram_bot_token}/setWebhook",
                json={
                    "url": webhook_url,
                    "secret_token": settings.telegram_webhook_secret,
                    "allowed_updates": ["message"],
                },
            )
            data = resp.json()
            if data.get("ok"):
                log.info("telegram.webhook_set", url=webhook_url)
                return True
            log.error("telegram.webhook_error", resp=data)
            return False
    except Exception as e:
        log.error("telegram.webhook_failed", error=str(e))
        return False


async def handle_update(update: dict) -> None:
    """
    Traite un update Telegram entrant.
    Appelé depuis le webhook route.
    """
    message = update.get("message", {})
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    first_name = message.get("from", {}).get("first_name", "parieur")

    if not chat_id or not text:
        return

    if text.startswith("/start"):
        await _cmd_start(chat_id, first_name)
    elif text.startswith("/vb"):
        await _cmd_vb(chat_id)
    elif text.startswith("/programme"):
        await _cmd_programme(chat_id)
    elif text.startswith("/alerte"):
        parts = text.split()
        niveau = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 2
        await _cmd_alerte(chat_id, min(max(niveau, 1), 4))
    elif text.startswith("/stop"):
        await _cmd_stop(chat_id)
    else:
        await _send(chat_id, (
            "🏇 <b>BlackTurf Bot</b>\n\n"
            "Commandes disponibles :\n"
            "• /vb — Value bets du jour\n"
            "• /programme — Programme des courses\n"
            "• /alerte [1-4] — S'abonner aux alertes VB\n"
            "• /stop — Se désabonner\n"
            "• /start — Aide"
        ))


async def _cmd_start(chat_id: int, first_name: str) -> None:
    await _send(chat_id, (
        f"🏇 Bonjour <b>{first_name}</b> !\n\n"
        "Bienvenue sur <b>BlackTurf Bot</b> — vos value bets hippiques en temps réel.\n\n"
        "<b>Commandes :</b>\n"
        "• /vb — Value bets actifs du jour\n"
        "• /programme — Programme PMU du jour\n"
        "• /alerte 2 — Alertes VB niveau ≥ 2 (1-4)\n"
        "• /stop — Désactiver les alertes\n\n"
        "🌐 <a href=\"https://blackturf.fr\">blackturf.fr</a>"
    ))


async def _cmd_vb(chat_id: int) -> None:
    """Affiche les value bets actifs du jour."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.api_url}/api/v1/predictions/value-bets",
                params={"limit": 10, "niveau_min": 2},
            )
            if resp.status_code != 200:
                await _send(chat_id, "❌ Impossible de charger les value bets.")
                return
            data = resp.json()
    except Exception:
        await _send(chat_id, "❌ Service temporairement indisponible.")
        return

    vbs = data.get("value_bets", [])
    if not vbs:
        await _send(chat_id, "🔍 Aucun value bet détecté pour le moment. Revenez plus tard.")
        return

    lines = ["🏇 <b>Value Bets du jour</b>\n"]
    for vb in vbs[:8]:
        etoiles = "⭐" * vb.get("niveau", 1)
        ev = round(vb.get("ev_max", 0) * 100, 1)
        cote = vb.get("cote_pmu") or vb.get("cote_min", 0)
        lines.append(
            f"{etoiles} <b>{vb.get('nom_cheval', '')}</b>\n"
            f"   📍 {vb.get('hippodrome_nom', '')} · 🕐 {vb.get('date_heure', '')[-5:]}\n"
            f"   Cote: {cote:.1f} · EV: <b>+{ev}%</b>"
        )

    lines.append("\n🌐 <a href=\"https://blackturf.fr/value-bets\">Voir tous les VB →</a>")
    await _send(chat_id, "\n\n".join(lines))


async def _cmd_programme(chat_id: int) -> None:
    """Affiche le programme du jour."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.api_url}/api/v1/programme")
            if resp.status_code != 200:
                await _send(chat_id, "❌ Impossible de charger le programme.")
                return
            data = resp.json()
    except Exception:
        await _send(chat_id, "❌ Service temporairement indisponible.")
        return

    reunions = data.get("reunions", [])
    if not reunions:
        await _send(chat_id, "🔍 Aucune course trouvée pour aujourd'hui.")
        return

    jour = data.get("date") or "aujourd'hui"
    lines = [f"🏇 <b>Programme du {jour}</b>\n"]
    for r in reunions[:8]:
        courses = r.get("courses", [])
        if not courses:
            continue
        premiere = courses[0].get("date_heure", "")[-5:]
        derniere = courses[-1].get("date_heure", "")[-5:]
        lines.append(
            f"📍 <b>{r.get('hippodrome', '')}</b> — {len(courses)} courses ({premiere}–{derniere})"
        )

    lines.append(f"\n📊 {data.get('nb_courses', 0)} courses au total")
    lines.append("🌐 <a href=\"https://blackturf.fr/programme\">Programme complet →</a>")
    await _send(chat_id, "\n".join(lines))


async def _cmd_alerte(chat_id: int, niveau: int) -> None:
    """Abonne le chat_id aux alertes VB de niveau >= niveau."""
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        prefs = {"niveau_min": niveau, "actif": True}
        await redis.hset("telegram:subscribers", str(chat_id), json.dumps(prefs))
        await _send(chat_id, (
            f"✅ <b>Alertes activées !</b>\n\n"
            f"Tu recevras les value bets de niveau ≥ {niveau} ⭐{'⭐' * (niveau - 1)}\n\n"
            "Pour désactiver : /stop"
        ))
    except Exception as e:
        log.error("telegram.alerte_subscribe", error=str(e))
        await _send(chat_id, "❌ Erreur lors de l'abonnement. Réessaie.")


async def _cmd_stop(chat_id: int) -> None:
    """Désabonne le chat_id."""
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        await redis.hdel("telegram:subscribers", str(chat_id))
        await _send(chat_id, "👋 Alertes désactivées. Tu peux te réabonner avec /alerte")
    except Exception as e:
        await _send(chat_id, "❌ Erreur. Réessaie.")


async def broadcast_vb_alert(vb_data: dict) -> int:
    """
    Envoie une alerte VB à tous les abonnés Telegram dont niveau_min <= vb_data["niveau"].
    Retourne le nombre de messages envoyés.
    """
    if not settings.telegram_bot_token:
        return 0

    niveau_vb = vb_data.get("niveau", 1)
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        subscribers = await redis.hgetall("telegram:subscribers")
    except Exception:
        return 0

    sent = 0
    etoiles = "⭐" * niveau_vb
    ev = round(vb_data.get("ev_max", 0) * 100, 1)
    cote = vb_data.get("cote_pmu") or vb_data.get("cote_min", 0) or 0
    spi = " ⚡ Steam" if vb_data.get("spi_detected") else ""

    msg = (
        f"🚨 <b>Value Bet {etoiles}{spi}</b>\n\n"
        f"🐴 <b>{vb_data.get('nom_cheval', '')}</b>\n"
        f"📍 {vb_data.get('hippodrome', '')} · {vb_data.get('heure', '')}\n"
        f"Cote: {cote:.1f} · EV: <b>+{ev}%</b>\n\n"
        f"🌐 <a href=\"https://blackturf.fr/courses/{vb_data.get('course_id', '')}\">Voir la course →</a>\n\n"
        "⚠️ Paris responsable — joueurs-info-service.fr"
    )

    for chat_id_str, prefs_json in subscribers.items():
        try:
            prefs = json.loads(prefs_json)
            if not prefs.get("actif", True):
                continue
            niveau_min = prefs.get("niveau_min", 2)
            if niveau_vb < niveau_min:
                continue
            ok = await _send(int(chat_id_str), msg)
            if ok:
                sent += 1
        except Exception:
            continue

    log.info("telegram.broadcast_vb", sent=sent, niveau=niveau_vb)
    return sent


async def send_telegram_alert(chat_id: str | int, vb_data: dict) -> bool:
    """Envoie une alerte VB à un chat_id spécifique."""
    niveau_vb = vb_data.get("niveau", 1)
    etoiles = "⭐" * niveau_vb
    ev = round(vb_data.get("ev_max", 0) * 100, 1)
    cote = vb_data.get("cote_pmu") or vb_data.get("cote_min", 0) or 0
    msg = (
        f"🚨 <b>Value Bet {etoiles}</b>\n\n"
        f"🐴 <b>{vb_data.get('nom_cheval', '')}</b>\n"
        f"📍 {vb_data.get('hippodrome', '')} · {vb_data.get('heure', '')}\n"
        f"Cote: {cote:.1f} · EV: <b>+{ev}%</b>\n\n"
        f"🌐 <a href=\"https://blackturf.fr/courses/{vb_data.get('course_id', '')}\">Voir →</a>"
    )
    return await _send(chat_id, msg)
