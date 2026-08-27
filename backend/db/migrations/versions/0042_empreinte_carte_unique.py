"""Une carte bancaire n'ouvre qu'un seul essai gratuit, quel que soit l'e-mail.

Contexte (2026-08-27). L'essai de 7 jours était déjà verrouillé par compte
(`users.essai_utilise_at`, migration 0036), mais le verrou portait sur la mauvaise
clé : rien n'empêchait de recréer un compte avec une autre adresse e-mail et la
MÊME carte pour repartir pour 7 jours gratuits, en boucle. Une carte prépayée
vidée suffit : Stripe valide l'enregistrement du moyen de paiement sans jamais
vérifier le solde, et l'échec n'arrive qu'à la fin de l'essai — trop tard.

`cartes_connues` mémorise l'empreinte Stripe (`card.fingerprint`) de chaque carte
présentée et le compte qui l'a présentée en premier. L'empreinte est stable pour
un même numéro de carte à l'intérieur d'un compte Stripe, y compris quand le
`payment_method` change à chaque checkout : c'est le seul identifiant qui survit
au changement d'adresse e-mail. Aucun numéro de carte n'est stocké — l'empreinte
est un condensé opaque calculé par Stripe.

La table est renseignée par les webhooks, elle démarre donc vide : les deux
abonnés existants seront enregistrés à leur prochain mouvement Stripe. Aucun
rattrapage n'est tenté ici — appeler l'API Stripe depuis une migration rendrait
le déploiement dépendant du réseau.

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cartes_connues",
        sa.Column("empreinte", sa.String(64), primary_key=True),
        # ondelete SET NULL : purger un compte (RGPD) ne doit pas rouvrir le
        # droit à l'essai pour la carte qu'il avait utilisée.
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("stripe_payment_method_id", sa.String(100), nullable=True),
        sa.Column("marque", sa.String(20), nullable=True),
        sa.Column("dernier4", sa.String(4), nullable=True),
        sa.Column("financement", sa.String(15), nullable=True),
        sa.Column("tentatives_autres_comptes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("premiere_vue", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("derniere_vue", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cartes_connues_user_id", "cartes_connues", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_cartes_connues_user_id", table_name="cartes_connues")
    op.drop_table("cartes_connues")
