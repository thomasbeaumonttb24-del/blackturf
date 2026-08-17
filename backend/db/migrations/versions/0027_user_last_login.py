"""Dernière connexion réelle des utilisateurs.

`users.updated_at` bouge à toute modification de la ligne (plan, bankroll,
profil…) et ne reflète pas si le compte est utilisé. Cette colonne est posée
au login (email/Google) et à la reprise de session (/auth/me), NULL tant que
l'utilisateur ne s'est jamais reconnecté après ce déploiement.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-17
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at")
