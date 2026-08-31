"""Mémoriser la date de la dernière course vue à l'entraînement d'un modèle.

Contexte (2026-08-31). L'arbitrage champion/challenger (`_head_to_head_auc`) est
décrit dans le code comme « la seule comparaison honnête entre deux modèles ». Il
ne s'est en réalité JAMAIS exécuté : chaque nuit
`pipeline.h2h.sample_too_small n_rows=381 min_rows=2000`.

La cause est une confusion entre deux dates. Pour comparer équitablement, le
head-to-head ne garde que les courses qu'AUCUN des deux modèles n'a vues, et il
prenait pour borne `model_versions.created_at` — la date de PROMOTION du champion.
Or `BlackTurfEnsemble.train()` réserve les 20 % de courses les plus récentes en
hold-out et n'entraîne que sur les 80 % antérieurs : un modèle promu hier s'est en
fait arrêté d'apprendre environ 73 jours plus tôt. Borner à sa promotion jetait
donc ~73 jours de hold-out parfaitement valides pour n'en garder qu'un — d'où les
381 lignes, sous le seuil de 2 000, toutes les nuits. Le repli était le
walk-forward, que le même fichier déclare non comparable d'une génération de
données à l'autre.

`train_fin` porte la date de la dernière course RÉELLEMENT apprise. Elle est
renseignée à chaque promotion à partir du dernier `course_id` du côté entraînement
du découpage.

Colonne NULLABLE et sans rattrapage : la valeur ne peut pas être reconstruite
après coup (le dataset a changé depuis), et l'inventer serait pire que l'ignorer —
une borne surestimée ferait noter le champion sur des courses qu'il a apprises,
donc lui donnerait un avantage mécanique. Tant qu'elle est NULL, le head-to-head
retombe sur l'ancienne borne stricte : le comportement reste exactement celui
d'aujourd'hui, et l'arbitrage redevient possible dès la première promotion qui
suit cette migration.

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("train_fin", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_versions", "train_fin")
