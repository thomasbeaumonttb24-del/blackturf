"""Le tunnel d'abonnement — essai unique, carte exigée, un seul abonnement par compte.

Constaté en production le 2026-08-20 sur un compte réel : TROIS abonnements
`trialing` simultanés (2 Standard + 1 Expert) ouverts en 24 h, aucun moyen de
paiement. Trois défauts distincts, chacun couvert ici :

1. `create_checkout` passait `trial_period_days: 7` à chaque appel sans jamais
   regarder si le compte avait déjà eu son essai — et Stripe ne déduplique pas
   les essais par client ;
2. changer de formule repassait par Checkout et créait un SECOND abonnement, le
   premier restant actif — donc double facturation dès qu'une carte existait ;
3. la fin du premier abonnement posait `plan = "free"` alors qu'un autre courait
   encore, coupant l'accès trop tôt.
"""
import time
import uuid
import pytest

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from db.models import User, Subscription
import api.routes.stripe_routes as sr


def _sub_stripe(status: str = "trialing", price_id: str = "price_test_standard",
                sub_id: str | None = None, trial_end: int | None = None,
                periode_sur_item: bool = False) -> dict:
    now = int(time.time())
    item: dict = {
        "id": "si_test",
        "price": {"id": price_id, "recurring": {"interval": "month"}},
    }
    sub: dict = {
        "id": sub_id or str(uuid.uuid4()),
        "customer": "cus_test",
        "status": status,
        "items": {"data": [item]},
        "trial_end": trial_end,
    }
    # Les versions récentes de l'API Stripe portent la période sur l'ARTICLE.
    cible = item if periode_sur_item else sub
    cible["current_period_start"] = now
    cible["current_period_end"] = now + 30 * 86400
    return sub


async def _user(db, **kw) -> User:
    user = User(user_id=str(uuid.uuid4()),
                email=kw.pop("email", f"{uuid.uuid4().hex[:8]}@blackturf.fr"),
                plan=kw.pop("plan", "free"),
                stripe_customer_id=kw.pop("stripe_customer_id", "cus_test"),
                **kw)
    db.add(user)
    await db.commit()
    return user


async def _abo(db, user: User, plan: str = "standard", statut: str = "active",
               stripe_id: str | None = None, essai_fin=None,
               periodicite: str = "monthly") -> Subscription:
    sub = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=stripe_id or f"sub_{uuid.uuid4().hex[:12]}",
        plan=plan,
        periodicite=periodicite,
        statut=statut,
        periode_debut=datetime.now(timezone.utc),
        periode_fin=datetime.now(timezone.utc) + timedelta(days=30),
        essai_fin=essai_fin,
    )
    db.add(sub)
    await db.commit()
    return sub


def _capture_checkout(monkeypatch) -> dict:
    captured: dict = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return type("S", (), {"url": "https://checkout.stripe.test/x"})()

    monkeypatch.setattr(sr.stripe.checkout.Session, "create", _fake_create)
    monkeypatch.setattr(sr, "PRICE_MAP", {"standard_monthly": "price_test_standard",
                                          "expert_monthly": "price_test_expert"})
    return captured


# ─────────────────────────────────────────────
# 1. Essai gratuit : une seule fois, carte exigée
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_premier_checkout_sans_essai_et_carte_exigee(db, monkeypatch):
    """Essai gratuit supprimé le 2026-10-04 : même un compte neuf paie dès le
    premier jour ; aucun paramètre d'essai ne part chez Stripe."""
    captured = _capture_checkout(monkeypatch)
    user = await _user(db)

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)

    assert res["essai"] is False
    assert "trial_period_days" not in captured["subscription_data"]
    assert "trial_settings" not in captured["subscription_data"]
    assert captured["payment_method_collection"] == "always"


@pytest.mark.asyncio
async def test_essai_deja_consomme_pas_de_second_essai(db, monkeypatch):
    """Le cœur de l'abus : essai → annulation → nouveau checkout → 7 jours de plus."""
    captured = _capture_checkout(monkeypatch)
    user = await _user(db, essai_utilise_at=datetime.now(timezone.utc) - timedelta(days=30))

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)

    assert res["essai"] is False
    assert "trial_period_days" not in captured["subscription_data"]
    assert "trial_settings" not in captured["subscription_data"]
    assert captured["payment_method_collection"] == "always"


@pytest.mark.asyncio
async def test_webhook_marque_lessai_comme_consomme(db, monkeypatch):
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    user = await _user(db)
    assert user.essai_utilise_at is None

    await sr._handle_subscription_created(
        _sub_stripe("trialing", trial_end=int(time.time()) + 7 * 86400), db)

    await db.refresh(user)
    assert user.essai_utilise_at is not None


@pytest.mark.asyncio
async def test_abonnement_sans_essai_ne_consomme_pas_lessai(db, monkeypatch):
    """Souscrire directement en payant ne doit pas brûler le droit à l'essai."""
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    user = await _user(db)

    await sr._handle_subscription_created(_sub_stripe("active", trial_end=None), db)

    await db.refresh(user)
    assert user.essai_utilise_at is None


# ─────────────────────────────────────────────
# 2. Un seul abonnement par compte
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_meme_formule_deja_active_renvoie_409(db, monkeypatch):
    _capture_checkout(monkeypatch)
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active")

    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(
            sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_standard_vers_expert_modifie_labonnement_sans_en_creer_un_second(db, monkeypatch):
    captured = _capture_checkout(monkeypatch)
    modifs: list[tuple] = []

    monkeypatch.setattr(sr.stripe.Subscription, "retrieve",
                        lambda sid: _sub_stripe("trialing", sub_id=sid))
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda sid, **kw: modifs.append((sid, kw)) or {"status": "trialing"})

    user = await _user(db, plan="standard")
    abo = await _abo(db, user, plan="standard", statut="active", stripe_id="sub_courant")

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)

    # Aucune session Checkout : pas de second abonnement, donc pas de double prélèvement.
    assert captured == {}
    assert res["change_de_plan"] is True
    assert len(modifs) == 1
    sid, kw = modifs[0]
    assert sid == "sub_courant"
    assert kw["items"] == [{"id": "si_test", "price": "price_test_expert"}]
    assert kw["proration_behavior"] == "create_prorations"

    await db.refresh(user)
    await db.refresh(abo)
    assert user.plan == "expert"
    assert abo.plan == "expert"


@pytest.mark.asyncio
async def test_changement_de_plan_ferme_les_doublons_herites(db, monkeypatch):
    """Cas réel du 2026-08-20 : 3 abonnements en essai sur un même compte."""
    _capture_checkout(monkeypatch)
    supprimes: list[str] = []

    monkeypatch.setattr(sr.stripe.Subscription, "retrieve",
                        lambda sid: _sub_stripe("trialing", sub_id=sid))
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda sid, **kw: {"status": "trialing"})
    monkeypatch.setattr(sr.stripe.Subscription, "delete",
                        lambda sid: supprimes.append(sid))

    user = await _user(db, plan="standard")
    essai = datetime.now(timezone.utc) + timedelta(days=6)
    recent = await _abo(db, user, plan="standard", statut="active",
                        stripe_id="sub_recent", essai_fin=essai)
    vieux = await _abo(db, user, plan="standard", statut="active",
                       stripe_id="sub_vieux", essai_fin=essai)
    # `_subs_vivantes` trie par date de création décroissante ; on force l'ordre.
    vieux.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    recent.created_at = datetime.now(timezone.utc)
    await db.commit()

    await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)

    assert supprimes == ["sub_vieux"]
    await db.refresh(vieux)
    assert vieux.statut == "canceled"


# ─────────────────────────────────────────────
# 3. Ne pas rétrograder tant qu'un abonnement court
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fin_dun_abonnement_ne_retrograde_pas_si_un_autre_court(db):
    user = await _user(db, plan="expert")
    await _abo(db, user, plan="expert", statut="active", stripe_id="sub_expert")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_standard")

    await sr._handle_subscription_deleted(
        {"id": "sub_standard", "customer": "cus_test"}, db)

    await db.refresh(user)
    assert user.plan == "expert"


@pytest.mark.asyncio
async def test_fin_du_dernier_abonnement_retrograde_en_free(db):
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_seul")

    await sr._handle_subscription_deleted(
        {"id": "sub_seul", "customer": "cus_test"}, db)

    await db.refresh(user)
    assert user.plan == "free"


# ─────────────────────────────────────────────
# 4. Résiliation : plusieurs abonnements possibles
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resiliation_couvre_tous_les_abonnements(db, monkeypatch):
    """`scalar_one_or_none()` levait MultipleResultsFound, avalé par le `except` :
    le client recevait « demande enregistrée » et RIEN n'était résilié."""
    annules: list[str] = []
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda sid, **kw: annules.append(sid))
    monkeypatch.setattr(sr.settings, "stripe_secret_key", "sk_test", raising=False)

    async def _pas_demail(**kw):
        return None

    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _pas_demail)

    user = await _user(db, plan="expert")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_a")
    await _abo(db, user, plan="expert", statut="active", stripe_id="sub_b")

    res = await sr.cancel_subscription(db, user)

    assert res["via_stripe"] is True
    assert sorted(annules) == ["sub_a", "sub_b"]


# ─────────────────────────────────────────────
# 5. Périodes portées par l'article d'abonnement
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_periode_lue_sur_larticle_quand_absente_de_labonnement(db, monkeypatch):
    """Trois lignes `subscriptions` avaient `periode_debut`/`periode_fin` NULL en
    production : l'API récente porte `current_period_*` sur `items.data[0]`."""
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    user = await _user(db)

    await sr._handle_subscription_created(
        _sub_stripe("trialing", sub_id="sub_item", periode_sur_item=True), db)

    from sqlalchemy import select
    res = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == "sub_item"))
    abo = res.scalar_one()
    assert abo.periode_debut is not None
    assert abo.periode_fin is not None


# ─────────────────────────────────────────────
# 6. Essai sans carte : aucun accès tant que la carte n'est pas là
# ─────────────────────────────────────────────
def _sans_carte(monkeypatch):
    """Aucun moyen de paiement, où que Stripe le cherche."""
    monkeypatch.setattr(sr.stripe.Customer, "retrieve",
                        lambda cid: {"invoice_settings": {}})
    monkeypatch.setattr(sr.stripe.PaymentMethod, "list",
                        lambda **kw: {"data": []})


@pytest.mark.asyncio
async def test_essai_sans_carte_nouvre_aucun_acces(db, monkeypatch):
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    _sans_carte(monkeypatch)
    user = await _user(db)

    await sr._handle_subscription_created(
        _sub_stripe("trialing", sub_id="sub_bloque",
                    trial_end=int(time.time()) + 7 * 86400), db)

    await db.refresh(user)
    assert user.plan == "free"
    # L'essai est tout de même consommé : il a bien été ouvert.
    assert user.essai_utilise_at is not None

    from sqlalchemy import select
    abo = (await db.execute(select(Subscription).where(
        Subscription.stripe_subscription_id == "sub_bloque"))).scalar_one()
    assert abo.statut == sr.STATUT_SANS_CARTE


@pytest.mark.asyncio
async def test_essai_avec_carte_ouvre_lacces(db, monkeypatch):
    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    user = await _user(db)

    sub = _sub_stripe("trialing", trial_end=int(time.time()) + 7 * 86400)
    sub["default_payment_method"] = "pm_test"
    await sr._handle_subscription_created(sub, db)

    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_carte_ajoutee_debloque_lacces(db, monkeypatch):
    """Stripe n'émet PAS `subscription.updated` quand une carte est attachée au
    client : sans traitement dédié, l'abonné qui régularise resterait bloqué."""
    user = await _user(db, plan="free")
    abo = await _abo(db, user, plan="expert", statut=sr.STATUT_SANS_CARTE,
                     stripe_id="sub_bloque",
                     essai_fin=datetime.now(timezone.utc) + timedelta(days=5))

    sub = _sub_stripe("trialing", price_id="price_test_expert", sub_id="sub_bloque")
    sub["default_payment_method"] = "pm_test"
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid: sub)

    await sr._handle_moyen_paiement_ajoute({"customer": "cus_test"}, db)

    await db.refresh(user)
    await db.refresh(abo)
    assert abo.statut == "active"
    assert user.plan == "expert"


@pytest.mark.asyncio
async def test_essai_bloque_ne_compte_pas_pour_lacces(db, monkeypatch):
    """`_plan_effectif` ne doit jamais accorder un plan sur un essai sans carte."""
    user = await _user(db, plan="free")
    await _abo(db, user, plan="expert", statut=sr.STATUT_SANS_CARTE, stripe_id="sub_x")

    assert await sr._plan_effectif(user.user_id, db) == "free"


@pytest.mark.asyncio
async def test_essai_bloque_empeche_douvrir_un_second_abonnement(db, monkeypatch):
    """Bloqué ne veut pas dire libre : il ne doit pas pouvoir repartir sur un
    nouvel abonnement pour contourner le blocage."""
    _capture_checkout(monkeypatch)
    user = await _user(db, plan="free")
    await _abo(db, user, plan="standard", statut=sr.STATUT_SANS_CARTE, stripe_id="sub_y")

    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(
            sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)
    assert exc.value.status_code == 409


# ─────────────────────────────────────────────
# 7. Journal des mouvements
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ouverture_dessai_est_journalisee(db, monkeypatch):
    from db.models import SubscriptionEvent
    from sqlalchemy import select

    monkeypatch.setattr(sr, "PLAN_FROM_PRICE", {"price_test_standard": "standard"})
    _sans_carte(monkeypatch)
    user = await _user(db)

    await sr._handle_subscription_created(
        _sub_stripe("trialing", trial_end=int(time.time()) + 7 * 86400), db)

    events = (await db.execute(select(SubscriptionEvent))).scalars().all()
    assert [e.type for e in events] == ["essai_sans_carte"]
    assert events[0].email == user.email
    assert events[0].pendant_essai is True


@pytest.mark.asyncio
async def test_essai_perdu_et_resiliation_ne_sont_pas_le_meme_mouvement(db, monkeypatch):
    """Un essai qui meurt faute de carte n'est pas un client qui part : les
    confondre fausserait le churn."""
    from db.models import SubscriptionEvent
    from sqlalchemy import select

    user = await _user(db, plan="free")
    await _abo(db, user, plan="standard", statut=sr.STATUT_SANS_CARTE, stripe_id="sub_perdu")
    await sr._handle_subscription_deleted({"id": "sub_perdu", "customer": "cus_test"}, db)

    autre = await _user(db, plan="expert", email="paye@blackturf.fr",
                        stripe_customer_id="cus_paye")
    await _abo(db, autre, plan="expert", statut="active", stripe_id="sub_paye")
    await sr._handle_subscription_deleted({"id": "sub_paye", "customer": "cus_paye"}, db)

    types = {e.email: e.type for e in
             (await db.execute(select(SubscriptionEvent))).scalars().all()}
    assert types[user.email] == "essai_termine_sans_carte"
    assert types["paye@blackturf.fr"] == "resilie"


# ─────────────────────────────────────────────
# 8. Le blocage doit être EXPLIQUÉ à l'abonné
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_auth_me_signale_lessai_bloque(client, db, auth_headers):
    """Bloquer sans le dire produit un abonné qui croit à une panne. `/auth/me`
    porte donc le signal qui déclenche le bandeau « enregistrez votre carte »."""
    from sqlalchemy import select

    avant = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert avant.json()["essai_bloque_sans_carte"] is False

    user = (await db.execute(
        select(User).where(User.email == "test@blackturf.fr"))).scalar_one()
    fin = datetime.now(timezone.utc) + timedelta(days=5)
    await _abo(db, user, plan="expert", statut=sr.STATUT_SANS_CARTE,
               stripe_id="sub_bloque_me", essai_fin=fin)

    apres = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert apres["essai_bloque_sans_carte"] is True
    assert apres["essai_fin"] is not None


# ─────────────────────────────────────────────
# 4. Changement de formule (2026-09-29) : jamais en un clic, hausse payée tout
#    de suite, impayé d'abord réglé.
# ─────────────────────────────────────────────
def _stripe_changement(monkeypatch, status="active", prorata_lines=(), modify_ret=None):
    appels: list[tuple] = []
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve",
                        lambda sid: _sub_stripe(status, sub_id=sid))
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda sid, **kw: appels.append((sid, kw)) or (modify_ret or {"status": status}))
    monkeypatch.setattr(sr.stripe.Price, "retrieve", lambda pid: {"unit_amount": 1900 if "expert" in pid else 1200})
    monkeypatch.setattr(sr.stripe.Invoice, "upcoming", lambda **kw: {"lines": {"data": [
        {"amount": a, "proration": True} for a in prorata_lines] + [{"amount": 1900, "proration": False}]}})
    return appels


@pytest.mark.asyncio
async def test_sans_confirmation_rien_ne_change_et_un_apercu_chiffre_est_rendu(db, monkeypatch):
    _capture_checkout(monkeypatch)
    appels = _stripe_changement(monkeypatch, prorata_lines=(-600, 950))
    user = await _user(db, plan="standard")
    abo = await _abo(db, user, plan="standard", statut="active", stripe_id="sub_c")

    res = await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)

    assert res["confirmation_requise"] is True
    ap = res["apercu"]
    assert ap["sens"] == "hausse" and ap["montant_immediat_cents"] == 350
    assert "3,50 €" in ap["message"] and "aujourd'hui" in ap["message"]
    assert appels == []  # aucune modification chez Stripe
    await db.refresh(abo)
    await db.refresh(user)
    assert abo.plan == "standard" and user.plan == "standard"


@pytest.mark.asyncio
async def test_hausse_en_periode_payee_encaisse_la_difference_tout_de_suite(db, monkeypatch):
    _capture_checkout(monkeypatch)
    appels = _stripe_changement(monkeypatch)
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_c")

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)

    kw = appels[0][1]
    assert kw["proration_behavior"] == "always_invoice"
    assert kw["payment_behavior"] == "pending_if_incomplete"
    assert "metadata" not in kw  # refusé par Stripe avec pending_if_incomplete
    assert res["change_de_plan"] is True
    await db.refresh(user)
    assert user.plan == "expert"


@pytest.mark.asyncio
async def test_hausse_paiement_non_abouti_ne_donne_pas_expert(db, monkeypatch):
    _capture_checkout(monkeypatch)
    _stripe_changement(monkeypatch, modify_ret={
        "status": "active", "pending_update": {"subscription_items": []},
        "latest_invoice": {"hosted_invoice_url": "https://invoice.stripe.test/x"}})
    user = await _user(db, plan="standard")
    abo = await _abo(db, user, plan="standard", statut="active", stripe_id="sub_c")

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)

    assert res["paiement_requis"] is True and res["url"] == "https://invoice.stripe.test/x"
    await db.refresh(abo)
    await db.refresh(user)
    assert abo.plan == "standard" and user.plan == "standard"


@pytest.mark.asyncio
async def test_baisse_credit_reporte_sur_la_prochaine_facture(db, monkeypatch):
    _capture_checkout(monkeypatch)
    appels = _stripe_changement(monkeypatch, prorata_lines=(-1900, 1200))
    user = await _user(db, plan="expert")
    await _abo(db, user, plan="expert", statut="active", stripe_id="sub_c")

    ap = (await sr.create_checkout(sr.CheckoutRequest(plan="standard", periodicite="monthly"),
                                   db, user))["apercu"]
    assert ap["sens"] == "baisse" and ap["ajustement_prochaine_facture_cents"] == -700
    assert "7 €" in ap["message"]

    await sr.create_checkout(
        sr.CheckoutRequest(plan="standard", periodicite="monthly", confirmer=True), db, user)
    assert appels[0][1]["proration_behavior"] == "create_prorations"
    await db.refresh(user)
    assert user.plan == "standard"


@pytest.mark.asyncio
async def test_changement_refuse_tant_qu_un_prelevement_est_impaye(db, monkeypatch):
    _capture_checkout(monkeypatch)
    appels = _stripe_changement(monkeypatch, status="past_due")
    user = await _user(db, plan="free")
    await _abo(db, user, plan="expert", statut="past_due", stripe_id="sub_c")

    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(
            sr.CheckoutRequest(plan="standard", periodicite="monthly", confirmer=True), db, user)
    assert exc.value.status_code == 409 and "attente" in exc.value.detail
    assert appels == []


@pytest.mark.asyncio
async def test_changement_pendant_l_essai_ne_preleve_rien(db, monkeypatch):
    _capture_checkout(monkeypatch)
    appels = _stripe_changement(monkeypatch, status="trialing")
    user = await _user(db, plan="standard")
    await _abo(db, user, plan="standard", statut="active", stripe_id="sub_c",
               essai_fin=datetime.now(timezone.utc) + timedelta(days=5))

    ap = (await sr.create_checkout(sr.CheckoutRequest(plan="expert", periodicite="monthly"),
                                   db, user))["apercu"]
    assert ap["en_essai"] is True and "Aucun prélèvement" in ap["message"]
    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly", confirmer=True), db, user)
    assert appels[0][1]["proration_behavior"] == "create_prorations"
    assert "essai=1" in res["url"]
