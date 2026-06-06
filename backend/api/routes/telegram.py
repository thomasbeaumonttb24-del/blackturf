"""
Telegram webhook route — BlackTurf.
POST /telegram/webhook  → reçoit les updates Telegram et les dispatche.
"""
import structlog
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from typing import Optional
from api.config import get_settings
from api.routes.auth import require_admin
from db.models import User
from services.telegram_bot import handle_update

log = structlog.get_logger()
settings = get_settings()
router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Reçoit les updates Telegram via webhook.
    Vérifie le secret token si configuré.
    """
    # Vérification du secret token (optionnel mais recommandé)
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Token invalide")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    # Traitement non-bloquant (fire and forget)
    import asyncio
    asyncio.create_task(handle_update(update))

    return {"ok": True}


@router.post("/setup-webhook")
async def setup_webhook(request: Request, _: User = Depends(require_admin)):
    """
    Configure le webhook Telegram.
    Requiert authentification admin.
    Appeler une seule fois après déploiement.
    """
    from services.telegram_bot import set_webhook

    webhook_url = f"{settings.api_url}/api/v1/telegram/webhook"
    ok = await set_webhook(webhook_url)
    return {"ok": ok, "webhook_url": webhook_url}
