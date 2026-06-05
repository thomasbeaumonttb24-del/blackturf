"""Add bankrolls table and bankroll_id FK on bankroll_entries.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create bankrolls table ─────────────────────────────────────────────────
    op.create_table(
        "bankrolls",
        sa.Column("bankroll_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("discipline", sa.String(20), nullable=True),
        sa.Column("montant_initial", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("est_principale", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("couleur", sa.String(10), nullable=True),
        sa.Column("est_supprime", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_bankrolls_user", "bankrolls", ["user_id"])

    # ── Add bankroll_id column to bankroll_entries ────────────────────────────
    try:
        op.add_column(
            "bankroll_entries",
            sa.Column(
                "bankroll_id",
                sa.String(36),
                sa.ForeignKey("bankrolls.bankroll_id"),
                nullable=True,
            ),
        )
        op.create_index("ix_bankroll_entries_bankroll_id", "bankroll_entries", ["bankroll_id"])
    except Exception as e:
        print(f"bankroll_entries.bankroll_id: {e}")


def downgrade() -> None:
    try:
        op.drop_index("ix_bankroll_entries_bankroll_id", table_name="bankroll_entries")
        op.drop_column("bankroll_entries", "bankroll_id")
    except Exception as e:
        print(f"downgrade bankroll_entries: {e}")

    try:
        op.drop_index("ix_bankrolls_user", table_name="bankrolls")
        op.drop_table("bankrolls")
    except Exception as e:
        print(f"downgrade bankrolls: {e}")
