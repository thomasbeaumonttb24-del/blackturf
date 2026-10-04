"""Plafond mensuel des crédits de parrainage, et ce que le parrain paie vraiment.

Règle (exploitant, 2026-09-27) : les crédits d'un mois ne dépassent pas ce qu'il
faut pour rendre la mensualité gratuite — 4 en Expert (19 €), 3 en Standard
(12 €). Au-delà, le crédit est gagné mais reporté au mois suivant.

La facturation est simulée avec la règle de Stripe sur le solde client : le
crédit s'impute sur la facture jusqu'à 0 €, jamais en dessous, et le reste
demeure sur le solde pour la facture suivante.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import api.routes.stripe_routes as sr
from db.models import Subscription, User
from services import parrainage as P


class Stripe:
    def __init__(self, monkeypatch):
        self.soldes: list[dict] = []
        monkeypatch.setattr(P.settings, "stripe_secret_key", "sk_test")

        class _Liste(list):
            def auto_paging_iter(self):
                return iter(self)

        def _balance(customer, **kw):
            self.soldes.append({"customer": customer, **kw})
            return {"id": f"cbtxn_{len(self.soldes)}"}

        monkeypatch.setattr(P.stripe.Customer, "create_balance_transaction", _balance)
        monkeypatch.setattr(P.stripe.Customer, "list_balance_transactions", lambda c, **kw: _Liste(
            {"id": f"cbtxn_{i + 1}", "metadata": s.get("metadata")}
            for i, s in enumerate(self.soldes) if s["customer"] == c))
        monkeypatch.setattr(P.stripe.Customer, "retrieve", lambda cid: {"balance": self.solde(cid)})
        monkeypatch.setattr(P.stripe.Customer, "create", lambda **kw: {"id": f"cus_{kw['metadata']['user_id'][:8]}"})
        monkeypatch.setattr(P.stripe.Invoice, "create_preview",
                            lambda **kw: (_ for _ in ()).throw(P.stripe.error.InvalidRequestError("x", None)))
        monkeypatch.setattr(sr, "_cartes_du_client", lambda sub: [
            {"empreinte": f"fp_{sub.get('customer')}", "pm": "pm", "marque": "visa",
             "dernier4": "4242", "financement": "debit"}])

    def solde(self, customer: str) -> int:
        return sum(s["amount"] for s in self.soldes if s["customer"] == customer)

    def facturer(self, customer: str, prix_cents: int) -> int:
        """Ce que Stripe prélève sur une facture de `prix_cents`, solde imputé."""
        credit = max(0, -self.solde(customer))
        impute = min(credit, prix_cents)
        if impute:
            self.soldes.append({"customer": customer, "amount": impute, "metadata": {"facture": True}})
        return prix_cents - impute


async def _parrain(db, plan: str | None, periodicite="monthly") -> User:
    u = User(user_id=str(uuid.uuid4()), email=f"p{uuid.uuid4().hex[:6]}@blackturf.fr", prenom="Paul",
             plan=plan or "free", email_verified=True, stripe_customer_id=f"cus_p{uuid.uuid4().hex[:6]}")
    db.add(u)
    await db.commit()
    if plan:
        db.add(Subscription(sub_id=str(uuid.uuid4()), user_id=u.user_id, stripe_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
                            plan=plan, periodicite=periodicite, statut="active",
                            periode_debut=datetime.now(timezone.utc) - timedelta(days=10),
                            periode_fin=datetime.now(timezone.utc) + timedelta(days=20)))
        await db.commit()
    return u


async def _filleuls_qui_paient(db, parrain: User, n: int) -> list:
    code = await P.code_de(parrain, db)
    liens = []
    for i in range(n):
        f = User(user_id=str(uuid.uuid4()), email=f"f{uuid.uuid4().hex[:6]}@blackturf.fr", prenom=f"Ami{i}",
                 plan="free", email_verified=True, stripe_customer_id=f"cus_f{uuid.uuid4().hex[:6]}")
        db.add(f)
        await db.flush()
        liens.append(await P.rattacher_filleul(f, code, db))
        await db.commit()
        await sr._handle_payment_succeeded(
            {"id": f"in_{i}_{f.user_id[:4]}", "customer": f.stripe_customer_id, "amount_paid": 1400, "total": 1400, "charge": f"ch_{i}"}, db)
    return liens


async def _nouveau_mois(db, parrain: User):
    """Renouvellement : Stripe fait démarrer une nouvelle période."""
    sub = (await sr._subs_vivantes(parrain.user_id, db))[0]
    sub.periode_debut = datetime.now(timezone.utc) + timedelta(seconds=1)
    sub.periode_fin = sub.periode_debut + timedelta(days=30)
    await db.commit()


# ─── Les exemples de l'exploitant ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_expert_3_filleuls_paie_4_euros(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    await _filleuls_qui_paient(db, paul, 3)
    assert s.solde(paul.stripe_customer_id) == -1500
    assert s.facturer(paul.stripe_customer_id, 1900) == 400  # 19 € − 15 € = 4 €


@pytest.mark.asyncio
async def test_expert_4_filleuls_mois_gratuit(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    await _filleuls_qui_paient(db, paul, 4)
    assert s.facturer(paul.stripe_customer_id, 1900) == 0  # aucun prélèvement
    # 20 € − 19 € : 1 € reste au crédit, déduit le mois suivant.
    assert s.solde(paul.stripe_customer_id) == -100
    assert s.facturer(paul.stripe_customer_id, 1900) == 1800


@pytest.mark.asyncio
async def test_standard_3_filleuls_mois_gratuit(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "standard")
    await _filleuls_qui_paient(db, paul, 3)
    assert s.facturer(paul.stripe_customer_id, 1200) == 0
    assert s.solde(paul.stripe_customer_id) == -300


# ─── Plafond et report ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_expert_plafond_4_le_reste_reporte_au_mois_suivant(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    liens = await _filleuls_qui_paient(db, paul, 6)

    # Ce mois : 4 crédits posés (mois gratuit), 2 gagnés mais reportés.
    assert s.solde(paul.stripe_customer_id) == -2000
    assert [bool(l.credit_pose_at) for l in liens] == [True] * 4 + [False] * 2
    assert all(l.statut == "valide" and l.motif == "plafond_atteint" for l in liens[4:])
    resume = await P.resume(paul, db)
    assert resume["mois"]["plafond"] == 4 and resume["mois"]["poses"] == 4 and resume["mois"]["reportes"] == 2
    assert resume["gagne_cents"] == 3000  # tout est gagné, même reporté
    assert [f["etape"] for f in resume["filleuls"]].count("reporte") == 2

    # Échéance : facture couverte (0 €), Stripe l'émet quand même → nouveau mois.
    assert s.facturer(paul.stripe_customer_id, 1900) == 0
    await _nouveau_mois(db, paul)
    await sr._handle_payment_succeeded(
        {"id": "in_paul_2", "customer": paul.stripe_customer_id, "amount_paid": 0, "total": 1900}, db)

    # Les 2 reportés sont posés : 1 € restant + 10 € → mois suivant à 8 €.
    assert all(l.credit_pose_at for l in liens)
    assert s.facturer(paul.stripe_customer_id, 1900) == 800


@pytest.mark.asyncio
async def test_standard_plafond_3(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "standard")
    liens = await _filleuls_qui_paient(db, paul, 4)
    assert s.solde(paul.stripe_customer_id) == -1500
    assert liens[3].credit_pose_at is None
    assert (await P.resume(paul, db))["mois"]["plafond"] == 3


@pytest.mark.asyncio
async def test_parrain_gratuit_plafond_4_par_mois_civil(db, monkeypatch):
    s = Stripe(monkeypatch)
    zoe = await _parrain(db, None)
    await _filleuls_qui_paient(db, zoe, 5)
    assert s.solde(zoe.stripe_customer_id) == -2000
    mois = (await P.resume(zoe, db))["mois"]
    assert mois["plafond"] == 4 and mois["debut"].day == 1 and mois["reportes"] == 1


@pytest.mark.asyncio
async def test_tache_quotidienne_pose_les_reportes(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    liens = await _filleuls_qui_paient(db, paul, 5)
    assert liens[4].credit_pose_at is None
    assert await P.liberer_tous_les_credits(db) == 0  # même mois : rien
    await _nouveau_mois(db, paul)
    assert await P.liberer_tous_les_credits(db) == 1
    assert s.solde(paul.stripe_customer_id) == -2500


@pytest.mark.asyncio
async def test_remboursement_dun_credit_reporte(db, monkeypatch):
    """Crédit jamais posé : annulé sans rien reprendre chez Stripe."""
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    liens = await _filleuls_qui_paient(db, paul, 5)
    avant = list(s.soldes)
    await P.sur_remboursement({"id": "ch", "invoice": liens[4].stripe_invoice_id}, db, "paiement_rembourse")
    assert liens[4].statut == "annule" and s.soldes == avant


@pytest.mark.asyncio
async def test_remboursement_libere_une_place_du_mois(db, monkeypatch):
    s = Stripe(monkeypatch)
    paul = await _parrain(db, "expert")
    liens = await _filleuls_qui_paient(db, paul, 5)
    await P.sur_remboursement({"id": "ch", "invoice": liens[0].stripe_invoice_id}, db, "paiement_rembourse")
    await P.liberer_credits(paul, db)
    # 4 posés − 1 repris + le reporté posé à sa place : toujours 20 € au plus ce mois.
    assert liens[4].credit_pose_at is not None
    assert s.solde(paul.stripe_customer_id) == -2000


@pytest.mark.asyncio
async def test_email_du_credit_reporte():
    from services.email_compte import parrainage_credite
    _, texte = parrainage_credite("Paul", "Léa", "https://x", "reporte")
    assert "plafond" in texte and "mois suivant" in texte and "perdu" in texte
