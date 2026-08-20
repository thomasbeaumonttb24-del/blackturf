"""Aucun mouvement d'abonnement n'était conservé.

Contexte (2026-08-20). `subscriptions` ne porte que l'ÉTAT COURANT : chaque
webhook écrase la ligne. Impossible, dès lors, de répondre aux questions que
pose l'exploitation — quand l'essai a-t-il démarré, le client a-t-il résilié
AVANT ou APRÈS sa fin, quand la carte est-elle arrivée, combien d'essais se
terminent sans conversion. Le seul historique disponible était la table
`stripe_events`, qui ne stocke qu'un identifiant d'événement pour
l'idempotence : ni le compte, ni le plan, ni le montant.

Ce journal est APPEND-ONLY : une ligne par mouvement, jamais modifiée. Il
alimente le suivi admin et les notifications.

`email` est dénormalisé à dessein : le journal doit rester lisible après
suppression du compte (purger un utilisateur n'efface pas l'historique
commercial). La clé étrangère est donc NULLABLE et en SET NULL — supprimer un
utilisateur ne doit jamais échouer à cause de ce journal, ni emporter ses lignes.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("plan", sa.String(10), nullable=True),
        sa.Column("plan_precedent", sa.String(10), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True),
        sa.Column("montant_cents", sa.Integer(), nullable=True),
        sa.Column("essai_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("periode_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pendant_essai", sa.Boolean(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subscription_events_user_id", "subscription_events", ["user_id"])
    op.create_index("ix_subscription_events_type", "subscription_events", ["type"])
    op.create_index("ix_subscription_events_created_at", "subscription_events", ["created_at"])
    op.create_index("ix_subscription_events_stripe_subscription_id",
                    "subscription_events", ["stripe_subscription_id"])
    op.create_index("ix_subscription_events_user_date",
                    "subscription_events", ["user_id", "created_at"])

    # ATTENTION : pas de « : » dans les littéraux SQL de `op.execute`.
    # SQLAlchemy y lit un paramètre lié — `':amorce'` a fait échouer cette
    # migration en production avec « A value is required for bind parameter
    # 'amorce' », alors que le même SQL passait sous psql (qui n'interprète
    # aucun bind). Le suffixe n'a d'autre rôle que de rendre l'identifiant
    # déterministe et distinct de tout UUID réel.
    # Amorçage depuis l'état courant : sans lui le suivi admin s'ouvre vide alors
    # que des abonnements existent déjà. On ne peut reconstituer que l'ouverture
    # (date de création connue) — les résiliations passées ne sont pas datées
    # ailleurs, on ne les invente pas.
    op.execute(
        """
        INSERT INTO subscription_events (
            event_id, user_id, email, type, plan, stripe_subscription_id,
            essai_fin, periode_fin, pendant_essai, detail, created_at)
        SELECT
            md5(s.sub_id || '-amorce')::uuid::text,
            s.user_id,
            u.email,
            CASE WHEN s.essai_fin IS NOT NULL THEN 'essai_ouvert' ELSE 'abonnement_actif' END,
            s.plan,
            s.stripe_subscription_id,
            s.essai_fin,
            s.periode_fin,
            NULL,
            '{"source": "amorce_migration_0037"}'::json,
            s.created_at
          FROM subscriptions s
          LEFT JOIN users u ON u.user_id = s.user_id
        """
    )


def downgrade() -> None:
    op.drop_table("subscription_events")
