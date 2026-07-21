"""Valeur de handicap (#10) : note du handicapeur par partant.

Exploite le champ PMU `valeurHandicap` (présent dans les courses à handicap). C'est
la valeur officielle attribuée par le handicapeur — proxy direct de la qualité du
cheval, distinct du poids porté. Stockée pour alimenter les features ML.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-18
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE participations ADD COLUMN IF NOT EXISTS valeur_handicap INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE participations DROP COLUMN IF EXISTS valeur_handicap")
