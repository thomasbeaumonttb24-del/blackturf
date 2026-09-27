"""Tous les paris candidats d'une course, retenus ou non, réglés en observation.

Cf. ml/candidats_paris.py : le journal qui permet de comparer, sur la même course
et au même horaire, la formule jouée à celles que le moteur a écartées.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidats_paris",
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), primary_key=True),
        sa.Column("cle", sa.String(120), primary_key=True),
        sa.Column("type_pari", sa.String(40), nullable=False),
        sa.Column("numeros", postgresql.JSONB(), nullable=False),
        sa.Column("niveau", sa.String(20)),
        sa.Column("proba_gain", sa.Float()),
        sa.Column("rapport_estime", sa.Float()),
        sa.Column("ev", sa.Float()),
        sa.Column("edge", sa.Float()),
        sa.Column("cotes", postgresql.JSONB()),
        sa.Column("retenu_par", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model_version_id", sa.String(36)),
        sa.Column("statut", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("gagne", sa.Boolean()),
        sa.Column("gain_1eur", sa.Float()),
        sa.Column("note_reglement", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_candidats_paris_statut", "candidats_paris", ["statut"])
    op.create_index("ix_candidats_paris_created_at", "candidats_paris", ["created_at"])


def downgrade():
    op.drop_table("candidats_paris")
