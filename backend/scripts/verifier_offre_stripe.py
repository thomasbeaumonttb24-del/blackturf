"""Vérifie l'offre anniversaire de bout en bout sur Stripe, en mode TEST.

Ce que le script prouve, avec de vrais objets Stripe (supprimés à la fin) :
  1. le coupon existe : −50 %, `duration=once`, fin au 15 octobre ;
  2. une page de paiement mensuelle avec le coupon affiche 6 € (Standard) et
     9,50 € (Expert) au lieu de 12 € / 19 € ;
  3. un abonnement payé avec le coupon facture 50 % le premier mois, PUIS le
     prix plein à l'échéance suivante (la remise ne se répète pas).

Refuse une clé LIVE : aucun prélèvement réel. Clé : STRIPE_SECRET_KEY
(environnement ou .env) — utilisez la clé sk_test_ du compte, avec les
STRIPE_PRICE_* de test.

    STRIPE_SECRET_KEY=sk_test_... STRIPE_PRICE_STARTER_MONTHLY=price_... \\
    STRIPE_PRICE_PRO_MONTHLY=price_... python scripts/verifier_offre_stripe.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stripe  # noqa: E402

from api.config import get_settings  # noqa: E402
from services import offre_anniversaire as oa  # noqa: E402


def controle(ok: bool, texte: str) -> bool:
    print(("  OK    " if ok else "  ÉCHEC ") + texte)
    return ok


def main() -> None:
    s = get_settings()
    stripe.api_key = s.stripe_secret_key
    if not stripe.api_key.startswith(("sk_test", "rk_test")):
        sys.exit("Clé Stripe de TEST exigée (sk_test_…) : ce script crée et paie un abonnement.")
    prix = {"standard": s.stripe_price_starter_monthly, "expert": s.stripe_price_pro_monthly}
    tout_ok = True

    print("1. Coupon")
    coupon = stripe.Coupon.retrieve(oa.assurer_coupon())
    tout_ok &= controle(coupon.percent_off == oa.POURCENT, f"remise {coupon.percent_off} %")
    tout_ok &= controle(coupon.duration == "once", f"durée « {coupon.duration} » : premier paiement seulement")
    tout_ok &= controle(coupon.redeem_by == int(oa.FIN.timestamp()), "fin de validité au " + oa.FIN_TEXTE)

    client = stripe.Customer.create(email="verification-offre@blackturf.fr",
                                    payment_method="pm_card_visa",
                                    invoice_settings={"default_payment_method": "pm_card_visa"},
                                    metadata={"app": "blackturf", "verification": "offre-anniversaire"})
    try:
        print("2. Page de paiement")
        for plan, price_id in prix.items():
            avant, apres = oa.PRIX[plan]
            sess = stripe.checkout.Session.create(
                customer=client.id, mode="subscription", payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                discounts=[{"coupon": oa.COUPON_ID}],
                success_url="https://blackturf.fr/", cancel_url="https://blackturf.fr/")
            tout_ok &= controle(sess.amount_subtotal == avant and sess.amount_total == apres,
                                f"{plan} : {sess.amount_subtotal / 100:.2f} € → {sess.amount_total / 100:.2f} €")
            stripe.checkout.Session.expire(sess.id)

        print("3. Premier paiement, puis le suivant")
        avant, apres = oa.PRIX["expert"]
        sub = stripe.Subscription.create(customer=client.id, items=[{"price": prix["expert"]}],
                                         discounts=[{"coupon": oa.COUPON_ID}],
                                         metadata={"offre": oa.COUPON_ID}, expand=["latest_invoice"])
        premiere = sub.latest_invoice
        tout_ok &= controle(premiere.amount_paid == apres,
                            f"1re facture payée : {premiere.amount_paid / 100:.2f} €")
        suivante = stripe.Invoice.upcoming(customer=client.id, subscription=sub.id)
        tout_ok &= controle(suivante.amount_due == avant,
                            f"facture suivante : {suivante.amount_due / 100:.2f} € (prix plein)")
        stripe.Subscription.cancel(sub.id)
    finally:
        stripe.Customer.delete(client.id)

    print("\nTOUT EST BON" if tout_ok else "\nUN CONTRÔLE A ÉCHOUÉ")
    sys.exit(0 if tout_ok else 1)


if __name__ == "__main__":
    main()
