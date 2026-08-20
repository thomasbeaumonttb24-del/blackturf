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
async def test_premier_checkout_accorde_lessai_et_exige_la_carte(db, monkeypatch):
    captured = _capture_checkout(monkeypatch)
    user = await _user(db)

    res = await sr.create_checkout(
        sr.CheckoutRequest(plan="standard", periodicite="monthly"), db, user)

    assert res["essai"] is True
    assert captured["subscription_data"]["trial_period_days"] == 7
    # Décision produit du 2026-08-20 : la carte est exigée dès l'ouverture de l'essai.
    assert captured["payment_method_collection"] == "always"
    assert (captured["subscription_data"]["trial_settings"]["end_behavior"]
            ["missing_payment_method"]) == "cancel"


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
        sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)

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
        sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)

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
