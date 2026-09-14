"""Communauté : salon de discussion entre membres connectés.

- `users.pseudo` : nom public dans le salon, choisi à la première visite. Jamais
  le prénom ni l'e-mail — on discute paris entre inconnus, l'identité réelle n'a
  rien à y faire. Unicité INSENSIBLE À LA CASSE (« Turfiste » et « turfiste »
  seraient deux personnes indiscernables à l'écran) : index unique sur lower().
- `users.chat_banni_at` : bannissement du salon SEUL. Ne touche ni la connexion,
  ni l'abonnement payé.
- `chat_messages` : suppression douce (`supprime_at`) — la modération doit pouvoir
  relire ce qu'elle a retiré si un membre conteste.
- `chat_signalements` : un signalement par membre et par message.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pseudo", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("chat_banni_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("CREATE UNIQUE INDEX ux_users_pseudo_lower ON users (lower(pseudo))")

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("contenu", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("supprime_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supprime_par", sa.String(36), nullable=True),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    op.create_table(
        "chat_signalements",
        sa.Column("signalement_id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36),
                  sa.ForeignKey("chat_messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("motif", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("traite_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("message_id", "user_id", name="uq_chat_signalement_message_user"),
    )
    op.create_index("ix_chat_signalements_message_id", "chat_signalements", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_signalements_message_id", table_name="chat_signalements")
    op.drop_table("chat_signalements")
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.execute("DROP INDEX IF EXISTS ux_users_pseudo_lower")
    op.drop_column("users", "chat_banni_at")
    op.drop_column("users", "pseudo")
