"""Passes sans renouvellement (jour / semaine / mois), payés une fois.

Revision ID: 0058
Revises: 0057
"""
from alembic import op
import sqlalchemy as sa

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "passes_acces",
        sa.Column("pass_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("duree", sa.String(10), nullable=False),
        sa.Column("plan", sa.String(10), nullable=False, server_default="expert"),
        sa.Column("montant_cents", sa.Integer(), nullable=False),
        sa.Column("stripe_session_id", sa.String(100), nullable=False),
        sa.Column("stripe_payment_intent", sa.String(100)),
        sa.Column("debut", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statut", sa.String(12), nullable=False, server_default="actif"),
        sa.Column("renonciation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renonciation_version", sa.String(10), nullable=False),
        sa.Column("expire_traite_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("stripe_session_id", name="uq_passes_acces_session"),
    )
    op.create_index("ix_passes_acces_user_id", "passes_acces", ["user_id"])
    op.create_index("ix_passes_acces_fin", "passes_acces", ["fin"])
    op.create_index("ix_passes_acces_stripe_payment_intent", "passes_acces", ["stripe_payment_intent"])


def downgrade():
    op.drop_table("passes_acces")
