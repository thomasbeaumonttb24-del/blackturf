"""ELO point-in-time (avant course) par participation — anti-fuite temporelle.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-07
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

COLS = ["elo_avant_global", "elo_avant_plat", "elo_avant_trot", "elo_avant_obstacle"]


def upgrade() -> None:
    for c in COLS:
        op.execute(f"ALTER TABLE participations ADD COLUMN IF NOT EXISTS {c} DOUBLE PRECISION")


def downgrade() -> None:
    for c in COLS:
        op.execute(f"ALTER TABLE participations DROP COLUMN IF EXISTS {c}")
