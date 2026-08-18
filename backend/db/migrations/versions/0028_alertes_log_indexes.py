"""Index de lecture sur alertes_log (centre de notifications).

`alertes_log` dépasse 200 000 lignes (chaque value bet écrit une ligne par canal ×
par utilisateur payant) et ne portait AUCUN index hors clé primaire : la colonne
`user_id` est une simple FK. Chaque ouverture de /notifications faisait donc deux
seq scans complets (liste + compteur de non lues), et le badge navbar un troisième
toutes les 60 secondes.

  - ix_alertes_log_user_created : liste paginée d'un utilisateur (ORDER BY created_at DESC)
  - ix_alertes_log_user_unread  : index PARTIEL sur les non lues → compteur badge
  - ix_alertes_log_created      : purge/rétention et back-office admin (ORDER BY created_at)

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-17
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_alertes_log_user_created "
        "ON alertes_log (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_alertes_log_user_unread "
        "ON alertes_log (user_id) WHERE lue = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_alertes_log_created "
        "ON alertes_log (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_alertes_log_user_created")
    op.execute("DROP INDEX IF EXISTS ix_alertes_log_user_unread")
    op.execute("DROP INDEX IF EXISTS ix_alertes_log_created")
