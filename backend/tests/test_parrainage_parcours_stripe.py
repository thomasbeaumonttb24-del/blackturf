"""Parcours complet du parrainage, par le VRAI point d'entrée Stripe.

Les événements passent par `/api/v1/stripe/webhook`, signés comme Stripe les
signe : c'est le chemin qu'emprunte la production, contrôle de signature et
anti-rejeu compris. Seuls les appels sortants vers l'API Stripe sont simulés
(leurs paramètres sont par ailleurs validés contre la spécification officielle
par `test_parrainage_stripe_mock.py` quand stripe-mock tourne).
"""
import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import select

import api.routes.stripe_routes as sr
from api.routes.auth import create_tokens
from db.models import Parrainage, Subscription, User
from services import parrainage as P

SECRET = "whsec_test_parrainage"


def _signe(evenement: dict) -> tuple[bytes, dict]:
    corps = json.dumps(evenement).encode()
    t = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    return corps, {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def _evenement(type_: str, objet: dict, eid: str | None = None) -> dict:
    return {"id": eid or f"evt_{uuid.uuid4().hex[:10]}", "object": "event", "type": type_,
            "data": {"object": objet}}


@pytest.fixture
def stripe_simule(monkeypatch):
    soldes: list[dict] = []
    # Le webhook crée sa table anti-rejeu en SQL PostgreSQL (`DEFAULT now()`),
    # que SQLite refuse : traduit ici pour la base de test, et pour elle seule.
    from sqlalchemy import text as _text
    monkeypatch.setattr(sr, "text", lambda sql: _text(
        sql.replace("TIMESTAMPTZ NOT NULL DEFAULT now()", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")))
    monkeypatch.setattr(sr.settings, "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(P.settings, "stripe_secret_key", "sk_test")
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_std": "standard"})
    monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [
        {"empreinte": "fp_filleul", "pm": "pm_1", "marque": "visa", "dernier4": "4242", "financement": "debit"}])
    monkeypatch.setattr(sr, "_a_moyen_de_paiement", lambda sub: True)

    class _Liste(list):
        def auto_paging_iter(self):
            return iter(self)

    def _balance(customer, **kw):
        soldes.append({"customer": customer, **kw})
        return {"id": f"cbtxn_{len(soldes)}"}

    monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", _balance)
    monkeypatch.setattr(P.stripe.Customer, "list_balance_transactions", lambda c, **kw: _Liste(
        {"id": f"cbtxn_{i + 1}", "metadata": s.get("metadata")} for i, s in enumerate(soldes) if s["customer"] == c))
    monkeypatch.setattr(P.stripe.Customer, "retrieve", lambda cid: {
        "balance": sum(s["amount"] for s in soldes if s["customer"] == cid)})
    return soldes


@pytest.mark.asyncio
async def test_parcours_complet(client, db, stripe_simule):
    soldes = stripe_simule

    # 1. Le parrain récupère son lien.
    parrain = User(user_id=str(uuid.uuid4()), email="paul@blackturf.fr", prenom="Paul",
                   plan="standard", email_verified=True, stripe_customer_id="cus_parrain")
    db.add(parrain)
    await db.commit()
    jeton = {"Authorization": f"Bearer {create_tokens(parrain.user_id, 'standard').access_token}"}
    lien = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    code = lien["code"]
    assert lien["lien"].endswith(f"/inscription?parrain={code}")

    # 2. L'ami s'inscrit par le lien.
    r = await client.post("/api/v1/auth/register", json={
        "email": "fanny@blackturf.fr", "password": "motdepasse123", "prenom": "Fanny", "pseudo": "Fanny", "code_parrain": code})
    assert r.status_code == 200, r.text
    filleul = (await db.execute(select(User).where(User.email == "fanny@blackturf.fr"))).scalar_one()
    filleul.email_verified = True
    filleul.stripe_customer_id = "cus_filleul"
    await db.commit()
    suivi = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    assert suivi["filleuls"][0]["etape"] == "attente_paiement"
    assert "En attente du premier paiement" in suivi["filleuls"][0]["etape_libelle"]

    # 3. Stripe : abonnement créé (sans essai), mais pas encore payé → rien pour le parrain.
    sub = {"id": "sub_filleul", "object": "subscription", "customer": "cus_filleul", "status": "active",
           "items": {"data": [{"id": "si_1", "price": {"id": "price_std", "unit_amount": 1200,
                                                         "recurring": {"interval": "month"}},
                               "current_period_start": int(time.time()),
                               "current_period_end": int(time.time()) + 30 * 86400}]},
           "trial_end": None, "metadata": {"parrainage_id": "x"}}
    corps, entetes = _signe(_evenement("customer.subscription.created", sub))
    assert (await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)).status_code == 200
    assert soldes == []
    suivi = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    assert suivi["filleuls"][0]["etape"] == "paiement_en_cours"

    # 4. Facture payée : 12 € − 5 € = 7 € encaissés → le parrain est crédité de 5 €.
    facture = {"id": "in_1", "object": "invoice", "customer": "cus_filleul", "amount_paid": 700,
               "subscription": "sub_filleul", "billing_reason": "subscription_create"}
    evt = _evenement("invoice.payment_succeeded", facture, eid="evt_paiement")
    corps, entetes = _signe(evt)
    assert (await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)).status_code == 200
    assert [(s["customer"], s["amount"]) for s in soldes] == [("cus_parrain", -500)]

    # 5. Stripe renvoie le même événement : rien de plus.
    corps, entetes = _signe(evt)
    await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)
    assert len(soldes) == 1

    suivi = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    assert suivi["valides"] == 1 and suivi["gagne_cents"] == 500
    assert suivi["credit_disponible_cents"] == 500
    assert suivi["filleuls"][0]["etape"] == "credite"

    # 6. Plus jamais de remise ni d'essai pour le filleul.
    filleul = (await db.execute(select(User).where(User.email == "fanny@blackturf.fr"))).scalar_one()
    assert await P.remise_filleul_due(filleul, db) is None

    # 7. Premier paiement remboursé → crédit repris.
    corps, entetes = _signe(_evenement("charge.refunded", {
        "id": "ch_1", "object": "charge", "customer": "cus_filleul", "invoice": "in_1",
        "created": int(time.time())}))
    assert (await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)).status_code == 200
    assert soldes[-1]["customer"] == "cus_parrain" and soldes[-1]["amount"] == 500
    lienp = (await db.execute(select(Parrainage))).scalar_one()
    await db.refresh(lienp)
    assert lienp.statut == "annule"
    suivi = (await client.get("/api/v1/parrainage", headers=jeton)).json()
    assert suivi["filleuls"][0]["etape"] == "annule" and suivi["credit_disponible_cents"] == 0


@pytest.mark.asyncio
async def test_signature_invalide_rejetee(client, stripe_simule):
    corps, entetes = _signe(_evenement("invoice.payment_succeeded", {"id": "in_x"}))
    entetes["Stripe-Signature"] = entetes["Stripe-Signature"][:-4] + "0000"
    assert (await client.post("/api/v1/stripe/webhook", content=corps, headers=entetes)).status_code == 400
    assert stripe_simule == []
