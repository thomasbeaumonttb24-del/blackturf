"""Colonne `paris_disponibles` sur courses — liste RÉELLE des paris PMU offerts.

Le PMU n'offre pas les mêmes paris sur toutes les courses : un champ réduit
remplace le Couplé Gagnant/Placé par un Couplé ORDRE (E_COUPLE_ORDRE), idem
Trio → Trio Ordre (E_TRIO_ORDRE). Les booléens est_tierce/quarte/quinte/2sur4
ne suffisent plus : on stocke la LISTE complète des `paris[].codePari` du
programme PMU (ex. ["E_SIMPLE_GAGNANT","E_COUPLE_ORDRE","E_TRIO_ORDRE",...]) pour
ne JAMAIS proposer un pari que la course n'accepte pas, et proposer les paris à
l'ordre quand le champ réduit l'impose.

Défaut NULL : tant qu'une course n'a pas été (re)scrapée avec ce champ, on
retombe sur les booléens est_* existants (rétro-compat). Les courses live sont
re-scrapées à chaque cycle → liste correcte.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-14
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS paris_disponibles JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS paris_disponibles")
