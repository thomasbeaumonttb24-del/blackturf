"""Le classement des modèles était mesuré, mais jamais celui du marché.

Contexte (diagnostic algorithmique, 2026-08-20). ``model_versions`` ne stockait
que des AUC **poolées** — ``auc_roc``, ``walk_forward_auc`` — calculées sur
toutes les lignes de toutes les courses mélangées. Cette métrique mélange la
variance INTER-course et le classement INTRA-course, alors que le produit ne
fait qu'ordonner les partants d'une même course. Un modèle qui se contente de
relire la cote y obtient un excellent score.

Mesuré sur 3 322 courses de la cohorte pré-course : le modèle complet obtient
0,7340 d'AUC intra-course contre 0,7351 pour la cote qu'il avait sous les yeux.
Aucune ligne du code ne posait cette comparaison ; le gate de promotion ne
confrontait le challenger qu'au champion précédent. 513 versions ont donc pu se
succéder sous le niveau d'un simple ``ORDER BY cote_pmu`` sans qu'aucune alerte
ne se déclenche.

Cette migration ajoute les trois colonnes qui rendent le fait vérifiable dans le
temps : le classement du modèle, celui du marché sur le même échantillon, et
leur écart. Elles sont NULLABLES sans valeur par défaut — les 513 versions
antérieures n'ont pas été mesurées ainsi, et leur inventer un zéro les ferait
passer pour « à égalité avec le marché », exactement le faux positif que ce
travail cherche à rendre impossible.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


COLONNES = (
    # AUC de classement intra-course du modèle (moyenne des folds walk-forward).
    ("rank_auc", "AUC de classement intra-course du modele (0.5 = hasard)"),
    # Même mesure pour un simple ORDER BY cote_pmu, sur exactement les mêmes folds.
    ("market_rank_auc", "Meme mesure pour ORDER BY cote_pmu sur les memes folds"),
    # rank_auc - market_rank_auc. Negatif = le produit ferait mieux sans modele.
    ("rank_delta_market", "Ecart au marche ; negatif = modele inutile au classement"),
)


def upgrade() -> None:
    for nom, commentaire in COLONNES:
        op.add_column(
            "model_versions",
            sa.Column(nom, sa.Float(), nullable=True, comment=commentaire),
        )


def downgrade() -> None:
    for nom, _ in reversed(COLONNES):
        op.drop_column("model_versions", nom)
