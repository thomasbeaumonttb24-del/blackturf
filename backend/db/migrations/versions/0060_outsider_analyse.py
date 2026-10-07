"""Fiche d'analyse complète de chaque outsider (critères placés dans le champ).

Revision ID: 0060
Revises: 0059
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outsider_signaux",
                  sa.Column("analyse", postgresql.JSONB(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("outsider_signaux", "analyse")
