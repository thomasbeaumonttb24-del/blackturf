"""Crée ou retrouve le catalogue Stripe Test de BlackTurf et affiche les Price IDs.

Le script est idempotent grâce aux lookup_keys Stripe. Il lit STRIPE_SECRET_KEY
depuis le .env à la racine et ne journalise jamais la clé.
"""
from pathlib import Path

import stripe


ROOT = Path(__file__).resolve().parents[2]

PLANS = {
    "standard_monthly": ("BlackTurf Standard", 1200, "month"),
    "standard_annual": ("BlackTurf Standard", 11520, "year"),
    "expert_monthly": ("BlackTurf Expert", 1900, "month"),
    "expert_annual": ("BlackTurf Expert", 18240, "year"),
}

WEBHOOK_URL = "https://api.blackturf.fr/api/v1/stripe/webhook"
WEBHOOK_EVENTS = [
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
]


def read_secret() -> str:
    env_file = ROOT / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("STRIPE_SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("STRIPE_SECRET_KEY absent de .env")


def main() -> None:
    stripe.api_key = read_secret()
    products: dict[str, str] = {}
    output: dict[str, str] = {}

    for lookup_key, (product_name, unit_amount, interval) in PLANS.items():
        price_lookup_key = f"blackturf_{lookup_key}_{unit_amount}"
        existing = stripe.Price.list(lookup_keys=[price_lookup_key], active=True, limit=1)
        if existing.data:
            output[lookup_key] = existing.data[0].id
            continue

        if product_name not in products:
            found = stripe.Product.search(query=f"name:'{product_name}'", limit=1)
            product = found.data[0] if found.data else stripe.Product.create(
                name=product_name,
                metadata={"app": "blackturf"},
            )
            products[product_name] = product.id

        price = stripe.Price.create(
            product=products[product_name],
            currency="eur",
            unit_amount=unit_amount,
            recurring={"interval": interval},
            lookup_key=price_lookup_key,
            metadata={"app": "blackturf", "plan": lookup_key},
        )
        output[lookup_key] = price.id

    for key, price_id in output.items():
        print(f"{key}={price_id}")

    # Les montants Stripe sont immuables : désactiver les anciennes versions pour
    # éviter qu'un ancien Price ID reste vendable par erreur.
    for price in stripe.Price.list(active=True, limit=100).auto_paging_iter():
        plan_key = (price.metadata or {}).get("plan")
        if (price.metadata or {}).get("app") == "blackturf" and plan_key in output:
            if price.id != output[plan_key]:
                stripe.Price.modify(price.id, active=False)

    endpoints = stripe.WebhookEndpoint.list(limit=100)
    endpoint = next((item for item in endpoints.auto_paging_iter() if item.url == WEBHOOK_URL), None)
    if endpoint is None:
        endpoint = stripe.WebhookEndpoint.create(
            url=WEBHOOK_URL,
            enabled_events=WEBHOOK_EVENTS,
            description="BlackTurf subscriptions (test)",
        )
        print(f"webhook_secret={endpoint.secret}")
    else:
        stripe.WebhookEndpoint.modify(endpoint.id, enabled_events=WEBHOOK_EVENTS)
        print(f"webhook_endpoint={endpoint.id} (déjà présent, secret inchangé)")


if __name__ == "__main__":
    main()
