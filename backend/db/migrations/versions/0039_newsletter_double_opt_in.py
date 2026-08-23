"""Le site n'avait aucun moyen de garder un visiteur qui n'achète pas tout de suite.

Contexte (2026-08-24). Deux issues seulement s'offraient au visiteur : s'abonner, ou
partir. Sur un produit à 12 €/mois qu'on n'achète pas au premier contact, c'était la
fuite la plus coûteuse du tunnel — et le seul canal d'acquisition qui ne dépend d'aucune
autorisation réglementaire (cf. la certification ANJ exigée pour la publicité).

Double opt-in : une adresse ne reçoit RIEN tant qu'elle n'a pas cliqué le lien de
confirmation. C'est ce qui protège de l'inscription d'un tiers par malveillance, et ce
qui rend le consentement démontrable.

Une désinscription ne supprime PAS la ligne : sans elle, une adresse désinscrite pourrait
être réinscrite par un tiers et recevoir à nouveau des envois. Le statut fait foi.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newsletter_abonnes",
        sa.Column("abonne_id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("statut", sa.String(15), nullable=False, server_default="en_attente"),
        sa.Column("token_confirmation", sa.String(64), nullable=True),
        sa.Column("token_desinscription", sa.String(64), nullable=False),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("consentement_texte", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("confirme_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("desinscrit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dernier_envoi_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("relance_confirmation_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Unicité de l'adresse : une seconde soumission de la même adresse doit retomber sur
    # la ligne existante, jamais en créer une deuxième (sinon un envoi en double).
    op.create_index("ux_newsletter_email", "newsletter_abonnes", ["email"], unique=True)
    op.create_index("ux_newsletter_token_confirmation", "newsletter_abonnes",
                    ["token_confirmation"], unique=True)
    op.create_index("ux_newsletter_token_desinscription", "newsletter_abonnes",
                    ["token_desinscription"], unique=True)
    op.create_index("ix_newsletter_statut", "newsletter_abonnes", ["statut"])


def downgrade() -> None:
    op.drop_index("ix_newsletter_statut", table_name="newsletter_abonnes")
    op.drop_index("ux_newsletter_token_desinscription", table_name="newsletter_abonnes")
    op.drop_index("ux_newsletter_token_confirmation", table_name="newsletter_abonnes")
    op.drop_index("ux_newsletter_email", table_name="newsletter_abonnes")
    op.drop_table("newsletter_abonnes")
