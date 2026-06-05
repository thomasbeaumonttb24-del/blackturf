"""Race dynamics columns on historique_courses (Phase 1).

Adds per-past-race dynamics signals consumed by ML features :
  - reduction_km        : individual time per km (trot reference), s/km
  - acceleration_index  : final-400m speed / average speed
  - acceleration_label  : accelere / regulier / faiblit
  - commentaire_course  : in-running comment / déroulé (scraper, Phase 1.1)

All nullable — never fabricated, NULL when the source datum is missing.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("reduction_km", sa.Float()),
    ("acceleration_index", sa.Float()),
    ("acceleration_label", sa.String(length=15)),
    ("commentaire_course", sa.Text()),
]


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        try:
            op.add_column("historique_courses", sa.Column(name, type_, nullable=True))
        except Exception:
            # Idempotence : colonne déjà présente (re-run / env partiel)
            pass


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        try:
            op.drop_column("historique_courses", name)
        except Exception:
            pass
