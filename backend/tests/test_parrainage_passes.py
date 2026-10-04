"""Parrainage × passes sans abonnement, et failles relevées par l'audit du 2026-10-04.

Règles :
- le parrainage vaut pour les Pass Semaine et Mois, JAMAIS pour le Pass Jour
  (5 € − 5 € = gratuit, deux comptes se renverraient la balle en boucle) ;
- la remise du filleul n'est jamais accordée avant paiement : il paie le plein
  tarif, puis 5 € lui sont REMBOURSÉS une fois sa carte vérifiée. Accordée
  d'avance, une carte déjà connue n'était repérée qu'après coup, et la reprise
  ne se prélevait jamais chez qui n'achète que des passes.
Chaque scénario de contournement a son test.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import api.routes.stripe_routes as sr
from db.models import CarteConnue, PassAcces, Parrainage, User
from services import parrainage as P
from services import passes as PS
from tests.test_parrainage import _Stripe, _couple, _user
from tests.test_passes import _antidater, _capture_pass, _session

pytestmark = pytest.mark.asyncio


def _paiement(monkeypatch, empreinte="fp_filleul", rembourse=False, conteste=False):
    """Infos du paiement lues chez Stripe (carte qui a payé, remboursé ?, contesté ?)."""
    cartes = [] if empreinte is None else [
        {"empreinte": empreinte, "pm": "pm_x", "marque": "visa", "dernier4": "4242", "financement": "debit"}]
    monkeypatch.setattr(P, "infos_paiement", lambda pi: {
        "cartes": cartes, "rembourse": rembourse, "conteste": conteste, "charge": "ch_x"})


async def _lien(db, filleul):
    return (await db.execute(select(Parrainage).where(Parrainage.filleul_id == filleul.user_id)
                             .execution_options(populate_existing=True))).scalar_one()


def _remb(spy, pi):
    return [r for r in spy.remboursements if r.get("payment_intent") == pi]


# ── Création du paiement : toujours plein tarif, aucun coupon ────────────────
@pytest.mark.parametrize("duree", ["jour", "semaine", "mois"])
async def test_aucun_coupon_avant_paiement_meme_pour_un_filleul(db, monkeypatch, duree):
    captured = _capture_pass(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    r = await sr.creer_checkout_pass(sr.PassRequest(duree=duree), db, filleul)
    assert "discounts" not in captured and "remise_parrainage" not in captured["metadata"]
    # Le site annonce le remboursement à venir, sauf sur le Pass Jour.
    assert r["remise_parrainage"] is (duree != "jour")


async def test_session_remisee_refusee(db):
    """Une session payée moins que le tarif (coupon glissé hors serveur) : refusée."""
    user = await _user(db, stripe_customer_id="cus_v")
    s = _session(user, duree="semaine")
    s["amount_total"] = 700
    s["total_details"] = {"amount_discount": 500}
    s["metadata"]["remise_parrainage"] = "1"
    with pytest.raises(PS.PassInvalide):
        PS.valider_session(s)


# ── Octroi + remboursement de la remise + crédit du parrain ──────────────────
async def test_pass_semaine_filleul_rembourse_5_et_credite_le_parrain(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    p, _ = await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_s1", customer=filleul.stripe_customer_id))
    assert p.montant_cents == 1200  # plein tarif encaissé
    remb = _remb(spy, "pi_cs_s1")
    assert len(remb) == 1 and remb[0]["amount"] == 500
    assert remb[0]["metadata"]["type"] == P.METADATA_REMBOURSEMENT_REMISE
    lien = await _lien(db, filleul)
    assert lien.statut == "valide" and lien.remise_filleul_at is not None
    assert lien.stripe_invoice_id == "pi_cs_s1"  # retrouvable sans limite de délai
    assert [s["amount"] for s in spy.soldes if s["customer"] == "cus_parrain"] == [-500]
    # Second pass : ni second remboursement, ni second crédit.
    await PS.accorder(db, _session(filleul, duree="mois", sid="cs_s2", customer=filleul.stripe_customer_id))
    assert len(spy.remboursements) == 1
    assert len([s for s in spy.soldes if s["customer"] == "cus_parrain"]) == 1


async def test_pass_jour_filleul_rien_et_remise_gardee(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="jour", sid="cs_j", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "en_attente" and lien.remise_filleul_at is None
    assert spy.remboursements == [] and spy.soldes == []
    await db.refresh(filleul)
    assert await P.remise_filleul_due(filleul, db) is not None


@pytest.mark.parametrize("proprietaire,motif", [("parrain", "carte_du_parrain"),
                                                ("autre", "carte_autre_compte"),
                                                ("supprime", "carte_compte_supprime")])
async def test_carte_deja_connue_ni_remboursement_ni_credit(db, monkeypatch, proprietaire, motif):
    """Même carte que le parrain, qu'un autre compte, ou qu'un compte SUPPRIMÉ :
    plein tarif payé, rien remboursé, parrain non crédité — et rien à rattraper."""
    spy = _Stripe(monkeypatch)
    parrain, filleul, _l = await _couple(db)
    autre = await _user(db, stripe_customer_id="cus_autre")
    owner = {"parrain": parrain.user_id, "autre": autre.user_id, "supprime": None}[proprietaire]
    db.add(CarteConnue(empreinte="fp_vue", user_id=owner, email="x@x.fr"))
    await db.commit()
    _paiement(monkeypatch, "fp_vue")
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_c", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "refuse" and lien.motif == motif
    assert spy.remboursements == [] and spy.soldes == []
    await db.refresh(filleul)
    assert filleul.plan == "expert"  # le pass, payé plein tarif, reste acquis
    # La carte n'est pas réattribuée au filleul.
    carte = await db.get(CarteConnue, "fp_vue")
    assert carte.user_id == owner


async def test_alias_gmail_meme_carte_remise_une_seule_fois(db, monkeypatch):
    """La faille de l'audit : comptes `nom+1@`, `nom+2@`… avec la même carte. Le
    premier récupère 5 € ; les suivants paient plein tarif, rien n'est remboursé."""
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch, "fp_unique")
    parrain = await _user(db, prenom="P", stripe_customer_id="cus_parrain")
    code = await P.code_de(parrain, db)
    for i in range(3):
        f = await _user(db, email=f"nom+{i}@gmail.com", stripe_customer_id=f"cus_f{i}")
        await P.rattacher_filleul(f, code, db)
        await db.commit()
        await PS.accorder(db, _session(f, duree="semaine", sid=f"cs_a{i}", customer=f"cus_f{i}"))
    assert len(spy.remboursements) == 1
    assert len([s for s in spy.soldes if s["customer"] == "cus_parrain"]) == 1


async def test_carte_illisible_rien_n_est_tranche(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch, None)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_i", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "en_attente" and lien.motif == "cartes_indisponibles"
    assert spy.remboursements == [] and spy.soldes == [] and lien.remise_filleul_at is None


async def test_remboursement_de_remise_ne_reprend_ni_pass_ni_credit(db, monkeypatch):
    """Le remboursement de 5 € de la remise déclenche `charge.refunded` (partiel) :
    ni le pass du filleul ni le crédit du parrain ne doivent être repris."""
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_rr", customer=filleul.stripe_customer_id))
    monkeypatch.setattr(P.stripe.Refund, "list", lambda **kw: type("L", (), {
        "auto_paging_iter": lambda self: iter([{"metadata": {"type": P.METADATA_REMBOURSEMENT_REMISE},
                                               "status": "succeeded"}])})())
    await sr._traiter_evenement("charge.refunded", {
        "id": "ch_rr", "object": "charge", "refunded": False, "amount_refunded": 500,
        "payment_intent": "pi_cs_rr", "customer": filleul.stripe_customer_id}, db)
    await db.commit()
    assert (await _lien(db, filleul)).statut == "valide"
    pas = (await db.execute(select(PassAcces).where(PassAcces.user_id == filleul.user_id))).scalar_one()
    assert pas.statut == "actif"
    assert [s["amount"] for s in spy.soldes if s["customer"] == "cus_parrain"] == [-500]


async def test_remboursement_total_du_pass_reprend_le_credit(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_rb", customer=filleul.stripe_customer_id))
    await sr._traiter_evenement("charge.refunded", {
        "id": "ch_rb", "object": "charge", "refunded": True, "amount_refunded": 1200,
        "payment_intent": "pi_cs_rb", "customer": filleul.stripe_customer_id, "invoice": None}, db)
    await db.commit()
    assert (await _lien(db, filleul)).statut == "annule"
    assert [s["amount"] for s in spy.soldes if s["customer"] == "cus_parrain"] == [-500, 500]


async def test_contestation_tardive_retrouve_le_parrainage_par_le_paiement(db, monkeypatch):
    """Contestation à J+100 (délai bancaire jusqu'à 120 jours) : retrouvé par le
    paiement mémorisé, au-delà de la fenêtre de 60 jours du repli par client."""
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_ct", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    lien.valide_at = datetime.now(timezone.utc) - timedelta(days=100)
    await db.commit()
    await P.sur_remboursement({"id": "ch_ct", "object": "charge", "payment_intent": "pi_cs_ct",
                               "customer": "cus_inconnu"}, db, "paiement_conteste")
    await db.commit()
    assert (await _lien(db, filleul)).statut == "annule"
    assert [s["amount"] for s in spy.soldes if s["customer"] == "cus_parrain"] == [-500, 500]


# ── Octroi : robustesse ──────────────────────────────────────────────────────
@pytest.mark.parametrize("rembourse,conteste", [(True, False), (False, True)])
async def test_webhook_rejoue_apres_remboursement_n_accorde_rien(db, monkeypatch, rembourse, conteste):
    _paiement(monkeypatch, rembourse=rembourse, conteste=conteste)
    user = await _user(db, stripe_customer_id="cus_rj")
    with pytest.raises(PS.PassInvalide):
        await PS.accorder(db, _session(user, sid="cs_rj", customer="cus_rj"))
    assert (await db.execute(select(PassAcces))).first() is None


async def test_carte_d_un_acheteur_ordinaire_memorisee(db, monkeypatch):
    _Stripe(monkeypatch)
    _paiement(monkeypatch, "fp_acheteur")
    user = await _user(db, stripe_customer_id="cus_ach")
    await PS.accorder(db, _session(user, sid="cs_m", customer="cus_ach"))
    carte = await db.get(CarteConnue, "fp_acheteur")
    assert carte is not None and carte.user_id == user.user_id


async def test_une_erreur_de_parrainage_ne_retire_jamais_le_pass(db, monkeypatch):
    _Stripe(monkeypatch)
    _paiement(monkeypatch)

    async def _boum(*a, **k):
        raise RuntimeError("panne")

    monkeypatch.setattr(P, "_sur_paiement_pass", _boum)
    _parrain, filleul, _l = await _couple(db)
    _p, cree = await PS.accorder(db, _session(filleul, duree="semaine", customer=filleul.stripe_customer_id))
    assert cree
    await db.refresh(filleul)
    assert filleul.plan == "expert"


async def test_remboursement_stripe_en_echec_rien_n_est_valide(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _paiement(monkeypatch)

    def _panne(**kw):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(P.stripe.Refund, "create", _panne)
    _parrain, filleul, _l = await _couple(db)
    await PS.accorder(db, _session(filleul, duree="semaine", sid="cs_pe", customer=filleul.stripe_customer_id))
    lien = await _lien(db, filleul)
    assert lien.statut == "en_attente" and lien.motif == "remise_en_echec"
    assert lien.remise_filleul_at is None and spy.soldes == []


# ── Pass enchaînés après un remboursement ────────────────────────────────────
async def test_pass_enchaine_apres_un_pass_rembourse_est_recale(db, monkeypatch):
    """Audit : Pass Mois remboursé alors qu'un Pass Semaine attendait derrière — le
    Semaine payé démarrait à J30 sans accès. Il est désormais recalé à maintenant."""
    _paiement(monkeypatch, "fp_r")
    user = await _user(db, stripe_customer_id="cus_rc")
    mois, _ = await PS.accorder(db, _session(user, duree="mois", sid="cs_m1", customer="cus_rc"))
    sem, _ = await PS.accorder(db, _session(user, duree="semaine", sid="cs_s1", customer="cus_rc"))
    await PS.retirer_par_paiement(db, "pi_cs_m1", "paiement_rembourse")
    await db.refresh(sem)
    await db.refresh(user)
    debut = sem.debut if sem.debut.tzinfo else sem.debut.replace(tzinfo=timezone.utc)
    fin = sem.fin if sem.fin.tzinfo else sem.fin.replace(tzinfo=timezone.utc)
    assert abs((debut - datetime.now(timezone.utc)).total_seconds()) < 5
    assert fin - debut == timedelta(days=7)  # durée payée intacte
    assert user.plan == "expert"


async def test_filet_de_securite_retablit_un_pass_commence_non_reflete(db, monkeypatch):
    _paiement(monkeypatch, "fp_f")
    user = await _user(db, stripe_customer_id="cus_fs")
    await PS.accorder(db, _session(user, sid="cs_fs", customer="cus_fs"))
    user.plan = "free"  # plan écrasé par un autre chemin
    await db.commit()
    assert await PS.activer_passes_commences(db) == 1
    await db.refresh(user)
    assert user.plan == "expert"
    assert await PS.activer_passes_commences(db) == 0


async def test_requete_ouvre_l_acces_d_un_pass_qui_commence(client, db, inscrire, monkeypatch):
    _paiement(monkeypatch, "fp_q")
    headers = await inscrire(email="enchaine@blackturf.fr")
    user = (await db.execute(select(User).where(User.email == "enchaine@blackturf.fr"))).scalar_one()
    p, _ = await PS.accorder(db, _session(user, sid="cs_q"))
    # Le pass « commence plus tard », le compte est retombé gratuit…
    p.debut = datetime.now(timezone.utc) + timedelta(hours=1)
    p.fin = p.debut + timedelta(hours=24)
    user.plan = "free"
    await db.commit()
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["plan"] == "free"
    # …puis l'heure arrive : accès ouvert dès la requête suivante.
    p.debut = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["plan"] == "expert"


# ── Inscription : une boîte mail = un compte ─────────────────────────────────
@pytest.mark.parametrize("alias", ["nom+2@gmail.com", "n.o.m@gmail.com", "NOM@googlemail.com"])
async def test_alias_d_une_boite_gmail_deja_inscrite_refuse(client, inscrire, alias):
    await inscrire(email="nom@gmail.com", pseudo="original")
    r = await client.post("/api/v1/auth/register", json={
        "email": alias, "password": "TestPassword123!", "pseudo": "alias01"})
    assert r.status_code == 400


async def test_boite_differente_acceptee(client, inscrire):
    await inscrire(email="nom@gmail.com", pseudo="original")
    r = await client.post("/api/v1/auth/register", json={
        "email": "autre.nom@gmail.com", "password": "TestPassword123!", "pseudo": "autre01"})
    assert r.status_code == 200


# ── Admin : suppression d'un compte avec pass en cours ───────────────────────
async def test_suppression_admin_bloquee_si_pass_en_cours(client, admin_headers, db, monkeypatch):
    _paiement(monkeypatch, "fp_adm")
    user = await _user(db, stripe_customer_id="cus_adm")
    await PS.accorder(db, _session(user, sid="cs_adm", customer="cus_adm"))
    r = await client.delete(f"/admin/api/users/{user.user_id}", headers=admin_headers)
    assert r.status_code == 409 and "forcer_pass" in r.json()["detail"]
    r = await client.delete(f"/admin/api/users/{user.user_id}?forcer_pass=true", headers=admin_headers)
    assert r.status_code == 200


async def test_suppression_admin_libre_si_pass_echu(client, admin_headers, db, monkeypatch):
    _paiement(monkeypatch, "fp_adm2")
    user = await _user(db, stripe_customer_id="cus_adm2")
    p, _ = await PS.accorder(db, _session(user, sid="cs_adm2", customer="cus_adm2"))
    await _antidater(db, p)
    r = await client.delete(f"/admin/api/users/{user.user_id}", headers=admin_headers)
    assert r.status_code == 200


# ── Abonnement : même principe de remboursement ──────────────────────────────
async def test_abonnement_filleul_5_euros_rembourses_au_premier_paiement(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await P.sur_paiement(filleul, {"id": "in_ab", "amount_paid": 1900, "customer": "cus_filleul",
                                   "charge": "ch_ab"}, db)
    assert [(r.get("charge"), r["amount"]) for r in spy.remboursements] == [("ch_ab", 500)]
    assert (await _lien(db, filleul)).statut == "valide"


async def test_abonnement_avec_ancien_coupon_pas_de_double_remise(db, monkeypatch):
    """Souscription lancée AVANT le passage au remboursement : la facture porte
    encore le coupon de 5 € — aucun remboursement en plus."""
    spy = _Stripe(monkeypatch)
    _parrain, filleul, _l = await _couple(db)
    await P.sur_paiement(filleul, {"id": "in_old", "amount_paid": 1400, "customer": "cus_filleul",
                                   "charge": "ch_old", "total_discount_amounts": [{"amount": 500}]}, db)
    assert spy.remboursements == []
    lien = await _lien(db, filleul)
    assert lien.statut == "valide" and lien.remise_filleul_at is not None


async def test_client_stripe_cree_avec_cle_d_idempotence(db, monkeypatch):
    """Double clic : la même clé renvoie le même client chez Stripe (pas d'orphelin)."""
    vus = []
    monkeypatch.setattr(sr.stripe.Customer, "create", lambda **kw: vus.append(kw) or type("C", (), {"id": "cus_n"})())
    _capture_pass(monkeypatch)
    user = await _user(db)
    await sr.creer_checkout_pass(sr.PassRequest(duree="jour"), db, user)
    assert vus and vus[0]["idempotency_key"] == f"client-{user.user_id}"
