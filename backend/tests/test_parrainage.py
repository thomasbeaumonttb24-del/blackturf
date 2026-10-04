"""Parrainage — 5 € de remise au filleul, 5 € de crédit au parrain.

Règles de l'exploitant (2026-09-27) : pas d'essai pour un filleul, remise sur sa
première facture payante ; le parrain n'est crédité qu'une fois ce paiement
RÉELLEMENT encaissé, jamais avant, et le crédit est une réduction sur son
abonnement (solde client Stripe), jamais un versement.
"""
import uuid

import pytest
from fastapi import HTTPException

import api.routes.stripe_routes as sr
from api.routes.auth import me
from db.models import CarteConnue, Parrainage, SubscriptionEvent, User
from services import parrainage as P
from sqlalchemy import select


async def _user(db, **kw) -> User:
    user = User(user_id=str(uuid.uuid4()),
                email=kw.pop("email", f"{uuid.uuid4().hex[:8]}@blackturf.fr"),
                plan="free", email_verified=kw.pop("email_verified", True), **kw)
    db.add(user)
    await db.commit()
    return user


async def _couple(db):
    parrain = await _user(db, prenom="Paul", stripe_customer_id="cus_parrain")
    code = await P.code_de(parrain, db)
    filleul = await _user(db, prenom="Fanny", stripe_customer_id="cus_filleul")
    lien = await P.rattacher_filleul(filleul, code, db)
    await db.commit()
    return parrain, filleul, lien


class _Stripe:
    """Espion des appels Stripe du parrainage."""

    def __init__(self, monkeypatch, cartes=("fp_filleul",)):
        self.soldes: list[dict] = []
        self.clients: list[dict] = []
        monkeypatch.setattr(P.settings, "stripe_secret_key", "sk_test")

        def _balance(customer, **kw):
            self.soldes.append({"customer": customer, **kw})
            return {"id": f"cbtxn_{len(self.soldes)}"}

        def _client(**kw):
            self.clients.append(kw)
            return {"id": "cus_nouveau"}

        class _Liste:
            def __init__(self, items):
                self.items = items

            def auto_paging_iter(self):
                return iter(self.items)

        def _lister(customer, **kw):
            return _Liste([{"id": f"cbtxn_{i + 1}", "metadata": s.get("metadata")}
                           for i, s in enumerate(self.soldes) if s["customer"] == customer])

        monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", _balance)
        monkeypatch.setattr(P.stripe.Customer, "list_balance_transactions", _lister)
        monkeypatch.setattr(P.stripe.Customer, "create", _client)

        # Remise du filleul = remboursement de 5 € sur SON paiement (2026-10-04).
        self.remboursements: list[dict] = []

        def _rembourser(**kw):
            self.remboursements.append(kw)
            return {"id": f"re_{len(self.remboursements)}", "metadata": kw.get("metadata")}

        def _lister_remb(**kw):
            return _Liste([{"id": f"re_{i + 1}", "metadata": r.get("metadata"), "status": "succeeded"}
                           for i, r in enumerate(self.remboursements)
                           if (r.get("charge") or r.get("payment_intent")) in (kw.get("charge"), kw.get("payment_intent"))])

        def _charges(customer=None, **kw):
            return _Liste([{"id": f"ch_{customer}", "status": "succeeded", "paid": True, "amount": 700,
                            "refunded": False, "created": 0}])

        monkeypatch.setattr(P.stripe.Refund, "create", _rembourser)
        monkeypatch.setattr(P.stripe.Refund, "list", _lister_remb)
        monkeypatch.setattr(P.stripe.Charge, "list", _charges)
        monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [
            {"empreinte": e, "pm": "pm_x", "marque": "visa", "dernier4": "4242",
             "financement": "debit"} for e in cartes])


def _facture(montant=700, fid="in_1"):
    return {"id": fid, "amount_paid": montant, "customer": "cus_filleul", "charge": f"ch_{fid}"}


# ─── Rattachement ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_code_stable_et_lisible(db):
    user = await _user(db)
    code = await P.code_de(user, db)
    assert len(code) == 8 and set(code) <= set(P.ALPHABET)
    assert await P.code_de(user, db) == code


@pytest.mark.asyncio
async def test_rattachement_et_remise_due(db):
    parrain, filleul, lien = await _couple(db)
    assert filleul.parraine_par_id == parrain.user_id
    assert lien.statut == "en_attente"
    assert await P.remise_filleul_due(filleul, db) is not None


@pytest.mark.asyncio
async def test_code_saisi_en_minuscules_avec_espaces(db):
    parrain = await _user(db)
    code = await P.code_de(parrain, db)
    assert (await P.parrain_du_code(f" {code.lower()[:4]} {code.lower()[4:]} ", db)).user_id == parrain.user_id


@pytest.mark.asyncio
async def test_code_inconnu_refuse(db):
    filleul = await _user(db)
    with pytest.raises(P.CodeInvalide):
        await P.rattacher_filleul(filleul, "ZZZZZZZZ", db)


@pytest.mark.asyncio
async def test_parrain_non_confirme_ne_parraine_pas(db):
    from datetime import datetime, timezone
    parrain = await _user(db, email_verified=False, created_at=datetime.now(timezone.utc))
    parrain.code_parrain = "BCDFGHJK"
    await db.commit()
    filleul = await _user(db)
    with pytest.raises(P.CodeInvalide):
        await P.rattacher_filleul(filleul, "BCDFGHJK", db)


@pytest.mark.asyncio
async def test_pas_dauto_parrainage(db):
    user = await _user(db)
    code = await P.code_de(user, db)
    with pytest.raises(P.CodeInvalide):
        await P.rattacher_filleul(user, code, db)


@pytest.mark.asyncio
async def test_un_seul_parrain(db):
    parrain, filleul, _ = await _couple(db)
    autre = await _user(db)
    assert await P.rattacher_filleul(filleul, await P.code_de(autre, db), db) is None
    assert filleul.parraine_par_id == parrain.user_id


# ─── Checkout du filleul ─────────────────────────────────────────────────────
def _capture(monkeypatch) -> dict:
    captured: dict = {}

    def _fake(**kw):
        captured.update(kw)
        return type("S", (), {"url": "https://checkout.stripe.test/x"})()

    monkeypatch.setattr(sr.stripe.checkout.Session, "create", _fake)
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_std",
                                          "expert_annual": "price_exp_an"})
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [])
    monkeypatch.setattr(P, "coupon_filleul", lambda: P.COUPON_FILLEUL_ID)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("plan,periodicite", [("standard", "monthly"), ("expert", "annual")])
async def test_filleul_sans_essai_avec_remise(db, monkeypatch, plan, periodicite):
    captured = _capture(monkeypatch)
    _, filleul, _ = await _couple(db)

    res = await sr.create_checkout(sr.CheckoutRequest(plan=plan, periodicite=periodicite), db, filleul)

    assert res["essai"] is False and res["remise_parrainage"] is True
    assert "trial_period_days" not in captured["subscription_data"]
    # 2026-10-04 : plus de coupon avant paiement — 5 € remboursés après
    # vérification de la carte. Pas de code promo cumulable pour un filleul.
    assert "discounts" not in captured
    assert captured["allow_promotion_codes"] is False


@pytest.mark.asyncio
async def test_client_ordinaire_garde_les_codes_promo_sans_essai(db, monkeypatch):
    """Essai supprimé le 2026-10-04 : plus d'essai pour personne, codes promo gardés."""
    captured = _capture(monkeypatch)
    user = await _user(db, stripe_customer_id="cus_x")
    res = await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)
    assert res["essai"] is False and res["remise_parrainage"] is False
    assert "trial_period_days" not in captured["subscription_data"]
    assert captured["allow_promotion_codes"] is True
    assert "discounts" not in captured


@pytest.mark.asyncio
async def test_carte_connue_ailleurs_pas_de_remise(db, monkeypatch):
    captured = _capture(monkeypatch)
    _, filleul, _ = await _couple(db)
    ancien = await _user(db)
    db.add(CarteConnue(empreinte="fp_ancien", user_id=ancien.user_id, email=ancien.email))
    await db.commit()
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [{"empreinte": "fp_ancien"}])

    res = await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, filleul)
    # Aucune remise accordée d'avance : la carte est jugée APRÈS paiement, et une
    # carte connue ailleurs n'obtient alors aucun remboursement.
    assert res["essai"] is False
    assert "discounts" not in captured


@pytest.mark.asyncio
async def test_le_checkout_filleul_ne_depend_plus_d_aucun_coupon(db, monkeypatch):
    captured = _capture(monkeypatch)

    def _panne():
        raise RuntimeError("stripe down")

    monkeypatch.setattr(P, "coupon_filleul", _panne)
    _, filleul, _ = await _couple(db)
    res = await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, filleul)
    assert res["url"] and "discounts" not in captured


@pytest.mark.asyncio
async def test_me_filleul(db):
    _, filleul, _ = await _couple(db)
    res = await me(filleul, db)
    assert res.remise_parrainage is True
    assert res.essai_disponible is False


# ─── Récompense du parrain ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sans_paiement_pas_de_credit(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    await P.sur_paiement(filleul, _facture(montant=0), db)
    assert spy.soldes == []
    assert lien.statut == "en_attente" and lien.remise_filleul_at is None


@pytest.mark.asyncio
async def test_premier_paiement_credite_le_parrain_une_seule_fois(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    parrain, filleul, lien = await _couple(db)

    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()
    await P.sur_paiement(filleul, _facture(fid="in_2"), db)

    assert len(spy.soldes) == 1
    credit = spy.soldes[0]
    assert credit["customer"] == "cus_parrain"
    assert credit["amount"] == -500 and credit["currency"] == "eur"
    assert credit["idempotency_key"] == f"parrainage-credit-{lien.parrainage_id}"
    assert lien.statut == "valide" and lien.stripe_invoice_id == "in_1"
    assert lien.remise_filleul_at is not None
    assert await P.remise_filleul_due(filleul, db) is None
    types = (await db.execute(select(SubscriptionEvent.type))).scalars().all()
    assert types.count("parrainage_valide") == 1


@pytest.mark.asyncio
async def test_parrain_sans_client_stripe_credite_quand_meme(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    parrain = await _user(db)
    filleul = await _user(db, stripe_customer_id="cus_filleul")
    await P.rattacher_filleul(filleul, await P.code_de(parrain, db), db)
    await db.commit()

    await P.sur_paiement(filleul, _facture(), db)

    assert parrain.stripe_customer_id == "cus_nouveau"
    assert spy.soldes[0]["customer"] == "cus_nouveau"


@pytest.mark.asyncio
async def test_carte_du_parrain_refusee(db, monkeypatch):
    spy = _Stripe(monkeypatch, cartes=("fp_parrain",))
    parrain, filleul, lien = await _couple(db)
    db.add(CarteConnue(empreinte="fp_parrain", user_id=parrain.user_id, email=parrain.email))
    await db.commit()

    await P.sur_paiement(filleul, _facture(), db)

    # Auto-parrainage : aucun crédit au parrain, AUCUN remboursement au filleul
    # (rien n'avait été accordé d'avance, donc rien à rattraper).
    assert spy.soldes == [] and spy.remboursements == []
    assert lien.statut == "refuse" and lien.motif == "carte_du_parrain"


@pytest.mark.asyncio
async def test_cartes_illisibles_la_recompense_attend(db, monkeypatch):
    spy = _Stripe(monkeypatch, cartes=())
    _, filleul, lien = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    assert spy.soldes == [] and lien.statut == "en_attente"
    # Rien n'est tranché : ni remboursement, ni remise consommée (elle sera
    # remboursée au paiement suivant si la carte est la sienne).
    assert spy.remboursements == [] and lien.remise_filleul_at is None


@pytest.mark.asyncio
async def test_credit_en_echec_repose_plus_tard(db, monkeypatch):
    """Stripe injoignable au moment du paiement du filleul : les 5 € restent
    GAGNÉS (le filleul a payé) et sont posés au passage suivant."""
    spy = _Stripe(monkeypatch)
    parrain, filleul, lien = await _couple(db)
    ok = P.stripe.Customer.create_balance_transaction

    def _panne(*a, **kw):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", _panne)
    await P.sur_paiement(filleul, _facture(), db)
    assert lien.statut == "valide" and lien.credit_pose_at is None
    assert lien.motif == "credit_en_echec"
    assert P._etape(lien, filleul, True) == "verification"

    monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", ok)
    assert await P.liberer_credits(parrain, db) == 1
    assert lien.credit_pose_at is not None and len(spy.soldes) == 1
    assert await P.liberer_credits(parrain, db) == 0


@pytest.mark.asyncio
async def test_webhook_paiement_valide_le_parrainage(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    # Facture arrivée avant l'abonnement : le parrainage est tout de même traité.
    await sr._handle_payment_succeeded(
        {"id": "in_1", "amount_paid": 700, "customer": "cus_filleul", "subscription": "sub_x"}, db)
    await db.refresh(lien)
    assert lien.statut == "valide" and len(spy.soldes) == 1


# ─── Remboursement / contestation ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_remboursement_reprend_le_credit(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()

    await P.sur_remboursement({"id": "ch_1", "invoice": "in_1", "customer": "cus_filleul"},
                              db, "paiement_rembourse")
    await P.sur_remboursement({"id": "ch_1", "invoice": "in_1", "customer": "cus_filleul"},
                              db, "paiement_rembourse")

    reprises = [s for s in spy.soldes if s["amount"] > 0]
    assert len(reprises) == 1 and reprises[0]["amount"] == 500
    assert lien.statut == "annule"


@pytest.mark.asyncio
async def test_contestation_reprend_le_credit(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()
    monkeypatch.setattr(P.stripe.Charge, "retrieve",
                        lambda cid: {"id": cid, "invoice": None, "customer": "cus_filleul"})

    await P.sur_remboursement({"object": "dispute", "charge": "ch_1"}, db, "paiement_conteste")
    assert lien.statut == "annule" and spy.soldes[-1]["amount"] == 500


@pytest.mark.asyncio
async def test_remboursement_sans_parrainage_ignore(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    await P.sur_remboursement({"id": "ch_9", "invoice": "in_9", "customer": "cus_inconnu"}, db, "x")
    assert spy.soldes == []


# ─── Résumé ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resume_parrain(db, monkeypatch):
    _Stripe(monkeypatch)
    monkeypatch.setattr(P.stripe.Customer, "retrieve", lambda cid: {"balance": -1000})
    parrain, filleul, _ = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()

    res = await P.resume(parrain, db)
    assert res["lien"].endswith(f"/inscription?parrain={res['code']}")
    assert res["valides"] == 1 and res["gagne_cents"] == 500
    assert res["credit_disponible_cents"] == 1000
    assert res["filleuls"][0]["prenom"] == "Fanny"
    assert "email" not in res["filleuls"][0]
    assert (await db.execute(select(Parrainage))).scalars().one().statut == "valide"


# ─── Inscription par lien ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_inscription_avec_code(client, db):
    parrain = await _user(db)
    code = await P.code_de(parrain, db)
    resp = await client.post("/api/v1/auth/register", json={
        "email": "filleul@blackturf.fr", "password": "motdepasse123",
        "prenom": "Fanny", "pseudo": "Fanny1", "code_parrain": code.lower(),
    })
    assert resp.status_code == 200, resp.text
    filleul = (await db.execute(select(User).where(User.email == "filleul@blackturf.fr"))).scalar_one()
    assert filleul.parraine_par_id == parrain.user_id

    publique = (await client.get(f"/api/v1/parrainage/code/{code}")).json()
    assert publique["valide"] is True and "email" not in publique


@pytest.mark.asyncio
async def test_inscription_code_invalide_refusee_sans_creer_le_compte(client, db):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "filleul@blackturf.fr", "password": "motdepasse123",
        "prenom": "Fanny", "pseudo": "Fanny2", "code_parrain": "ZZZZZZZZ",
    })
    assert resp.status_code == 422
    assert (await db.execute(select(User).where(User.email == "filleul@blackturf.fr"))).first() is None
    assert (await client.get("/api/v1/parrainage/code/ZZZZZZZZ")).json() == {"valide": False}


# ─── Tentatives de contournement ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_filleul_ne_cumule_jamais_remise_et_essai(db, monkeypatch):
    """Payer avec la remise, résilier, se réabonner : pas d'essai derrière."""
    captured = _capture(monkeypatch)
    _Stripe(monkeypatch)
    _, filleul, _ = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()

    res = await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, filleul)
    assert res["essai"] is False and res["remise_parrainage"] is False
    assert "trial_period_days" not in captured["subscription_data"]
    assert "discounts" not in captured
    assert (await me(filleul, db)).essai_disponible is False


@pytest.mark.asyncio
async def test_carte_deja_connue_remise_refacturee_au_filleul(db, monkeypatch):
    """Ancien client qui rouvre un compte pour la remise : parrain non crédité,
    et aucun remboursement — il a payé plein tarif, rien à rattraper."""
    spy = _Stripe(monkeypatch, cartes=("fp_ancien",))
    _, filleul, lien = await _couple(db)
    ancien = await _user(db)
    db.add(CarteConnue(empreinte="fp_ancien", user_id=ancien.user_id, email=ancien.email))
    await db.commit()

    await P.sur_paiement(filleul, _facture(), db)

    assert lien.statut == "refuse" and lien.motif == "carte_autre_compte"
    assert spy.soldes == [] and spy.remboursements == []


@pytest.mark.asyncio
async def test_credit_deja_pose_chez_stripe_jamais_double(db, monkeypatch):
    """Crédit parti chez Stripe mais jamais enregistré ici (coupure) : le retry
    d'un mois plus tard, clé d'idempotence expirée, ne recrédite pas."""
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    cle = f"parrainage-credit-{lien.parrainage_id}"
    spy.soldes.append({"customer": "cus_parrain", "amount": -500, "metadata": {"cle": cle}})

    await P.sur_paiement(filleul, _facture(), db)

    assert len(spy.soldes) == 1
    assert lien.statut == "valide" and lien.stripe_credit_txn_id == "cbtxn_1"


@pytest.mark.asyncio
async def test_remboursement_dune_mensualite_ulterieure_ne_reprend_rien(db, monkeypatch):
    import time
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    await P.sur_paiement(filleul, _facture(), db)
    await db.commit()

    # Paiement d'un mois plus tard, sans facture portée (API récente).
    await P.sur_remboursement({"id": "ch_2", "customer": "cus_filleul",
                               "created": int(time.time()) + 30 * 86400}, db, "paiement_rembourse")
    assert lien.statut == "valide" and all(s["amount"] < 0 for s in spy.soldes)

    # Le premier paiement, lui, reprend bien le crédit.
    await P.sur_remboursement({"id": "ch_1", "customer": "cus_filleul",
                               "created": int(time.time())}, db, "paiement_rembourse")
    assert lien.statut == "annule"


@pytest.mark.asyncio
async def test_webhook_rejoue_ne_credite_quune_fois(db, monkeypatch):
    spy = _Stripe(monkeypatch)
    _, filleul, lien = await _couple(db)
    facture = {"id": "in_1", "amount_paid": 700, "customer": "cus_filleul", "subscription": "sub_x"}
    await sr._handle_payment_succeeded(facture, db)
    await sr._handle_payment_succeeded(facture, db)
    assert len(spy.soldes) == 1


@pytest.mark.asyncio
async def test_suivi_etape_par_etape(db, monkeypatch):
    from datetime import datetime, timezone
    _Stripe(monkeypatch)
    monkeypatch.setattr(P.stripe.Customer, "retrieve", lambda cid: {"balance": 0})
    parrain = await _user(db, stripe_customer_id="cus_parrain")
    code = await P.code_de(parrain, db)
    non_confirme = await _user(db, prenom="Nina", email_verified=False, created_at=datetime.now(timezone.utc))
    attente = await _user(db, prenom="Alex")
    paye = await _user(db, prenom="Fanny", stripe_customer_id="cus_filleul")
    for u in (non_confirme, attente, paye):
        await P.rattacher_filleul(u, code, db)
    await db.commit()
    await P.sur_paiement(paye, _facture(), db)
    await db.commit()

    etapes = {f["prenom"]: f["etape"] for f in (await P.resume(parrain, db))["filleuls"]}
    assert etapes == {"Nina": "email_a_confirmer", "Alex": "attente_paiement", "Fanny": "credite"}


@pytest.mark.asyncio
async def test_suppression_de_compte_detache_les_parrainages(db):
    from sqlalchemy import update
    parrain, filleul, lien = await _couple(db)
    # Même opération que la suppression admin, puis suppression réelle.
    await db.execute(update(Parrainage).where(Parrainage.parrain_id == parrain.user_id).values(parrain_id=None))
    await db.execute(update(User).where(User.parraine_par_id == parrain.user_id).values(parraine_par_id=None))
    await db.delete(parrain)
    await db.commit()
    await db.refresh(lien)
    assert lien.parrain_id is None and lien.filleul_id == filleul.user_id
