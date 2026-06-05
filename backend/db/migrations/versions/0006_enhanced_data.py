"""Enhanced data collection: new tables + new columns on existing tables.

Adds:
  - cotes_bookmakers (Winamax, Betclic, Unibet, Betfair Exchange)
  - pool_pmu_historique (smart-money / volume)
  - suspensions_professionnels (France Galop + LeTrot)
  - penetrometre_log (coefficients de sol officiels)
  - temps_passage (splits chronométriques)
  - pronostics_presse (Paris-Turf, CanalTurf, Geny Expert)
  - associations_jockey_entraineur (stats paire jockey × entraîneur)

  Columns on participations:
    cote_winamax, cote_betclic, cote_betclic_ouverture, cote_unibet,
    cote_betfair_exchange, jours_depuis_derniere, changement_jockey, poids_reel_pesee

  Columns on courses:
    penetrometre_coef, penetrometre_desc, pool_total_centimes,
    pool_gagnant_centimes, avantage_couloir

  Columns on chevaux:
    mere_de_mere, prix_vente_yearling, running_style, taux_en_tete, racing_post_url

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── participations — nouveaux champs ────────────────────────────────────
    try:
        op.add_column("participations", sa.Column("cote_winamax", sa.Float(), nullable=True))
        op.add_column("participations", sa.Column("cote_betclic", sa.Float(), nullable=True))
        op.add_column("participations", sa.Column("cote_betclic_ouverture", sa.Float(), nullable=True))
        op.add_column("participations", sa.Column("cote_unibet", sa.Float(), nullable=True))
        op.add_column("participations", sa.Column("cote_betfair_exchange", sa.Float(), nullable=True))
        op.add_column("participations", sa.Column("jours_depuis_derniere", sa.Integer(), nullable=True))
        op.add_column("participations", sa.Column("changement_jockey", sa.Boolean(), server_default="false", nullable=False))
        op.add_column("participations", sa.Column("poids_reel_pesee", sa.Float(), nullable=True))
    except Exception as e:
        print(f"participations columns already exist or error: {e}")

    # ── courses — nouveaux champs ────────────────────────────────────────────
    try:
        op.add_column("courses", sa.Column("penetrometre_coef", sa.Float(), nullable=True))
        op.add_column("courses", sa.Column("penetrometre_desc", sa.String(30), nullable=True))
        op.add_column("courses", sa.Column("pool_total_centimes", sa.BigInteger(), nullable=True))
        op.add_column("courses", sa.Column("pool_gagnant_centimes", sa.BigInteger(), nullable=True))
        op.add_column("courses", sa.Column("avantage_couloir", sa.String(20), nullable=True))
    except Exception as e:
        print(f"courses columns already exist or error: {e}")

    # ── chevaux — nouveaux champs ────────────────────────────────────────────
    try:
        op.add_column("chevaux", sa.Column("mere_de_mere", sa.String(100), nullable=True))
        op.add_column("chevaux", sa.Column("prix_vente_yearling", sa.Integer(), nullable=True))
        op.add_column("chevaux", sa.Column("running_style", sa.String(20), nullable=True))
        op.add_column("chevaux", sa.Column("taux_en_tete", sa.Float(), nullable=True))
        op.add_column("chevaux", sa.Column("racing_post_url", sa.String(300), nullable=True))
    except Exception as e:
        print(f"chevaux columns already exist or error: {e}")

    # ── cotes_bookmakers ─────────────────────────────────────────────────────
    try:
        op.create_table(
            "cotes_bookmakers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id"), nullable=False),
            sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("cote", sa.Float(), nullable=False),
            sa.Column("est_cote_ouverture", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_cotes_bookmakers_participation_source", "cotes_bookmakers", ["participation_id", "source"])
        op.create_index("ix_cotes_bookmakers_course", "cotes_bookmakers", ["course_id"])
    except Exception as e:
        print(f"cotes_bookmakers already exists or error: {e}")

    # ── pool_pmu_historique ───────────────────────────────────────────────────
    try:
        op.create_table(
            "pool_pmu_historique",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
            sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("pool_total_centimes", sa.BigInteger(), nullable=True),
            sa.Column("pool_gagnant_centimes", sa.BigInteger(), nullable=True),
            sa.Column("pool_place_centimes", sa.BigInteger(), nullable=True),
            sa.Column("nb_parieurs", sa.Integer(), nullable=True),
        )
        op.create_index("ix_pool_course_time", "pool_pmu_historique", ["course_id", "scraped_at"])
    except Exception as e:
        print(f"pool_pmu_historique already exists or error: {e}")

    # ── suspensions_professionnels ────────────────────────────────────────────
    try:
        op.create_table(
            "suspensions_professionnels",
            sa.Column("suspension_id", sa.String(36), primary_key=True),
            sa.Column("nom", sa.String(100), nullable=False),
            sa.Column("type_pro", sa.String(20), nullable=False),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("date_debut", sa.Date(), nullable=False),
            sa.Column("date_fin", sa.Date(), nullable=True),
            sa.Column("nb_jours", sa.Integer(), nullable=True),
            sa.Column("motif", sa.Text(), nullable=True),
            sa.Column("est_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("nom", "source", "date_debut", name="uq_suspension_nom_source_date"),
        )
        op.create_index("ix_suspensions_nom_active", "suspensions_professionnels", ["nom", "est_active"])
        op.create_index("ix_suspensions_date", "suspensions_professionnels", ["date_debut"])
    except Exception as e:
        print(f"suspensions_professionnels already exists or error: {e}")

    # ── penetrometre_log ──────────────────────────────────────────────────────
    try:
        op.create_table(
            "penetrometre_log",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("reunion_id", sa.String(20), sa.ForeignKey("reunions.reunion_id"), nullable=False),
            sa.Column("hippodrome", sa.String(100), nullable=False),
            sa.Column("date_mesure", sa.Date(), nullable=False),
            sa.Column("coefficient", sa.Float(), nullable=False),
            sa.Column("description", sa.String(30), nullable=False),
            sa.Column("heure_mesure", sa.String(10), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("reunion_id", name="uq_penetrometre_reunion"),
        )
        op.create_index("ix_penetrometre_hippodrome_date", "penetrometre_log", ["hippodrome", "date_mesure"])
    except Exception as e:
        print(f"penetrometre_log already exists or error: {e}")

    # ── temps_passage ─────────────────────────────────────────────────────────
    try:
        op.create_table(
            "temps_passage",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
            sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id"), nullable=True),
            sa.Column("numero", sa.Integer(), nullable=False),
            sa.Column("nom_cheval", sa.String(100), nullable=False),
            sa.Column("passage_400m", sa.String(15), nullable=True),
            sa.Column("passage_800m", sa.String(15), nullable=True),
            sa.Column("passage_1000m", sa.String(15), nullable=True),
            sa.Column("passage_1600m", sa.String(15), nullable=True),
            sa.Column("passage_dernier_400m", sa.String(15), nullable=True),
            sa.Column("vitesse_max_kmh", sa.Float(), nullable=True),
            sa.Column("position_500m", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("course_id", "numero", name="uq_temps_passage_course_numero"),
        )
        op.create_index("ix_temps_passage_course", "temps_passage", ["course_id"])
    except Exception as e:
        print(f"temps_passage already exists or error: {e}")

    # ── pronostics_presse ─────────────────────────────────────────────────────
    try:
        op.create_table(
            "pronostics_presse",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
            sa.Column("source", sa.String(30), nullable=False),
            sa.Column("journaliste", sa.String(100), nullable=True),
            sa.Column("selection", postgresql.JSON(), nullable=False, server_default="[]"),
            sa.Column("commentaire", sa.Text(), nullable=True),
            sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("course_id", "source", "journaliste", name="uq_pronostic_course_source_journaliste"),
        )
        op.create_index("ix_pronostics_course", "pronostics_presse", ["course_id"])
    except Exception as e:
        print(f"pronostics_presse already exists or error: {e}")

    # ── associations_jockey_entraineur ────────────────────────────────────────
    try:
        op.create_table(
            "associations_jockey_entraineur",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("jockey_id", sa.String(36), sa.ForeignKey("jockeys.jockey_id"), nullable=False),
            sa.Column("entraineur_id", sa.String(36), sa.ForeignKey("entraineurs.entraineur_id"), nullable=False),
            sa.Column("saison", sa.Integer(), nullable=False),
            sa.Column("nb_courses", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_victoires", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_places", sa.Integer(), server_default="0", nullable=False),
            sa.Column("taux_victoire", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("taux_place", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("roi", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("jockey_id", "entraineur_id", "saison", name="uq_asso_jockey_entraineur_saison"),
        )
        op.create_index("ix_asso_jockey_entraineur", "associations_jockey_entraineur", ["jockey_id", "entraineur_id"])
    except Exception as e:
        print(f"associations_jockey_entraineur already exists or error: {e}")


def downgrade() -> None:
    # Nouvelles tables
    for table in [
        "associations_jockey_entraineur",
        "pronostics_presse",
        "temps_passage",
        "penetrometre_log",
        "suspensions_professionnels",
        "pool_pmu_historique",
        "cotes_bookmakers",
    ]:
        try:
            op.drop_table(table)
        except Exception:
            pass

    # Nouvelles colonnes participations
    for col in ["cote_winamax", "cote_betclic", "cote_betclic_ouverture", "cote_unibet",
                "cote_betfair_exchange", "jours_depuis_derniere", "changement_jockey", "poids_reel_pesee"]:
        try:
            op.drop_column("participations", col)
        except Exception:
            pass

    # Nouvelles colonnes courses
    for col in ["penetrometre_coef", "penetrometre_desc", "pool_total_centimes",
                "pool_gagnant_centimes", "avantage_couloir"]:
        try:
            op.drop_column("courses", col)
        except Exception:
            pass

    # Nouvelles colonnes chevaux
    for col in ["mere_de_mere", "prix_vente_yearling", "running_style", "taux_en_tete", "racing_post_url"]:
        try:
            op.drop_column("chevaux", col)
        except Exception:
            pass
