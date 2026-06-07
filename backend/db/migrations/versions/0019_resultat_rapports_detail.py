"""Détail complet des rapports PMU (par combinaison) sur les résultats.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-07
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE resultats ADD COLUMN IF NOT EXISTS rapports_detail JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE resultats DROP COLUMN IF EXISTS rapports_detail")
