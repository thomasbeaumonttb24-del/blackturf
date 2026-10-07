"""Secours SMTP quand Resend refuse pour quota : l'inscription ne doit plus rester sans mail."""
import types

import httpx
import pytest

from services import alerts


class _Resp:
    def __init__(self, status, corps):
        self.status_code = status
        self.text = corps

    def json(self):
        return {"id": "re_1"}


@pytest.fixture
def env(monkeypatch):
    # pytest repose PYTEST_CURRENT_TEST à chaque phase : on masque os.environ côté module.
    monkeypatch.setattr(alerts, "os", types.SimpleNamespace(environ={}))
    monkeypatch.setattr(alerts.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(alerts.settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(alerts.settings, "smtp_user", "u")
    monkeypatch.setattr(alerts.settings, "smtp_password", "p")
    monkeypatch.setattr(alerts, "_resend_pause_jusqua", None)
    appels = {"resend": 0, "smtp": 0}

    def poser_resend(reponse):
        async def post(self, *a, **k):
            appels["resend"] += 1
            if isinstance(reponse, Exception):
                raise reponse
            return reponse
        monkeypatch.setattr(httpx.AsyncClient, "post", post)

    async def smtp(*a, **k):
        appels["smtp"] += 1
        return alerts.ResultatEnvoi(True, provider_id="smtp:x")
    monkeypatch.setattr(alerts, "_envoi_smtp", smtp)
    return appels, poser_resend


@pytest.mark.asyncio
async def test_quota_resend_bascule_sur_smtp_puis_pause(env):
    appels, poser_resend = env
    poser_resend(_Resp(429, '{"name":"daily_quota_exceeded"}'))
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert r and r.provider_id == "smtp:x"
    # Resend en pause : le mail suivant part directement en SMTP.
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert r and appels == {"resend": 1, "smtp": 2}


@pytest.mark.asyncio
async def test_resend_ok_pas_de_smtp(env):
    appels, poser_resend = env
    poser_resend(_Resp(200, ""))
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert appels["smtp"] == 0


@pytest.mark.asyncio
async def test_delai_ambigu_ne_double_pas(env):
    appels, poser_resend = env
    poser_resend(httpx.ReadTimeout("t"))
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert not r and appels["smtp"] == 0
