"""Journal des publications sociales — pour ne jamais publier deux fois la même.

La story de bilan devient automatique : un job la publie dès que la journée est
courue ET réglée. Ce moment n'a pas d'heure fixe — le 2026-09-06, les 165 derniers
plans du 5 n'ont été réglés qu'à 04 h 19 — donc le job ne peut pas tourner « une
fois, à 23 h » : il repasse toutes les demi-heures et publie la première journée
qui devient publiable.

Un job qui repasse a besoin d'une MÉMOIRE, sinon il republie à chaque passage. Cette
mémoire ne peut pas vivre en RAM : le conteneur redémarre à chaque déploiement, et
un redéploiement à 5 h du matin republierait la story du jour. L'unicité porte donc
sur (jour, canal) et c'est la BASE qui interdit le doublon, pas le code.

Les échecs sont enregistrés eux aussi, avec leur raison, mais SANS bloquer une
nouvelle tentative : `publie_at` reste NULL tant que rien n'est parti, et le job
retente au passage suivant. Un jeton expiré à 23 h doit pouvoir publier à 23 h 30 ;
une publication réussie, jamais deux fois.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-06
"""
from alembic import op


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS publications_sociales (
            publication_id   VARCHAR(36) PRIMARY KEY,
            -- Jour PMU illustré, au format AAAA-MM-JJ. C'est la clé métier : deux
            -- stories du même jour, c'est le défaut qu'on interdit.
            jour             VARCHAR(10)  NOT NULL,
            canal            VARCHAR(30)  NOT NULL,
            media_id         VARCHAR(64),
            -- NULL tant que rien n'est parti : le job peut donc retenter.
            publie_at        TIMESTAMPTZ,
            derniere_tentative_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            nb_tentatives    INTEGER      NOT NULL DEFAULT 0,
            derniere_raison  VARCHAR(300),
            CONSTRAINT uq_publication_jour_canal UNIQUE (jour, canal)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_publications_sociales_canal_jour "
        "ON publications_sociales (canal, jour)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS publications_sociales")
