"""Audit des e-mails du 10/10/2026 : échecs visibles, rebonds des relais, envoi hôte.

- `send_email` ne lève jamais : un mail d'alerte raté passait inaperçu. `alerter_admin`
  journalise l'échec et rend le résultat.
- Les rebonds Brevo/Mailjet n'alimentaient pas la liste de suppression : une adresse
  morte continuait de recevoir l'éditorial.
- La sentinelle et la sonde de santé n'avaient que Resend : quota saturé = alerte perdue.
"""
import importlib.util
import os
import pathlib
import smtplib
import types

import pytest
from sqlalchemy import select

from db.models import EmailLivraison
from services import alerts
from services import email_campaigns as campaign

RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent


# ── alerter_admin ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_alerter_admin_journalise_et_rend_l_echec(monkeypatch):
    vus = []

    async def _refus(**kw):
        vus.append(kw)
        return alerts.ResultatEnvoi(False, "HTTP 429 quota")

    erreurs = []
    monkeypatch.setattr(alerts, "send_email", _refus)
    monkeypatch.setattr(alerts.log, "error", lambda ev, **kw: erreurs.append((ev, kw)))
    res = await alerts.alerter_admin("Sujet", "<p>x</p>", contexte="essai")
    assert not res and res.erreur == "HTTP 429 quota"
    assert vus[0]["to"] == alerts.settings.admin_email
    assert erreurs and erreurs[0][0] == "alerts.admin.echec"
    assert erreurs[0][1]["contexte"] == "essai"


@pytest.mark.asyncio
async def test_alerter_admin_ne_leve_jamais(monkeypatch):
    async def _casse(**kw):
        raise RuntimeError("panne")

    monkeypatch.setattr(alerts, "send_email", _casse)
    res = await alerter_admin_res(monkeypatch)
    assert not res and "panne" in res.erreur


async def alerter_admin_res(monkeypatch):
    monkeypatch.setattr(alerts.log, "error", lambda *a, **k: None)
    return await alerts.alerter_admin("S", "<p>x</p>", to="ops@exemple.fr")


def test_texte_depuis_html_lisible():
    t = alerts.texte_depuis_html("<style>p{}</style><h3>Titre</h3><ul><li>A &amp; B</li>"
                                 "<li>C &lt;D&gt;</li></ul><p>fin<br>ligne</p>")
    assert t == "Titre\nA & B\nC <D>\nfin\nligne"


@pytest.mark.asyncio
async def test_partie_texte_aussi_chez_resend(monkeypatch):
    # Les alertes admin partaient en HTML seul chez Resend.
    monkeypatch.setattr(alerts, "os", types.SimpleNamespace(environ={}))
    monkeypatch.setattr(alerts.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(alerts, "_relais_smtp", lambda: [])
    monkeypatch.setattr(alerts, "_pauses", {})
    recu = {}

    async def _resend(to, subject, html, text, **kw):
        recu["text"] = text
        return alerts.ResultatEnvoi(True, provider_id="re_1")

    monkeypatch.setattr(alerts, "_envoi_resend", _resend)
    assert await alerts.send_email("a@b.fr", "s", "<p>Bonjour</p>", transactionnel=True)
    assert recu["text"] == "Bonjour"


# ── Rebonds des relais SMTP ──────────────────────────────────────────────────
def test_evenements_relais_ne_gardent_que_les_adresses_mortes():
    from api.routes.newsletter import evenements_relais
    assert evenements_relais("brevo", {"event": "hard_bounce", "email": "A@X.fr",
                                       "message-id": "<1@blackturf.fr>"}) == [
        ("a@x.fr", "bounced", "<1@blackturf.fr>")]
    assert evenements_relais("brevo", {"event": "soft_bounce", "email": "a@x.fr"}) == []
    assert evenements_relais("brevo", {"event": "spam", "email": "a@x.fr"})[0][1] == "complained"
    assert evenements_relais("mailjet", [
        {"event": "bounce", "hard_bounce": False, "email": "mou@x.fr"},
        {"event": "bounce", "hard_bounce": True, "email": "dur@x.fr"},
        {"event": "spam", "email": "plainte@x.fr"},
        {"event": "open", "email": "lu@x.fr"},
        "pas un objet",
    ]) == [("dur@x.fr", "bounced", None), ("plainte@x.fr", "complained", None)]


@pytest.mark.asyncio
async def test_webhook_relais_exige_le_jeton(client):
    path = "/api/v1/newsletter/relais-webhook/brevo"
    ev = {"event": "hard_bounce", "email": "a@x.fr"}
    assert (await client.post(path, json=ev)).status_code == 403
    assert (await client.post(path + "?jeton=faux", json=ev)).status_code == 403
    assert (await client.post("/api/v1/newsletter/relais-webhook/autre?jeton=x", json=ev)).status_code == 404


@pytest.mark.asyncio
async def test_rebond_brevo_supprime_l_adresse_pour_l_editorial(client, db, monkeypatch):
    from api.routes.newsletter import jeton_webhook_relais
    monkeypatch.setattr(alerts.settings, "smtp_host", "smtp-relay.brevo.com")
    monkeypatch.setattr(alerts.settings, "smtp_user", "u")
    monkeypatch.setattr(alerts.settings, "smtp_password", "p")
    db.add(EmailLivraison(cle="l1", campagne="jour-2026-10-10", email="mort@x.fr", requete={},
                          statut="sent", provider_id="smtp:smtp-relay.brevo.com:<42@blackturf.fr>"))
    await db.commit()
    path = f"/api/v1/newsletter/relais-webhook/brevo?jeton={jeton_webhook_relais('brevo')}"
    r = await client.post(path, json={"event": "hard_bounce", "email": "mort@x.fr",
                                      "message-id": "<42@blackturf.fr>"})
    assert r.status_code == 200 and r.json()["traites"] == 1
    row = await db.get(EmailLivraison, "l1")
    await db.refresh(row)
    assert row.statut == "bounced"

    # `deliver()` n'écrit plus à cette adresse.
    envois = []

    async def _envoi(**kw):
        envois.append(kw)
        return alerts.ResultatEnvoi(True)

    monkeypatch.setattr(alerts, "send_email", _envoi)
    from datetime import datetime, timezone
    assert await campaign.deliver(db, "jour-2026-10-11", "mort@x.fr", "s", "<p>x</p>", "x",
                                  None, datetime.now(timezone.utc)) is False
    assert envois == []


@pytest.mark.asyncio
async def test_plainte_mailjet_sans_envoi_editorial_cree_une_suppression(client, db):
    from api.routes.newsletter import jeton_webhook_relais
    path = f"/api/v1/newsletter/relais-webhook/mailjet?jeton={jeton_webhook_relais('mailjet')}"
    r = await client.post(path, json=[{"event": "spam", "email": "Plainte@X.fr"},
                                      {"event": "spam", "email": "plainte@x.fr"}])
    assert r.status_code == 200
    rows = (await db.execute(select(EmailLivraison).where(
        EmailLivraison.email == "plainte@x.fr"))).scalars().all()
    assert [(x.campagne, x.statut) for x in rows] == [("suppression-mailjet", "complained")]


# ── Envoi depuis l'hôte (sentinelle, sonde de santé) ─────────────────────────
@pytest.fixture
def mailer():
    chemin = RACINE / "scripts" / "bt_mail_admin.py"
    if not chemin.exists():
        pytest.fail(f"{chemin} introuvable : monter le dépôt (scripts/gate_tests.sh)")
    spec = importlib.util.spec_from_file_location("bt_mail_admin", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ENV = {"ADMIN_EMAIL": "ops@exemple.fr", "RESEND_API_KEY": "re_x",
       "SMTP_HOST": "brevo.test", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
       "SMTP2_HOST": "mailjet.test", "SMTP2_USER": "u2", "SMTP2_PASSWORD": "p2"}


def test_mailer_bascule_sur_le_relais_si_resend_refuse(mailer, monkeypatch):
    appels = []

    def _resend(*a, **k):
        appels.append("resend")
        raise mailer.Refus("resend HTTP 429 quota")

    def _smtp(env, pre, *a, **k):
        appels.append(pre)
        return f"{pre}ok"

    monkeypatch.setattr(mailer, "par_resend", _resend)
    monkeypatch.setattr(mailer, "par_smtp", _smtp)
    ok, cr = mailer.envoyer(ENV, "[BlackTurf] essai", "<p>x</p>")
    assert ok and appels == ["resend", "SMTP_"]


def test_mailer_ne_double_pas_un_envoi_ambigu(mailer, monkeypatch):
    appels = []

    def _resend(*a, **k):
        appels.append("resend")
        raise TimeoutError("délai")  # le mail est peut-être parti

    monkeypatch.setattr(mailer, "par_resend", _resend)
    monkeypatch.setattr(mailer, "par_smtp", lambda *a, **k: appels.append("smtp"))
    ok, cr = mailer.envoyer(ENV, "s", "<p>x</p>")
    assert not ok and appels == ["resend"] and "délai" in cr


def test_mailer_sans_destinataire(mailer):
    assert mailer.envoyer({}, "s", "x") == (False, "ADMIN_EMAIL absente du .env")


def test_mailer_smtp_refus_avant_transmission_est_explicite(mailer, monkeypatch):
    class _Srv:
        def __init__(self, *a, **k):
            pass

        def starttls(self, **k):
            raise ConnectionRefusedError("fermé")

    monkeypatch.setattr(smtplib, "SMTP", _Srv)
    with pytest.raises(mailer.Refus):
        mailer.par_smtp(ENV, "SMTP_", "ops@exemple.fr", "s", "<p>x</p>", "a@blackturf.fr", "BT")


def test_mailer_lit_le_env(mailer, tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nADMIN_EMAIL=\"ops@x.fr\"\nRESEND_API_KEY=re_a=b\n\nVIDE=\n", encoding="utf-8")
    assert mailer.lire_env(str(f)) == {"ADMIN_EMAIL": "ops@x.fr", "RESEND_API_KEY": "re_a=b", "VIDE": ""}


def test_sentinelle_et_sonde_passent_par_le_mailer():
    for nom in ("bt_sentinelle.sh", "bt_sante.sh"):
        texte = (RACINE / "scripts" / nom).read_text(encoding="utf-8")
        assert "api.resend.com" not in texte, nom
        assert "bt_mail_admin.py" in texte, nom
    sentinelle = (RACINE / "scripts" / "bt_sentinelle.sh").read_text(encoding="utf-8")
    # Le sujet n'est marqué « vu » qu'après un envoi réussi.
    alerte = sentinelle.split("alerte() {", 1)[1].split("\n}", 1)[0]
    assert "> \"$f\"" not in alerte
