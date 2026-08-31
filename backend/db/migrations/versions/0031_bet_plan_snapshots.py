"""Journal append-only des plans de mise émis et de leur règlement PMU.

Expand uniquement. ``profil_run_log`` reste inchangée et continue d'alimenter
l'apprentissage par profil ; ces deux tables enregistrent en plus le conseil
EXACT rendu à chaque demande (y compris utilisateur) et son règlement sur les
rapports réels. Aucun backfill : un plan reconstruit après le résultat ne serait
pas un plan émis.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-18
"""
from alembic import op


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bet_plan_snapshots (
            plan_snapshot_id VARCHAR(36) PRIMARY KEY,
            course_id VARCHAR(30) NOT NULL REFERENCES courses(course_id),
            prediction_run_id VARCHAR(36),
            model_version_id VARCHAR(36) REFERENCES model_versions(version_id),
            subject_hash VARCHAR(64) NOT NULL DEFAULT 'system',
            profil VARCHAR(20) NOT NULL,
            montant_demande DOUBLE PRECISION NOT NULL,
            bankroll DOUBLE PRECISION,
            plan JSONB NOT NULL,
            plan_hash VARCHAR(64) NOT NULL,
            cotes_utilisees JSONB NOT NULL,
            algo_config JSONB NOT NULL,
            algo_version VARCHAR(40) NOT NULL,
            nb_paris INTEGER NOT NULL,
            montant_joue DOUBLE PRECISION NOT NULL,
            ev_estimee DOUBLE PRECISION,
            esperance_gain DOUBLE PRECISION,
            emitted_at TIMESTAMPTZ NOT NULL,
            course_start_at TIMESTAMPTZ,
            is_pre_course BOOLEAN NOT NULL,
            origin VARCHAR(30) NOT NULL DEFAULT 'mise_plan',
            CONSTRAINT uq_bet_plan_snapshot_idempotence
                UNIQUE (course_id, subject_hash, plan_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_snapshots_course_id "
        "ON bet_plan_snapshots (course_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_snapshots_prediction_run_id "
        "ON bet_plan_snapshots (prediction_run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_snapshots_course_emitted "
        "ON bet_plan_snapshots (course_id, emitted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_snapshots_pre_course "
        "ON bet_plan_snapshots (course_start_at) WHERE is_pre_course = true"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bet_plan_settlements (
            settlement_id VARCHAR(36) PRIMARY KEY,
            plan_snapshot_id VARCHAR(36) NOT NULL
                REFERENCES bet_plan_snapshots(plan_snapshot_id),
            course_id VARCHAR(30) NOT NULL REFERENCES courses(course_id),
            bilan JSONB NOT NULL,
            montant_mise DOUBLE PRECISION NOT NULL,
            montant_retour DOUBLE PRECISION NOT NULL,
            net DOUBLE PRECISION NOT NULL,
            roi DOUBLE PRECISION,
            nb_paris INTEGER NOT NULL,
            nb_gagnes INTEGER NOT NULL,
            statut VARCHAR(20) NOT NULL,
            settled_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_settlements_plan_snapshot_id "
        "ON bet_plan_settlements (plan_snapshot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_settlements_course_id "
        "ON bet_plan_settlements (course_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bet_plan_settlements_plan_settled "
        "ON bet_plan_settlements (plan_snapshot_id, settled_at)"
    )

    # Défense en profondeur, identique à prediction_snapshots : le compte
    # applicatif ne peut ni réécrire un conseil émis, ni effacer un règlement.
    # Une correction se fait par un NOUVEL événement, jamais en place.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_bet_plan_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table in ("bet_plan_snapshots", "bet_plan_settlements"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_bet_plan_mutation()
            """
        )

    # Read-model du ROI : dernier règlement CONNU de chaque plan émis avant le
    # départ. Un plan sans règlement, post-départ, ou dont le dernier règlement
    # est encore 'partial' (rapport PMU non publié) n'est PAS mesurable et
    # n'apparaît donc pas ici — plutôt que d'être compté comme une perte sèche.
    op.execute(
        """
        CREATE OR REPLACE VIEW bet_plan_evaluation AS
        SELECT DISTINCT ON (s.plan_snapshot_id)
            s.plan_snapshot_id,
            s.course_id,
            s.prediction_run_id,
            s.model_version_id,
            s.subject_hash,
            s.profil,
            s.montant_demande,
            s.bankroll,
            s.plan_hash,
            s.algo_version,
            s.nb_paris AS nb_paris_emis,
            s.montant_joue,
            s.ev_estimee,
            s.esperance_gain,
            s.emitted_at,
            s.course_start_at,
            s.origin,
            t.settlement_id,
            t.bilan,
            t.montant_mise,
            t.montant_retour,
            t.net,
            t.roi,
            t.nb_gagnes,
            t.settled_at
        FROM bet_plan_snapshots s
        JOIN bet_plan_settlements t ON t.plan_snapshot_id = s.plan_snapshot_id
        WHERE s.is_pre_course = true
          AND t.statut = 'settled'
        ORDER BY s.plan_snapshot_id, t.settled_at DESC, t.settlement_id DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS bet_plan_evaluation")
    op.execute("DROP TABLE IF EXISTS bet_plan_settlements")
    op.execute("DROP TABLE IF EXISTS bet_plan_snapshots")
    op.execute("DROP FUNCTION IF EXISTS reject_bet_plan_mutation()")
