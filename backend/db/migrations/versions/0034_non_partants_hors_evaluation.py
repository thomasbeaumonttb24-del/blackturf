"""Un cheval non-partant ne s'évalue pas.

Contexte (production, 2026-08-19). ``db_writer`` supprimait la prédiction d'un
cheval déclaré non-partant pour le retirer du pronostic. Depuis la migration 0029,
``prediction_snapshots`` référence ``predictions`` par clé étrangère : la
suppression était refusée et c'est la transaction de la course ENTIÈRE qui était
annulée — plus aucune sauvegarde ne passait pour les courses déjà snapshotées (ni
cotes, ni statut non-partant, ni résultats). Le même piège existait avec
``value_bets``, dont la clé étrangère vers ``predictions`` est aussi en NO ACTION.

Le correctif côté code cesse de supprimer : la prédiction reste en base, et c'est
``participations.non_partant`` — déjà mis à jour dans la même transaction — qui
fait autorité. Reste alors ce que cette migration corrige : la ligne survit donc
dans ``prediction_evaluation``, où les calibrateurs (isotonique, longshots, cotes)
la compteraient en PERDANTE alors que le cheval n'a jamais couru, rabaissant les
probabilités pour rien. La vue exclut désormais les non-partants sur ses deux
branches (snapshot et legacy).

Aucune clé étrangère n'est touchée : sans suppression de prédiction, elles ne sont
plus violées, et le journal reste vérifiable.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-19
"""
from alembic import op


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


VUE_AVEC_FILTRE_NON_PARTANT = """
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
    LEFT JOIN participations pa_snap
      ON pa_snap.participation_id = ps.participation_id
    WHERE ps.is_pre_course = true
      AND ps.is_replayable = true
      AND COALESCE(pa_snap.non_partant, false) = false
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
LEFT JOIN participations pa_legacy
  ON pa_legacy.participation_id = p.participation_id
WHERE NOT EXISTS (
    SELECT 1 FROM latest_snapshot s
    WHERE s.participation_id = p.participation_id
)
  AND COALESCE(pa_legacy.non_partant, false) = false
"""


VUE_0030_SANS_FILTRE = """
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


def upgrade() -> None:
    op.execute(VUE_AVEC_FILTRE_NON_PARTANT)


def downgrade() -> None:
    op.execute(VUE_0030_SANS_FILTRE)
