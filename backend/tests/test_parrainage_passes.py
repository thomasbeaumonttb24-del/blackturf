"""Parrainage × passes sans abonnement (2026-10-04).

Règle : le parrainage vaut pour les Pass Semaine et Mois (−5 € au filleul, 5 € de
crédit au parrain), JAMAIS pour le Pass Jour — 5 € − 5 € = gratuit, deux comptes
se renverraient la balle en boucle. Chaque scénario de contournement a son test.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

import api.routes.stripe_routes as sr
from db.models import CarteConnue, PassAcces, Parrainage, User
from services import parrainage as P
from services import passes as PS
from tests.test_parrainage import _Stripe, _couple, _user
from tests.test_passes import _capture_pass, _session

pytestmark = pytest.mark.asyncio


def _session_remise(user, duree="semaine", sid="cs_r1", **kw):
    s = _session(user, duree=duree, sid=sid, **kw)
    s["amount_total"] = PS.PASSES[duree][0] - P.REMISE_CENTS
    s["total_details"] = {"amount_discount": P.REMISE_CENTS}
    s["metadata"]["remise_parrainage"] = "1"
    return s


def _cartes(monkeypatch, empreinte="fp_filleul"):
    monkeypatch.setattr(P, "cartes_du_paiement", lambda pi: [] if empreinte is None else [
        {"empreinte": empreinte, "pm": "pm_x", "marque": "visa", "dernier4": "4242", "financement": "debit"}])


async def _lien(db, filleul):
    return (await db.execute(select(Parrainage).where(Parrainage.filleul_id == filleul.user_id)
                             .execution_options(populate_existing=True))).scalar_one()


# ── Création du paiement ─────────────────────────────────────────────────────
@pytest.mark.parametrize("duree", ["semaine", "mois"])
async def test_filleul_a_moins_5_euros_sur_semaine_et_mois(db, monkeypatch, duree):
    captured = _capture_pass(monkeypatch)
    monkeypatch.setattr(P, "coupon_filleul", lambda: P.COUPON_FILLEUL_ID)
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [])
    _parrain, filleul, _l = await _couple(db)
    r = await sr.creer_checkout_pass(sr.PassRequest(duree=duree), db, filleul)
    assert r["remise_parrainage"] is True
    assert captured["discounts"] == [{"coupon": P.COUPON_FILLEUL_ID}]
    assert captured["metadata"]["remise_parrainage"] == "1"


async def test_pass_jour_jamais_de_remise_meme_pour_un_filleul(db, monkeypatch):
    captured = _capture_pass(monkeypatch)
    monkeypatch.setattr(P, "coupon_filleul", lambda: P.COUPON_FILLEUL_ID)
    _parrain, filleul, _l = await _couple(db)
    r = await sr.creer_checkout_pass(sr.PassRequest(duree="jour"), db, filleul)
    assert r["remise_parrainage"] is False
    assert "discounts" not in captured and "remise_parrainage" not in captured["metadata"]


async def test_client_ordinaire_pas_de_remise_sur_un_pass(db, monkeypatch):
    captured = _capture_pass(monkeypatch)
    user = await _user(db, stripe_customer_id="cus_ordinaire")
    await sr.creer_checkout_pass(sr.PassRequest(duree="semaine"), db, user)
    assert "discounts" not in captured


async def test_carte_enregistree_connue_ailleurs_pas_de_remise(db, monkeypatch):
    captured = _capture_pass(monkeypatch)
    monkeypatch.setattr(P, "coupon_filleul", lambda: P.COUPON_FILLEUL_ID)
    parrain, filleul, _l = await _couple(db)
    db.add(CarteConnue(empreinte="fp_ancien", user_id=parrain.user_id, email=parrain.email))
    await db.commit()
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [{"empreinte": "fp_ancien"}])
    await sr.creer_checkout_pass(sr.PassRequest(duree="mois"), db, filleul)
    assert "discounts" not in captured


async def test_coupon_indisponible_bloque_plutot_que_plein_tarif_silencieux(db, monkeypatch):
    _capture_pass(monkeypatch)
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [])

    def _panne():
        raise RuntimeError("stripe")

    monkeypatch.setattr(P, "coupon_filleul", _panne)
    _parrain, filleul, _l = await _couple(db)
    with pytest.raises(HTTPException) as exc:
        await sr.creer_checkout_pass(sr.PassRequest(duree="semaine"), db, filleul)
    assert exc.value.status_code == 503


# ── Validation du paiement ───────────────────────────────────────────────────
async def test_montant_remise_accepte_seulement_avec_remise_serveur(db):
    user = await _user(db, stripe_customer_id="cus_v")
    v = PS.valider_session(_session_remise(user))
    assert v["montant_cents"] == 700 and v["remise_parrainage"] is True
    # 7 € SANS remise posée par le serveur : refusé.
    s = _session(user, duree="semaine"); s["amount_total"] = 700
    with pytest.raises(PS.PassInvalide):
        PS.valider_session(s)
    # Remise annoncée mais pas réellement appliquée par Stripe : refusé.
    s = _session_remise(user); s["total_details"] = {"amount_discount": 0}
    with pytest.raises(PS.PassInvalide):
        PS.valider_session(s)
    # Remise sur un Pass Jour (0 €) : refusé.
    with pytest.raises(PS.PassInvalide):
        PS.valider_session(_session_remise(user, duree="jour"))


# ── Octroi + parrainage ──────────────────────────────────────────────────────
async def test_pass_semaine_du_filleul_credite_le_parrain_une_seule_fois(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    _cartes(monkeypatch)
    parrain, filleul, _l = await _couple(db)
    p, _ = await PS.accorder(db, _session_remise(filleul, customer=filleul.stripe_customer_id))
    assert p.montant_cents == 700
    lien = await _lien(db, filleul)
    assert lien.statut == "valide" and lien.remise_filleul_at is not None
    credits = [s for s in stripe_.soldes if s["customer"] == "cus_parrain"]
    assert len(credits) == 1 and credits[0]["amount"] == -500
    # Second pass du filleul : rien de plus pour le parrain, plus de remise due.
    await PS.accorder(db, _session(filleul, duree="mois", sid="cs_r2", customer=filleul.stripe_customer_id))
    assert len([s for s in stripe_.soldes if s["customer"] == "cus_parrain"]) == 1
    await db.refresh(filleul)
    assert await P.remise_filleul_due(filleul, db) is None


async def test_pass_jour_du_filleul_ne_valide_rien_et_garde_sa_remise(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    _cartes(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="jour", sid="cs_j", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "en_attente" and lien.remise_filleul_at is None
    assert stripe_.soldes == []
    await db.refresh(filleul)
    assert await P.remise_filleul_due(filleul, db) is not None  # garde ses −5 € pour Semaine/Mois


async def test_deux_paiements_remises_en_parallele_la_seconde_est_refacturee(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    _cartes(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session_remise(filleul, sid="cs_a", customer=filleul.stripe_customer_id))
    await PS.accorder(db, _session_remise(filleul, duree="mois", sid="cs_b", customer=filleul.stripe_customer_id))
    reprises = [s for s in stripe_.soldes if s["customer"] == "cus_filleul"]
    assert len(reprises) == 1 and reprises[0]["amount"] == 500
    assert len([s for s in stripe_.soldes if s["customer"] == "cus_parrain"]) == 1


async def test_filleul_qui_paie_avec_la_carte_du_parrain_refuse(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    parrain, filleul, _l = await _couple(db)
    db.add(CarteConnue(empreinte="fp_parrain", user_id=parrain.user_id, email=parrain.email))
    await db.commit()
    _cartes(monkeypatch, "fp_parrain")
    await PS.accorder(db, _session_remise(filleul, customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "refuse" and lien.motif == "carte_du_parrain"
    assert not [s for s in stripe_.soldes if s["customer"] == "cus_parrain"]
    assert [s["amount"] for s in stripe_.soldes if s["customer"] == "cus_filleul"] == [500]  # remise refacturée
    # Le pass, payé, reste acquis.
    await db.refresh(filleul)
    assert filleul.plan == "expert"


async def test_carte_illisible_la_recompense_attend(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    _cartes(monkeypatch, None)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session_remise(filleul, customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "en_attente" and lien.motif == "cartes_indisponibles"
    assert stripe_.soldes == []


async def test_remboursement_du_pass_du_filleul_reprend_le_credit(db, monkeypatch):
    stripe_ = _Stripe(monkeypatch)
    _cartes(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session_remise(filleul, sid="cs_rb", customer=filleul.stripe_customer_id))
    await sr._traiter_evenement("charge.refunded", {
        "id": "ch_rb", "object": "charge", "refunded": True, "payment_intent": "pi_cs_rb",
        "customer": filleul.stripe_customer_id, "invoice": None}, db)
    await db.commit()
    lien = await _lien(db, filleul)
    assert lien.statut == "annule"
    assert [s["amount"] for s in stripe_.soldes if s["customer"] == "cus_parrain"] == [-500, 500]
    pas = (await db.execute(select(PassAcces).where(PassAcces.user_id == filleul.user_id))).scalar_one()
    assert pas.statut == "rembourse"


async def test_carte_d_un_acheteur_de_pass_ordinaire_est_memorisee(db, monkeypatch):
    _Stripe(monkeypatch)
    _cartes(monkeypatch, "fp_acheteur")
    user = await _user(db, stripe_customer_id="cus_ach")
    await PS.accorder(db, _session(user, sid="cs_m", customer="cus_ach"))
    carte = await db.get(CarteConnue, "fp_acheteur")
    assert carte is not None and carte.user_id == user.user_id


async def test_une_erreur_de_parrainage_ne_retire_jamais_le_pass(db, monkeypatch):
    _Stripe(monkeypatch)
    _cartes(monkeypatch)

    async def _boum(*a, **k):
        raise RuntimeError("panne")

    monkeypatch.setattr(P, "_sur_paiement_pass", _boum)
    _parrain, filleul, _l = await _couple(db)
    p, cree = await PS.accorder(db, _session_remise(filleul, customer=filleul.stripe_customer_id))
    assert cree
    await db.refresh(filleul)
    assert filleul.plan == "expert"
