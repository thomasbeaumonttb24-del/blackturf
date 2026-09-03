"""Cliquet anti-dérive de la promotion nocturne, et provenance de la mesure de rang.

Contexte (2026-09-03). Deux défauts distincts, tous deux nommés dans les audits
précédents et laissés ouverts.

1. AUCUN CLIQUET. `_should_deploy` tolère délibérément une régression du
   head-to-head jusqu'à `h2h_tolerance` (0,002), mais toujours CONTRE LE CHAMPION
   DE LA VEILLE, jamais contre le meilleur niveau jamais atteint. Une dérive de
   quelques dix-millièmes par nuit est donc acceptée indéfiniment : mesuré du 25
   au 31/08, le classement est passé de 0,7632 à 0,7608 et le walk-forward de
   0,7886 à 0,7869 sans qu'aucune nuit ne dépasse le seuil. Le rapport matinal le
   dit lui-même : « une baisse répétée sous le seuil de tolérance est acceptée
   nuit après nuit ».

   `retrain_ratchet` porte la DETTE : la somme des régressions déjà acceptées
   depuis le dernier niveau record. Le gate ne compare plus le challenger au seul
   champion mais à `dette + delta`, c'est-à-dire à la distance qui le sépare du
   meilleur niveau. Une nuit qui progresse rembourse la dette ; la dette ne peut
   jamais devenir un crédit (plafonnée à 0), sans quoi une bonne nuit achèterait
   le droit de reculer les suivantes.

   Ce n'est PAS le gel de l'audit 2026-08-16 : ce gel-là venait d'une référence
   FIGÉE (un walk-forward de juin, mesuré sur un autre dataset) que rien ne
   recalculait. Ici la référence est un cumul de deltas mesurés chaque nuit sur un
   hold-out commun aux deux modèles, et une seule nuit meilleure la remet à zéro.

2. LA PROVENANCE DE `rank_auc` N'ÉTAIT PAS ENREGISTRÉE. Jusqu'au 2026-09-02 le
   trio `rank_auc` / `market_rank_auc` / `rank_delta_market` recevait la mesure du
   WALK-FORWARD — un XGBoost jetable de 100 arbres — et non celle de l'ensemble
   réellement déployé. Corrigé le 02/09, mais les versions déjà en base gardent
   l'ancienne mesure : v527 porte +0,0190 là où le hold-out du vrai ensemble donne
   −0,0472 sur la même nuit. Le rapport matinal compare le modèle du jour à son
   « record historique » : sans marqueur de provenance il comparerait une mesure
   de hold-out à un record de walk-forward et annoncerait chaque matin une chute
   de 0,066 qui n'a jamais eu lieu.

   `rank_source` vaut `hold_out`, `h2h` ou `walk_forward` (cf.
   `ml.pipeline._source_rang_marche`). NULL = versions antérieures à cette
   migration, dont la provenance ne peut pas être reconstruite après coup : le
   rapport les traite comme non comparables plutôt que d'inventer une valeur.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("rank_source", sa.String(16), nullable=True),
    )
    op.create_table(
        "retrain_ratchet",
        # Ligne unique (id = 1) : il n'y a qu'un champion à la fois.
        sa.Column("id", sa.Integer, primary_key=True),
        # Dette cumulée, en points d'AUC de classement. TOUJOURS <= 0.
        sa.Column("dette", sa.Float, nullable=False, server_default="0"),
        # Version depuis laquelle la dette court — sert au diagnostic : une dette
        # ancienne signale une dérive lente, une dette d'hier une simple nuit molle.
        sa.Column("depuis_version", sa.Integer, nullable=True),
        # TIMESTAMPTZ et non TIMESTAMP : asyncpg refuse un datetime avec fuseau sur
        # une colonne sans fuseau, et le défaut ne se voit qu'en production.
        sa.Column("maj", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("retrain_ratchet")
    op.drop_column("model_versions", "rank_source")
