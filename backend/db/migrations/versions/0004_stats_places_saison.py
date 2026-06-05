"""stats_jockeys / stats_entraineurs: add places_saison column for incremental tracking

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.add_column(
            "stats_jockeys",
            sa.Column("places_saison", sa.Integer(), nullable=False, server_default="0"),
        )
    except Exception:
        pass

    try:
        op.add_column(
            "stats_entraineurs",
            sa.Column("places_saison", sa.Integer(), nullable=False, server_default="0"),
        )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column("stats_entraineurs", "places_saison")
    op.drop_column("stats_jockeys", "places_saison")
