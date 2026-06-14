"""Colonnes `proba_top1_raw` / `proba_top3_raw` sur predictions — proba MODÈLE BRUTE.

Audit edge 2026-06-14 : les calibrations (isotonic top1/top3, longshot, cote)
étaient fittées sur `proba_top1` qui est la proba DÉJÀ calibrée (temperature +
blend marché + longshot + isotonic). Boucle fermée : le modèle calibrait sa
propre sortie → ECE faussement bas, ne mesure jamais le vrai mapping brut→réel.

On persiste donc la proba modèle BRUTE (avant toute correction post-hoc) pour
que les calibrateurs apprennent brut→résultat (FLAG BT_CALIB_ON_RAW).

Nullable + défaut NULL : rétro-compat. predict_course ne remplit ces colonnes
que lorsque BT_CALIB_ON_RAW est actif ; sinon elles restent NULL et les
calibrateurs retombent sur proba_top1/proba_top3 (comportement historique).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-14
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE predictions ADD COLUMN IF NOT EXISTS proba_top1_raw DOUBLE PRECISION")
    op.execute("ALTER TABLE predictions ADD COLUMN IF NOT EXISTS proba_top3_raw DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE predictions DROP COLUMN IF EXISTS proba_top3_raw")
    op.execute("ALTER TABLE predictions DROP COLUMN IF EXISTS proba_top1_raw")
