"""Initial schema — BlackTurf v1.0

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # hippodromes
    op.create_table(
        "hippodromes",
        sa.Column("hippodrome_id", sa.String(36), primary_key=True),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("pays", sa.String(5), default="FR"),
        sa.Column("ville", sa.String(100)),
        sa.Column("type_piste", sa.String(30)),
        sa.Column("longitude", sa.Float),
        sa.Column("latitude", sa.Float),
    )
    op.create_index("ix_hippodromes_nom", "hippodromes", ["nom"], unique=True)
    op.create_index("ix_hippodromes_code", "hippodromes", ["code"], unique=True)

    # jockeys
    op.create_table(
        "jockeys",
        sa.Column("jockey_id", sa.String(36), primary_key=True),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("pmu_id", sa.String(50), unique=True),
        sa.Column("nationalite", sa.String(5)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_jockeys_nom", "jockeys", ["nom"])

    # stats_jockeys
    op.create_table(
        "stats_jockeys",
        sa.Column("stat_id", sa.String(36), primary_key=True),
        sa.Column("jockey_id", sa.String(36), sa.ForeignKey("jockeys.jockey_id"), nullable=False),
        sa.Column("saison", sa.Integer, nullable=False),
        sa.Column("victoires_saison", sa.Integer, default=0),
        sa.Column("courses_saison", sa.Integer, default=0),
        sa.Column("taux_victoire_global", sa.Float, default=0.0),
        sa.Column("taux_place_global", sa.Float, default=0.0),
        sa.Column("taux_par_distance", postgresql.JSONB),
        sa.Column("taux_par_hippodrome", postgresql.JSONB),
        sa.Column("taux_par_terrain", postgresql.JSONB),
        sa.Column("roi_global", sa.Float, default=0.0),
        sa.Column("montes_30j", sa.Integer, default=0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("jockey_id", "saison"),
    )

    # entraineurs
    op.create_table(
        "entraineurs",
        sa.Column("entraineur_id", sa.String(36), primary_key=True),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("pmu_id", sa.String(50), unique=True),
        sa.Column("nationalite", sa.String(5)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # stats_entraineurs
    op.create_table(
        "stats_entraineurs",
        sa.Column("stat_id", sa.String(36), primary_key=True),
        sa.Column("entraineur_id", sa.String(36), sa.ForeignKey("entraineurs.entraineur_id"), nullable=False),
        sa.Column("saison", sa.Integer, nullable=False),
        sa.Column("victoires_saison", sa.Integer, default=0),
        sa.Column("courses_saison", sa.Integer, default=0),
        sa.Column("taux_victoire_global", sa.Float, default=0.0),
        sa.Column("taux_place_global", sa.Float, default=0.0),
        sa.Column("taux_par_distance", postgresql.JSONB),
        sa.Column("taux_par_hippodrome", postgresql.JSONB),
        sa.Column("roi_global", sa.Float, default=0.0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("entraineur_id", "saison"),
    )

    # chevaux
    op.create_table(
        "chevaux",
        sa.Column("cheval_id", sa.String(36), primary_key=True),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("nom_anglais", sa.String(100)),
        sa.Column("code_sire", sa.String(20), unique=True),
        sa.Column("age", sa.Integer),
        sa.Column("sexe", sa.String(5)),
        sa.Column("robe", sa.String(30)),
        sa.Column("pays_naissance", sa.String(5)),
        sa.Column("date_naissance", sa.Date),
        sa.Column("pere", sa.String(100)),
        sa.Column("mere", sa.String(100)),
        sa.Column("pere_de_mere", sa.String(100)),
        sa.Column("eleveur", sa.String(100)),
        sa.Column("proprietaire", sa.String(100)),
        sa.Column("casaque_description", sa.String(200)),
        sa.Column("entraineur_actuel", sa.String(100)),
        sa.Column("elo_score_global", sa.Float, default=1500.0),
        sa.Column("elo_score_plat", sa.Float, default=1500.0),
        sa.Column("elo_score_trot", sa.Float, default=1500.0),
        sa.Column("elo_score_obstacle", sa.Float, default=1500.0),
        sa.Column("indice_valeur_officiel", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chevaux_nom", "chevaux", ["nom"])
    op.execute("CREATE INDEX ix_chevaux_nom_trgm ON chevaux USING gin (nom gin_trgm_ops)")

    # performances_carriere
    op.create_table(
        "performances_carriere",
        sa.Column("cheval_id", sa.String(36), sa.ForeignKey("chevaux.cheval_id"), primary_key=True),
        sa.Column("gains_carriere_total", sa.BigInteger, default=0),
        sa.Column("gains_annee_n", sa.BigInteger, default=0),
        sa.Column("gains_annee_n1", sa.BigInteger, default=0),
        sa.Column("gains_annee_n2", sa.BigInteger, default=0),
        sa.Column("nb_courses_total", sa.Integer, default=0),
        sa.Column("nb_victoires_total", sa.Integer, default=0),
        sa.Column("nb_places_total", sa.Integer, default=0),
        sa.Column("nb_courses_annee", sa.Integer, default=0),
        sa.Column("nb_victoires_annee", sa.Integer, default=0),
        sa.Column("meilleur_temps_all", sa.String(20)),
        sa.Column("meilleur_temps_dist_actuelle", sa.String(20)),
        sa.Column("record_hippodrome_actuel", sa.String(20)),
        sa.Column("date_record_perso", sa.Date),
        sa.Column("hippodrome_record", sa.String(100)),
        sa.Column("retard_gains", sa.BigInteger, default=0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # reunions
    op.create_table(
        "reunions",
        sa.Column("reunion_id", sa.String(20), primary_key=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("hippodrome_id", sa.String(36), sa.ForeignKey("hippodromes.hippodrome_id")),
        sa.Column("hippodrome_nom", sa.String(100), nullable=False),
        sa.Column("numero", sa.Integer, nullable=False),
        sa.Column("pays", sa.String(5), default="FR"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reunions_date", "reunions", ["date"])

    # courses
    op.create_table(
        "courses",
        sa.Column("course_id", sa.String(30), primary_key=True),
        sa.Column("reunion_id", sa.String(20), sa.ForeignKey("reunions.reunion_id")),
        sa.Column("numero", sa.Integer, nullable=False),
        sa.Column("nom", sa.String(200)),
        sa.Column("date_heure", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hippodrome_nom", sa.String(100), nullable=False),
        sa.Column("discipline", sa.String(20), nullable=False),
        sa.Column("distance", sa.Integer, nullable=False),
        sa.Column("terrain_officiel", sa.String(30)),
        sa.Column("terrain_code", sa.Integer),
        sa.Column("corde", sa.String(15)),
        sa.Column("nb_partants", sa.Integer, default=0),
        sa.Column("allocation", sa.BigInteger),
        sa.Column("niveau_course", sa.String(30)),
        sa.Column("type_depart", sa.String(5)),
        sa.Column("est_quinte", sa.Boolean, default=False),
        sa.Column("est_quarte", sa.Boolean, default=False),
        sa.Column("est_tierce", sa.Boolean, default=False),
        sa.Column("est_pick5", sa.Boolean, default=False),
        sa.Column("statut", sa.String(20), default="a_venir"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_courses_statut_date", "courses", ["statut", "date_heure"])
    op.create_index("ix_courses_date_heure", "courses", ["date_heure"])

    # users
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("nom", sa.String(100)),
        sa.Column("prenom", sa.String(100)),
        sa.Column("profil_risque", sa.String(15), default="equilibre"),
        sa.Column("email_verified", sa.Boolean, default=False),
        sa.Column("google_id", sa.String(100), unique=True),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("is_admin", sa.Boolean, default=False),
        sa.Column("plan", sa.String(10), default="free"),
        sa.Column("stripe_customer_id", sa.String(100), unique=True),
        sa.Column("push_subscription", postgresql.JSONB),
        sa.Column("bankroll_initiale", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # model_versions
    op.create_table(
        "model_versions",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("version_num", sa.Integer, nullable=False, unique=True),
        sa.Column("nom_fichier", sa.String(200), nullable=False),
        sa.Column("auc_roc", sa.Float, nullable=False),
        sa.Column("brier_score", sa.Float, nullable=False),
        sa.Column("precision_top3", sa.Float, nullable=False),
        sa.Column("roi_simule", sa.Float, nullable=False),
        sa.Column("nb_courses_train", sa.Integer, nullable=False),
        sa.Column("est_actif", sa.Boolean, default=False),
        sa.Column("est_rollback", sa.Boolean, default=False),
        sa.Column("feature_importance", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # participations
    op.create_table(
        "participations",
        sa.Column("participation_id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), nullable=False),
        sa.Column("cheval_id", sa.String(36), sa.ForeignKey("chevaux.cheval_id"), nullable=False),
        sa.Column("jockey_id", sa.String(36), sa.ForeignKey("jockeys.jockey_id")),
        sa.Column("entraineur_id", sa.String(36), sa.ForeignKey("entraineurs.entraineur_id")),
        sa.Column("numero", sa.Integer, nullable=False),
        sa.Column("numero_corde", sa.Integer),
        sa.Column("poids_prevu", sa.Float),
        sa.Column("poids_porte", sa.Float),
        sa.Column("decharge", sa.Float),
        sa.Column("handicap_poids", sa.Float),
        sa.Column("valeur_indice", sa.Integer),
        sa.Column("retard_gains", sa.BigInteger),
        sa.Column("cote_pmu", sa.Float),
        sa.Column("cote_geny", sa.Float),
        sa.Column("cote_bzh", sa.Float),
        sa.Column("rang_pronostic_pmu", sa.Integer),
        sa.Column("rang_pronostic_geny", sa.Integer),
        sa.Column("musique", sa.String(50)),
        sa.Column("non_partant", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("course_id", "numero", name="uq_participation_course_numero"),
    )
    op.create_index("ix_participations_course_numero", "participations", ["course_id", "numero"])
    op.create_index("ix_participations_cheval", "participations", ["cheval_id"])

    # equipements
    op.create_table(
        "equipements",
        sa.Column("equipement_id", sa.String(36), primary_key=True),
        sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id"), unique=True),
        sa.Column("cheval_id", sa.String(36), sa.ForeignKey("chevaux.cheval_id")),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("deferre", sa.String(30)),
        sa.Column("oeilleres", sa.String(30)),
        sa.Column("plaques", sa.String(50)),
        sa.Column("muserolle", sa.Boolean),
        sa.Column("muserolle_type", sa.String(30)),
        sa.Column("langue_attachee", sa.Boolean),
        sa.Column("visiere", sa.Boolean),
        sa.Column("blinkers", sa.Boolean),
        sa.Column("deferre_change", sa.Boolean, default=False),
        sa.Column("oeilleres_change", sa.Boolean, default=False),
        sa.Column("equipement_nouveau", sa.Boolean, default=False),
        sa.Column("premier_deferre", sa.Boolean, default=False),
        sa.Column("premieres_oeilleres", sa.Boolean, default=False),
    )
    op.create_index("ix_equipements_cheval", "equipements", ["cheval_id"])

    # historique_courses
    op.create_table(
        "historique_courses",
        sa.Column("historique_id", sa.String(36), primary_key=True),
        sa.Column("cheval_id", sa.String(36), sa.ForeignKey("chevaux.cheval_id"), nullable=False),
        sa.Column("course_id", sa.String(30)),
        sa.Column("date_course", sa.Date, nullable=False),
        sa.Column("hippodrome", sa.String(100), nullable=False),
        sa.Column("pays", sa.String(5), default="FR"),
        sa.Column("discipline", sa.String(20), nullable=False),
        sa.Column("distance", sa.Integer, nullable=False),
        sa.Column("terrain", sa.String(30)),
        sa.Column("corde", sa.String(15)),
        sa.Column("nb_partants", sa.Integer),
        sa.Column("position_arrivee", sa.Integer),
        sa.Column("incident", sa.String(100)),
        sa.Column("ecart_longueurs", sa.Float),
        sa.Column("temps_officiel", sa.String(20)),
        sa.Column("indice_vitesse", sa.Float),
        sa.Column("niveau_course", sa.String(30)),
        sa.Column("allocation", sa.BigInteger),
        sa.Column("cote_depart", sa.Float),
        sa.Column("rang_pronostic", sa.Integer),
        sa.Column("jockey_course", sa.String(100)),
        sa.Column("poids_porte_course", sa.Float),
        sa.Column("equipement_course", postgresql.JSONB),
        sa.Column("gains_rapportes", sa.BigInteger),
        sa.Column("video_url", sa.String(300)),
    )
    op.create_index("ix_historique_cheval_date", "historique_courses", ["cheval_id", "date_course"])

    # cotes_historique (TimescaleDB)
    op.create_table(
        "cotes_historique",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participation_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("cote", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("time", "participation_id"),
    )
    op.execute("SELECT create_hypertable('cotes_historique', 'time', if_not_exists => TRUE)")
    op.create_index("ix_cotes_participation_time", "cotes_historique", ["participation_id", "time"])

    # meteo_courses
    op.create_table(
        "meteo_courses",
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), primary_key=True),
        sa.Column("terrain_officiel", sa.String(30)),
        sa.Column("terrain_code", sa.Integer),
        sa.Column("temperature", sa.Float),
        sa.Column("vent_vitesse", sa.Float),
        sa.Column("vent_direction", sa.String(5)),
        sa.Column("pluie_24h", sa.Float),
        sa.Column("humidite", sa.Float),
        sa.Column("pression", sa.Float),
        sa.Column("visibilite", sa.Integer),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # resultats
    op.create_table(
        "resultats",
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id"), primary_key=True),
        sa.Column("classement", postgresql.JSONB, nullable=False),
        sa.Column("rapports", postgresql.JSONB),
        sa.Column("temps_gagnant", sa.String(20)),
        sa.Column("incidents", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # elo_historique
    op.create_table(
        "elo_historique",
        sa.Column("elo_id", sa.String(36), primary_key=True),
        sa.Column("cheval_id", sa.String(36), sa.ForeignKey("chevaux.cheval_id"), nullable=False),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("date_course", sa.Date, nullable=False),
        sa.Column("discipline", sa.String(20), nullable=False),
        sa.Column("elo_avant", sa.Float, nullable=False),
        sa.Column("elo_apres", sa.Float, nullable=False),
        sa.Column("delta_elo", sa.Float, nullable=False),
    )
    op.create_index("ix_elo_cheval_date", "elo_historique", ["cheval_id", "date_course"])

    # features_ml
    op.create_table(
        "features_ml",
        sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id"), primary_key=True),
        sa.Column("features", postgresql.JSONB, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # predictions
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.String(36), primary_key=True),
        sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id"), unique=True),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.version_id")),
        sa.Column("proba_top1", sa.Float, nullable=False),
        sa.Column("proba_top3", sa.Float, nullable=False),
        sa.Column("rang_predit", sa.Integer, nullable=False),
        sa.Column("score_borda", sa.Float),
        sa.Column("confidence_score", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_predictions_course", "predictions", ["course_id"])

    # value_bets
    op.create_table(
        "value_bets",
        sa.Column("vb_id", sa.String(36), primary_key=True),
        sa.Column("prediction_id", sa.String(36), sa.ForeignKey("predictions.prediction_id")),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("participation_id", sa.String(36), sa.ForeignKey("participations.participation_id")),
        sa.Column("ev_pmu", sa.Float),
        sa.Column("ev_geny", sa.Float),
        sa.Column("ev_bzh", sa.Float),
        sa.Column("ev_max", sa.Float, nullable=False),
        sa.Column("meilleure_source", sa.String(10)),
        sa.Column("niveau", sa.Integer, nullable=False),
        sa.Column("actif", sa.Boolean, default=True),
        sa.Column("detecte_a", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_valuebets_actif_time", "value_bets", ["actif", "detecte_a"])
    op.create_index("ix_valuebets_course", "value_bets", ["course_id"])

    # recommandations
    op.create_table(
        "recommandations",
        sa.Column("reco_id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id")),
        sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.version_id")),
        sa.Column("niveau", sa.String(15), nullable=False),
        sa.Column("type_pari", sa.String(30), nullable=False),
        sa.Column("chevaux_selectionnes", postgresql.JSONB, nullable=False),
        sa.Column("mise_suggeree", sa.Float),
        sa.Column("ev_calcule", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column("texte_explication", sa.Text),
        sa.Column("nb_combinaisons", sa.Integer),
        sa.Column("cout_total", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_recommandations_course", "recommandations", ["course_id"])

    # subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("sub_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id")),
        sa.Column("stripe_subscription_id", sa.String(100), unique=True, nullable=False),
        sa.Column("plan", sa.String(10), nullable=False),
        sa.Column("periodicite", sa.String(10), nullable=False),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("periode_debut", sa.DateTime(timezone=True)),
        sa.Column("periode_fin", sa.DateTime(timezone=True)),
        sa.Column("essai_fin", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # bankroll_entries
    op.create_table(
        "bankroll_entries",
        sa.Column("entry_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("course_id", sa.String(30), sa.ForeignKey("courses.course_id")),
        sa.Column("reco_id", sa.String(36), sa.ForeignKey("recommandations.reco_id")),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type_pari", sa.String(50), nullable=False),
        sa.Column("chevaux", sa.String(200)),
        sa.Column("mise", sa.Float, nullable=False),
        sa.Column("cote", sa.Float),
        sa.Column("resultat", sa.String(10)),
        sa.Column("gain_perte", sa.Float),
        sa.Column("suivi_reco_ia", sa.Boolean, default=False),
        sa.Column("notes", sa.String(500)),
    )
    op.create_index("ix_bankroll_user_date", "bankroll_entries", ["user_id", "date"])

    # strategies
    op.create_table(
        "strategies",
        sa.Column("strategie_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("filtres", postgresql.JSONB, nullable=False),
        sa.Column("indicateurs", postgresql.JSONB, nullable=False),
        sa.Column("alerte_email", sa.Boolean, default=False),
        sa.Column("partage_communaute", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # alertes_log
    op.create_table(
        "alertes_log",
        sa.Column("alerte_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id")),
        sa.Column("type_alerte", sa.String(50), nullable=False),
        sa.Column("canal", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("envoye", sa.Boolean, default=False),
        sa.Column("erreur", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # scrape_log
    op.create_table(
        "scrape_log",
        sa.Column("log_id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("nb_courses", sa.Integer, default=0),
        sa.Column("nb_partants", sa.Integer, default=0),
        sa.Column("erreur", sa.Text),
        sa.Column("duree_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    tables = [
        "scrape_log", "alertes_log", "strategies", "bankroll_entries",
        "subscriptions", "recommandations", "value_bets", "predictions",
        "features_ml", "elo_historique", "resultats", "meteo_courses",
        "cotes_historique", "historique_courses", "equipements",
        "participations", "model_versions", "users", "courses",
        "reunions", "performances_carriere", "chevaux", "stats_entraineurs",
        "entraineurs", "stats_jockeys", "jockeys", "hippodromes",
    ]
    for table in tables:
        op.drop_table(table)
