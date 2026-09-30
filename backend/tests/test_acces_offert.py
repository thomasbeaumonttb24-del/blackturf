"""Accès offert (gagnant du jeu concours) : jamais effacé par Stripe, expire à
la date prévue, rend alors le plan que les abonnements justifient."""
from datetime import datetime, timedelta, timezone

import pytest

import api.routes.stripe_routes as sr
from services import acces_offert as AO
from tests.test_stripe_essai_et_changement_plan import _abo, _user

pytestmark = pytest.mark.asyncio


async def test_gagnant_garde_expert_malgre_la_fin_de_son_essai(db):
    user = await _user(db, plan="free")
    await AO.offrir(db, user, "expert", 30, "Défi du mois d'octobre", par="admin")
    assert user.plan == "expert"
    abo = await _abo(db, user, plan="standard", statut="active", stripe_id="sub_essai")
    # Fin d'essai sans carte : l'abonnement meurt — l'accès offert reste.
    await sr._handle_subscription_deleted({"id": "sub_essai", "customer": "cus_test"}, db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_abonne_standard_qui_gagne_expert_reste_expert_apres_paiement(db):
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_std")
    await AO.offrir(db, user, "expert", 30, "concours", par="admin")
    await sr._handle_payment_succeeded({"id": "in_1", "customer": "cus_test", "subscription": "sub_std",
                                        "amount_paid": 1200, "billing_reason": "subscription_cycle"}, db)
    await db.refresh(user)
    assert user.plan == "expert"


async def test_echeance_rend_le_plan_des_abonnements(db):
    user = await _user(db, plan="free")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_std2")
    await AO.offrir(db, user, "expert", 1, "concours", par="admin")
    assert user.plan == "expert"
    # Échéance passée : on antidate le don.
    from sqlalchemy import select
    from db.models import SubscriptionEvent
    ev = (await db.execute(select(SubscriptionEvent).where(SubscriptionEvent.type == "acces_offert"))).scalar_one()
    ev.detail = {**ev.detail, "jusqu_au": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    await db.commit()
    assert await AO.expirer_acces_offerts(db) == 1
    await db.refresh(user)
    assert user.plan == "standard"
    assert await AO.expirer_acces_offerts(db) == 0  # une seule fois


async def test_retrait_immediat_et_le_dernier_geste_gagne(db):
    user = await _user(db, plan="free")
    await AO.offrir(db, user, "expert", None, "test", par="admin")
    await AO.retirer(db, user, par="admin")
    assert user.plan == "free"
    assert await AO.plan_offert_actif(db, user.user_id) is None


async def test_route_admin_offrir_et_retirer(client, admin_headers, db):
    user = await _user(db, plan="free", stripe_customer_id=None)
    r = await client.post(f"/admin/api/users/{user.user_id}/acces-offert", headers=admin_headers,
                          json={"plan": "expert", "jours": 30, "motif": "Gagnant défi"})
    assert r.status_code == 200 and r.json()["plan"] == "expert"
    d = (await client.get(f"/admin/api/users/{user.user_id}", headers=admin_headers)).json()
    assert d["acces_offert"]["plan"] == "expert" and d["acces_offert"]["actif"] is True
    ab = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    assert any(o["email"] == user.email and o["jusqu_au"] for o in ab["offerts"])
    r = await client.delete(f"/admin/api/users/{user.user_id}/acces-offert", headers=admin_headers)
    assert r.json()["plan"] == "free"
    bad = await client.post(f"/admin/api/users/{user.user_id}/acces-offert", headers=admin_headers,
                            json={"plan": "platine"})
    assert bad.status_code == 400
