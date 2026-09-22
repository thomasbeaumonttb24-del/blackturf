"""Casaque jockey : image PMU par partant.

`participations.casaque_image_url` — urlCasaque renvoyée par l'API PMU pour chaque
partant, une image PNG générée pour CETTE course/numPmu (ex.
.../20260922-AUT-1-1.png). Stockée sur `participations` (pas `chevaux`) car l'image
est propre à la course, pas au cheval : le même cheval peut avoir des casaques
différentes d'une course à l'autre.

Aucun champ texte descriptif de casaque n'existe côté API PMU (contrairement à
`chevaux.casaque_description`, jamais alimentée) : seule l'image est disponible.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participations", sa.Column("casaque_image_url", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("participations", "casaque_image_url")
