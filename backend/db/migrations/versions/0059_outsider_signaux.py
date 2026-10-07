"""Outsiders repérés par le cerveau des outsiders (ml.outsider_brain).

Une ligne par partant signalé, figée au départ : c'est ce registre — et non un
recalcul après coup — qui alimente le bilan public des outsiders.

Revision ID: 0059
Revises: 0058
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outsider_signaux",
        sa.Column("participation_id", sa.String(36),
                  sa.ForeignKey("participations.participation_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id", ondelete="CASCADE"), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("chance_place", sa.Float(), nullable=False),
        sa.Column("cote_signal", sa.Float(), nullable=False),
        sa.Column("niveau", sa.String(10), nullable=False),
        sa.Column("places_payees", sa.Integer(), nullable=False),
        sa.Column("raisons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("modele_entraine_le", sa.String(40)),
        sa.Column("premier_signal_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("maj_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_outsider_signaux_course_id", "outsider_signaux", ["course_id"])
    op.create_index("ix_outsider_signaux_premier_signal_at", "outsider_signaux", ["premier_signal_at"])


def downgrade():
    op.drop_table("outsider_signaux")
