"""Ajoute alertes_log.lue (statut lu/non-lu) — manquante en DB, casse /notifications.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-06
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alertes_log ADD COLUMN IF NOT EXISTS lue BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE alertes_log DROP COLUMN IF EXISTS lue")
