"""Champs PMU enrichis : mouvement de cote natif, avis entraîneur, forme granulaire,
commentaire post-course, race/robe.

Exploite davantage l'API PMU : dernierRapportReference (cote ouverture), indicateur
tendance, avisEntraineur, nombrePlacesSecond/Troisieme, handicapDistance,
indicateurInedit, jumentPleine, commentaireApresCourse, dureeCourse.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-06
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


PART_COLS = [
    ("cote_reference", "DOUBLE PRECISION"),
    ("tendance_cote", "VARCHAR(2)"),
    ("tendance_force", "DOUBLE PRECISION"),
    ("est_favori_pmu", "BOOLEAN"),
    ("avis_entraineur", "VARCHAR(20)"),
    ("nb_places_second", "INTEGER"),
    ("nb_places_troisieme", "INTEGER"),
    ("handicap_distance", "INTEGER"),
    ("indicateur_inedit", "BOOLEAN"),
    ("jument_pleine", "BOOLEAN"),
]


def upgrade() -> None:
    for col, typ in PART_COLS:
        op.execute(f"ALTER TABLE participations ADD COLUMN IF NOT EXISTS {col} {typ}")
    op.execute("ALTER TABLE chevaux ADD COLUMN IF NOT EXISTS race VARCHAR(40)")
    op.execute("ALTER TABLE resultats ADD COLUMN IF NOT EXISTS commentaire TEXT")
    op.execute("ALTER TABLE resultats ADD COLUMN IF NOT EXISTS duree_course INTEGER")


def downgrade() -> None:
    for col, _ in PART_COLS:
        op.execute(f"ALTER TABLE participations DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE chevaux DROP COLUMN IF EXISTS race")
    op.execute("ALTER TABLE resultats DROP COLUMN IF EXISTS commentaire")
    op.execute("ALTER TABLE resultats DROP COLUMN IF EXISTS duree_course")
