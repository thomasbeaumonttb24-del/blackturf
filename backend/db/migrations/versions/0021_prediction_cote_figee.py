"""Cote figée au moment du calcul du pronostic (gel du prono 10 min avant départ).

Le plan de mise lit `cote_figee` au lieu de la cote live de `participations`.
Tant que la course est à > 10 min du départ, le cycle de prédiction recalcule et
met à jour `cote_figee` (le prono suit le marché). Dès T-10 min, le cycle s'arrête
→ `cote_figee` est figée → le pronostic/plan ne bouge plus. Les cotes affichées
(`participations.cote_pmu`, endpoint cotes-live) continuent d'évoluer.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-11
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE predictions ADD COLUMN IF NOT EXISTS cote_figee DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE predictions DROP COLUMN IF EXISTS cote_figee")
