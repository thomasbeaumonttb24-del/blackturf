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
    # IF NOT EXISTS partout : idempotent et SANS empoisonner la transaction
    # (un try/except autour d'un DDL qui échoue laisse la transaction PostgreSQL
    # avortée — tout le reste de la migration casse alors).
    op.execute("ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS walk_forward_auc DOUBLE PRECISION")
    op.execute("ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS walk_forward_variance DOUBLE PRECISION")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profil_risque VARCHAR(20) DEFAULT 'equilibre'")
    op.execute("ALTER TABLE value_bets ADD COLUMN IF NOT EXISTS spi_detected BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE value_bets ADD COLUMN IF NOT EXISTS spi_score DOUBLE PRECISION")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_plan ON users (plan)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_statut ON subscriptions (statut)")


def downgrade() -> None:
    op.drop_column("model_versions", "walk_forward_variance")
    op.drop_column("model_versions", "walk_forward_auc")
