"""La suite de tests ne doit JAMAIS envoyer de vrai e-mail.

Constaté le 2026-08-20 : `backend/.env` porte une `RESEND_API_KEY` valide, que
pydantic charge aussi sous pytest. Les tests d'abonnement, qui journalisent des
mouvements et notifient l'exploitant, ont donc expédié des dizaines de messages
RÉELS dans sa boîte, au nom de comptes fictifs — `6d121afe@blackturf.fr`,
`sub_courant`, `sub_seul`. Chaque exécution de la suite en renvoyait une salve.

Le garde-fou vit dans `send_email` et couvre donc TOUS les appelants, présents et
à venir : c'est le seul endroit qui traverse le réseau.
"""
import pytest

from services import alerts
from services.abonnements import journaliser


@pytest.mark.asyncio
async def test_send_email_ne_traverse_jamais_le_reseau_sous_pytest(monkeypatch):
    """Même avec une clé API valide, aucun appel HTTP ne doit partir."""
    monkeypatch.setattr(alerts.settings, "resend_api_key", "re_cle_valide", raising=False)

    def _interdit(*a, **kw):
        raise AssertionError("un e-mail réel a été envoyé depuis un test")

    monkeypatch.setattr(alerts.httpx, "AsyncClient", _interdit)

    res = await alerts.send_email(to="victime@example.com", subject="x", html="<p>x</p>")

    assert not res
    assert "pytest" in (res.erreur or "")


@pytest.mark.asyncio
async def test_journaliser_un_mouvement_nenvoie_rien(db, monkeypatch):
    """Le chemin exact qui a provoqué la salve : journaliser → notifier l'admin."""
    import uuid
    from db.models import User

    monkeypatch.setattr(alerts.settings, "resend_api_key", "re_cle_valide", raising=False)

    def _interdit(*a, **kw):
        raise AssertionError("un e-mail réel a été envoyé depuis un test")

    monkeypatch.setattr(alerts.httpx, "AsyncClient", _interdit)

    user = User(user_id=str(uuid.uuid4()), email="fictif@blackturf.fr", plan="free")
    db.add(user)
    await db.commit()

    event = await journaliser(db, "essai_ouvert", user, plan="standard")
    assert event is not None  # le journal, lui, doit bien être écrit
