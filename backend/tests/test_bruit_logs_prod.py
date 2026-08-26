"""Deux sources de bruit constatées dans les logs de production le 25/08/2026.

Aucune ne cassait une fonctionnalité — c'est précisément pourquoi elles sont
restées : elles produisaient des lignes d'erreur pour des situations normales,
et ce bruit masque les vraies pannes sur la même page de logs. Le second cas
allait plus loin : il comptait un échec sur la source CRITIQUE.
"""
import asyncio

import pytest
from starlette.websockets import WebSocketState

from api.routes.ws import fermer_ws, _est_deconnexion
from scraper.sources.pmu import PmuScraper


class _WSFactice:
    """WebSocket minimal : suit ses états et compte les fermetures."""

    def __init__(self, client=WebSocketState.CONNECTED, application=WebSocketState.CONNECTED):
        self.client_state = client
        self.application_state = application
        self.fermetures = 0
        self.codes: list[int] = []

    async def close(self, code: int = 1000):
        self.fermetures += 1
        self.codes.append(code)
        self.client_state = WebSocketState.DISCONNECTED
        self.application_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_fermeture_ws_une_seule_fois():
    """Deux fermetures concurrentes (heartbeat + sortie du handler) ne doivent
    produire qu'un seul `close` — sinon Starlette lève et uvicorn journalise une
    pile ASGI complète pour une déconnexion normale."""
    ws = _WSFactice()
    await fermer_ws(ws, code=4401)
    await fermer_ws(ws)
    assert ws.fermetures == 1
    assert ws.codes == [4401]


@pytest.mark.asyncio
async def test_fermeture_ws_absorbe_le_runtimeerror():
    """Course perdue malgré la garde d'état : l'erreur ne doit pas remonter."""

    class _WSQuiLeve(_WSFactice):
        async def close(self, code: int = 1000):
            raise RuntimeError(
                "Unexpected ASGI message 'websocket.close', after sending 'websocket.close'"
            )

    await fermer_ws(_WSQuiLeve())  # ne lève pas


class _Reponse:
    def __init__(self, status_code=200, content=b"{}", payload=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if not self.content:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _ClientFactice:
    def __init__(self, reponse):
        self.reponse = reponse
        self.appels = 0

    async def get(self, url):
        self.appels += 1
        return self.reponse


@pytest.mark.asyncio
async def test_pmu_204_nest_pas_un_echec(monkeypatch):
    """Le PMU répond 204 sans corps sur `masse-enjeu` d'une réunion qui ne publie
    pas ses enjeux. Traité comme une panne, cela faisait 3 requêtes, une ligne
    d'erreur par course, et un `record_failure` sur la source critique — assez de
    204 d'affilée et le disjoncteur s'ouvrait, bloquant les VRAIS appels PMU."""
    s = PmuScraper()
    client = _ClientFactice(_Reponse(status_code=204, content=b""))
    monkeypatch.setattr(s, "_get_client", lambda: asyncio.sleep(0, result=client))

    echecs = []
    monkeypatch.setattr(s._cb, "record_failure", lambda *a, **k: echecs.append(a))
    monkeypatch.setattr(s._cb, "is_open", lambda: False)

    assert await s._fetch_json("https://exemple/masse-enjeu") is None
    assert client.appels == 1, "aucun retry sur un 204 : le serveur a répondu"
    assert echecs == [], "un 204 ne doit jamais compter comme un échec du disjoncteur"


@pytest.mark.asyncio
async def test_pmu_json_valide_toujours_servi(monkeypatch):
    """Garde-fou : le court-circuit du 204 ne doit pas avaler une réponse pleine."""
    s = PmuScraper()
    client = _ClientFactice(_Reponse(status_code=200, content=b'{"a":1}', payload={"a": 1}))
    monkeypatch.setattr(s, "_get_client", lambda: asyncio.sleep(0, result=client))
    monkeypatch.setattr(s._cb, "is_open", lambda: False)
    monkeypatch.setattr(s._cb, "record_success", lambda *a, **k: None)

    assert await s._fetch_json("https://exemple/programme") == {"a": 1}


def test_deconnexion_client_nest_pas_une_erreur():
    """Écrire sur une socket que le navigateur vient de fermer — onglet quitté,
    téléphone verrouillé — remonte un `RuntimeError` de Starlette. Journalisé en
    `error`, il remplissait la supervision de faux positifs (constaté en prod le
    26/08/2026 : `ws.alertes.error … Need to call "accept" first`)."""
    from fastapi import WebSocketDisconnect

    assert _est_deconnexion(RuntimeError('WebSocket is not connected. Need to call "accept" first.'))
    assert _est_deconnexion(RuntimeError("Unexpected ASGI message 'websocket.close'"))
    assert _est_deconnexion(WebSocketDisconnect(code=1001))
    assert _est_deconnexion(ConnectionResetError("peer reset"))

    # …mais une vraie panne doit rester une erreur.
    assert not _est_deconnexion(ValueError("payload illisible"))
    assert not _est_deconnexion(RuntimeError("redis indisponible"))
