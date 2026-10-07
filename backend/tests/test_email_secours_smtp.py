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
async def test_delai_ambigu_ne_double_pas_un_mail_de_masse(env):
    appels, reponses = env
    reponses["brevo.test"] = alerts.ResultatEnvoi(False, "SMTP TimeoutError: t")
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert not r and appels == ["brevo.test"]


@pytest.mark.asyncio
async def test_sans_relais_tout_passe_par_resend(env, monkeypatch):
    appels, _ = env
    monkeypatch.setattr(alerts.settings, "smtp_host", "")
    monkeypatch.setattr(alerts.settings, "smtp2_host", "")
    assert await alerts.send_email("a@b.fr", "s", "<p>x</p>")
    assert appels == ["resend"]


# ── _envoi_smtp : TLS vérifié, refus avant transmission vs coupure ambiguë ──
import smtplib  # noqa: E402

_RELAIS = {"nom": "smtp:h", "host": "h", "port": 587, "user": "u", "password": "p", "from": ""}


def _faux_smtp(monkeypatch, echec_a=None, exc=None):
    vu = {}

    class F:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def starttls(self, context=None):
            vu["contexte"] = context
            if echec_a == "tls":
                raise exc

        def login(self, u, p):
            if echec_a == "login":
                raise exc

        def send_message(self, m):
            if echec_a == "envoi":
                raise exc
    monkeypatch.setattr(smtplib, "SMTP", F)
    monkeypatch.setattr(alerts, "_pauses", {})
    return vu


@pytest.mark.asyncio
async def test_smtp_verifie_le_certificat(monkeypatch):
    import ssl
    vu = _faux_smtp(monkeypatch)
    r = await alerts._envoi_smtp("a@b.fr", "s", "<p>x</p>", None, unsubscribe_url=None, relais=_RELAIS)
    assert r
    assert vu["contexte"] is not None and vu["contexte"].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.asyncio
async def test_echec_authentification_est_un_refus(monkeypatch):
    _faux_smtp(monkeypatch, "login", smtplib.SMTPAuthenticationError(535, b"bad"))
    r = await alerts._envoi_smtp("a@b.fr", "s", "<p>x</p>", None, unsubscribe_url=None, relais=_RELAIS)
    assert not r and alerts._refus_explicite(r)


@pytest.mark.asyncio
async def test_coupure_pendant_transmission_est_ambigue(monkeypatch):
    _faux_smtp(monkeypatch, "envoi", smtplib.SMTPServerDisconnected("coupé"))
    r = await alerts._envoi_smtp("a@b.fr", "s", "<p>x</p>", None, unsubscribe_url=None, relais=_RELAIS)
    assert not r and not alerts._refus_explicite(r)


@pytest.mark.asyncio
async def test_refus_quota_met_en_pause_mais_pas_le_debit(monkeypatch):
    _faux_smtp(monkeypatch, "envoi", smtplib.SMTPDataError(421, b"too many connections"))
    await alerts._envoi_smtp("a@b.fr", "s", "<p>x</p>", None, unsubscribe_url=None, relais=_RELAIS)
    assert not alerts._en_pause("smtp:h")
    _faux_smtp(monkeypatch, "envoi", smtplib.SMTPDataError(554, b"daily quota exceeded"))
    r = await alerts._envoi_smtp("a@b.fr", "s", "<p>x</p>", None, unsubscribe_url=None, relais=_RELAIS)
    assert alerts._refus_explicite(r) and alerts._en_pause("smtp:h")


@pytest.mark.asyncio
async def test_mail_vital_delai_ambigu_tente_le_suivant(env):
    # Inscription/paiement : mieux vaut un doublon qu'un mail perdu.
    appels, reponses = env
    reponses["resend"] = httpx.ReadTimeout("t")
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert r and appels == ["resend", "brevo.test"]


@pytest.mark.asyncio
async def test_mail_vital_tous_fournisseurs_essayes(env):
    appels, reponses = env
    reponses["resend"] = _Resp(500, "boom")
    reponses["brevo.test"] = alerts.ResultatEnvoi(False, "SMTP TimeoutError: t")
    r = await alerts.send_email("a@b.fr", "s", "<p>x</p>", transactionnel=True)
    assert r and appels == ["resend", "brevo.test", "mailjet.test"]
