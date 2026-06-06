"""Ajoute model_versions.est_synthetique + marque le modèle synthétique courant.

Le prior cold-start (entraîné sur données synthétiques) a un AUC gonflé qui
bloquerait tout modèle réel au déploiement. Ce flag permet à _do_retraining de
remplacer inconditionnellement un prior synthétique par le 1er vrai modèle.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-06
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS "
        "est_synthetique BOOLEAN NOT NULL DEFAULT false"
    )
    # le modèle actif actuel (v1) est synthétique
    op.execute("UPDATE model_versions SET est_synthetique = true WHERE version_num = 1")


def downgrade() -> None:
    op.execute("ALTER TABLE model_versions DROP COLUMN IF EXISTS est_synthetique")
