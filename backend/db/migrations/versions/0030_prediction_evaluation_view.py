"""Vue canonique du dernier pronostic pré-course évaluable.

La vue préfère le dernier snapshot live immuable de chaque participation. Tant
qu'aucun snapshot n'existe, elle expose la ligne ``predictions`` historique en la
marquant explicitement non rejouable. Les anciens lecteurs restent inchangés ; les
lecteurs historiques peuvent migrer indépendamment vers cette projection.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-18
"""
from alembic import op


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_latest_eval
        ON prediction_snapshots (participation_id, observed_at DESC)
        WHERE is_pre_course = true AND is_replayable = true
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW prediction_evaluation AS
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (ps.participation_id)
                ps.snapshot_id AS evaluation_id,
                ps.prediction_id,
                ps.participation_id,
                ps.course_id,
                ps.model_version_id,
                ps.proba_top1,
                ps.proba_top3,
                ps.proba_top1_raw,
                ps.proba_top3_raw,
                ps.proba_top1_low,
                ps.proba_top1_high,
                ps.rang_predit,
                NULL::double precision AS score_borda,
                ps.confidence_score,
                ps.cote_figee,
                ps.observed_at AS created_at,
                ps.features,
                ps.features_hash,
                ps.feature_schema_hash,
                ps.origin AS source_origin,
                true AS is_snapshot,
                ps.is_replayable
            FROM prediction_snapshots ps
            WHERE ps.is_pre_course = true AND ps.is_replayable = true
            ORDER BY ps.participation_id, ps.observed_at DESC, ps.snapshot_id DESC
        )
        SELECT * FROM latest_snapshot
        UNION ALL
        SELECT
            p.prediction_id AS evaluation_id,
            p.prediction_id,
            p.participation_id,
            p.course_id,
            p.model_version_id,
            p.proba_top1,
            p.proba_top3,
            p.proba_top1_raw,
            p.proba_top3_raw,
            p.proba_top1_low,
            p.proba_top1_high,
            p.rang_predit,
            p.score_borda,
            p.confidence_score,
            p.cote_figee,
            p.created_at,
            NULL::jsonb AS features,
            NULL::varchar(64) AS features_hash,
            NULL::varchar(64) AS feature_schema_hash,
            'legacy_mutable_row'::varchar(30) AS source_origin,
            false AS is_snapshot,
            false AS is_replayable
        FROM predictions p
        WHERE NOT EXISTS (
            SELECT 1 FROM latest_snapshot s
            WHERE s.participation_id = p.participation_id
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS prediction_evaluation")
    op.execute("DROP INDEX IF EXISTS ix_prediction_snapshots_latest_eval")
