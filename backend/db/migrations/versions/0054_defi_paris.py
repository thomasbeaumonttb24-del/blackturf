"""Défi du mois : paris en points, immuables et réglés par le serveur."""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "defi_paris",
        sa.Column("pari_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("mois", sa.String(7), nullable=False),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
        sa.Column("type_pari", sa.String(30), nullable=False),
        sa.Column("chevaux", sa.JSON(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("origine", sa.String(10), nullable=False),
        sa.Column("engage_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statut", sa.String(12), nullable=False, server_default="en_attente"),
        sa.Column("rapport", sa.Float()),
        sa.Column("points_retour", sa.Float()),
        sa.Column("regle_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_defi_paris_user_id", "defi_paris", ["user_id"])
    op.create_index("ix_defi_paris_course_id", "defi_paris", ["course_id"])
    op.create_index("ix_defi_paris_mois_user", "defi_paris", ["mois", "user_id"])

    op.create_table(
        "defi_recompenses",
        sa.Column("recompense_id", sa.String(36), primary_key=True),
        sa.Column("mois", sa.String(7), nullable=False),
        sa.Column("rang", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("nom_public", sa.String(40), nullable=False),
        sa.Column("solde", sa.Float(), nullable=False),
        sa.Column("plan_offert", sa.String(10), nullable=False),
        sa.Column("plan_precedent", sa.String(10)),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("attribue_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mois", "rang", name="uq_defi_recompense_mois_rang"),
        sa.UniqueConstraint("mois", "user_id", name="uq_defi_recompense_mois_user"),
    )
    op.create_index("ix_defi_recompenses_user_id", "defi_recompenses", ["user_id"])


def downgrade():
    op.drop_table("defi_recompenses")
    op.drop_table("defi_paris")
