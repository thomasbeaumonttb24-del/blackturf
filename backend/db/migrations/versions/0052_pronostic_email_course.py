"""Popup fiche course : « pronostic gratuit pour cette course » par e-mail.

Contexte (2026-09-22). Analyse concurrentielle Boturfers.fr : la capture d'e-mail
ciblée sur UNE course précise (pas la newsletter hebdo générique) est un des
meilleurs leviers funnel gratuit → conversion. L'e-mail envoyé est transactionnel
(déclenché par une action explicite du visiteur sur cette course précise) donc pas
de double opt-in comme `newsletter_abonnes` — mais chaque envoi porte son propre
lien de désinscription, et une adresse qui s'en sert ne reçoit plus jamais cet
e-mail, quelle que soit la course redemandée ensuite (table `pronostic_email_blocages`,
consultée avant tout envoi).

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pronostic_email_envois",
        sa.Column("envoi_id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
        sa.Column("token_desinscription", sa.String(64), nullable=False),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("envoye_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pronostic_email_envois_email", "pronostic_email_envois", ["email"])
    op.create_index("ix_pronostic_email_envois_course_id", "pronostic_email_envois", ["course_id"])
    op.create_index("ux_pronostic_email_course", "pronostic_email_envois",
                    ["email", "course_id"], unique=True)
    op.create_index("ux_pronostic_email_token_desinscription", "pronostic_email_envois",
                    ["token_desinscription"], unique=True)

    op.create_table(
        "pronostic_email_blocages",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("bloque_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pronostic_email_blocages")
    op.drop_index("ux_pronostic_email_token_desinscription", table_name="pronostic_email_envois")
    op.drop_index("ux_pronostic_email_course", table_name="pronostic_email_envois")
    op.drop_index("ix_pronostic_email_envois_course_id", table_name="pronostic_email_envois")
    op.drop_index("ix_pronostic_email_envois_email", table_name="pronostic_email_envois")
    op.drop_table("pronostic_email_envois")
