"""Un paiement refusé ne doit jamais enfermer l'abonné.

Impasse constatée en production le 2026-09-03 sur deux abonnés à 19 €/mois,
tous deux refusés par leur banque au premier prélèvement d'après essai
(`insufficient_funds` sur une carte prépayée, `try_again_later` sur une carte de
débit). Aucune de ces trois pièces n'est fautive isolément ; c'est leur
assemblage qui ferme toutes les portes :

1. `_handle_payment_failed` rétrograde le compte en `free` (décision assumée du
   2026-08-27 : la fenêtre de relance de Stripe dure jusqu'à trois semaines, et
   `past_due` ne doit plus donner accès) ;
2. la page profil décidait d'après le seul `plan` — passée en `free`, elle
   masquait « Gérer l'abonnement via Stripe », SEUL chemin pour changer de carte ;
3. `/stripe/checkout` refuse un second abonnement tant que le premier vit, et
   `past_due` compte parmi `STATUTS_VIVANTS` — donc 409, avec un message qui
   renvoie « depuis votre profil », vers le bouton qu'on venait de cacher.

L'abonné perdait l'accès sans un mot et sans porte de sortie, pendant que Stripe
continuait de relancer sa carte. L'invariant posé ici : **si le checkout refuse
parce qu'un abonnement vit encore, alors `/auth/me` doit déclarer cet abonnement
pilotable.** Les deux moitiés ne peuvent plus diverger sans devenir rouges.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import api.routes.stripe_routes as sr
from db.models import Subscription, User
from tests._descripteurs_deploiement import RACINE, exiger

PAGE_PROFIL = RACINE / "frontend" / "src" / "app" / "(main)" / "profil" / "page.tsx"
LAYOUT_PRINCIPAL = RACINE / "frontend" / "src" / "app" / "(main)" / "layout.tsx"
BANDEAU = RACINE / "frontend" / "src" / "components" / "layout" / "PaiementEchoueBanner.tsx"


async def _abo(db, user: User, *, statut: str, plan: str = "expert",
               stripe_id: str | None = None) -> Subscription:
    sub = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=stripe_id or f"sub_{uuid.uuid4().hex[:12]}",
        plan=plan,
        periodicite="monthly",
        statut=statut,
        periode_debut=datetime.now(timezone.utc),
        periode_fin=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()
    return sub


async def _utilisateur_de_test(db) -> User:
    return (await db.execute(
        select(User).where(User.email == "test@blackturf.fr"))).scalar_one()


# ─────────────────────────────────────────────
# 1. L'API dit ce qui reste pilotable
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_auth_me_declare_labonnement_pilotable_malgre_le_plan_free(
        client, db, auth_headers):
    """Le compte est retombé en `free`, l'abonnement Stripe vit toujours."""
    avant = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    # Témoin : sans lui, un champ codé en dur à True passerait le test.
    assert avant["abonnement_gerable"] is False
    assert avant["paiement_en_echec"] is False

    user = await _utilisateur_de_test(db)
    user.plan = "free"          # ce que fait `_handle_payment_failed`
    await db.commit()
    await _abo(db, user, statut="past_due")

    apres = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert apres["plan"] == "free", "le compte est bien rétrogradé"
    assert apres["abonnement_gerable"] is True, (
        "L'abonnement Stripe vit encore : sans ce signal, la page profil masque "
        "le portail et l'abonné n'a plus aucun moyen de changer de carte."
    )
    assert apres["paiement_en_echec"] is True


@pytest.mark.asyncio
async def test_essai_sans_carte_nest_pas_un_abonnement_pilotable(
        client, db, auth_headers):
    """`essai_sans_carte` est un statut maison : il n'y a pas encore de carte, le
    portail Stripe n'aurait rien à montrer. Son propre bandeau le couvre déjà."""
    user = await _utilisateur_de_test(db)
    user.plan = "free"
    await db.commit()
    await _abo(db, user, statut=sr.STATUT_SANS_CARTE)

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["abonnement_gerable"] is False
    assert me["paiement_en_echec"] is False
    assert me["essai_bloque_sans_carte"] is True


# ─────────────────────────────────────────────
# 2. L'invariant : refuser le checkout OBLIGE à offrir le portail
# ─────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("statut", [s for s in sr.STATUTS_VIVANTS
                                    if s != sr.STATUT_SANS_CARTE])
async def test_tout_statut_qui_bloque_le_checkout_reste_pilotable(
        client, db, auth_headers, monkeypatch, statut):
    """Pour CHAQUE statut qui fait refuser un nouvel abonnement, `/auth/me` doit
    déclarer l'abonnement pilotable. C'est exactement la paire qui manquait :
    porte d'entrée fermée, porte de sortie cachée.

    Paramétré sur `STATUTS_VIVANTS` : ajouter demain un statut à la liste sans
    l'ouvrir au portail rend ce test rouge tout seul.
    """
    monkeypatch.setattr(sr, "PRICE_MAP", {"expert_monthly": "price_test_expert"})
    user = await _utilisateur_de_test(db)
    user.plan = "free"
    await db.commit()
    await _abo(db, user, statut=statut, plan="expert")

    with pytest.raises(HTTPException) as exc:
        await sr.create_checkout(
            sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)
    assert exc.value.status_code == 409, (
        f"statut {statut!r} : le checkout devait refuser un second abonnement"
    )

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["abonnement_gerable"] is True, (
        f"statut {statut!r} : le checkout refuse (409) MAIS l'abonnement n'est "
        "pas déclaré pilotable. C'est l'impasse du 2026-09-03 — l'abonné ne peut "
        "ni se réabonner, ni changer sa carte."
    )


@pytest.mark.asyncio
async def test_sans_abonnement_le_checkout_passe_et_rien_nest_pilotable(
        client, db, auth_headers, monkeypatch):
    """Témoin négatif du test précédent : sans abonnement vivant, le checkout ne
    refuse PAS — donc le 409 ci-dessus prouve bien quelque chose."""
    monkeypatch.setattr(sr, "PRICE_MAP", {"expert_monthly": "price_test_expert"})
    monkeypatch.setattr(sr.stripe.checkout.Session, "create",
                        lambda **kw: type("S", (), {"url": "https://x.test"})())
    user = await _utilisateur_de_test(db)
    # Client Stripe déjà connu : sinon le checkout appelle `Customer.create`,
    # qui part vraiment sur le réseau et échoue en AuthenticationError.
    user.stripe_customer_id = "cus_test"
    await db.commit()

    await sr.create_checkout(
        sr.CheckoutRequest(plan="expert", periodicite="monthly"), db, user)

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["abonnement_gerable"] is False


# ─────────────────────────────────────────────
# 3. Le frontend ne doit plus décider d'après le plan
# ─────────────────────────────────────────────
def test_la_page_profil_ne_gate_plus_le_portail_sur_le_seul_plan():
    """`isFree ? offre : portail` est la ligne qui a fait disparaître le bouton.
    Le portail doit dépendre de l'existence d'un abonnement."""
    source = exiger(PAGE_PROFIL)
    assert "abonnement_gerable" in source, (
        "La page profil n'utilise pas `abonnement_gerable` : elle redécide donc "
        "d'après `plan`, et le bouton « Gérer l'abonnement via Stripe » "
        "disparaît dès qu'un paiement échoue."
    )
    # `isFree` reste légitime ailleurs (griser les fonctions d'une formule
    # supérieure). Ce qui est interdit, c'est de trancher le CTA — offre d'un
    # côté, portail de l'autre — sur le seul plan. Le garde porte donc sur la
    # condition corrigée, pas sur toute mention d'`isFree`.
    assert re.search(r"isFree\s*&&\s*!\s*abonnementGerable", source), (
        "Le CTA de la page profil ne croise plus `isFree` avec l'existence d'un "
        "abonnement : un abonné en échec de paiement est en `free` tout en "
        "gardant un abonnement vivant, et se retrouve devant « Voir les offres » "
        "alors que le checkout lui répondra 409."
    )


def test_le_bandeau_dexplication_est_monte_dans_le_layout():
    """Un accès coupé sans un mot se lit comme une panne, et l'abonné écrit au
    support au lieu d'aller changer sa carte."""
    layout = exiger(LAYOUT_PRINCIPAL)
    bandeau = exiger(BANDEAU)
    assert "PaiementEchoueBanner" in layout, (
        "Le bandeau d'échec de paiement n'est pas monté : la coupure reste muette."
    )
    assert "paiement_en_echec" in bandeau
    assert "/stripe/portal" in bandeau, (
        "Le bandeau doit mener au portail Stripe — l'application ne touche "
        "jamais aux données bancaires, c'est le seul endroit où saisir une carte."
    )
