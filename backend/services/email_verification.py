"""Adresse e-mail confirmée : qui doit l'être, et depuis quand.

Le mail de confirmation partait déjà à l'inscription, mais `email_verified`
n'était lu nulle part comme condition : une adresse inexistante — ou celle d'un
tiers — donnait un compte pleinement fonctionnel. Deux dégâts concrets :

- les envois (alertes, e-mail hebdomadaire) partent vers des boîtes mortes, et
  les rebonds dégradent la délivrabilité de TOUS les messages, y compris ceux
  destinés aux vrais abonnés ;
- l'essai gratuit Stripe se multiplie à volonté, une adresse bidon par compte.

La règle vaut maintenant à la CONNEXION (`api.routes.auth.login`) : sans
confirmation, pas de session, donc pas de compte utilisable. Elle est également
relue devant ce qui coûte de l'argent (`require_verified_email`), car les
sessions ouvertes avant sa mise en service vivent encore jusqu'à 7 jours.

On exige donc la confirmation — mais seulement pour les comptes créés à partir de
la mise en service. Les comptes antérieurs sont dispensés : ils se sont inscrits
sous une règle qui ne l'exigeait pas, et l'un d'eux est un abonné payant. Leur
fermer la porte a posteriori serait une régression pour eux, pas une sécurité.
"""
from datetime import datetime, timezone

from sqlalchemy import or_

from db.models import User

# Date de mise en service de l'exigence (UTC). Tout compte créé AVANT est dispensé.
VERIFICATION_OBLIGATOIRE_DEPUIS = datetime(2026, 8, 19, tzinfo=timezone.utc)


def email_confirme(user: User) -> bool:
    """Vrai si l'on peut se fier à l'adresse de ce compte.

    Les comptes Google arrivent déjà avec `email_verified=True` (Google atteste
    l'adresse), ils passent donc par le premier test.
    """
    if getattr(user, "email_verified", False):
        return True
    cree_le = getattr(user, "created_at", None)
    if cree_le is None:
        # Date de création inconnue (lignes anciennes) : on ne pénalise pas.
        return True
    if cree_le.tzinfo is None:
        cree_le = cree_le.replace(tzinfo=timezone.utc)
    return cree_le < VERIFICATION_OBLIGATOIRE_DEPUIS


def clause_email_utilisable():
    """Même règle, exprimée en SQL — pour ne pas charger tous les comptes en
    mémoire avant de filtrer les destinataires d'un envoi."""
    return or_(
        User.email_verified == True,  # noqa: E712
        User.created_at < VERIFICATION_OBLIGATOIRE_DEPUIS,
    )
