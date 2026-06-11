"""Flag `est_2sur4` sur courses — 2sur4 réellement proposé par le PMU.

Le 2sur4 (DEUX_SUR_QUATRE) n'est offert que sur CERTAINES courses, indépendamment
du nombre de partants. L'ancienne heuristique « ≥8 partants » générait des pronos
2sur4 impossibles (ex. R6C7 : ≥8 partants mais pas de 2sur4 au PMU). On stocke
désormais la disponibilité RÉELLE déduite de `paris[].codePari` du programme PMU.

Défaut FALSE : tant qu'une course n'a pas été (re)scrapée avec ce champ, aucun
prono 2sur4 ne sera proposé — on préfère rater un 2sur4 valide qu'en proposer un
impossible. Les courses live sont re-scrapées à chaque cycle → flag correct.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-11
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS est_2sur4 BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS est_2sur4")
