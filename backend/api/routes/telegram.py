"""
Telegram webhook route — BlackTurf.
POST /telegram/webhook  → reçoit les updates Telegram et les dispatche.
"""
import secrets

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
    """Reçoit les updates Telegram.

    Le secret partagé est EXIGÉ, jamais optionnel. Il l'était auparavant
    (« vérifié s'il est configuré ») et il n'était pas configuré en production :
    n'importe qui pouvait donc POSTer ici et faire exécuter `handle_update`
    — c'est-à-dire déclencher des tâches et des requêtes en base au nom d'un
    expéditeur non authentifié. Une route sans secret est une route fermée.
    """
    attendu = settings.telegram_webhook_secret
    if not attendu:
        log.warning("telegram.webhook.desactive_faute_de_secret")
        raise HTTPException(
            status_code=403,
            detail="Webhook Telegram désactivé : TELEGRAM_WEBHOOK_SECRET n'est pas configuré.",
        )
    # compare_digest = comparaison à temps constant ; `!=` fuit la longueur du
    # préfixe commun et permet de reconstituer le secret octet par octet.
    if not x_telegram_bot_api_secret_token or not secrets.compare_digest(
        x_telegram_bot_api_secret_token, attendu
    ):
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

    # Sans secret, Telegram n'enverrait aucun en-tête d'authentification et la
    # route ci-dessus rejetterait TOUT : autant le dire ici plutôt que de laisser
    # croire à un webhook opérationnel.
    if not settings.telegram_webhook_secret:
        raise HTTPException(
            status_code=400,
            detail="Configurez d'abord TELEGRAM_WEBHOOK_SECRET (openssl rand -hex 32).",
        )

    webhook_url = f"{settings.api_url}/api/v1/telegram/webhook"
    ok = await set_webhook(webhook_url)
    return {"ok": ok, "webhook_url": webhook_url}
