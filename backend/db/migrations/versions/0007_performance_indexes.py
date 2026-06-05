"""Performance indexes for new columns + partial indexes for enrichissement queries.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── participations — colonnes bookmakers (requêtes VB detection) ──────────
    try:
        # Index partiel : uniquement les lignes avec cote_betfair renseignée
        op.create_index(
            "ix_participations_betfair",
            "participations", ["cote_betfair_exchange"],
            postgresql_where=sa.text("cote_betfair_exchange IS NOT NULL"),
        )
        op.create_index(
            "ix_participations_winamax",
            "participations", ["cote_winamax"],
            postgresql_where=sa.text("cote_winamax IS NOT NULL"),
        )
        op.create_index(
            "ix_participations_jours_null",
            "participations", ["participation_id"],
            postgresql_where=sa.text("jours_depuis_derniere IS NULL AND non_partant = false"),
        )
        op.create_index(
            "ix_participations_changement_jockey",
            "participations", ["course_id"],
            postgresql_where=sa.text("changement_jockey = true"),
        )
    except Exception as e:
        print(f"participations indexes: {e}")

    # ── courses — pénétromètre + pool ─────────────────────────────────────────
    try:
        op.create_index(
            "ix_courses_penetrometre",
            "courses", ["penetrometre_coef"],
            postgresql_where=sa.text("penetrometre_coef IS NOT NULL"),
        )
        op.create_index(
            "ix_courses_pool",
            "courses", ["pool_total_centimes"],
            postgresql_where=sa.text("pool_total_centimes IS NOT NULL"),
        )
    except Exception as e:
        print(f"courses indexes: {e}")

    # ── chevaux — running style ────────────────────────────────────────────────
    try:
        op.create_index(
            "ix_chevaux_running_style",
            "chevaux", ["running_style"],
            postgresql_where=sa.text("running_style IS NOT NULL"),
        )
        op.create_index(
            "ix_chevaux_no_pedigree",
            "chevaux", ["cheval_id"],
            postgresql_where=sa.text("pere IS NULL"),
        )
    except Exception as e:
        print(f"chevaux indexes: {e}")

    # ── cotes_historique — accélère les requêtes de mouvement par source ───────
    try:
        op.create_index(
            "ix_cotes_historique_pid_source_time",
            "cotes_historique",
            ["participation_id", "source", "time"],
        )
    except Exception as e:
        print(f"cotes_historique index: {e}")

    # ── cotes_bookmakers — recherche par source + date ────────────────────────
    try:
        op.create_index(
            "ix_cotes_bookmakers_scraped_at",
            "cotes_bookmakers", ["scraped_at"],
        )
    except Exception as e:
        print(f"cotes_bookmakers index: {e}")

    # ── pool_pmu_historique — séries temporelles par course ──────────────────
    try:
        op.create_index(
            "ix_pool_historique_course_time",
            "pool_pmu_historique", ["course_id", "scraped_at"],
        )
    except Exception as e:
        print(f"pool_pmu_historique index: {e}")

    # ── suspensions — recherche par date (query quotidienne) ─────────────────
    try:
        op.create_index(
            "ix_suspensions_active_today",
            "suspensions_professionnels", ["nom"],
            postgresql_where=sa.text("est_active = true"),
        )
    except Exception as e:
        print(f"suspensions index: {e}")

    # ── pronostics_presse — JSON index sur selection (GIN) ────────────────────
    try:
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pronostics_selection_gin "
            "ON pronostics_presse USING gin(selection jsonb_path_ops)"
        )
    except Exception as e:
        print(f"pronostics_presse GIN index: {e}")

    # ── associations_jockey_entraineur — saison courante ─────────────────────
    try:
        op.create_index(
            "ix_asso_saison",
            "associations_jockey_entraineur", ["saison", "jockey_id", "entraineur_id"],
        )
    except Exception as e:
        print(f"associations index: {e}")

    # ── historique_courses — optimiser les requêtes features batch ────────────
    try:
        # Index composite pour la requête batch principale
        op.create_index(
            "ix_historique_cheval_date_comp",
            "historique_courses",
            ["cheval_id", "date_course", "position_arrivee"],
        )
    except Exception as e:
        print(f"historique_courses index: {e}")


def downgrade() -> None:
    indexes = [
        ("ix_participations_betfair", "participations"),
        ("ix_participations_winamax", "participations"),
        ("ix_participations_jours_null", "participations"),
        ("ix_participations_changement_jockey", "participations"),
        ("ix_courses_penetrometre", "courses"),
        ("ix_courses_pool", "courses"),
        ("ix_chevaux_running_style", "chevaux"),
        ("ix_chevaux_no_pedigree", "chevaux"),
        ("ix_cotes_historique_pid_source_time", "cotes_historique"),
        ("ix_cotes_bookmakers_scraped_at", "cotes_bookmakers"),
        ("ix_pool_historique_course_time", "pool_pmu_historique"),
        ("ix_suspensions_active_today", "suspensions_professionnels"),
        ("ix_asso_saison", "associations_jockey_entraineur"),
        ("ix_historique_cheval_date_comp", "historique_courses"),
    ]
    for idx_name, table in indexes:
        try:
            op.drop_index(idx_name, table_name=table)
        except Exception:
            pass
    try:
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_pronostics_selection_gin")
    except Exception:
        pass
