"""Revenus réels par mois et échéancier des renouvellements (2026-09-25).

Le MRR dit ce que les abonnements DEVRAIENT rapporter ; l'exploitant veut voir
ce qui est réellement entré en caisse, mois par mois, et la date du prochain
prélèvement de chaque abonné.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from db.models import Subscription, SubscriptionEvent, User

pytestmark = pytest.mark.asyncio


async def test_revenus_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/revenus", headers=auth_headers)
    assert resp.status_code == 403


async def test_revenus_encaissements_reels_et_echeancier(client: AsyncClient, admin_headers, db):
    now = datetime.now(timezone.utc)
    payant = User(user_id=str(uuid.uuid4()), email="payant@x.fr", plan="expert")
    essai = User(user_id=str(uuid.uuid4()), email="essai@x.fr", plan="standard")
    partant = User(user_id=str(uuid.uuid4()), email="partant@x.fr", plan="standard")
    db.add_all([payant, essai, partant])
    sid = "sub_payant"
    db.add_all([
        Subscription(sub_id=str(uuid.uuid4()), user_id=payant.user_id, stripe_subscription_id=sid,
                     plan="expert", periodicite="monthly", statut="active",
                     periode_debut=now - timedelta(days=20), periode_fin=now + timedelta(days=10)),
        Subscription(sub_id=str(uuid.uuid4()), user_id=essai.user_id, stripe_subscription_id="sub_essai",
                     plan="standard", periodicite="monthly", statut="active",
                     periode_debut=now, periode_fin=now + timedelta(days=5),
                     essai_fin=now + timedelta(days=5)),
        Subscription(sub_id=str(uuid.uuid4()), user_id=partant.user_id, stripe_subscription_id="sub_part",
                     plan="standard", periodicite="monthly", statut="cancel_at_period_end",
                     periode_debut=now - timedelta(days=25), periode_fin=now + timedelta(days=5)),
        # Deux encaissements réels : le premier (création), puis un renouvellement.
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=payant.user_id, email="payant@x.fr",
                          type="paiement_recu", plan="expert", stripe_subscription_id=sid,
                          montant_cents=1900, detail={"motif": "subscription_create"},
                          created_at=now - timedelta(minutes=10)),
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=payant.user_id, email="payant@x.fr",
                          type="paiement_recu", plan="expert", stripe_subscription_id=sid,
                          montant_cents=1900, detail={"motif": "subscription_cycle"},
                          created_at=now - timedelta(minutes=5)),
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=partant.user_id, email="partant@x.fr",
                          type="paiement_echoue", plan="standard", stripe_subscription_id="sub_part",
                          montant_cents=1200, created_at=now - timedelta(minutes=3)),
    ])
    await db.commit()

    resp = await client.get("/admin/api/revenus?mois=3", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["mois"]) == 3
    courant = data["mois"][-1]
    assert courant["encaisse_cents"] == 3800
    assert courant["nb_paiements"] == 2
    assert courant["nouveaux_cents"] == 1900
    assert courant["renouvellements_cents"] == 1900
    assert courant["par_formule"] == {"standard": 0, "expert": 3800}
    assert courant["nb_echecs"] == 1 and courant["echecs_cents"] == 1200
    assert courant["nb_clients"] == 1
    assert [p["nature"] for p in courant["paiements"]] == ["renouvellement", "nouveau"]
    assert data["totaux"]["mois_courant_cents"] == 3800

    par_email = {e["email"]: e for e in data["echeancier"]}
    assert par_email["payant@x.fr"]["nature"] == "renouvellement"
    assert par_email["payant@x.fr"]["montant_cents"] == 1900
    assert par_email["essai@x.fr"]["nature"] == "premier_prelevement"
    # Une résiliation programmée ne débitera rien : elle ne gonfle pas la prévision.
    assert par_email["partant@x.fr"]["nature"] == "fin_acces"
    assert par_email["partant@x.fr"]["montant_cents"] == 0
    assert sum(p["prevu_cents"] for p in data["prevision"]) >= 1900 + 1200


async def test_revenus_prevision_couvre_des_mois_entiers(client: AsyncClient, admin_headers, db):
    """Un abonnement mensuel doit peser le MÊME montant dans chacun des mois de
    prévision : une fenêtre en jours coupait le dernier mois et simulait une chute."""
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="mensuel@x.fr", plan="standard")
    db.add(u)
    await db.flush()
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id="sub_m",
                        plan="standard", periodicite="monthly", statut="active",
                        periode_debut=now - timedelta(days=10), periode_fin=now + timedelta(days=2)))
    await db.commit()

    data = (await client.get("/admin/api/revenus?mois=2&mois_prevision=3", headers=admin_headers)).json()
    courant = data["mois"][-1]["mois"]
    futurs = [p for p in data["prevision"] if p["mois"] > courant]
    assert len(futurs) == 3
    assert all(p["prevu_cents"] == 1200 for p in futurs)


# ─────────────────────────────────────────────────────────────
# Source Stripe (2026-09-25) : l'écran montrait 19 € quand deux abonnés avaient
# payé — le journal interne avait un trou. Les montants viennent désormais de
# l'API Stripe ; le journal sert au rapprochement.
# ─────────────────────────────────────────────────────────────
def _livre(now, *, avec_remboursement=False):
    from services.revenus_stripe import Encaissement, Grand_livre, Remboursement, Virement
    livre = Grand_livre(lu_le=now.timestamp())
    livre.encaissements = [
        Encaissement("ch_a", now - timedelta(minutes=30), 1900, 0, 57, 1843, "eur",
                     "cus_a", "payant@x.fr", "in_a", "https://pay.stripe.com/receipts/a", "Abonnement Expert"),
        Encaissement("ch_b", now - timedelta(minutes=20), 1200, 0, 43, 1157, "eur",
                     "cus_b", "oublie@x.fr", "in_b", "https://pay.stripe.com/receipts/b", "Abonnement Standard"),
    ]
    if avec_remboursement:
        livre.remboursements = [Remboursement("re_b", "ch_b", now - timedelta(minutes=10), 1200, -1200, "oublie@x.fr")]
    livre.virements = [Virement("po_1", now - timedelta(minutes=5), 3000, "paid")]
    return livre


async def test_revenus_lus_chez_stripe_et_rapproches(client: AsyncClient, admin_headers, db, monkeypatch):
    from api.config import get_settings
    from services import revenus_stripe
    now = datetime.now(timezone.utc)
    a = User(user_id=str(uuid.uuid4()), email="payant@x.fr", plan="expert", stripe_customer_id="cus_a")
    b = User(user_id=str(uuid.uuid4()), email="oublie@x.fr", plan="standard", stripe_customer_id="cus_b")
    db.add_all([a, b])
    # Le journal ne connaît QUE le premier paiement : c'est le trou constaté en prod.
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=a.user_id, email="payant@x.fr",
                             type="paiement_recu", plan="expert", stripe_subscription_id="sub_a",
                             montant_cents=1900, created_at=now - timedelta(minutes=29)))
    await db.commit()

    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setattr(revenus_stripe, "lire", lambda cle, depuis, forcer=False: _livre(now))

    data = (await client.get("/admin/api/revenus?mois=2", headers=admin_headers)).json()
    assert data["source"]["type"] == "stripe"
    m = data["mois"][-1]
    assert m["encaisse_cents"] == 3100          # les DEUX paiements, pas seulement le journalisé
    assert m["ca_cents"] == 3100
    assert m["frais_cents"] == 100
    assert m["net_cents"] == 3000
    assert m["verse_cents"] == 3000
    assert m["par_formule"] == {"standard": 1200, "expert": 1900}
    assert {p["recu_url"] for p in m["paiements"]} == {
        "https://pay.stripe.com/receipts/a", "https://pay.stripe.com/receipts/b"}
    # Le rapprochement nomme le paiement que le journal a manqué.
    assert [e["email"] for e in data["rapprochement"]["absents_du_journal"]] == ["oublie@x.fr"]
    assert data["rapprochement"]["absents_de_stripe"] == []


async def test_revenus_remboursement_deduit_du_chiffre_d_affaires(client: AsyncClient, admin_headers, monkeypatch):
    from api.config import get_settings
    from services import revenus_stripe
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setattr(revenus_stripe, "lire", lambda cle, depuis, forcer=False: _livre(now, avec_remboursement=True))

    data = (await client.get("/admin/api/revenus?mois=2", headers=admin_headers)).json()
    m = data["mois"][-1]
    assert m["encaisse_cents"] == 3100
    assert m["rembourse_cents"] == 1200
    assert m["ca_cents"] == 1900
    assert m["net_cents"] == 3000 - 1200
    assert data["totaux"]["periode_cents"] == 1900


async def test_revenus_stripe_injoignable_repli_signale(client: AsyncClient, admin_headers, monkeypatch):
    from api.config import get_settings
    from services import revenus_stripe

    def _panne(*_a, **_k):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setattr(revenus_stripe, "lire", _panne)
    data = (await client.get("/admin/api/revenus?mois=2", headers=admin_headers)).json()
    assert data["source"]["type"] == "journal"
    assert "Stripe" in data["source"]["erreur"]
    assert data["rapprochement"]["verifie"] is False


async def test_seuls_les_debits_reussis_et_captures_sont_de_l_argent_encaisse():
    from services.revenus_stripe import _encaissement
    base = {"id": "ch", "created": 1_760_000_000, "amount": 1200, "amount_captured": 1200,
            "amount_refunded": 0, "currency": "eur", "customer": "cus",
            "billing_details": {"email": "a@x.fr"},
            "balance_transaction": {"fee": 43, "net": 1157}}
    ok = _encaissement({**base, "status": "succeeded", "paid": True, "captured": True})
    assert (ok.montant_cents, ok.frais_cents, ok.net_cents, ok.email) == (1200, 43, 1157, "a@x.fr")
    assert _encaissement({**base, "status": "failed", "paid": False}) is None
    assert _encaissement({**base, "status": "succeeded", "paid": True, "captured": False}) is None
