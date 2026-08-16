"""
Tests du paywall sur /ws/value-bets (audit 2026-08-16).

Régression protégée : `ws_value_bets` authentifiait le JWT mais ne vérifiait
AUCUN plan — un compte gratuit pouvait streamer en direct les value bets
réservés Standard+ (la donnée payante la plus sensible du produit), en
contournant entièrement le paywall appliqué côté REST (`GET /value-bets`,
`Depends(require_pro)` + délai 15 min pour Standard).

Le handler est appelé DIRECTEMENT avec un WebSocket mocké (AsyncMock) plutôt que
via starlette.testclient : le TestClient exécute l'ASGI app dans un thread
séparé dont les logs/exceptions serveur ne remontent pas de façon fiable au
test, ce qui rend un vrai bug de requête indiscernable d'un artefact de
threading. L'appel direct est aussi la manière standard de tester un handler
WebSocket FastAPI en isolation.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

import api.routes.ws as wsmod
from api.routes.auth import _hash
from api.routes.ws import PLANS_ABONNES, _get_user_plan, ws_value_bets
from db.models import User, ValueBet, Participation, Cheval, Course, Hippodrome, Reunion, Prediction


async def _create_test_course(db, course_id: str) -> None:
    """Chaîne FK minimale Hippodrome→Reunion→Course (même pattern que
    test_courses.py::_create_test_course)."""
    from datetime import date
    hippo = Hippodrome(hippodrome_id=f"H-{course_id}", nom="Test", code=course_id[:3])
    db.add(hippo)
    reunion = Reunion(reunion_id=f"R-{course_id}", date=date.today(),
                      hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Test", numero=1)
    db.add(reunion)


def _patch_session_factory(monkeypatch, db):
    """Pointe `async_session_factory` (utilisée en dur par ws.py, indépendamment
    de get_db) vers la session de test SQLite en mémoire du fixture `db`."""
    @asynccontextmanager
    async def _ctx():
        yield db
    monkeypatch.setattr(wsmod, "async_session_factory", _ctx)


def _make_ws():
    """WebSocket mocké :
    - accept() : no-op.
    - receive_text() : lève TimeoutError instantanément (simule un client
      silencieux, sans vrai délai — sinon la boucle de heartbeat 60x1s ralentit
      chaque test d'une minute réelle).
    - send_json() : enregistre le payload ; le 2e appel (le premier "ping" du
      heartbeat, après l'envoi initial des value bets) lève une déconnexion —
      termine la boucle `while True` proprement, comme un vrai client qui se
      déconnecte juste après avoir reçu ses données.
    - close() : enregistre le code, ne lève jamais (laisse le handler retourner
      normalement, pas de propagation d'exception à gérer côté test)."""
    ws = AsyncMock()
    ws.accept = AsyncMock(return_value=None)
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError)

    ws.sent = []
    async def _send_json(payload):
        ws.sent.append(payload)
        if len(ws.sent) >= 2:
            raise _ClientGone()
    ws.send_json = AsyncMock(side_effect=_send_json)

    ws.closed_with = []
    async def _close(code=1000, reason=None):
        ws.closed_with.append(code)
    ws.close = AsyncMock(side_effect=_close)
    return ws


class _ClientGone(Exception):
    """Simule une déconnexion client au milieu d'un send_json — capturée par le
    `except Exception` de ws_value_bets exactement comme une vraie
    WebSocketDisconnect le serait à ce point du code."""


async def _create_user(db, plan: str) -> str:
    user = User(user_id=str(uuid.uuid4()), email=f"{plan}-{uuid.uuid4().hex[:8]}@blackturf.fr",
               hashed_password=_hash("Xx123456!"), plan=plan)
    db.add(user)
    await db.commit()
    return user.user_id


def _token_for(user_id: str) -> str:
    from datetime import timedelta
    from api.routes.auth import _create_token
    return _create_token({"sub": user_id, "type": "access"}, timedelta(minutes=30))


# ─────────────────────────────────────────────
# _get_user_plan — unité
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_user_plan_retourne_le_plan_reel(db, monkeypatch):
    _patch_session_factory(monkeypatch, db)
    user_id = await _create_user(db, "expert")
    assert await _get_user_plan(user_id) == "expert"


@pytest.mark.asyncio
async def test_get_user_plan_none_si_introuvable(db, monkeypatch):
    _patch_session_factory(monkeypatch, db)
    assert await _get_user_plan(str(uuid.uuid4())) is None


def test_plans_abonnes_exclut_free_et_decouverte():
    """Documente l'ensemble protégé — doit rester aligné avec require_pro (auth.py)."""
    assert "free" not in PLANS_ABONNES
    assert "decouverte" not in PLANS_ABONNES
    assert set(PLANS_ABONNES) == {"starter", "standard", "expert"}


# ─────────────────────────────────────────────
# ws_value_bets — paywall bout-en-bout (handler appelé directement)
# ─────────────────────────────────────────────
@pytest.mark.parametrize("plan", ["free", "decouverte"])
@pytest.mark.asyncio
async def test_plan_gratuit_rejette_avec_4403(db, monkeypatch, plan):
    _patch_session_factory(monkeypatch, db)
    user_id = await _create_user(db, plan)
    token = _token_for(user_id)
    ws = _make_ws()

    await ws_value_bets(ws, token=token)

    assert ws.closed_with == [4403]
    assert ws.sent == [], "aucune donnée value bet ne doit fuiter avant le close"


@pytest.mark.parametrize("plan", ["starter", "standard", "expert"])
@pytest.mark.asyncio
async def test_plan_abonne_recoit_le_flux(db, monkeypatch, plan):
    _patch_session_factory(monkeypatch, db)
    user_id = await _create_user(db, plan)
    token = _token_for(user_id)
    ws = _make_ws()

    await ws_value_bets(ws, token=token)

    assert 4403 not in ws.closed_with, f"plan={plan} devrait passer le paywall"
    assert len(ws.sent) >= 1
    assert ws.sent[0]["type"] == "value_bets"


@pytest.mark.asyncio
async def test_token_invalide_rejette_avec_4401_pas_4403(db, monkeypatch):
    """Un token invalide doit échouer à l'AUTHENTIFICATION (4401), pas au
    paywall (4403) — les deux codes ne doivent jamais se confondre."""
    _patch_session_factory(monkeypatch, db)
    ws = _make_ws()

    await ws_value_bets(ws, token="token-invalide")

    assert ws.closed_with == [4401]


@pytest.mark.asyncio
async def test_plan_standard_applique_le_delai_15min(db, monkeypatch):
    """Même règle que GET /value-bets (require_pro + délai standard) : un value
    bet détecté il y a moins de 15 min ne doit PAS apparaître pour un compte
    Standard, pour empêcher un contournement du délai REST via le flux WS."""
    from datetime import datetime, timezone

    _patch_session_factory(monkeypatch, db)
    user_id = await _create_user(db, "standard")
    token = _token_for(user_id)

    await _create_test_course(db, "C1")
    course = Course(course_id="C1", reunion_id="R-C1", numero=1, nom="Prix Test",
                    hippodrome_nom="Test", date_heure=datetime.now(timezone.utc),
                    discipline="Plat", distance=1600, nb_partants=1, statut="a_venir")
    cheval = Cheval(cheval_id="H1", nom="Testeur", age=4, sexe="H")
    part = Participation(participation_id="P1", course_id="C1", cheval_id="H1",
                         numero=1, cote_pmu=5.0)
    pred = Prediction(prediction_id="PR1", participation_id="P1", course_id="C1",
                      proba_top1=0.2, proba_top3=0.5, rang_predit=1)
    vb_recent = ValueBet(vb_id="VB1", prediction_id="PR1", course_id="C1", participation_id="P1",
                        actif=True, ev_max=0.20, niveau=2,
                        detecte_a=datetime.now(timezone.utc))  # < 15 min
    db.add_all([course, cheval, part, pred, vb_recent])
    await db.commit()

    ws = _make_ws()
    await ws_value_bets(ws, token=token)

    assert ws.sent[0]["data"] == [], "value bet détecté < 15 min doit être masqué pour Standard"


@pytest.mark.asyncio
async def test_plan_expert_ne_subit_pas_le_delai(db, monkeypatch):
    from datetime import datetime, timezone

    _patch_session_factory(monkeypatch, db)
    user_id = await _create_user(db, "expert")
    token = _token_for(user_id)

    await _create_test_course(db, "C2")
    course = Course(course_id="C2", reunion_id="R-C2", numero=1, nom="Prix Test 2",
                    hippodrome_nom="Test", date_heure=datetime.now(timezone.utc),
                    discipline="Plat", distance=1600, nb_partants=1, statut="a_venir")
    cheval = Cheval(cheval_id="H2", nom="Testeur2", age=4, sexe="H")
    part = Participation(participation_id="P2", course_id="C2", cheval_id="H2",
                         numero=1, cote_pmu=5.0)
    pred = Prediction(prediction_id="PR2", participation_id="P2", course_id="C2",
                      proba_top1=0.2, proba_top3=0.5, rang_predit=1)
    vb_recent = ValueBet(vb_id="VB2", prediction_id="PR2", course_id="C2", participation_id="P2",
                        actif=True, ev_max=0.20, niveau=2,
                        detecte_a=datetime.now(timezone.utc))
    db.add_all([course, cheval, part, pred, vb_recent])
    await db.commit()

    ws = _make_ws()
    await ws_value_bets(ws, token=token)

    assert len(ws.sent[0]["data"]) == 1, "Expert doit voir le value bet immédiatement"
