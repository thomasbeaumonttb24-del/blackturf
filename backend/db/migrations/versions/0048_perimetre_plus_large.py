"""Élargir `enjeux_course_historique.perimetre` : « international » fait 13 caractères.

La colonne avait été créée en VARCHAR(10) alors qu'on ne connaissait que deux
périmètres (« total », « internet »). Le troisième, découvert le 2026-09-07 —
la masse commune avec le pays organisateur, qui porte les plus gros montants de
la base (3,8 M€ sur une course de Happy Valley) — dépasse la largeur.

PostgreSQL a REFUSÉ l'écriture (StringDataRightTruncationError) au lieu de
tronquer : 841 courses en erreur, zéro donnée fausse. C'est le bon comportement,
et la raison pour laquelle on garde des largeurs contraintes plutôt qu'un TEXT
partout — mais il faut alors les élargir quand le domaine s'élargit.

VARCHAR(20) laisse la place à un quatrième périmètre sans nouvelle migration.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-07
"""
from alembic import op


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE enjeux_course_historique "
        "ALTER COLUMN perimetre TYPE VARCHAR(20)"
    )


def downgrade() -> None:
    # Rétrécir tronquerait les valeurs « international » déjà écrites : on les
    # efface plutôt que de les rendre fausses.
    op.execute(
        "UPDATE enjeux_course_historique SET perimetre = NULL "
        "WHERE length(perimetre) > 10"
    )
    op.execute(
        "ALTER TABLE enjeux_course_historique "
        "ALTER COLUMN perimetre TYPE VARCHAR(10)"
    )
