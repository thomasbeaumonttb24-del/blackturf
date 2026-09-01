"""Une anomalie qui dure est UNE anomalie, pas une par heure.

Contexte (2026-09-01). Le back-office annonçait « 42 ouvertes » sur 72 h. Il n'y
avait en réalité que **trois** faits distincts : la dérive de calibration de la
bande 0,40-0,50, les features à variance nulle, et deux
`TooManyConnectionsError`. Les 40 premières lignes sont le même couple de
messages réécrit toutes les heures par `job_data_quality_check` (cron minute 20),
qui appelait `record_error` sans jamais regarder si l'anomalie était déjà
ouverte.

Ce n'est pas un défaut cosmétique. Un compteur qui grossit à cadence fixe
DÉTRUIT l'information qu'il est censé porter : il ne distingue plus « un
problème qui dure depuis 20 h » de « vingt problèmes différents », il repousse
hors des huit premières lignes affichées toute anomalie réellement nouvelle, et
il rend « marquer résolu » inopérant puisque la ligne suivante réapparaît une
heure plus tard.

Réparation : une CLÉ de déduplication, et un index unique PARTIEL sur les seules
lignes ouvertes. Deux occurrences de la même clé fusionnent (`ON CONFLICT DO
UPDATE`) en incrémentant `occurrences` et en repoussant `derniere_occurrence` ;
`created_at` garde la PREMIÈRE apparition — c'est la durée du problème qui
intéresse, pas son dernier écho. Le prédicat `WHERE resolved = false` est ce qui
rend le geste « marquer résolu » réellement utile : une fois la ligne close, une
réapparition ouvre une NOUVELLE ligne, visiblement datée d'après la résolution.

Les lignes sans clé (`cle IS NULL`) ne se dédupliquent pas — NULL n'entre pas en
conflit avec NULL. Un appelant qui ne sait pas nommer son anomalie garde donc
exactement le comportement d'avant.

Rattrapage de l'existant : la clé des alertes `data_quality` est déjà en base,
c'est `detail` (il porte le code de l'anomalie depuis l'origine). On la recopie,
puis on replie chaque famille sur sa ligne la plus ANCIENNE — celle qui date le
début du problème — en sommant les occurrences, et on marque les autres
résolues. Sans ce repli, la création de l'index unique échouerait sur les
doublons déjà présents.

La table est auto-créée par `services/error_monitor` (`CREATE TABLE IF NOT
EXISTS`, même mécanique que `signal_performance`) : elle peut donc ne pas exister
au moment de la migration, sur une base neuve. Tout est écrit en `IF NOT EXISTS`
pour valoir dans les deux sens, et `_ensure` côté runtime pose les mêmes colonnes
— une base créée par le code seul, sans alembic, reste correcte.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-01
"""
from alembic import op


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS system_errors (
            id         BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            source     VARCHAR(80)  NOT NULL,
            level      VARCHAR(20)  NOT NULL DEFAULT 'error',
            message    TEXT         NOT NULL,
            detail     TEXT,
            endpoint   VARCHAR(300),
            resolved   BOOLEAN      NOT NULL DEFAULT false
        )
    """)
    op.execute("ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS cle VARCHAR(160)")
    op.execute("ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS occurrences INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE system_errors ADD COLUMN IF NOT EXISTS derniere_occurrence TIMESTAMPTZ")
    op.execute("UPDATE system_errors SET derniere_occurrence = created_at WHERE derniere_occurrence IS NULL")

    # `detail` porte le code de l'anomalie pour toutes les lignes `data_quality`
    # (`verifier_et_alerter` le pose depuis l'origine) : la clé existe déjà, il
    # suffit de la nommer. Les autres sources n'avaient pas d'identité stable —
    # elles n'en reçoivent pas rétroactivement, seules leurs nouvelles lignes en
    # auront une.
    op.execute("""
        UPDATE system_errors
           SET cle = left(detail, 160)
         WHERE cle IS NULL AND source = 'data_quality'
           AND detail IS NOT NULL AND detail <> ''
    """)

    # Repli des doublons ouverts sur la ligne la PLUS ANCIENNE de chaque famille :
    # c'est elle qui date le début du problème. Les autres sont closes plutôt que
    # supprimées — une ligne d'historique effacée est une mesure perdue.
    op.execute("""
        WITH agrege AS (
            SELECT source, cle,
                   min(id)         AS garde,
                   sum(occurrences) AS n,
                   max(coalesce(derniere_occurrence, created_at)) AS derniere
              FROM system_errors
             WHERE resolved = false AND cle IS NOT NULL
             GROUP BY source, cle
        )
        UPDATE system_errors e
           SET occurrences = a.n,
               derniere_occurrence = a.derniere
          FROM agrege a
         WHERE e.id = a.garde AND a.n > e.occurrences
    """)
    op.execute("""
        WITH gardes AS (
            SELECT min(id) AS garde FROM system_errors
             WHERE resolved = false AND cle IS NOT NULL
             GROUP BY source, cle
        )
        UPDATE system_errors e
           SET resolved = true
         WHERE e.resolved = false AND e.cle IS NOT NULL
           AND e.id NOT IN (SELECT garde FROM gardes)
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_system_errors_cle_ouverte
            ON system_errors (source, cle) WHERE resolved = false
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_system_errors_cle_ouverte")
    op.execute("ALTER TABLE system_errors DROP COLUMN IF EXISTS derniere_occurrence")
    op.execute("ALTER TABLE system_errors DROP COLUMN IF EXISTS occurrences")
    op.execute("ALTER TABLE system_errors DROP COLUMN IF EXISTS cle")
