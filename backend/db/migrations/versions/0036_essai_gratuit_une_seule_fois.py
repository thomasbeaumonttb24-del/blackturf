"""L'essai gratuit n'était limité par rien.

Contexte (production, 2026-08-20). ``create_checkout`` passait
``trial_period_days: 7`` à CHAQUE session Stripe Checkout, sans jamais regarder
si le compte avait déjà bénéficié d'un essai — et Stripe, de son côté, ne
déduplique pas les essais par client. Un même utilisateur pouvait donc
enchaîner : essai 7 jours → annulation automatique faute de carte → nouveau
checkout → 7 jours de plus, indéfiniment.

Ce n'est pas théorique : le compte ``mahbouba504@yahoo.com`` cumulait
3 abonnements ``trialing`` simultanés (2 Standard + 1 Expert) ouverts en 24 h,
tous sans moyen de paiement.

Cette migration ajoute le fait manquant : la date à laquelle le compte a
consommé son essai. NULLABLE — NULL signifie « jamais utilisé », et c'est bien
l'état de l'immense majorité des comptes. Le backfill la renseigne pour les
comptes qui ont déjà eu au moins un abonnement assorti d'une période d'essai :
on prend la date de création de cet abonnement, seule donnée d'époque
disponible (``essai_fin`` est une date de FIN, la poser ici ferait croire à un
essai ouvert dans le futur).

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "essai_utilise_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de consommation de l'essai gratuit ; NULL = jamais utilise",
        ),
    )
    # Backfill : tout compte ayant déjà eu un abonnement avec période d'essai a
    # consommé le sien. On retient le PREMIER, pour ne pas déplacer la date à
    # chaque nouvel abonnement.
    op.execute(
        """
        UPDATE users u
           SET essai_utilise_at = sub.premier_essai
          FROM (
                SELECT user_id, MIN(created_at) AS premier_essai
                  FROM subscriptions
                 WHERE essai_fin IS NOT NULL
              GROUP BY user_id
               ) AS sub
         WHERE sub.user_id = u.user_id
           AND u.essai_utilise_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("users", "essai_utilise_at")
