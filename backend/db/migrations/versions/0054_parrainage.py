"""Parrainage : code d'invitation, parrain du compte, suivi des récompenses."""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("code_parrain", sa.String(12), nullable=True))
    op.create_unique_constraint("uq_users_code_parrain", "users", ["code_parrain"])
    op.add_column("users", sa.Column("parraine_par_id", sa.String(36),
                                     sa.ForeignKey("users.user_id"), nullable=True))
    op.create_index("ix_users_parraine_par_id", "users", ["parraine_par_id"])

    op.create_table(
        "parrainages",
        sa.Column("parrainage_id", sa.String(36), primary_key=True),
        sa.Column("parrain_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("filleul_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("statut", sa.String(12), nullable=False, server_default="en_attente"),
        sa.Column("motif", sa.String(60)),
        sa.Column("remise_filleul_at", sa.DateTime(timezone=True)),
        sa.Column("stripe_invoice_id", sa.String(100)),
        sa.Column("credit_cents", sa.Integer()),
        sa.Column("stripe_credit_txn_id", sa.String(100)),
        sa.Column("credit_pose_at", sa.DateTime(timezone=True)),
        sa.Column("valide_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("filleul_id", name="uq_parrainages_filleul_id"),
    )
    op.create_index("ix_parrainages_parrain_id", "parrainages", ["parrain_id"])
    op.create_index("ix_parrainages_statut", "parrainages", ["statut"])
    op.create_index("ix_parrainages_stripe_invoice_id", "parrainages", ["stripe_invoice_id"])


def downgrade():
    op.drop_table("parrainages")
    op.drop_index("ix_users_parraine_par_id", table_name="users")
    op.drop_column("users", "parraine_par_id")
    op.drop_constraint("uq_users_code_parrain", "users", type_="unique")
    op.drop_column("users", "code_parrain")
