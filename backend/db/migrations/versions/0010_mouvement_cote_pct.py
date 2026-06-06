"""Add participations.mouvement_cote_pct (used by ML feature loader).

Phantom column referenced in features.py but never created → predict crash.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE participations ADD COLUMN IF NOT EXISTS mouvement_cote_pct DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE participations DROP COLUMN IF EXISTS mouvement_cote_pct")
