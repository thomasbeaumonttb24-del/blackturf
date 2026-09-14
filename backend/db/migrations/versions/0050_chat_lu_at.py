"""Communauté : repère de lecture par membre (bulle « messages non lus »).

`users.chat_lu_at` : instant jusqu'où le membre a lu le salon. NULL = jamais ouvert ;
le compteur part alors de la création du compte, ce qui invite les membres
existants à découvrir le salon sans noyer un nouvel inscrit sous l'historique.

La colonne est `deferred` dans le modèle : absente des `select(User)` courants, elle
ne fait pas échouer l'API pendant les secondes où le nouveau code tourne avant que
cette migration soit passée (le déploiement relance les conteneurs AVANT alembic —
la migration 0049 avait produit une erreur `column users.pseudo does not exist`).

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("chat_lu_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "chat_lu_at")
