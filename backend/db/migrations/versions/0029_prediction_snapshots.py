"""Journal append-only des états successifs de prédiction pré-course.

Expand uniquement : ``predictions`` reste inchangée et continue d'alimenter tous
les lecteurs existants. Le nouveau code effectue ensuite un dual-write. Aucun
backfill n'est fait ici : les anciennes lignes ont été mutées en place et ne sont
donc pas présentées à tort comme des snapshots historiques fiables.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-18
"""
from alembic import op


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_snapshots (
            snapshot_id VARCHAR(36) PRIMARY KEY,
            prediction_run_id VARCHAR(36) NOT NULL,
            prediction_id VARCHAR(36) NOT NULL REFERENCES predictions(prediction_id),
            participation_id VARCHAR(36) NOT NULL REFERENCES participations(participation_id),
            course_id VARCHAR(30) NOT NULL REFERENCES courses(course_id),
            model_version_id VARCHAR(36) REFERENCES model_versions(version_id),
            features JSONB NOT NULL,
            features_hash VARCHAR(64) NOT NULL,
            feature_schema_hash VARCHAR(64) NOT NULL,
            proba_top1 DOUBLE PRECISION NOT NULL,
            proba_top3 DOUBLE PRECISION NOT NULL,
            proba_top1_raw DOUBLE PRECISION,
            proba_top3_raw DOUBLE PRECISION,
            proba_top1_low DOUBLE PRECISION,
            proba_top1_high DOUBLE PRECISION,
            rang_predit INTEGER NOT NULL,
            confidence_score DOUBLE PRECISION,
            cote_figee DOUBLE PRECISION,
            observed_at TIMESTAMPTZ NOT NULL,
            odds_observed_at TIMESTAMPTZ,
            course_start_at TIMESTAMPTZ,
            is_pre_course BOOLEAN NOT NULL,
            origin VARCHAR(30) NOT NULL DEFAULT 'live',
            is_replayable BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_prediction_snapshot_run_participation
                UNIQUE (prediction_run_id, participation_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_prediction_id "
        "ON prediction_snapshots (prediction_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_participation_id "
        "ON prediction_snapshots (participation_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_course_id "
        "ON prediction_snapshots (course_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_course_observed "
        "ON prediction_snapshots (course_id, observed_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_pre_course "
        "ON prediction_snapshots (course_start_at) WHERE is_pre_course = true"
    )
    # Défense en profondeur : aucune réécriture/suppression accidentelle par le
    # compte applicatif. Les corrections se font par un nouvel événement explicite.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_prediction_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'prediction_snapshots is append-only';
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS prediction_snapshots_append_only ON prediction_snapshots")
    op.execute(
        """
        CREATE TRIGGER prediction_snapshots_append_only
        BEFORE UPDATE OR DELETE ON prediction_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_prediction_snapshot_mutation()
        """
    )


def downgrade() -> None:
    # Les données historiques de cette table sont dérivées ; la projection
    # compatible ``predictions`` n'est jamais touchée par le rollback.
    op.execute("DROP TABLE IF EXISTS prediction_snapshots")
    op.execute("DROP FUNCTION IF EXISTS reject_prediction_snapshot_mutation()")
