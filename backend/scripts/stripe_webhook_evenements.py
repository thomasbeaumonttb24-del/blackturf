"""stripe_webhook_evenements.py — abonne le webhook Stripe aux événements utiles.

Lancé à chaque déploiement (cf. .github/workflows/deploy.yml), avec la clé
Stripe du serveur : personne n'a à cocher des cases dans le tableau de bord.

N'AJOUTE que les événements manquants, ne retire jamais rien, ne touche qu'au
point de terminaison qui pointe sur notre route `/api/v1/stripe/webhook`.
Idempotent : sans rien à ajouter, aucun appel d'écriture. Sort toujours en 0 —
un Stripe injoignable ne doit pas faire échouer un déploiement.

    python scripts/stripe_webhook_evenements.py            # applique
    python scripts/stripe_webhook_evenements.py --verifier # affiche seulement
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import stripe  # noqa: E402

from api.config import get_settings  # noqa: E402

ROUTE = "/api/v1/stripe/webhook"

# Événements traités par `stripe_webhook` (api/routes/stripe_routes.py).
# `charge.refunded` / `charge.dispute.created` : reprise du crédit de parrainage.
EVENEMENTS = [
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
    "charge.refunded",
    "charge.dispute.created",
]


def synchroniser(verifier: bool = False) -> list[dict]:
    """Renvoie, par point de terminaison concerné, ce qui manquait et ce qui a été fait."""
    bilan = []
    for point in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if ROUTE not in (point.get("url") or ""):
            continue
        actuels = list(point.get("enabled_events") or [])
        if "*" in actuels:
            bilan.append({"id": point["id"], "url": point["url"], "manquants": [], "action": "tous les événements déjà reçus"})
            continue
        manquants = [e for e in EVENEMENTS if e not in actuels]
        action = "rien à faire"
        if manquants and not verifier:
            stripe.WebhookEndpoint.modify(point["id"], enabled_events=actuels + manquants)
            action = "ajoutés"
        elif manquants:
            action = "à ajouter"
        bilan.append({"id": point["id"], "url": point["url"], "manquants": manquants, "action": action})
    return bilan


def main() -> int:
    settings = get_settings()
    if not settings.stripe_secret_key:
        print("stripe_webhook_evenements : pas de clé Stripe, rien à faire")
        return 0
    stripe.api_key = settings.stripe_secret_key
    try:
        bilan = synchroniser(verifier="--verifier" in sys.argv)
    except Exception as e:  # noqa: BLE001
        print(f"::warning::stripe_webhook_evenements : Stripe injoignable ({str(e)[:150]})")
        return 0
    if not bilan:
        print(f"::warning::stripe_webhook_evenements : aucun webhook Stripe ne pointe sur {ROUTE}")
    for ligne in bilan:
        print(f"stripe_webhook_evenements : {ligne['url']} — {ligne['action']}"
              + (f" : {', '.join(ligne['manquants'])}" if ligne["manquants"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
