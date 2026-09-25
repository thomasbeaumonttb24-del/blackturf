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
