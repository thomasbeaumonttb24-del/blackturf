"""Le webhook Telegram exige son secret partagé — toujours, pas « si configuré ».

La vérification était conditionnelle (`if settings.telegram_webhook_secret`) et le
secret n'était PAS configuré en production : n'importe qui pouvait POSTer sur la
route et faire exécuter `handle_update`, donc déclencher des tâches et des
requêtes en base au nom d'un expéditeur non authentifié.
"""
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import api.routes.telegram as telegram_route
from services import telegram_bot

SECRET = "s3cr3t-de-test-pour-telegram"
UPDATE = {"message": {"chat": {"id": 1}, "text": "/start", "from": {"first_name": "T"}}}


@pytest.fixture
def sans_secret(monkeypatch):
    monkeypatch.setattr(telegram_route.settings, "telegram_webhook_secret", "", raising=False)


@pytest.fixture
def avec_secret(monkeypatch):
    monkeypatch.setattr(telegram_route.settings, "telegram_webhook_secret", SECRET, raising=False)


async def test_sans_secret_configure_la_route_est_fermee(client: AsyncClient, sans_secret, monkeypatch):
    """C'était l'état réel de la production : route ouverte à tout le monde."""
    appel = AsyncMock()
    monkeypatch.setattr(telegram_route, "handle_update", appel)

    resp = await client.post("/api/v1/telegram/webhook", json=UPDATE)

    assert resp.status_code == 403
    assert "TELEGRAM_WEBHOOK_SECRET" in resp.json()["detail"]
    appel.assert_not_awaited()


async def test_mauvais_secret_rejete(client: AsyncClient, avec_secret, monkeypatch):
    appel = AsyncMock()
    monkeypatch.setattr(telegram_route, "handle_update", appel)

    resp = await client.post("/api/v1/telegram/webhook", json=UPDATE,
                             headers={"X-Telegram-Bot-Api-Secret-Token": "pas-le-bon"})

    assert resp.status_code == 403
    appel.assert_not_awaited()


async def test_entete_absent_rejete(client: AsyncClient, avec_secret, monkeypatch):
    appel = AsyncMock()
    monkeypatch.setattr(telegram_route, "handle_update", appel)

    resp = await client.post("/api/v1/telegram/webhook", json=UPDATE)

    assert resp.status_code == 403
    appel.assert_not_awaited()


async def test_bon_secret_accepte(client: AsyncClient, avec_secret, monkeypatch):
    appel = AsyncMock()
    monkeypatch.setattr(telegram_route, "handle_update", appel)

    resp = await client.post("/api/v1/telegram/webhook", json=UPDATE,
                             headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ── Enregistrement du webhook côté Telegram ──────────────────────────────────
async def test_set_webhook_refuse_sans_secret(monkeypatch):
    """Sans `secret_token`, Telegram appellerait la route sans en-tête : on refuse
    d'enregistrer un webhook que l'on rejetterait ensuite systématiquement."""
    monkeypatch.setattr(telegram_bot.settings, "telegram_bot_token", "jeton-bidon", raising=False)
    monkeypatch.setattr(telegram_bot.settings, "telegram_webhook_secret", "", raising=False)
    appel_http = AsyncMock()
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", appel_http)

    assert await telegram_bot.set_webhook("https://api.blackturf.fr/x") is False
    appel_http.assert_not_called()


async def test_endpoint_setup_explique_le_secret_manquant(
    client: AsyncClient, admin_headers, sans_secret
):
    resp = await client.post("/api/v1/telegram/setup-webhook", headers=admin_headers)
    assert resp.status_code == 400
    assert "TELEGRAM_WEBHOOK_SECRET" in resp.json()["detail"]


async def test_endpoint_setup_reste_reserve_aux_admins(client: AsyncClient, auth_headers, avec_secret):
    resp = await client.post("/api/v1/telegram/setup-webhook", headers=auth_headers)
    assert resp.status_code == 403
