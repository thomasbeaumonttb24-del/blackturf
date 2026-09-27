"""Parrainage — toutes les situations de parrain et de filleul rencontrées en vrai.

Chaque test est un cas concret : Victor (Expert offert à la main) qui parraine,
un abonné qui paie, un parrain en essai, résilié, gratuit, un filleul qui est
lui-même parrain, un parrain désactivé entre-temps, un client existant qui
tente un code…
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import api.routes.stripe_routes as sr
from api.routes.auth import create_tokens
from db.models import Parrainage, Subscription, User
from services import parrainage as P


class Stripe:
    """Stripe simulé : soldes clients, cartes, facture à venir."""

    def __init__(self, monkeypatch, apercu=None):
        self.soldes: list[dict] = []
        self.apercu = apercu  # dict de facture, ou Exception, ou None (pas de facture)
        self.cartes: dict[str, list[str]] = {}
        monkeypatch.setattr(P.settings, "stripe_secret_key", "sk_test")
        monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test")

        class _Liste(list):
            def auto_paging_iter(self):
                return iter(self)

        def _balance(customer, **kw):
            self.soldes.append({"customer": customer, **kw})
            return {"id": f"cbtxn_{len(self.soldes)}"}

        def _apercu(**kw):
            if isinstance(self.apercu, Exception) or self.apercu is None:
                raise self.apercu or P.stripe.error.InvalidRequestError("No upcoming invoices", None)
            return self.apercu

        monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", _balance)
        monkeypatch.setattr(P.stripe.Customer, "list_balance_transactions", lambda c, **kw: _Liste(
            {"id": f"cbtxn_{i + 1}", "metadata": s.get("metadata")}
            for i, s in enumerate(self.soldes) if s["customer"] == c))
        monkeypatch.setattr(P.stripe.Customer, "retrieve", lambda cid: {"balance": self.solde(cid)})
        monkeypatch.setattr(P.stripe.Customer, "create", lambda **kw: {"id": f"cus_{kw['metadata']['user_id'][:8]}"})
        monkeypatch.setattr(P.stripe.Invoice, "create_preview", _apercu)
        monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [
            {"empreinte": e, "pm": "pm", "marque": "visa", "dernier4": "4242", "financement": "debit"}
            for e in self.cartes.get(sub.get("customer"), [])])

    def solde(self, customer: str) -> int:
        return sum(s["amount"] for s in self.soldes if s["customer"] == customer)


async def _compte(db, prenom, **kw) -> User:
    u = User(user_id=str(uuid.uuid4()), email=f"{prenom.lower()}-{uuid.uuid4().hex[:4]}@blackturf.fr",
             prenom=prenom, plan=kw.pop("plan", "free"), email_verified=kw.pop("email_verified", True), **kw)
    db.add(u)
    await db.commit()
    return u


async def _parrainer(db, parrain: User, filleul: User) -> Parrainage:
    lien = await P.rattacher_filleul(filleul, await P.code_de(parrain, db), db)
    await db.commit()
    return lien


async def _abo(db, user: User, statut="active", plan="expert", **kw) -> Subscription:
    s = Subscription(sub_id=str(uuid.uuid4()), user_id=user.user_id,
                     stripe_subscription_id=f"sub_{uuid.uuid4().hex[:8]}", plan=plan,
                     periodicite=kw.pop("periodicite", "monthly"), statut=statut,
                     periode_debut=datetime.now(timezone.utc),
                     periode_fin=kw.pop("periode_fin", datetime.now(timezone.utc) + timedelta(days=20)), **kw)
    db.add(s)
    await db.commit()
    return s


def _facture(customer: str, paye=700, total=None, fid=None) -> dict:
    return {"id": fid or f"in_{uuid.uuid4().hex[:6]}", "customer": customer, "amount_paid": paye,
            "total": paye if total is None else total}


# ─── Victor : Expert offert à la main, sans Stripe ──────────────────────────
@pytest.mark.asyncio
async def test_victor_expert_offert_parraine(db, monkeypatch, client):
    stripe_ = Stripe(monkeypatch)
    victor = await _compte(db, "Victor", plan="expert")  # accordé par l'admin, aucun client Stripe
    lea = await _compte(db, "Lea", stripe_customer_id="cus_lea")
    stripe_.cartes["cus_lea"] = ["fp_lea"]

    # Son lien fonctionne comme celui de n'importe qui.
    jeton = {"Authorization": f"Bearer {create_tokens(victor.user_id, 'expert').access_token}"}
    r = await client.get("/api/v1/parrainage", headers=jeton)
    assert r.status_code == 200
    assert r.json()["deduction"] == {"situation": "offert"}
    code = r.json()["code"]
    assert (await client.get(f"/api/v1/parrainage/code/{code.lower()}")).json()["prenom"] == "Victor"

    lien = await P.rattacher_filleul(lea, code, db)
    await db.commit()
    await sr._handle_payment_succeeded(_facture("cus_lea"), db)

    # Crédité quand même : un client Stripe lui est ouvert, le crédit y attend.
    await db.refresh(victor)
    assert victor.stripe_customer_id and stripe_.solde(victor.stripe_customer_id) == -500
    assert victor.plan == "expert"  # son plan offert n'est pas touché
    await db.refresh(lien)
    assert lien.statut == "valide"
    resume = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    assert resume["credit_disponible_cents"] == 500
    assert resume["deduction"] == {"situation": "offert"}


def test_email_de_victor_dit_que_le_credit_attend():
    from services.email_compte import parrainage_credite
    _, texte = parrainage_credite("Victor", "Léa", "https://x", "offert")
    assert "offert" in texte and "réserve" in texte and "prochaine facture" not in texte


# ─── Situations du parrain ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_parrain_abonne_payant_voit_sa_facture_reduite(db, monkeypatch):
    echeance = int(time.time()) + 12 * 86400
    Stripe(monkeypatch, apercu={"total": 1900, "amount_due": 1400, "next_payment_attempt": echeance})
    paul = await _compte(db, "Paul", plan="expert", stripe_customer_id="cus_paul")
    await _abo(db, paul)
    d = (await P.resume(paul, db))["deduction"]
    assert d["situation"] == "facture" and d["total_cents"] == 1900 and d["a_payer_cents"] == 1400
    assert d["date"].timestamp() == echeance


@pytest.mark.asyncio
async def test_parrain_avec_code_promo_100_pourcent(db, monkeypatch):
    """Abonnement Stripe réel mais gratuit : aucune facture à payer → réserve."""
    Stripe(monkeypatch, apercu={"total": 0, "amount_due": 0, "next_payment_attempt": None})
    ami = await _compte(db, "Victor", plan="expert", stripe_customer_id="cus_v")
    await _abo(db, ami)
    assert (await P.resume(ami, db))["deduction"] == {"situation": "offert"}


@pytest.mark.asyncio
async def test_parrain_en_essai_stripe_injoignable(db, monkeypatch):
    Stripe(monkeypatch, apercu=RuntimeError("stripe down"))
    fin_essai = datetime.now(timezone.utc) + timedelta(days=5)
    alice = await _compte(db, "Alice", plan="standard", stripe_customer_id="cus_alice")
    await _abo(db, alice, statut="active", essai_fin=fin_essai)
    d = (await P.resume(alice, db))["deduction"]
    assert d["situation"] == "abonne"
    assert d["date"].replace(tzinfo=timezone.utc) == fin_essai


@pytest.mark.asyncio
async def test_parrain_resilie(db, monkeypatch):
    Stripe(monkeypatch)
    bob = await _compte(db, "Bob", plan="standard", stripe_customer_id="cus_bob")
    await _abo(db, bob, statut="cancel_at_period_end")
    assert (await P.resume(bob, db))["deduction"]["situation"] == "resilie"


@pytest.mark.asyncio
async def test_parrain_gratuit(db, monkeypatch):
    Stripe(monkeypatch)
    zoe = await _compte(db, "Zoe")
    assert (await P.resume(zoe, db))["deduction"] == {"situation": "sans_abonnement"}


@pytest.mark.asyncio
async def test_parrain_gratuit_credite_puis_sabonne(db, monkeypatch):
    """Crédit gagné avant d'être abonné : posé sur SON client Stripe, que le
    checkout réutilise — Stripe l'impute alors à ses factures."""
    stripe_ = Stripe(monkeypatch)
    zoe = await _compte(db, "Zoe")
    tom = await _compte(db, "Tom", stripe_customer_id="cus_tom")
    stripe_.cartes["cus_tom"] = ["fp_tom"]
    await _parrainer(db, zoe, tom)
    await sr._handle_payment_succeeded(_facture("cus_tom"), db)
    await db.refresh(zoe)
    client_zoe = zoe.stripe_customer_id
    assert client_zoe and stripe_.solde(client_zoe) == -500

    captured = {}
    monkeypatch.setattr(sr.stripe.checkout.Session, "create",
                        lambda **kw: captured.update(kw) or type("S", (), {"url": "u"})())
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_std"})
    await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, zoe)
    assert captured["customer"] == client_zoe  # même client → même solde
    # Zoé n'est pas filleule : elle garde son essai et les codes promo.
    assert captured["subscription_data"]["trial_period_days"] == 7


# ─── Situations du filleul ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_filleul_lui_meme_parrain_facture_soldee_par_son_credit(db, monkeypatch):
    """Sa première facture est payée par son propre crédit (0 € encaissé) :
    rien pour son parrain tant qu'il n'a pas réellement payé, mais sa remise
    est consommée."""
    stripe_ = Stripe(monkeypatch)
    paul = await _compte(db, "Paul", stripe_customer_id="cus_paul")
    marc = await _compte(db, "Marc", stripe_customer_id="cus_marc")
    stripe_.cartes["cus_marc"] = ["fp_marc"]
    lien = await _parrainer(db, paul, marc)

    await sr._handle_payment_succeeded(_facture("cus_marc", paye=0, total=700), db)
    await db.refresh(lien)
    assert lien.statut == "en_attente" and lien.remise_filleul_at is not None
    assert stripe_.soldes == []
    assert await P.remise_filleul_due(marc, db) is None

    # Premier vrai paiement le mois suivant → Paul est crédité.
    await sr._handle_payment_succeeded(_facture("cus_marc", paye=1200), db)
    await db.refresh(lien)
    assert lien.statut == "valide" and stripe_.solde("cus_paul") == -500


@pytest.mark.asyncio
async def test_facture_essai_a_zero_ne_consomme_rien(db, monkeypatch):
    Stripe(monkeypatch)
    paul = await _compte(db, "Paul")
    marc = await _compte(db, "Marc", stripe_customer_id="cus_marc")
    lien = await _parrainer(db, paul, marc)
    await sr._handle_payment_succeeded(_facture("cus_marc", paye=0, total=0), db)
    await db.refresh(lien)
    assert lien.remise_filleul_at is None


@pytest.mark.asyncio
async def test_chaine_a_parraine_b_qui_parraine_c(db, monkeypatch):
    stripe_ = Stripe(monkeypatch)
    a = await _compte(db, "Anne", stripe_customer_id="cus_a")
    b = await _compte(db, "Ben", stripe_customer_id="cus_b")
    c = await _compte(db, "Cleo", stripe_customer_id="cus_c")
    stripe_.cartes.update({"cus_b": ["fp_b"], "cus_c": ["fp_c"]})
    await _parrainer(db, a, b)
    await _parrainer(db, b, c)

    await sr._handle_payment_succeeded(_facture("cus_c"), db)
    # Un seul niveau : C rapporte à B, rien à A.
    assert stripe_.solde("cus_b") == -500 and stripe_.solde("cus_a") == 0
    await sr._handle_payment_succeeded(_facture("cus_b"), db)
    assert stripe_.solde("cus_a") == -500


@pytest.mark.asyncio
async def test_parrain_desactive_entre_temps(db, monkeypatch):
    """Le filleul garde sa remise (il n'y est pour rien), le parrain n'a rien."""
    stripe_ = Stripe(monkeypatch)
    paul = await _compte(db, "Paul", stripe_customer_id="cus_paul")
    marc = await _compte(db, "Marc", stripe_customer_id="cus_marc")
    stripe_.cartes["cus_marc"] = ["fp_marc"]
    lien = await _parrainer(db, paul, marc)
    paul.is_active = False
    await db.commit()

    assert await P.remise_filleul_due(marc, db) is not None
    await sr._handle_payment_succeeded(_facture("cus_marc"), db)
    await db.refresh(lien)
    assert lien.statut == "refuse" and lien.motif == "parrain_inactif"
    assert stripe_.soldes == []  # ni crédit, ni remise refacturée au filleul
    code = paul.code_parrain
    assert (await P.parrain_du_code(code, db)) is None


@pytest.mark.asyncio
async def test_paiement_echoue_puis_reussi(db, monkeypatch):
    stripe_ = Stripe(monkeypatch)
    paul = await _compte(db, "Paul", stripe_customer_id="cus_paul")
    marc = await _compte(db, "Marc", stripe_customer_id="cus_marc")
    stripe_.cartes["cus_marc"] = ["fp_marc"]
    lien = await _parrainer(db, paul, marc)
    await sr._handle_payment_failed({"id": "in_x", "customer": "cus_marc", "amount_due": 700,
                                     "attempt_count": 1}, db)
    await db.refresh(lien)
    assert lien.statut == "en_attente" and lien.remise_filleul_at is None
    await sr._handle_payment_succeeded(_facture("cus_marc"), db)
    await db.refresh(lien)
    assert lien.statut == "valide"


# ─── Transmission du lien et du code ────────────────────────────────────────
@pytest.mark.asyncio
async def test_code_colle_depuis_un_message(db, monkeypatch):
    """Code copié avec espaces, minuscules, ponctuation de fin de message."""
    Stripe(monkeypatch)
    paul = await _compte(db, "Paul")
    code = await P.code_de(paul, db)
    for variante in (code.lower(), f" {code[:4]} {code[4:]} ", f"{code}.", f"{code[:4]}-{code[4:]}"):
        assert (await P.parrain_du_code(variante, db)).user_id == paul.user_id, variante


@pytest.mark.asyncio
async def test_client_existant_ne_peut_pas_se_faire_parrainer(client, db, monkeypatch):
    Stripe(monkeypatch)
    paul = await _compte(db, "Paul")
    ancien = await _compte(db, "Ancien")
    r = await client.post("/api/v1/auth/register", json={
        "email": ancien.email, "password": "motdepasse123", "code_parrain": await P.code_de(paul, db)})
    assert r.status_code == 400
    await db.refresh(ancien)
    assert ancien.parraine_par_id is None
    assert (await db.execute(select(Parrainage))).first() is None


@pytest.mark.asyncio
async def test_parrain_non_confirme_na_pas_de_lien(client, db):
    recent = await _compte(db, "Nina", email_verified=False, created_at=datetime.now(timezone.utc))
    jeton = {"Authorization": f"Bearer {create_tokens(recent.user_id, 'free').access_token}"}
    assert (await client.get("/api/v1/parrainage", headers=jeton)).status_code == 403


@pytest.mark.asyncio
async def test_reinscription_non_confirmee_garde_le_premier_parrain(client, db, monkeypatch):
    Stripe(monkeypatch)
    paul = await _compte(db, "Paul")
    anne = await _compte(db, "Anne")
    corps = {"email": "marc@blackturf.fr", "password": "motdepasse123", "prenom": "Marc"}
    assert (await client.post("/api/v1/auth/register",
                              json={**corps, "code_parrain": await P.code_de(paul, db)})).status_code == 200
    # Il n'a pas confirmé et recommence avec un autre code : le premier parrain reste.
    assert (await client.post("/api/v1/auth/register",
                              json={**corps, "code_parrain": await P.code_de(anne, db)})).status_code == 200
    marc = (await db.execute(select(User).where(User.email == "marc@blackturf.fr"))).scalar_one()
    assert marc.parraine_par_id == paul.user_id
    assert len((await db.execute(select(Parrainage))).all()) == 1


@pytest.mark.asyncio
async def test_sans_code_inscription_normale_avec_essai(client, db, monkeypatch):
    r = await client.post("/api/v1/auth/register", json={
        "email": "solo@blackturf.fr", "password": "motdepasse123", "code_parrain": ""})
    assert r.status_code == 200
    solo = (await db.execute(select(User).where(User.email == "solo@blackturf.fr"))).scalar_one()
    assert solo.parraine_par_id is None
