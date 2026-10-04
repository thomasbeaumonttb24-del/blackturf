"""Catalogue Stripe de BlackTurf : produits des passes + événements du webhook.

Idempotent (lookup_keys Stripe) et PRUDENT, car il tourne aussi sur le compte
LIVE :
  · par défaut, il ne crée QUE les produits/prix des passes sans renouvellement
    et AJOUTE au webhook les événements que le code traite — il n'en retire
    jamais (le webhook live en porte que ce script ne connaissait pas) ;
  · les prix d'abonnement (Standard / Expert) ne sont touchés qu'avec
    `--abonnements` : l'ancienne version créait de nouveaux prix et DÉSACTIVAIT
    ceux que l'API utilise (STRIPE_PRICE_*) dès que leurs lookup_keys
    différaient — tous les checkouts d'abonnement seraient tombés ;
  · `--verifier` lit sans rien écrire.

Clé : variable d'environnement STRIPE_SECRET_KEY (dans le conteneur api), à
défaut le .env à la racine. La clé n'est jamais affichée ; seul le mode
(TEST / LIVE) l'est.

    python scripts/setup_stripe_catalog.py --verifier
    python scripts/setup_stripe_catalog.py
"""
import argparse
import os
import sys
from pathlib import Path

import stripe

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.passes_catalogue import PASSES, lookup_key as lookup_key_pass  # noqa: E402

PLANS = {
    "standard_monthly": ("BlackTurf Standard", 1200, "month"),
    "standard_annual": ("BlackTurf Standard", 11520, "year"),
    "expert_monthly": ("BlackTurf Expert", 1900, "month"),
    "expert_annual": ("BlackTurf Expert", 18240, "year"),
}

WEBHOOK_URL = "https://api.blackturf.fr/api/v1/stripe/webhook"
# Tous les événements traités par stripe_routes._traiter_evenement.
WEBHOOK_EVENTS = [
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.trial_will_end",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "payment_method.attached",
    "customer.updated",
    "setup_intent.succeeded",
    # Passes sans renouvellement (paiement unique) : octroi, puis retrait sur
    # remboursement ou contestation.
    "checkout.session.completed",
    "charge.refunded",
    "charge.dispute.created",
]


def read_secret() -> str:
    if os.environ.get("STRIPE_SECRET_KEY"):
        return os.environ["STRIPE_SECRET_KEY"].strip()
    env_file = ROOT / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("STRIPE_SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("STRIPE_SECRET_KEY absente (environnement et .env)")


def _produit(nom: str, description: str, ecrire: bool):
    trouves = stripe.Product.search(query=f"name:'{nom}' AND active:'true'", limit=1).data
    if trouves:
        return trouves[0]
    if not ecrire:
        return None
    return stripe.Product.create(name=nom, description=description,
                                 metadata={"app": "blackturf"})


def passes(ecrire: bool) -> bool:
    ok = True
    for duree, (montant, _delta, libelle) in PASSES.items():
        cle = lookup_key_pass(duree)
        existants = stripe.Price.list(lookup_keys=[cle], active=True, limit=1).data
        if existants:
            p = existants[0]
            conforme = (p.unit_amount == montant and p.currency == "eur" and not p.recurring)
            print(f"pass_{duree}: {p.id} {'OK' if conforme else 'NON CONFORME'} ({p.unit_amount} {p.currency})")
            ok &= conforme
            continue
        if not ecrire:
            print(f"pass_{duree}: ABSENT ({cle})")
            ok = False
            continue
        nom = f"BlackTurf {libelle.split(' — ')[0]}"
        produit = _produit(nom, libelle + ". Paiement unique, sans renouvellement.", ecrire)
        p = stripe.Price.create(
            product=produit.id, currency="eur", unit_amount=montant, lookup_key=cle,
            metadata={"app": "blackturf", "pass": duree},
        )
        print(f"pass_{duree}: {p.id} CRÉÉ")
    return ok


def abonnements(ecrire: bool) -> None:
    for cle_plan, (nom, montant, intervalle) in PLANS.items():
        cle = f"blackturf_{cle_plan}_{montant}"
        existants = stripe.Price.list(lookup_keys=[cle], active=True, limit=1).data
        if existants:
            print(f"{cle_plan}={existants[0].id}")
            continue
        if not ecrire:
            print(f"{cle_plan}: ABSENT ({cle})")
            continue
        produit = _produit(nom, nom, ecrire)
        p = stripe.Price.create(product=produit.id, currency="eur", unit_amount=montant,
                                recurring={"interval": intervalle}, lookup_key=cle,
                                metadata={"app": "blackturf", "plan": cle_plan})
        print(f"{cle_plan}={p.id} CRÉÉ — à reporter dans STRIPE_PRICE_* AVANT de désactiver l'ancien")


def webhook(ecrire: bool) -> bool:
    endpoint = next((e for e in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter()
                     if e.url == WEBHOOK_URL), None)
    if endpoint is None:
        print("webhook: ABSENT")
        if not ecrire:
            return False
        endpoint = stripe.WebhookEndpoint.create(url=WEBHOOK_URL, enabled_events=WEBHOOK_EVENTS,
                                                 description="BlackTurf")
        print(f"webhook: CRÉÉ — secret à poser dans STRIPE_WEBHOOK_SECRET : {endpoint.secret}")
        return True
    actuels = set(endpoint.enabled_events)
    manquants = [e for e in WEBHOOK_EVENTS if e not in actuels and "*" not in actuels]
    if not manquants:
        print(f"webhook: {endpoint.id} OK ({endpoint.status}, {len(actuels)} événements)")
        return endpoint.status == "enabled"
    print(f"webhook: {endpoint.id} manque {manquants}")
    if not ecrire:
        return False
    # UNION : on ajoute, on ne retire jamais.
    stripe.WebhookEndpoint.modify(endpoint.id, enabled_events=sorted(actuels | set(manquants)))
    print("webhook: événements ajoutés (aucun retiré)")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true", help="lecture seule")
    ap.add_argument("--abonnements", action="store_true", help="inclure les prix d'abonnement")
    args = ap.parse_args()
    cle = read_secret()
    stripe.api_key = cle
    print("mode:", "LIVE" if cle.startswith(("sk_live", "rk_live")) else "TEST")
    ecrire = not args.verifier
    ok = passes(ecrire)
    if args.abonnements:
        abonnements(ecrire)
    ok &= webhook(ecrire)
    if args.verifier and not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
