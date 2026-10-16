"""Provenance de l'inscription (utm_source / utm_campaign de la première visite).

Revision ID: 0061
Revises: 0060
"""
from alembic import op
import sqlalchemy as sa

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("provenance", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("users", "provenance")
