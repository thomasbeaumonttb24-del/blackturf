"""N° de réunion PUBLIC (PMU numExterne) pour matcher pmu.fr à l'affichage.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-06
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS numero_reunion INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS numero_reunion")
