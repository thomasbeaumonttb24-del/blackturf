"""Course enrichie : conditions complètes, catégorie, dotation gagnant, déclarés,
évolution du pool (smart money).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-06
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

COLS = [
    ("conditions_texte", "TEXT"),
    ("categorie_particularite", "VARCHAR(30)"),
    ("montant_offert_1er", "BIGINT"),
    ("nombre_declares_partants", "INTEGER"),
    ("pool_gagnant_evolution", "DOUBLE PRECISION"),
]


def upgrade() -> None:
    for col, typ in COLS:
        op.execute(f"ALTER TABLE courses ADD COLUMN IF NOT EXISTS {col} {typ}")


def downgrade() -> None:
    for col, _ in COLS:
        op.execute(f"ALTER TABLE courses DROP COLUMN IF EXISTS {col}")
