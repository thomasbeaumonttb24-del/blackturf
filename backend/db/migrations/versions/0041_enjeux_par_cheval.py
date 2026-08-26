"""Les enjeux PMU cheval par cheval : on sait enfin SUR QUI part l'argent.

Contexte (2026-08-26). Jusqu'ici BlackTurf ne stockait que la masse globale d'une
course (`pool_pmu_historique`) : « 39 926 € misés sur cette course ». Le PMU publie
pourtant, via l'endpoint `combinaisons`, le montant réellement joué sur CHAQUE
cheval en simple gagnant et en simple placé. C'était la donnée la plus parlante du
marché, et elle n'était pas collectée.

Choix de forme : une ligne par relevé, la répartition en JSON — et non une ligne
par cheval. On lit toujours la série d'une course en entier ; le format étroit
aurait produit environ 250 000 lignes par jour pour exactement la même
information, avec le coût de requête qu'on connaît déjà sur `cotes_historique`.

`autres_*_centimes` porte la queue du peloton : le PMU plafonne sa liste à 12
chevaux, donc au-delà de 12 partants la masse des non-listés est connue
globalement (masse − somme des listés) mais pas cheval par cheval. On la stocke
telle quelle plutôt que de la répartir arbitrairement.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enjeux_course_historique",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("maj_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("masse_gagnant_centimes", sa.BigInteger(), nullable=True),
        sa.Column("masse_place_centimes", sa.BigInteger(), nullable=True),
        sa.Column("enjeux", sa.JSON(), nullable=False),
        sa.Column("autres_gagnant_centimes", sa.BigInteger(), nullable=True),
        sa.Column("autres_place_centimes", sa.BigInteger(), nullable=True),
        sa.Column("nb_autres", sa.Integer(), nullable=True),
    )
    op.create_index("ix_enjeux_course_historique_course_id", "enjeux_course_historique", ["course_id"])
    op.create_index("ix_enjeux_course_historique_scraped_at", "enjeux_course_historique", ["scraped_at"])
    # L'accès réel est toujours « la série d'UNE course, dans l'ordre » : index composite.
    op.create_index("ix_enjeux_course_time", "enjeux_course_historique", ["course_id", "scraped_at"])


def downgrade() -> None:
    op.drop_index("ix_enjeux_course_time", table_name="enjeux_course_historique")
    op.drop_index("ix_enjeux_course_historique_scraped_at", table_name="enjeux_course_historique")
    op.drop_index("ix_enjeux_course_historique_course_id", table_name="enjeux_course_historique")
    op.drop_table("enjeux_course_historique")
