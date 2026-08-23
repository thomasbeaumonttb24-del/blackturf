"""Le jeton Instagram ne peut vivre ni dans un fichier .env, ni dans un presse-papiers.

Contexte (2026-08-23). Deux contraintes se rencontrent ici :

1. Un jeton d'accès Instagram est un SECRET : quiconque le lit publie au nom de la
   marque. Il ne doit donc transiter ni par un chat, ni par un historique de shell.
2. L'exploitant n'a pas à savoir se connecter en SSH pour faire vivre son produit. Le
   collage doit se faire depuis une page d'administration, sur une connexion chiffrée.

D'où cette table : le jeton est déposé une seule fois depuis l'admin, puis vit côté
serveur. Elle porte AUSSI la date d'expiration, parce qu'un jeton longue durée Instagram
expire au bout de 60 jours : sans renouvellement automatique, la publication s'arrêterait
sans prévenir deux mois après la mise en service — le genre de panne qu'on ne découvre
que des semaines plus tard.

Une seule ligne par fournisseur (contrainte d'unicité) : deux jetons concurrents pour le
même compte, c'est la garantie d'utiliser le mauvais.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jetons_integration",
        sa.Column("jeton_id", sa.String(36), primary_key=True),
        # "instagram" aujourd'hui ; la table sert à tout fournisseur ultérieur.
        sa.Column("fournisseur", sa.String(30), nullable=False),
        sa.Column("valeur", sa.Text(), nullable=False),
        sa.Column("compte_id", sa.String(64), nullable=True),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dernier_renouvellement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("derniere_erreur", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ux_jetons_integration_fournisseur", "jetons_integration",
                    ["fournisseur"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_jetons_integration_fournisseur", table_name="jetons_integration")
    op.drop_table("jetons_integration")
