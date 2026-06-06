"""Unique constraint on value_bets.participation_id (required by upsert ON CONFLICT).

save_value_bet uses on_conflict_do_update(index_elements=["participation_id"]) but
no matching unique constraint existed -> InvalidColumnReferenceError -> rolled back
the whole predict transaction (no value_bets saved, courses with value bets failed).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dédoublonnage défensif (au cas où) avant la contrainte
    op.execute("""
        DELETE FROM value_bets a USING value_bets b
        WHERE a.ctid < b.ctid AND a.participation_id = b.participation_id
    """)
    # idempotent : drop si déjà présente (ajoutée à chaud) puis (re)crée
    op.execute("ALTER TABLE value_bets DROP CONSTRAINT IF EXISTS uq_value_bets_participation")
    op.execute(
        "ALTER TABLE value_bets ADD CONSTRAINT uq_value_bets_participation "
        "UNIQUE (participation_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE value_bets DROP CONSTRAINT IF EXISTS uq_value_bets_participation")
