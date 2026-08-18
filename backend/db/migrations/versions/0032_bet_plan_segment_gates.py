"""État persisté des gates automatiques par segment (Point 11).

Un segment (ex. type de pari, profil) durablement négatif ou en drawdown excessif
sur les plans RÉELLEMENT émis (``bet_plan_evaluation``) voit ses poids appris
plafonnés. La décision est calculée nightly et persistée ici pour que la
sélection de mise (ml/bet_performance.get_learned_type_weights) l'applique sans
recalculer le rapport de rentabilité à chaque requête utilisateur.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-18
"""
from alembic import op


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bet_plan_segment_gates (
            dimension VARCHAR(20) NOT NULL,
            segment_key VARCHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL,
            factor DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            reason TEXT,
            roi_pct DOUBLE PRECISION,
            n_paris INTEGER,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (dimension, segment_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_segment_gates_status "
        "ON bet_plan_segment_gates (dimension, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bet_plan_segment_gates")
