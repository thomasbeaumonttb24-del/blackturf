"""Dédup historique_courses (cheval_id, course_id) + index unique partiel.

_save_historical_course faisait on_conflict_do_nothing sans cible → PK uuid neuf à
chaque run → jamais de conflit → doublons (jusqu'à 10x par cheval/course). Fausse
le dataset d'entraînement. On dédoublonne puis on pose un index unique partiel ciblé.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-06
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) dédoublonnage : garder la ligne la plus récente par (cheval_id, course_id)
    op.execute("""
        DELETE FROM historique_courses a
        USING historique_courses b
        WHERE a.course_id IS NOT NULL
          AND a.course_id = b.course_id
          AND a.cheval_id = b.cheval_id
          AND a.ctid < b.ctid
    """)
    # 2) index unique partiel (sert de cible ON CONFLICT)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_hist_cheval_course
        ON historique_courses (cheval_id, course_id)
        WHERE course_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_hist_cheval_course")
