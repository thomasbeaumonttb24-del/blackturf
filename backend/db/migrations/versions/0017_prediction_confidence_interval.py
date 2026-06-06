"""Intervalle de confiance sur proba_top1 (désaccord des 3 modèles de base).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-06
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

COLS = [
    ("proba_top1_low", "DOUBLE PRECISION"),
    ("proba_top1_high", "DOUBLE PRECISION"),
]


def upgrade() -> None:
    for col, typ in COLS:
        op.execute(f"ALTER TABLE predictions ADD COLUMN IF NOT EXISTS {col} {typ}")


def downgrade() -> None:
    for col, _ in COLS:
        op.execute(f"ALTER TABLE predictions DROP COLUMN IF EXISTS {col}")
