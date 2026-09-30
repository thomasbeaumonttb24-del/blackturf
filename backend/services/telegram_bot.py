"""
Telegram bot — BlackTurf.
Webhook mode (pas de polling).
Commandes : /start /programme /stop

AUCUN pari de valeur sur Telegram : un chat n'est rattaché à aucun compte, le
bot ne connaît donc pas le plan de son interlocuteur et ne peut pas appliquer
la règle de `services.valuebets_visibilite` (Free jamais, Standard +15 min,
Expert en direct). `/vb` (qui appelait une route inexistante) et `/alerte` (qui
abonnait n'importe quel chat à un envoi `broadcast_vb_alert` sans filtre de plan)
ont été retirés le 2026-09-30 ; ces commandes renvoient désormais vers le site.
`/stop` reste pour effacer un ancien abonnement (Redis `telegram:subscribers`).
"""
import structlog
import httpx
from api.config import get_settings

log = structlog.get_logger()
settings = get_settings()

TELEGRAM_API = "https://api.telegram.org/bot"

MSG_VALUE_BETS_SUR_LE_SITE = (
    "🔒 Les paris de valeur ne sont plus diffusés sur Telegram : ils sont réservés "
    "aux abonnés, sur le site.\n\n"
    "🌐 <a href=\"https://blackturf.fr/value-bets\">blackturf.fr/value-bets</a>"
)


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
    # Sans `secret_token`, Telegram appelle la route sans en-tête d'authentification
    # et n'importe qui peut se faire passer pour lui. On refuse d'enregistrer un
    # webhook dans cet état plutôt que d'ouvrir la porte.
    if not settings.telegram_webhook_secret:
        log.error("telegram.webhook_refuse", raison="TELEGRAM_WEBHOOK_SECRET absent")
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
    elif text.startswith("/programme"):
        await _cmd_programme(chat_id)
    elif text.startswith(("/vb", "/alerte")):
        await _send(chat_id, MSG_VALUE_BETS_SUR_LE_SITE)
    elif text.startswith("/stop"):
        await _cmd_stop(chat_id)
    else:
        await _send(chat_id, (
            "🏇 <b>BlackTurf Bot</b>\n\n"
            "Commandes disponibles :\n"
            "• /programme — Programme des courses\n"
            "• /start — Aide"
        ))


async def _cmd_start(chat_id: int, first_name: str) -> None:
    await _send(chat_id, (
        f"🏇 Bonjour <b>{first_name}</b> !\n\n"
        "Bienvenue sur <b>BlackTurf Bot</b>.\n\n"
        "<b>Commandes :</b>\n"
        "• /programme — Programme PMU du jour\n\n"
        "Les paris de valeur sont réservés aux abonnés, sur le site.\n"
        "🌐 <a href=\"https://blackturf.fr\">blackturf.fr</a>"
    ))


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


async def _cmd_stop(chat_id: int) -> None:
    """Désabonne le chat_id."""
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        await redis.hdel("telegram:subscribers", str(chat_id))
        await _send(chat_id, "👋 Alertes désactivées.")
    except Exception as e:
        await _send(chat_id, "❌ Erreur. Réessaie.")
