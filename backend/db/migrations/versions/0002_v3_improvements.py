"""v3 improvements — walk_forward metrics, user profil_risque, decouverte plan support

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # model_versions: walk_forward metrics
    op.add_column("model_versions", sa.Column("walk_forward_auc", sa.Float(), nullable=True))
    op.add_column("model_versions", sa.Column("walk_forward_variance", sa.Float(), nullable=True))

    # users: profil_risque field (already in v1 model but may be missing from initial migration)
    try:
        op.add_column("users", sa.Column("profil_risque", sa.String(20), nullable=True, server_default="equilibre"))
    except Exception:
        pass  # Column may already exist

    # users: allow decouverte as plan value (no schema change needed — it's a String field)
    # Update existing 'free' users to stay 'free' — no change needed for backwards compat

    # value_bets: SPI fields
    try:
        op.add_column("value_bets", sa.Column("spi_detected", sa.Boolean(), nullable=False, server_default="false"))
        op.add_column("value_bets", sa.Column("spi_score", sa.Float(), nullable=True))
    except Exception:
        pass

    # Add index on subscriptions for faster plan lookups
    try:
        op.create_index("ix_users_plan", "users", ["plan"])
    except Exception:
        pass

    try:
        op.create_index("ix_subscriptions_statut", "subscriptions", ["statut"])
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column("model_versions", "walk_forward_variance")
    op.drop_column("model_versions", "walk_forward_auc")
