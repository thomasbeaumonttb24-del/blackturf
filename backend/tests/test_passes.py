"""Passes sans renouvellement (jour / semaine / mois) : accordés seulement sur un
paiement Stripe vérifié, une seule fois par session, enchaînés sans perte,
retirés sur remboursement ou contestation, coupés à l'échéance."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import api.routes.stripe_routes as sr
from db.models import PassAcces
from services import passes as P
from tests.test_stripe_essai_et_changement_plan import _abo, _user

pytestmark = pytest.mark.asyncio


def _session(user, duree="jour", sid="cs_test_1", **surcharges) -> dict:
    s = {
        "id": sid, "object": "checkout.session", "mode": "payment",
        "status": "complete", "payment_status": "paid",
        "amount_total": P.PASSES[duree][0], "currency": "eur",
        "customer": user.stripe_customer_id, "payment_intent": f"pi_{sid}",
        # Case de renonciation cochée sur la page Stripe (v2), attestée par Stripe.
        "consent": {"terms_of_service": "accepted"},
        "metadata": {
            "type": "pass", "duree": duree, "user_id": user.user_id,
            "renonciation_at": datetime.now(timezone.utc).isoformat(),
            "renonciation_version": P.RENONCIATION_VERSION,
        },
    }
    meta = surcharges.pop("metadata", None)
    if meta is not None:
        s["metadata"] = {**s["metadata"], **meta}
    s.update(surcharges)
    return s


def _aware(d):
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


async def _nb_passes(db) -> int:
    return (await db.execute(select(func.count()).select_from(PassAcces))).scalar_one()


# ── Validation : rien n'est accordé sans paiement exact et vérifié ───────────
@pytest.mark.parametrize("surcharge", [
    {"payment_status": "unpaid"},
    {"status": "open"},
    {"mode": "subscription"},
    {"amount_total": 1},            # montant modifié
    {"amount_total": 1200},         # prix de la semaine pour un pass jour
    {"currency": "usd"},
    {"metadata": {"type": "autre"}},
    {"metadata": {"duree": "annee"}},
    {"metadata": {"renonciation_version": None}},
    {"consent": {"terms_of_service": None}},   # case non cochée sur Stripe
    {"metadata": {"user_id": ""}},
])
async def test_session_douteuse_naccorde_rien(db, surcharge):
    user = await _user(db)
    with pytest.raises(P.PassInvalide):
        await P.accorder(db, _session(user, **surcharge))
    assert await _nb_passes(db) == 0
    await db.refresh(user)
    assert user.plan == "free"


async def test_client_stripe_dun_autre_compte_refuse(db):
    user = await _user(db, stripe_customer_id="cus_a")
    await _user(db, stripe_customer_id="cus_b")
    with pytest.raises(P.PassInvalide):
        await P.accorder(db, _session(user, customer="cus_b"))
    assert await _nb_passes(db) == 0


async def test_client_orphelin_du_double_clic_accepte(db):
    """Deux clics : deux clients Stripe créés, le compte ne garde que le second.
    Le pass payé sur le premier (orphelin) reste dû."""
    user = await _user(db, stripe_customer_id="cus_second")
    _p, cree = await P.accorder(db, _session(user, customer="cus_premier"))
    assert cree is True


# ── Octroi ───────────────────────────────────────────────────────────────────
async def test_pass_jour_donne_expert_24h(db):
    user = await _user(db)
    p, cree = await P.accorder(db, _session(user))
    assert cree is True
    await db.refresh(user)
    assert user.plan == "expert"
    duree = _aware(p.fin) - _aware(p.debut)
    assert duree == timedelta(hours=24)
    assert p.montant_cents == 500 and p.renonciation_version == P.RENONCIATION_VERSION


async def test_meme_session_naccorde_quune_fois(db):
    """Webhook + page de retour (ou relivraison Stripe) : un seul pass."""
    user = await _user(db)
    s = _session(user, duree="semaine")
    await P.accorder(db, s)
    p2, cree2 = await P.accorder(db, s)
    assert cree2 is False
    assert await _nb_passes(db) == 1
    actif = await P.pass_actif(db, user.user_id)
    assert _aware(actif["fin"]) - datetime.now(timezone.utc) < timedelta(days=7, minutes=1)


async def test_deux_passes_senchainent_sans_perte(db):
    user = await _user(db)
    p1, _ = await P.accorder(db, _session(user, duree="jour", sid="cs_a"))
    p2, _ = await P.accorder(db, _session(user, duree="semaine", sid="cs_b"))
    assert _aware(p2.debut) == _aware(p1.fin)
    actif = await P.pass_actif(db, user.user_id)
    assert _aware(actif["fin"]) == _aware(p1.fin) + timedelta(days=7)


# ── Échéance ─────────────────────────────────────────────────────────────────
async def _antidater(db, p, heures=25):
    p.debut = datetime.now(timezone.utc) - timedelta(hours=heures)
    p.fin = datetime.now(timezone.utc) - timedelta(hours=heures - 24)
    await db.commit()


async def test_echeance_rend_free(db):
    user = await _user(db)
    p, _ = await P.accorder(db, _session(user))
    await _antidater(db, p)
    assert await P.expirer_passes(db) == 1
    await db.refresh(user)
    assert user.plan == "free"
    assert await P.expirer_passes(db) == 0  # idempotent


async def test_abonne_standard_retrouve_standard_apres_son_pass(db):
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active")
    p, _ = await P.accorder(db, _session(user))
    await db.refresh(user)
    assert user.plan == "expert"
    await _antidater(db, p)
    await P.expirer_passes(db)
    await db.refresh(user)
    assert user.plan == "standard"


async def test_pass_suivant_deja_paye_garde_lacces_a_lecheance_du_premier(db):
    user = await _user(db)
    p1, _ = await P.accorder(db, _session(user, sid="cs_1"))
    p2, _ = await P.accorder(db, _session(user, sid="cs_2"))
    # Le premier est échu, le second commence maintenant.
    maintenant = datetime.now(timezone.utc)
    p1.debut, p1.fin = maintenant - timedelta(hours=24), maintenant - timedelta(seconds=1)
    p2.debut, p2.fin = maintenant - timedelta(seconds=1), maintenant + timedelta(hours=24)
    await db.commit()
    await P.expirer_passes(db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_webhook_dabonnement_neffece_pas_un_pass(db):
    user = await _user(db)
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_x")
    await P.accorder(db, _session(user))
    await sr._handle_subscription_deleted({"id": "sub_x", "customer": user.stripe_customer_id}, db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_requete_apres_echeance_coupe_a_la_seconde(client, db, inscrire):
    headers = await inscrire(email="pass@blackturf.fr")
    from db.models import User
    user = (await db.execute(select(User).where(User.email == "pass@blackturf.fr"))).scalar_one()
    p, _ = await P.accorder(db, _session(user))
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["plan"] == "expert"
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["pass_fin"]
    await _antidater(db, p)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["plan"] == "free" and me["pass_fin"] is None
    assert me["essai_disponible"] is False


# ── Remboursement / contestation ─────────────────────────────────────────────
async def test_remboursement_total_retire_le_pass(db):
    user = await _user(db)
    p, _ = await P.accorder(db, _session(user, sid="cs_r"))
    await sr._traiter_evenement("charge.refunded",
                                {"id": "ch_1", "refunded": True, "payment_intent": "pi_cs_r"}, db)
    await db.refresh(user)
    await db.refresh(p)
    assert p.statut == "rembourse" and user.plan == "free"


async def test_remboursement_partiel_garde_le_pass(db):
    user = await _user(db)
    await P.accorder(db, _session(user, sid="cs_p"))
    await sr._traiter_evenement("charge.refunded",
                                {"id": "ch_2", "refunded": False, "payment_intent": "pi_cs_p"}, db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_contestation_retire_le_pass(db):
    user = await _user(db)
    await P.accorder(db, _session(user, sid="cs_d"))
    await sr._traiter_evenement("charge.dispute.created",
                                {"id": "dp_1", "payment_intent": "pi_cs_d"}, db)
    await db.refresh(user)
    assert user.plan == "free"


# ── Webhook checkout.session.completed ───────────────────────────────────────
async def test_webhook_checkout_accorde_et_ignore_les_abonnements(db):
    user = await _user(db)
    await sr._traiter_evenement("checkout.session.completed",
                                {"id": "cs_sub", "mode": "subscription", "metadata": {}}, db)
    assert await _nb_passes(db) == 0
    await sr._traiter_evenement("checkout.session.completed", _session(user, sid="cs_wh"), db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_webhook_session_douteuse_ne_leve_pas(db):
    """Stripe relivrerait en boucle une exception : on journalise et on n'accorde rien."""
    user = await _user(db)
    await sr._traiter_evenement("checkout.session.completed",
                                _session(user, amount_total=1), db)
    assert await _nb_passes(db) == 0


# ── Création du paiement ─────────────────────────────────────────────────────
def _capture_pass(monkeypatch) -> dict:
    captured: dict = {}

    def _fake_create(**kw):
        captured.update(kw)
        return SimpleNamespace(url="https://checkout.stripe.test/pass", id="cs_new")

    monkeypatch.setattr(sr.stripe.checkout.Session, "create", _fake_create)
    return captured


async def test_checkout_pass_prix_serveur_et_renonciation(db, monkeypatch):
    captured = _capture_pass(monkeypatch)
    user = await _user(db)
    r = await sr.creer_checkout_pass(sr.PassRequest(duree="mois", renonciation=True), db, user)
    assert r["url"]
    assert captured["mode"] == "payment"
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 2400
    assert captured["metadata"]["type"] == "pass" and captured["metadata"]["user_id"] == user.user_id
    assert captured["payment_intent_data"]["metadata"]["duree"] == "mois"
    assert "allow_promotion_codes" not in captured and "discounts" not in captured
    assert "subscription_data" not in captured
    # Case de renonciation OBLIGATOIRE sur la page Stripe (v2).
    assert captured["consent_collection"] == {"terms_of_service": "required"}
    assert "renonce" in captured["custom_text"]["terms_of_service_acceptance"]["message"]
    assert captured["metadata"]["renonciation_version"] == "v2"


@pytest.mark.parametrize("body,code", [
    ({"duree": "an"}, 400),
    ({"duree": ""}, 400),
])
async def test_checkout_pass_refus(db, monkeypatch, body, code):
    _capture_pass(monkeypatch)
    user = await _user(db)
    with pytest.raises(HTTPException) as exc:
        await sr.creer_checkout_pass(sr.PassRequest(**body), db, user)
    assert exc.value.status_code == code


async def test_checkout_pass_refuse_a_un_abonne_expert(db, monkeypatch):
    _capture_pass(monkeypatch)
    user = await _user(db, plan="expert")
    await _abo(db, user, plan="expert", statut="active")
    with pytest.raises(HTTPException) as exc:
        await sr.creer_checkout_pass(sr.PassRequest(duree="jour", renonciation=True), db, user)
    assert exc.value.status_code == 409


async def test_checkout_pass_cumul_plafonne(db, monkeypatch):
    _capture_pass(monkeypatch)
    user = await _user(db)
    await P.accorder(db, _session(user, duree="mois", sid="cs_m1"))
    await P.accorder(db, _session(user, duree="semaine", sid="cs_m2"))
    with pytest.raises(HTTPException) as exc:
        await sr.creer_checkout_pass(sr.PassRequest(duree="jour", renonciation=True), db, user)
    assert exc.value.status_code == 409


async def test_confirmation_refuse_la_session_dun_autre_compte(db, monkeypatch):
    victime = await _user(db, stripe_customer_id="cus_v")
    curieux = await _user(db, stripe_customer_id="cus_c")
    monkeypatch.setattr(sr.stripe.checkout.Session, "retrieve",
                        lambda sid: _session(victime, sid=sid))
    with pytest.raises(HTTPException) as exc:
        await sr.confirmer_pass(sr.PassConfirmation(session_id="cs_autre"), db, curieux)
    assert exc.value.status_code == 404
    assert await _nb_passes(db) == 0


async def test_confirmation_accorde_sa_propre_session(db, monkeypatch):
    user = await _user(db)
    monkeypatch.setattr(sr.stripe.checkout.Session, "retrieve", lambda sid: _session(user, sid=sid))
    r = await sr.confirmer_pass(sr.PassConfirmation(session_id="cs_ok"), db, user)
    assert r["plan"] == "expert" and r["duree"] == "jour"
    # Deuxième passage (rechargement de la page) : rien de plus.
    await sr.confirmer_pass(sr.PassConfirmation(session_id="cs_ok"), db, user)
    assert await _nb_passes(db) == 1


async def test_confirmation_session_non_payee_409(db, monkeypatch):
    user = await _user(db)
    monkeypatch.setattr(sr.stripe.checkout.Session, "retrieve",
                        lambda sid: _session(user, sid=sid, payment_status="unpaid", status="open"))
    with pytest.raises(HTTPException) as exc:
        await sr.confirmer_pass(sr.PassConfirmation(session_id="cs_np"), db, user)
    assert exc.value.status_code == 409


async def test_confirmation_identifiant_invalide(db):
    user = await _user(db)
    with pytest.raises(HTTPException) as exc:
        await sr.confirmer_pass(sr.PassConfirmation(session_id="pi_123"), db, user)
    assert exc.value.status_code == 400


# ── v2 : case cochée sur la page Stripe, attestée par session.consent ────────
def _session_v2(user, sid="cs_v2", consent="accepted", **kw):
    s = _session(user, sid=sid, **kw)
    s["metadata"] = {k: v for k, v in s["metadata"].items() if k != "renonciation_at"}
    s["metadata"]["renonciation_version"] = "v2"
    if consent is None:
        s.pop("consent", None)
    else:
        s["consent"] = {"terms_of_service": consent}
    return s


async def test_v2_case_attestee_par_stripe_accorde(db):
    user = await _user(db)
    p, cree = await P.accorder(db, _session_v2(user))
    assert cree and p.renonciation_version == "v2" and p.renonciation_at is not None


@pytest.mark.parametrize("consent", [None, "declined", ""])
async def test_v2_sans_case_attestee_rien_n_est_accorde(db, consent):
    user = await _user(db)
    with pytest.raises(P.PassInvalide):
        await P.accorder(db, _session_v2(user, consent=consent))
    assert await _nb_passes(db) == 0


async def test_version_de_renonciation_inconnue_refusee(db):
    user = await _user(db)
    with pytest.raises(P.PassInvalide):
        await P.accorder(db, _session(user, metadata={"renonciation_version": "v9"}))


# ── Fin de pass : relance « continuez avec Expert » ──────────────────────────
async def test_fin_de_pass_relance_une_seule_fois_les_comptes_retombes_en_gratuit(db, monkeypatch):
    from datetime import datetime as _dt
    import services.email_compte as EC
    envoyes = []

    async def _faux(user):
        envoyes.append(user.email)

    monkeypatch.setattr(EC, "envoyer_fin_pass", _faux)
    gratuit = await _user(db, email="fin@x.fr", stripe_customer_id="cus_fin")
    refus = await _user(db, email="refus@x.fr", stripe_customer_id="cus_refus",
                        marketing_opt_out_at=_dt.now(timezone.utc))
    abonne = await _user(db, email="abo@x.fr", plan="standard", stripe_customer_id="cus_abo")
    await _abo(db, abonne, plan="standard", statut="active")
    for u, sid in ((gratuit, "cs_f1"), (refus, "cs_f2"), (abonne, "cs_f3")):
        p, _ = await P.accorder(db, _session(u, sid=sid, customer=u.stripe_customer_id))
        await _antidater(db, p)
    await P.expirer_passes(db)
    assert envoyes == ["fin@x.fr"]          # ni le refus marketing, ni l'abonné Standard
    await P.expirer_passes(db)
    assert envoyes == ["fin@x.fr"]          # jamais deux fois