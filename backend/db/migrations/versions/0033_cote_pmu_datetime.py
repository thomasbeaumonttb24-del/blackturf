"""Heure de publication de la cote par la SOURCE (PMU dateRapport).

`participations.updated_at` date le SCRAPE, pas la cote : le PMU republie la même
valeur tant que le marché ne bouge pas, donc un scrape récent ne prouve en rien
une cote fraîche. Le champ `dernierRapportDirect.dateRapport` (epoch ms) était
disponible dans la réponse PMU depuis toujours et simplement ignoré.

Sans lui, impossible de distinguer « cote à jour » de « cote figée depuis des
heures », ni de dater honnêtement la cote gelée d'un pronostic
(`prediction_snapshots.odds_observed_at` valait l'heure du CALCUL).

Colonne nullable, aucun backfill : les lignes antérieures n'ont pas cette
information et ne doivent pas se voir attribuer une date fabriquée.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-18
"""
from alembic import op


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE participations "
        "ADD COLUMN IF NOT EXISTS cote_pmu_datetime TIMESTAMPTZ"
    )
    # Lecture typique du moniteur de fraîcheur : « quelles cotes d'une course à
    # venir n'ont pas bougé depuis N minutes ». Index partiel : seules les lignes
    # renseignées sont utiles, et elles resteront minoritaires longtemps.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_participations_cote_pmu_datetime "
        "ON participations (cote_pmu_datetime) "
        "WHERE cote_pmu_datetime IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_participations_cote_pmu_datetime")
    op.execute("ALTER TABLE participations DROP COLUMN IF EXISTS cote_pmu_datetime")
