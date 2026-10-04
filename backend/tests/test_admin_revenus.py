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


# ─────────────────────────────────────────────────────────────
# 2026-09-29 : facture Expert 19 € réglée par un abonné repassé en Standard
# entre l'échec et le paiement. L'écran affichait « Standard » (formule actuelle
# du compte) et annonçait 19 € au prochain prélèvement (plus gros montant payé).
# ─────────────────────────────────────────────────────────────
async def test_ligne_facturee_prend_la_ligne_principale_hors_prorata():
    from services.revenus_stripe import ligne_facturee
    facture = {"lines": {"data": [
        {"amount": -700, "price": {"id": "price_exp", "metadata": {"plan": "expert_monthly"}}},
        {"amount": 1200, "pricing": {"price_details": {"price": "price_std"}}},
    ]}}
    assert ligne_facturee(facture) == ("price_std", None)
    assert ligne_facturee({"lines": {"data": [
        {"amount": 1900, "price": {"id": "price_exp", "metadata": {"plan": "expert_monthly"}}}]}}) \
        == ("price_exp", "expert_monthly")
    assert ligne_facturee(None) == (None, None)


async def test_revenus_formule_payee_et_prochain_montant(client: AsyncClient, admin_headers, db, monkeypatch):
    from api.config import get_settings
    from api.routes import stripe_routes
    from services import revenus_stripe
    from services.revenus_stripe import Encaissement, Grand_livre
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="yas@x.fr", plan="standard", stripe_customer_id="cus_y")
    db.add(u)
    await db.flush()
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id="sub_y",
                        plan="standard", periodicite="monthly", statut="active",
                        periode_debut=now - timedelta(days=1), periode_fin=now + timedelta(days=3)))
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="yas@x.fr",
                             type="paiement_recu", plan="standard", stripe_subscription_id="sub_y",
                             montant_cents=1900, created_at=now - timedelta(minutes=30)))
    await db.commit()

    livre = Grand_livre(lu_le=now.timestamp())
    # Montant atypique (remise) : seule la ligne facturée dit que c'était de l'Expert.
    livre.encaissements = [Encaissement("ch_y", now - timedelta(minutes=30), 1400, 0, 50, 1350, "eur",
                                        "cus_y", None, "in_y", None, "Subscription update",
                                        price_id="price_exp")]
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setitem(stripe_routes.PLAN_FROM_PRICE, "price_exp", "expert")
    monkeypatch.setattr(revenus_stripe, "lire", lambda cle, depuis, forcer=False: livre)
    monkeypatch.setattr(revenus_stripe, "prochains_montants", lambda cle, ids, forcer=False: {"sub_y": 500})

    data = (await client.get("/admin/api/revenus?mois=2&mois_prevision=2", headers=admin_headers)).json()
    m = data["mois"][-1]
    assert m["paiements"][0]["plan"] == "expert"
    assert m["paiements"][0]["email"] == "yas@x.fr"
    assert m["par_formule"] == {"standard": 0, "expert": 1400}
    ech = {e["email"]: e for e in data["echeancier"]}["yas@x.fr"]
    assert ech["montant_cents"] == 500            # prochaine facture calculée par Stripe (prorata)
    futurs = [p["prevu_cents"] for p in data["prevision"]]
    assert futurs[0] == 500 and all(v == 1200 for v in futurs[1:])  # puis prix Standard


async def test_revenus_echecs_comptes_par_abonnement_pas_par_tentative(client: AsyncClient, admin_headers, db):
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="retry@x.fr", plan="standard")
    v = User(user_id=str(uuid.uuid4()), email="perdu@x.fr", plan="free")
    db.add_all([u, v])
    for i in range(4):  # Stripe réessaie la même facture : 4 tentatives, 1 échec
        db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="retry@x.fr",
                                 type="paiement_echoue", plan="standard", stripe_subscription_id="sub_r",
                                 montant_cents=1200, created_at=now - timedelta(minutes=60 - i)))
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="retry@x.fr",
                             type="paiement_recu", plan="standard", stripe_subscription_id="sub_r",
                             montant_cents=1200, created_at=now - timedelta(minutes=10)))
    for i in range(2):
        db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=v.user_id, email="perdu@x.fr",
                                 type="paiement_echoue", plan="expert", stripe_subscription_id="sub_p",
                                 montant_cents=1900, created_at=now - timedelta(minutes=50 - i)))
    await db.commit()

    m = (await client.get("/admin/api/revenus?mois=2", headers=admin_headers)).json()["mois"][-1]
    assert m["nb_echecs"] == 2
    assert m["echecs_cents"] == 1200 + 1900
    assert m["nb_tentatives_echouees"] == 6
    assert m["nb_echecs_regles"] == 1


async def test_revenus_frais_billing_et_moyenne_depuis_le_premier_encaissement(
        client: AsyncClient, admin_headers, monkeypatch):
    from api.config import get_settings
    from services import revenus_stripe
    from services.revenus_stripe import FraisDivers
    now = datetime.now(timezone.utc)
    livre = _livre(now)
    livre.frais_divers = [FraisDivers(now - timedelta(minutes=1), 29, "Billing - Usage Fee")]
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setattr(revenus_stripe, "lire", lambda cle, depuis, forcer=False: livre)
    monkeypatch.setattr(revenus_stripe, "prochains_montants", lambda cle, ids, forcer=False: {})

    data = (await client.get("/admin/api/revenus?mois=12", headers=admin_headers)).json()
    m = data["mois"][-1]
    assert m["frais_cents"] == 100 + 29
    assert m["net_cents"] == 3000 - 29
    # Un seul mois d'activité : la moyenne est ce mois, pas 31 € / 12.
    assert data["totaux"]["moyenne_mensuelle_cents"] == 3100


async def test_abonnements_mrr_prix_de_la_formule_actuelle(client: AsyncClient, admin_headers, db):
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="retro@x.fr", plan="standard")
    db.add(u)
    await db.flush()
    db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id="sub_retro",
                        plan="standard", periodicite="monthly", statut="active",
                        periode_debut=now - timedelta(days=1), periode_fin=now + timedelta(days=29)))
    # Facture Expert réglée APRÈS le passage en Standard.
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="retro@x.fr",
                             type="paiement_recu", plan="standard", stripe_subscription_id="sub_retro",
                             montant_cents=1900, created_at=now - timedelta(minutes=5)))
    await db.commit()
    data = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    assert data["resume"]["mrr"] == 12.0
    assert {a["email"]: a for a in data["abonnes"]}["retro@x.fr"]["montant_cents"] == 1200
    suivi = {c["email"]: c for c in data["suivi"]["comptes"]}["retro@x.fr"]
    assert suivi["montant_cents"] == 1200


async def test_suivi_prochaine_relance_suit_les_relances_faites(client: AsyncClient, admin_headers, db):
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="impaye@x.fr", plan="free")
    db.add(u)
    await db.flush()
    refus = now - timedelta(days=7, hours=9)
    relance = now - timedelta(hours=1)
    db.add_all([
        Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id="sub_imp",
                     plan="expert", periodicite="monthly", statut="past_due",
                     periode_debut=refus, periode_fin=refus + timedelta(days=30)),
        # Le webhook avait écrit « prochaine relance = J+3 » (attempt_count figé à 1).
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="impaye@x.fr",
                          type="paiement_echoue", plan="expert", stripe_subscription_id="sub_imp",
                          montant_cents=1900, created_at=refus,
                          detail={"facture": "in_imp", "prochaine_relance": int((refus + timedelta(days=3)).timestamp())}),
        SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="impaye@x.fr",
                          type="relance_paiement", plan="expert", stripe_subscription_id="sub_imp",
                          montant_cents=1900, created_at=relance, detail={"facture": "in_imp", "numero": 1}),
    ])
    await db.commit()
    data = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    c = {x["email"]: x for x in data["suivi"]["comptes"]}["impaye@x.fr"]
    assert c["relances_faites"] == 1
    # J+7 est passé, mais 4 jours doivent séparer les deux relances.
    prochaine = datetime.fromisoformat(c["prochaine_relance"].replace("Z", "+00:00"))
    assert abs((prochaine - (relance + timedelta(days=4))).total_seconds()) < 5


async def test_pass_range_a_part_et_rapproche_de_son_achat(client: AsyncClient, admin_headers, db, monkeypatch):
    """Un Pass Semaine (12 €) n'est PAS du Standard mensuel (même montant) : rangé
    en « pass », rapproché de son `pass_achete`, sans faire du client un abonné déjà vu."""
    from api.config import get_settings
    from services import revenus_stripe
    from services.revenus_stripe import Encaissement, Grand_livre
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="passant@x.fr", plan="free", stripe_customer_id="cus_p")
    db.add(u)
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=u.user_id, email="passant@x.fr",
                             type="pass_achete", plan="expert", montant_cents=1200,
                             created_at=now - timedelta(minutes=40)))
    await db.commit()
    livre = Grand_livre(lu_le=now.timestamp())
    livre.encaissements = [
        Encaissement("ch_p", now - timedelta(minutes=40), 1200, 0, 40, 1160, "eur", "cus_p", "passant@x.fr",
                     None, None, "BlackTurf — Pass Semaine", pass_duree="semaine"),
        # Puis il s'abonne : c'est bien un NOUVEAU client abonné.
        Encaissement("ch_s", now - timedelta(minutes=10), 1200, 0, 40, 1160, "eur", "cus_p", "passant@x.fr",
                     "in_s", None, "Subscription creation"),
    ]
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_local")
    monkeypatch.setattr(revenus_stripe, "lire", lambda cle, depuis, forcer=False: livre)

    m = (await client.get("/admin/api/revenus?mois=2", headers=admin_headers)).json()
    courant = m["mois"][-1]
    assert courant["passes_cents"] == 1200
    assert courant["par_formule"] == {"standard": 1200, "expert": 0}
    assert courant["nouveaux_cents"] == 1200
    natures = {p["charge_id"]: (p["nature"], p["plan"]) for p in courant["paiements"]}
    assert natures["ch_p"] == ("pass", "pass") and natures["ch_s"][0] == "nouveau"
    assert all(e["charge_id"] != "ch_p" for e in m["rapprochement"]["absents_du_journal"])
    assert m["rapprochement"]["absents_de_stripe"] == []


async def test_encaissement_reconnait_un_pass_a_ses_metadonnees():
    from services.revenus_stripe import _encaissement
    base = {"id": "ch_1", "amount": 1200, "created": 1, "currency": "eur",
            "status": "succeeded", "paid": True, "captured": True}
    assert _encaissement({**base, "metadata": {"type": "pass", "duree": "semaine"}}).pass_duree == "semaine"
    assert _encaissement({**base, "metadata": {}}).pass_duree is None


async def test_abonnements_compte_les_pass_a_part(client: AsyncClient, admin_headers, db):
    from db.models import PassAcces
    now = datetime.now(timezone.utc)
    u = User(user_id=str(uuid.uuid4()), email="pass@x.fr", plan="expert")
    db.add(u)
    db.add(PassAcces(user_id=u.user_id, duree="jour", plan="expert", montant_cents=500,
                     stripe_session_id="cs_x", debut=now - timedelta(hours=1), fin=now + timedelta(hours=23),
                     statut="actif", renonciation_at=now, renonciation_version="v1"))
    await db.commit()
    data = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    r = data["repartition"]
    assert r["passes"] == 1 and r["offerts"] == 0
    assert r["par_formule"]["expert"]["passes"] == 1
    assert [p["email"] for p in data["passes"]] == ["pass@x.fr"]
    fiche = (await client.get(f"/admin/api/users/{u.user_id}", headers=admin_headers)).json()
    assert fiche["passes"][0]["duree"] == "jour" and fiche["passes"][0]["statut"] == "actif"