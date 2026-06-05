"""value_bets: add notifie + created_at columns for notification tracking

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.add_column("value_bets", sa.Column("notifie", sa.Boolean(), nullable=False, server_default="false"))
    except Exception:
        pass

    try:
        op.add_column("value_bets", sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("NOW()"),
        ))
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column("value_bets", "created_at")
    op.drop_column("value_bets", "notifie")
