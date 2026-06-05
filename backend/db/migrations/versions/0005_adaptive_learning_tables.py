"""Adaptive learning tables: race_learning_log, bias_matrix, adaptive_learning_state

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── race_learning_log ────────────────────────────────────────────────
    try:
        op.create_table(
            "race_learning_log",
            sa.Column("log_id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.course_id"), unique=True, nullable=False),
            sa.Column("brier_score", sa.Float(), nullable=True),
            sa.Column("log_loss", sa.Float(), nullable=True),
            sa.Column("was_surprise", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("gagnant_proba_ia", sa.Float(), nullable=True),
            sa.Column("gagnant_rang_predit", sa.Integer(), nullable=True),
            sa.Column("discipline", sa.String(30), nullable=True),
            sa.Column("terrain", sa.String(30), nullable=True),
            sa.Column("hippodrome", sa.String(100), nullable=True),
            sa.Column("nb_partants", sa.Integer(), nullable=True),
            sa.Column("feature_autopsy", sa.JSON(), nullable=True),
            sa.Column("learning_signal", sa.JSON(), nullable=True),
            sa.Column("actions_recommandees", sa.JSON(), nullable=True),
            sa.Column("adaptive_updates", sa.JSON(), nullable=True),
            sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    except Exception:
        pass  # Table already exists

    # ── bias_matrix ──────────────────────────────────────────────────────
    try:
        op.create_table(
            "bias_matrix",
            sa.Column("bias_id", sa.String(36), primary_key=True),
            sa.Column("bias_key", sa.String(200), unique=True, nullable=False),
            sa.Column("discipline", sa.String(30), nullable=True),
            sa.Column("terrain", sa.String(30), nullable=True),
            sa.Column("hippodrome", sa.String(100), nullable=True),
            sa.Column("nb_courses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("nb_surprises", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("brier_moyen", sa.Float(), nullable=True),
            sa.Column("correction_factor", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("favori_win_rate", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        op.create_index("ix_bias_matrix_key", "bias_matrix", ["bias_key"])
    except Exception:
        pass  # Table already exists

    # ── adaptive_learning_state ──────────────────────────────────────────
    try:
        op.create_table(
            "adaptive_learning_state",
            sa.Column("state_id", sa.String(20), primary_key=True),  # 'singleton'
            sa.Column("temperature", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("feature_weights_json", sa.JSON(), nullable=True),
            sa.Column("n_races", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("brier_ema", sa.Float(), nullable=False, server_default="0.20"),
            sa.Column("surprise_ema", sa.Float(), nullable=False, server_default="0.30"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        # Seed la ligne singleton
        op.execute(
            "INSERT INTO adaptive_learning_state (state_id, temperature, n_races, brier_ema, surprise_ema) "
            "VALUES ('singleton', 1.0, 0, 0.20, 0.30) ON CONFLICT DO NOTHING"
        )
    except Exception:
        pass  # Table already exists


    # ── drift_detector_state ─────────────────────────────────────────────
    try:
        op.create_table(
            "drift_detector_state",
            sa.Column("state_id", sa.String(20), primary_key=True),  # 'singleton'
            sa.Column("state_json", sa.JSON(), nullable=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="'none'"),
            sa.Column("n_updates", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_drift_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.execute(
            "INSERT INTO drift_detector_state (state_id, severity, n_updates) "
            "VALUES ('singleton', 'none', 0) ON CONFLICT DO NOTHING"
        )
    except Exception:
        pass  # Table already exists


def downgrade() -> None:
    try:
        op.drop_index("ix_bias_matrix_key", table_name="bias_matrix")
    except Exception:
        pass
    op.drop_table("drift_detector_state")
    op.drop_table("bias_matrix")
    op.drop_table("race_learning_log")
    op.drop_table("adaptive_learning_state")
