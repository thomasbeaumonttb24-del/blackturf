"""Tests admin routes — accès restreint."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_dashboard_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/dashboard", headers=auth_headers)
    assert resp.status_code == 403


async def test_dashboard_admin_ok(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/dashboard", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert "modele" in data


async def test_list_users_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/users", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_users_non_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/users", headers=auth_headers)
    assert resp.status_code == 403


async def test_list_models_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/models", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_scraper_logs_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/scraper/logs", headers=admin_headers)
    assert resp.status_code == 200


async def test_scraper_status_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/scraper/status", headers=admin_headers)
    assert resp.status_code == 200


async def test_update_user_plan(client: AsyncClient, admin_headers, auth_headers):
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["user_id"]

    resp = await client.patch(
        f"/admin/api/users/{user_id}",
        json={"plan": "standard"},
        headers=admin_headers,
    )
    assert resp.status_code == 200

    me_after = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_after.json()["plan"] == "standard"


async def test_alertes_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/admin/api/alertes", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ─────────────────────────────────────────────
# Suivi des abonnements (2026-08-20)
# ─────────────────────────────────────────────
async def test_abonnements_requires_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/abonnements", headers=auth_headers)
    assert resp.status_code == 403


async def test_abonnements_expose_essais_et_mouvements(client: AsyncClient, admin_headers):
    """L'exploitant doit voir, en une requête : qui est en essai, jusqu'à quand,
    avec ou sans carte, et le journal des mouvements. `subscriptions` seule ne
    dit pas si un client a résilié AVANT la fin de son essai."""
    resp = await client.get("/admin/api/abonnements", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert set(data) >= {"resume", "abonnes", "mouvements"}
    assert set(data["resume"]) >= {
        "en_essai_avec_carte", "en_essai_sans_carte", "abonnes_payants",
        "fin_essai_sous_3j", "mrr", "essais_perdus_30j", "resiliations_30j",
        "resiliations_pendant_essai_30j",
    }
    assert isinstance(data["abonnes"], list)
    assert isinstance(data["mouvements"], list)


# ─────────────────────────────────────────────
# Suppression d'un compte
# ─────────────────────────────────────────────
async def _compte_avec_historique(db, email: str = "a-supprimer@blackturf.fr"):
    """Un compte et tout ce qui pend après lui : pari, portefeuille, stratégie,
    alerte, abonnement résilié et son journal comptable."""
    import uuid
    from datetime import datetime, timezone

    from api.routes.auth import _hash
    from db.models import (AlerteLog, Bankroll, BankrollEntry, Strategie,
                           Subscription, SubscriptionEvent, User)

    uid = str(uuid.uuid4())
    maintenant = datetime.now(timezone.utc)
    db.add_all([
        User(user_id=uid, email=email, hashed_password=_hash("MotDePasse123"),
             plan="free", email_verified=True),
        Bankroll(bankroll_id=str(uuid.uuid4()), user_id=uid, nom="Principal",
                 montant_initial=100.0, est_principale=True),
        BankrollEntry(entry_id=str(uuid.uuid4()), user_id=uid, date=maintenant,
                      type_pari="Simple Gagnant", mise=10.0),
        Strategie(strategie_id=str(uuid.uuid4()), user_id=uid, nom="Test",
                  filtres={}, indicateurs={}),
        AlerteLog(alerte_id=str(uuid.uuid4()), user_id=uid, type_alerte="value_bet",
                  canal="in-app"),
        Subscription(sub_id=str(uuid.uuid4()), user_id=uid,
                     stripe_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
                     plan="standard", periodicite="monthly", statut="canceled",
                     periode_debut=maintenant, periode_fin=maintenant),
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=uid, email=email,
                          type="resilie", plan="standard"),
    ])
    await db.commit()
    return uid


async def test_supprimer_un_compte_exige_les_droits_admin(client: AsyncClient, db, auth_headers):
    uid = await _compte_avec_historique(db, "protege@blackturf.fr")
    resp = await client.delete(f"/admin/api/users/{uid}", headers=auth_headers)
    assert resp.status_code == 403


async def test_supprimer_un_compte_efface_ce_qui_n_appartient_qu_a_lui(
    client: AsyncClient, db, admin_headers
):
    from sqlalchemy import select
    from db.models import (AlerteLog, Bankroll, BankrollEntry, Strategie,
                           Subscription, SubscriptionEvent, User)

    uid = await _compte_avec_historique(db)

    resp = await client.delete(f"/admin/api/users/{uid}", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    for modele, colonne in ((User, User.user_id), (Bankroll, Bankroll.user_id),
                            (BankrollEntry, BankrollEntry.user_id),
                            (Strategie, Strategie.user_id), (AlerteLog, AlerteLog.user_id),
                            (Subscription, Subscription.user_id)):
        restant = (await db.execute(select(modele).where(colonne == uid))).scalars().all()
        assert restant == [], f"{modele.__tablename__} garde une ligne du compte supprimé"


async def test_le_journal_comptable_survit_a_la_suppression(
    client: AsyncClient, db, admin_headers
):
    """Purger l'utilisateur n'efface pas l'historique d'abonnement : la ligne
    porte déjà l'e-mail en clair et se conserve — elle est seulement détachée."""
    from sqlalchemy import select
    from db.models import SubscriptionEvent

    uid = await _compte_avec_historique(db, "journal@blackturf.fr")

    assert (await client.delete(f"/admin/api/users/{uid}",
                                headers=admin_headers)).status_code == 200

    evenements = (await db.execute(
        select(SubscriptionEvent).where(SubscriptionEvent.email == "journal@blackturf.fr")
    )).scalars().all()
    assert len(evenements) == 1
    assert evenements[0].user_id is None


async def test_un_abonnement_vivant_bloque_la_suppression(
    client: AsyncClient, db, admin_headers
):
    """Supprimer le compte n'arrête pas Stripe : la facturation continuerait
    sans personne en face."""
    import uuid
    from datetime import datetime, timezone
    from sqlalchemy import select
    from db.models import Subscription, User

    uid = await _compte_avec_historique(db, "encore-abonne@blackturf.fr")
    maintenant = datetime.now(timezone.utc)
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=uid,
                        stripe_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
                        plan="expert", periodicite="monthly", statut="active",
                        periode_debut=maintenant, periode_fin=maintenant))
    await db.commit()

    resp = await client.delete(f"/admin/api/users/{uid}", headers=admin_headers)

    assert resp.status_code == 409
    assert "Stripe" in resp.json()["detail"]
    assert (await db.execute(select(User).where(User.user_id == uid))).scalar_one_or_none()


async def test_un_admin_ne_se_supprime_pas_lui_meme(client: AsyncClient, db, admin_headers):
    """Sinon la console d'administration se ferme d'un clic, sans retour possible."""
    from sqlalchemy import select
    from db.models import User

    admin = (await db.execute(
        select(User).where(User.email == "admin@blackturf.fr"))).scalar_one()

    resp = await client.delete(f"/admin/api/users/{admin.user_id}", headers=admin_headers)

    assert resp.status_code == 400
    assert (await db.execute(
        select(User).where(User.user_id == admin.user_id))).scalar_one_or_none()


async def test_un_autre_compte_admin_n_est_pas_supprimable(
    client: AsyncClient, db, admin_headers
):
    import uuid
    from sqlalchemy import select
    from api.routes.auth import _hash
    from db.models import User

    autre = User(user_id=str(uuid.uuid4()), email="admin2@blackturf.fr",
                 hashed_password=_hash("MotDePasse123"), plan="expert",
                 is_admin=True, email_verified=True)
    db.add(autre)
    await db.commit()

    resp = await client.delete(f"/admin/api/users/{autre.user_id}", headers=admin_headers)

    assert resp.status_code == 400
    assert (await db.execute(
        select(User).where(User.user_id == autre.user_id))).scalar_one_or_none()
