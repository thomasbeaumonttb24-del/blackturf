"""Désabonnement des e-mails marketing (RGPD).

Le job hebdomadaire « meilleur value bet de la semaine » (funnel de conversion
Free) envoie un e-mail non transactionnel : il DOIT donc porter un lien de
désabonnement fonctionnel. Cette colonne enregistre l'opt-out (NULL = abonné,
date = désabonné à cet instant). Volontairement séparée des préférences push
(`users.push_subscription`), qui concernent un autre canal et sont NULL pour la
grande majorité des comptes.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-16
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS marketing_opt_out_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS marketing_opt_out_at")
