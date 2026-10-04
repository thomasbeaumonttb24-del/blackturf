"""Tarifs des passes sans renouvellement — module sans dépendance (ni base, ni
réglages), partagé par l'API (services.passes) et le script de catalogue Stripe
(scripts/setup_stripe_catalog.py), qui tourne hors application."""
from datetime import timedelta

# durée → (prix en centimes, durée d'accès, libellé). Montants vérifiés au
# centime près sur la session payée : un prix modifié ici ne s'applique jamais
# à une session créée avant.
PASSES: dict[str, tuple[int, timedelta, str]] = {
    "jour": (500, timedelta(hours=24), "Pass Jour — 24 h d'accès Expert"),
    "semaine": (1200, timedelta(days=7), "Pass Semaine — 7 jours d'accès Expert"),
    "mois": (2400, timedelta(days=30), "Pass Mois — 30 jours d'accès Expert"),
}
DEVISE = "eur"


def lookup_key(duree: str) -> str:
    """Clé du prix Stripe du pass. Le montant fait partie de la clé : un nouveau
    tarif = un nouveau prix, jamais une modification silencieuse de l'ancien."""
    return f"blackturf_pass_{duree}_{PASSES[duree][0]}"
