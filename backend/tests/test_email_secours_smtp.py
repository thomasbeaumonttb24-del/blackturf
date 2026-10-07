"""Chaîne de fournisseurs gratuits : Resend réservé aux mails vitaux, relais SMTP pour le reste."""
import types

import httpx
import pytest

from services import alerts


class _Resp:
    def __init__(self, status, corps=""):
        self.status_code = status
        self.text = corps

    def json(self):
        return {"id": "re_1"}


@pytest.fixture
def env(monkeypatch):
    # pytest repose PYTEST_CURRENT_TEST à chaque phase : on masque os.environ côté module.
    monkeypatch.setattr(alerts, "os", types.SimpleNamespace(environ={}))
    s = alerts.settings
    monkeypatch.setattr(s, "resend_api_key", "re_test")
    for pre, host in (("smtp_", "brevo.test"), ("smtp2_", "mailjet.test")):
        monkeypatch.setattr(s, pre + "host", host)
        monkeypatch.setattr(s, pre + "user", "u")
        monkeypatch.setattr(s, pre + "password", "p")
    monkeypatch.setattr(alerts, "_pauses", {})
    appels: list[str] = []
    reponses: dict = {"resend": _Resp(200)}

    async def post(self, *a, **k):
        appels.append("resend")
        r = reponses["resend"]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    async def smtp(*a, relais, **k):
        appels.append(relais["host"])
        return reponses.get(relais["host"], alerts.ResultatEnvoi(True, provider_id="smtp:x"))
    monkeypatch.setattr(alerts, "_envoi_smtp", smtp)
    return appels, reponses


@pytest.mark.asyncio
async def test_mail_de_masse_ne_touche_pas_resend(env):
    appels, _ = env
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert appels == ["brevo.test"]


@pytest.mark.asyncio
async def test_transactionnel_passe_par_resend(env):
    appels, _ = env
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert appels == ["resend"]


@pytest.mark.asyncio
async def test_quota_resend_bascule_puis_pause(env):
    appels, reponses = env
    reponses["resend"] = _Resp(429, '{"name":"daily_quota_exceeded"}')
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert appels == ["resend", "brevo.test", "brevo.test"]


@pytest.mark.asyncio
async def test_refus_brevo_passe_a_mailjet(env):
    appels, reponses = env
    reponses["brevo.test"] = alerts.ResultatEnvoi(False, "SMTP-REFUS daily limit")
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert appels == ["brevo.test", "mailjet.test"]


@pytest.mark.asyncio
async def test_delai_ambigu_ne_double_pas(env):
    appels, reponses = env
    reponses["resend"] = httpx.ReadTimeout("t")
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert not r and appels == ["resend"]


@pytest.mark.asyncio
async def test_sans_relais_tout_passe_par_resend(env, monkeypatch):
    appels, _ = env
    monkeypatch.setattr(alerts.settings, "smtp_host", "")
    monkeypatch.setattr(alerts.settings, "smtp2_host", "")
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert appels == ["resend"]
