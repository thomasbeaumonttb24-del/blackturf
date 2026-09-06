"""Enjeux PMU : périmètre du relevé, combinaisons, masses par formule, origine.

Quatre colonnes, un même sujet — savoir où va vraiment l'argent d'une course.

Le PMU sert `combinaisons` sous DEUX périmètres, et pas le même selon la course.
Sans paramètre, il renvoie la masse nationale (guichets + en ligne) — mais il
répond 204 sur une grande partie de son offre : mesuré le 2026-09-06 sur 7 jours
de courses réglées, aucune course après 23 h n'avait d'enjeux, 8 % à 22 h, 29 %
à 21 h, et des réunions entières n'en avaient jamais (Rambouillet 0/9, Laval
0/8, Saratoga 0/10, Solvalla 0/9). Avec `?specialisation=INTERNET`, ces mêmes
courses répondent 200 avec le détail par cheval.

On lit donc le national en premier et l'en-ligne en repli. Les deux masses ne se
comparent pas : sur 06092026R8C4, SIMPLE_GAGNANT valait 42 658 € au national
contre 8 119 € en ligne, soit 19 %. Une série qui passerait de l'un à l'autre
afficherait une chute de 81 % de la masse et des « afflux » imaginaires à chaque
bascule. Le périmètre est donc stocké AVEC le relevé, et la lecture ne mélange
jamais deux périmètres dans une même série.

NULL = relevé écrit avant cette migration, donc national : c'était le seul
périmètre lu jusqu'ici. On ne réécrit pas les lignes existantes — la valeur par
défaut est portée à la lecture, ce qui évite un UPDATE sur une timeseries pour
une information qu'on connaît déjà.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-06
"""
from alembic import op


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col, type_ in (
        ("perimetre", "VARCHAR(10)"),
        # Combinaisons à plusieurs chevaux (couplé, trio, 2 sur 4…) : le PMU les
        # publie dans le MÊME payload que les simples, et on les jetait. Sur
        # 05092026R1C1, le simple gagnant pesait 231 554 € pour 721 000 € toutes
        # formules : les deux tiers de l'argent n'étaient ni lus ni montrés.
        ("combines", "JSON"),
        # Masse par type de pari, y compris les types sans liste de combinaisons
        # (MINI_MULTI, MULTI…). C'est ce qui permet de dire quelle FORMULE porte
        # l'argent d'une course, pas seulement quel cheval.
        ("masses", "JSON"),
        # "live" = relevé pris avant le départ, seul utilisable pour juger un
        # mouvement de marché. "backfill" = photo FINALE reconstituée après coup :
        # elle connaît l'issue des paris et ne doit JAMAIS servir de signal
        # pré-course, sous peine de fuite de données dans l'apprentissage.
        ("source", "VARCHAR(10)"),
    ):
        op.execute(
            f"ALTER TABLE enjeux_course_historique ADD COLUMN IF NOT EXISTS {col} {type_}"
        )


def downgrade() -> None:
    for col in ("perimetre", "combines", "masses", "source"):
        op.execute(
            f"ALTER TABLE enjeux_course_historique DROP COLUMN IF EXISTS {col}"
        )
