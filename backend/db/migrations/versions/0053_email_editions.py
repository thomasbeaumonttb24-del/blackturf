"""Frozen newsletter editions and idempotent deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("email_editions", sa.Column("cle", sa.String(64), primary_key=True),
                    sa.Column("donnees", sa.JSON(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("email_livraisons", sa.Column("cle", sa.String(64), primary_key=True),
                    sa.Column("campagne", sa.String(64), nullable=False),
                    sa.Column("email", sa.String(255), nullable=False),
                    sa.Column("requete", sa.JSON(), nullable=False),
                    sa.Column("statut", sa.String(30), nullable=False),
                    sa.Column("provider_id", sa.String(80)), sa.Column("erreur", sa.Text()),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("envoye_at", sa.DateTime(timezone=True)))
    for field in ("campagne", "email", "provider_id"):
        op.create_index(f"ix_email_livraisons_{field}", "email_livraisons", [field])


def downgrade():
    op.drop_table("email_livraisons")
    op.drop_table("email_editions")
