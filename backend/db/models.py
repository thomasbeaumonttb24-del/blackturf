"""
SQLAlchemy models — BlackTurf
Correspond au schéma complet CDC v2.0 + Addendum v1.1
"""
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Date,
    BigInteger, ForeignKey, UniqueConstraint, Index, func,
    JSON, Enum as SAEnum
)
# UUID and JSON: use standard types for SQLite/PostgreSQL compatibility
# String(36) stores UUID strings; JSON works on both dialects
# In production PostgreSQL, migrate to UUID/JSON via Alembic if needed for perf
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.database import Base


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def gen_uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Hippodromes
# ─────────────────────────────────────────────
class Hippodrome(Base):
    __tablename__ = "hippodromes"

    hippodrome_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nom: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    pays: Mapped[str] = mapped_column(String(5), default="FR")
    ville: Mapped[str | None] = mapped_column(String(100))
    type_piste: Mapped[str | None] = mapped_column(String(30))  # Plat/Trot/Mixte
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)


# ─────────────────────────────────────────────
# Jockeys / Drivers
# ─────────────────────────────────────────────
class Jockey(Base):
    __tablename__ = "jockeys"

    jockey_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    pmu_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    nationalite: Mapped[str | None] = mapped_column(String(5))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StatsJockey(Base):
    __tablename__ = "stats_jockeys"

    stat_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    jockey_id: Mapped[str] = mapped_column(ForeignKey("jockeys.jockey_id"), index=True)
    saison: Mapped[int] = mapped_column(Integer)
    victoires_saison: Mapped[int] = mapped_column(Integer, default=0)
    places_saison: Mapped[int] = mapped_column(Integer, default=0)
    courses_saison: Mapped[int] = mapped_column(Integer, default=0)
    taux_victoire_global: Mapped[float] = mapped_column(Float, default=0.0)
    taux_place_global: Mapped[float] = mapped_column(Float, default=0.0)
    taux_par_distance: Mapped[dict | None] = mapped_column(JSON)
    taux_par_hippodrome: Mapped[dict | None] = mapped_column(JSON)
    taux_par_terrain: Mapped[dict | None] = mapped_column(JSON)
    roi_global: Mapped[float] = mapped_column(Float, default=0.0)
    montes_30j: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("jockey_id", "saison"),)


# ─────────────────────────────────────────────
# Entraîneurs
# ─────────────────────────────────────────────
class Entraineur(Base):
    __tablename__ = "entraineurs"

    entraineur_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    pmu_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    nationalite: Mapped[str | None] = mapped_column(String(5))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StatsEntraineur(Base):
    __tablename__ = "stats_entraineurs"

    stat_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    entraineur_id: Mapped[str] = mapped_column(ForeignKey("entraineurs.entraineur_id"), index=True)
    saison: Mapped[int] = mapped_column(Integer)
    victoires_saison: Mapped[int] = mapped_column(Integer, default=0)
    places_saison: Mapped[int] = mapped_column(Integer, default=0)
    courses_saison: Mapped[int] = mapped_column(Integer, default=0)
    taux_victoire_global: Mapped[float] = mapped_column(Float, default=0.0)
    taux_place_global: Mapped[float] = mapped_column(Float, default=0.0)
    taux_par_distance: Mapped[dict | None] = mapped_column(JSON)
    taux_par_hippodrome: Mapped[dict | None] = mapped_column(JSON)
    roi_global: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("entraineur_id", "saison"),)


# ─────────────────────────────────────────────
# Chevaux
# ─────────────────────────────────────────────
class Cheval(Base):
    __tablename__ = "chevaux"

    cheval_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)

    # Identité
    nom: Mapped[str] = mapped_column(String(100), index=True)
    nom_anglais: Mapped[str | None] = mapped_column(String(100))
    code_sire: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    age: Mapped[int | None] = mapped_column(Integer)
    sexe: Mapped[str | None] = mapped_column(String(5))  # H/E/M/F/JP
    robe: Mapped[str | None] = mapped_column(String(30))
    race: Mapped[str | None] = mapped_column(String(40))  # race/breed (TROTTEUR FRANCAIS, PUR SANG...)
    pays_naissance: Mapped[str | None] = mapped_column(String(5))
    date_naissance: Mapped[datetime | None] = mapped_column(Date)

    # Généalogie
    pere: Mapped[str | None] = mapped_column(String(100))
    mere: Mapped[str | None] = mapped_column(String(100))
    pere_de_mere: Mapped[str | None] = mapped_column(String(100))
    mere_de_mere: Mapped[str | None] = mapped_column(String(100))
    eleveur: Mapped[str | None] = mapped_column(String(100))
    proprietaire: Mapped[str | None] = mapped_column(String(100))
    prix_vente_yearling: Mapped[int | None] = mapped_column(Integer)      # euros

    # Style de course
    running_style: Mapped[str | None] = mapped_column(String(20))         # mene/suit_tete/placier/ferme
    taux_en_tete: Mapped[float | None] = mapped_column(Float)
    racing_post_url: Mapped[str | None] = mapped_column(String(300))
    casaque_description: Mapped[str | None] = mapped_column(String(200))
    entraineur_actuel: Mapped[str | None] = mapped_column(String(100))

    # ELO scores
    elo_score_global: Mapped[float] = mapped_column(Float, default=1500.0)
    elo_score_plat: Mapped[float] = mapped_column(Float, default=1500.0)
    elo_score_trot: Mapped[float] = mapped_column(Float, default=1500.0)
    elo_score_obstacle: Mapped[float] = mapped_column(Float, default=1500.0)

    # Index officiel
    indice_valeur_officiel: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_chevaux_nom_trgm", "nom", postgresql_using="gin", postgresql_ops={"nom": "gin_trgm_ops"}),
    )


class PerformanceCarriere(Base):
    """Stats agrégées carrière — mise à jour après chaque course."""
    __tablename__ = "performances_carriere"

    cheval_id: Mapped[str] = mapped_column(ForeignKey("chevaux.cheval_id"), primary_key=True)
    gains_carriere_total: Mapped[int] = mapped_column(BigInteger, default=0)
    gains_annee_n: Mapped[int] = mapped_column(BigInteger, default=0)
    gains_annee_n1: Mapped[int] = mapped_column(BigInteger, default=0)
    gains_annee_n2: Mapped[int] = mapped_column(BigInteger, default=0)
    nb_courses_total: Mapped[int] = mapped_column(Integer, default=0)
    nb_victoires_total: Mapped[int] = mapped_column(Integer, default=0)
    nb_places_total: Mapped[int] = mapped_column(Integer, default=0)
    nb_courses_annee: Mapped[int] = mapped_column(Integer, default=0)
    nb_victoires_annee: Mapped[int] = mapped_column(Integer, default=0)
    meilleur_temps_all: Mapped[str | None] = mapped_column(String(20))
    meilleur_temps_dist_actuelle: Mapped[str | None] = mapped_column(String(20))
    record_hippodrome_actuel: Mapped[str | None] = mapped_column(String(20))
    date_record_perso: Mapped[datetime | None] = mapped_column(Date)
    hippodrome_record: Mapped[str | None] = mapped_column(String(100))
    retard_gains: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─────────────────────────────────────────────
# Réunions & Courses
# ─────────────────────────────────────────────
class Reunion(Base):
    __tablename__ = "reunions"

    reunion_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # R1, R2... format PMU
    date: Mapped[datetime] = mapped_column(Date, index=True)
    hippodrome_id: Mapped[str] = mapped_column(ForeignKey("hippodromes.hippodrome_id"))
    hippodrome_nom: Mapped[str] = mapped_column(String(100))
    numero: Mapped[int] = mapped_column(Integer)
    pays: Mapped[str] = mapped_column(String(5), default="FR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Course(Base):
    __tablename__ = "courses"

    course_id: Mapped[str] = mapped_column(String(30), primary_key=True)  # R1C1 format PMU
    reunion_id: Mapped[str] = mapped_column(ForeignKey("reunions.reunion_id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    # N° de réunion PUBLIC (PMU numExterne) — affiché à l'utilisateur, doit matcher
    # pmu.fr. Distinct de reunion_id (= numOfficiel, utilisé dans les URLs API PMU).
    numero_reunion: Mapped[int | None] = mapped_column(Integer)
    nom: Mapped[str | None] = mapped_column(String(200))
    date_heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    hippodrome_nom: Mapped[str] = mapped_column(String(100))

    # Caractéristiques
    discipline: Mapped[str] = mapped_column(String(20))  # Plat/Attelé/Monté/Haies/Steeple
    distance: Mapped[int] = mapped_column(Integer)  # en mètres
    terrain_officiel: Mapped[str | None] = mapped_column(String(30))
    terrain_code: Mapped[int | None] = mapped_column(Integer)
    corde: Mapped[str | None] = mapped_column(String(15))  # Intérieur/Extérieur
    nb_partants: Mapped[int] = mapped_column(Integer, default=0)
    allocation: Mapped[int | None] = mapped_column(BigInteger)  # en centimes
    niveau_course: Mapped[str | None] = mapped_column(String(30))  # Group1/Listed/Conditions/Réclamer
    type_depart: Mapped[str | None] = mapped_column(String(5))  # A/C/S/H
    # ── Enrichissements PMU (course) ─────────────────────────────────────────
    conditions_texte: Mapped[str | None] = mapped_column(Text)              # conditions complètes
    categorie_particularite: Mapped[str | None] = mapped_column(String(30)) # EUROPEENNE/NATIONALE/...
    montant_offert_1er: Mapped[int | None] = mapped_column(BigInteger)      # dotation gagnant (euros)
    nombre_declares_partants: Mapped[int | None] = mapped_column(Integer)   # déclarés (scratchings)
    pool_gagnant_evolution: Mapped[float | None] = mapped_column(Float)     # taux croissance pool (smart money)

    # Pénétromètre (France Galop)
    penetrometre_coef: Mapped[float | None] = mapped_column(Float)        # 0.0–9.0
    penetrometre_desc: Mapped[str | None] = mapped_column(String(30))     # Bon / Souple / Lourd

    # Pool PMU (mise à jour toutes les 5 min avant départ)
    pool_total_centimes: Mapped[int | None] = mapped_column(BigInteger)
    pool_gagnant_centimes: Mapped[int | None] = mapped_column(BigInteger)

    # Avantage de couloir (publié dans bulletin de réunion)
    avantage_couloir: Mapped[str | None] = mapped_column(String(20))      # interieur / exterieur / neutre

    # Désignations
    est_quinte: Mapped[bool] = mapped_column(Boolean, default=False)
    est_quarte: Mapped[bool] = mapped_column(Boolean, default=False)
    est_tierce: Mapped[bool] = mapped_column(Boolean, default=False)
    est_pick5: Mapped[bool] = mapped_column(Boolean, default=False)

    # Statut
    statut: Mapped[str] = mapped_column(String(20), default="a_venir")  # a_venir/en_cours/termine/annule

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_courses_statut_date", "statut", "date_heure"),
    )


# ─────────────────────────────────────────────
# Participations (partants à une course)
# ─────────────────────────────────────────────
class Participation(Base):
    __tablename__ = "participations"

    participation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    cheval_id: Mapped[str] = mapped_column(ForeignKey("chevaux.cheval_id"), index=True)
    jockey_id: Mapped[str | None] = mapped_column(ForeignKey("jockeys.jockey_id"))
    entraineur_id: Mapped[str | None] = mapped_column(ForeignKey("entraineurs.entraineur_id"))

    # Numérotation
    numero: Mapped[int] = mapped_column(Integer)
    numero_corde: Mapped[int | None] = mapped_column(Integer)

    # ELO POINT-IN-TIME : score ELO du cheval AVANT cette course (anti-fuite temporelle).
    # Rempli au rejeu chronologique. Les features d'entraînement le lisent au lieu de
    # l'ELO courant (qui inclut les courses futures). NULL pour les courses à venir
    # → on retombe sur l'ELO courant (= pré-course pour une course non encore disputée).
    elo_avant_global: Mapped[float | None] = mapped_column(Float)
    elo_avant_plat: Mapped[float | None] = mapped_column(Float)
    elo_avant_trot: Mapped[float | None] = mapped_column(Float)
    elo_avant_obstacle: Mapped[float | None] = mapped_column(Float)

    # Poids
    poids_prevu: Mapped[float | None] = mapped_column(Float)
    poids_porte: Mapped[float | None] = mapped_column(Float)
    decharge: Mapped[float | None] = mapped_column(Float)
    handicap_poids: Mapped[float | None] = mapped_column(Float)

    # Gains/conditions
    valeur_indice: Mapped[int | None] = mapped_column(Integer)
    retard_gains: Mapped[int | None] = mapped_column(BigInteger)

    # Cotes au scrape — PMU + bookmakers alternatifs
    cote_pmu: Mapped[float | None] = mapped_column(Float)
    cote_geny: Mapped[float | None] = mapped_column(Float)
    cote_bzh: Mapped[float | None] = mapped_column(Float)
    cote_winamax: Mapped[float | None] = mapped_column(Float)
    cote_betclic: Mapped[float | None] = mapped_column(Float)
    cote_betclic_ouverture: Mapped[float | None] = mapped_column(Float)   # cote J-1
    cote_unibet: Mapped[float | None] = mapped_column(Float)
    cote_betfair_exchange: Mapped[float | None] = mapped_column(Float)    # marché d'échange
    mouvement_cote_pct: Mapped[float | None] = mapped_column(Float)       # % mouvement cote (ouverture→actuelle)
    cote_reference: Mapped[float | None] = mapped_column(Float)           # cote d'ouverture (dernierRapportReference)
    tendance_cote: Mapped[str | None] = mapped_column(String(2))          # "+" / "-" / "="
    tendance_force: Mapped[float | None] = mapped_column(Float)           # ampleur tendance PMU
    est_favori_pmu: Mapped[bool | None] = mapped_column(Boolean)          # favori désigné PMU
    avis_entraineur: Mapped[str | None] = mapped_column(String(20))       # POSITIF / NEUTRE / NEGATIF
    nb_places_second: Mapped[int | None] = mapped_column(Integer)
    nb_places_troisieme: Mapped[int | None] = mapped_column(Integer)
    handicap_distance: Mapped[int | None] = mapped_column(Integer)
    indicateur_inedit: Mapped[bool | None] = mapped_column(Boolean)       # cheval débutant
    jument_pleine: Mapped[bool | None] = mapped_column(Boolean)
    rang_pronostic_pmu: Mapped[int | None] = mapped_column(Integer)
    rang_pronostic_geny: Mapped[int | None] = mapped_column(Integer)

    # Données calculées
    jours_depuis_derniere: Mapped[int | None] = mapped_column(Integer)    # freshness
    changement_jockey: Mapped[bool] = mapped_column(Boolean, default=False)
    poids_reel_pesee: Mapped[float | None] = mapped_column(Float)         # post-pesée officielle

    # Musique brute (ex: "1a2h3s")
    musique: Mapped[str | None] = mapped_column(String(50))

    # Non-partant
    non_partant: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("course_id", "numero"),
        Index("ix_participations_course_numero", "course_id", "numero"),
    )


class Equipement(Base):
    __tablename__ = "equipements"

    equipement_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.participation_id"), unique=True)
    cheval_id: Mapped[str] = mapped_column(ForeignKey("chevaux.cheval_id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"))

    deferre: Mapped[str | None] = mapped_column(String(30))  # Aucun/Avant/Arrière/Complet
    oeilleres: Mapped[str | None] = mapped_column(String(30))  # Sans/Standard/Australiennes/Cache-oeil
    plaques: Mapped[str | None] = mapped_column(String(50))
    muserolle: Mapped[bool | None] = mapped_column(Boolean)
    muserolle_type: Mapped[str | None] = mapped_column(String(30))
    langue_attachee: Mapped[bool | None] = mapped_column(Boolean)
    visiere: Mapped[bool | None] = mapped_column(Boolean)
    blinkers: Mapped[bool | None] = mapped_column(Boolean)

    # Changements détectés vs course précédente
    deferre_change: Mapped[bool] = mapped_column(Boolean, default=False)
    oeilleres_change: Mapped[bool] = mapped_column(Boolean, default=False)
    equipement_nouveau: Mapped[bool] = mapped_column(Boolean, default=False)
    premier_deferre: Mapped[bool] = mapped_column(Boolean, default=False)
    premieres_oeilleres: Mapped[bool] = mapped_column(Boolean, default=False)


# ─────────────────────────────────────────────
# Historique de courses (musique détaillée)
# ─────────────────────────────────────────────
class HistoriqueCourse(Base):
    __tablename__ = "historique_courses"

    historique_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    cheval_id: Mapped[str] = mapped_column(ForeignKey("chevaux.cheval_id"), index=True)
    course_id: Mapped[str | None] = mapped_column(String(30))  # NULL si course externe

    date_course: Mapped[datetime] = mapped_column(Date, index=True)
    hippodrome: Mapped[str] = mapped_column(String(100))
    pays: Mapped[str] = mapped_column(String(5), default="FR")
    discipline: Mapped[str] = mapped_column(String(20))
    distance: Mapped[int] = mapped_column(Integer)
    terrain: Mapped[str | None] = mapped_column(String(30))
    corde: Mapped[str | None] = mapped_column(String(15))
    nb_partants: Mapped[int | None] = mapped_column(Integer)

    position_arrivee: Mapped[int | None] = mapped_column(Integer)  # 99 = incident
    incident: Mapped[str | None] = mapped_column(String(100))  # Disq./Tombé/Abandonné
    ecart_longueurs: Mapped[float | None] = mapped_column(Float)
    temps_officiel: Mapped[str | None] = mapped_column(String(20))
    indice_vitesse: Mapped[float | None] = mapped_column(Float)

    niveau_course: Mapped[str | None] = mapped_column(String(30))
    allocation: Mapped[int | None] = mapped_column(BigInteger)
    cote_depart: Mapped[float | None] = mapped_column(Float)
    rang_pronostic: Mapped[int | None] = mapped_column(Integer)

    jockey_course: Mapped[str | None] = mapped_column(String(100))
    poids_porte_course: Mapped[float | None] = mapped_column(Float)
    equipement_course: Mapped[dict | None] = mapped_column(JSON)
    gains_rapportes: Mapped[int | None] = mapped_column(BigInteger)
    video_url: Mapped[str | None] = mapped_column(String(300))

    # Dynamique de course (Phase 1) — calculés/scrapés, NULL si indisponible
    reduction_km: Mapped[float | None] = mapped_column(Float)            # secondes/km
    acceleration_index: Mapped[float | None] = mapped_column(Float)      # vit. finale / vit. moyenne
    acceleration_label: Mapped[str | None] = mapped_column(String(15))  # accelere/regulier/faiblit
    commentaire_course: Mapped[str | None] = mapped_column(Text)        # déroulé (scraper, Phase 1.1)

    __table_args__ = (
        Index("ix_historique_cheval_date", "cheval_id", "date_course"),
    )


# ─────────────────────────────────────────────
# Cotes historique (TimescaleDB hypertable)
# ─────────────────────────────────────────────
class CoteHistorique(Base):
    __tablename__ = "cotes_historique"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    participation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # pmu/geny/bzh/zeturf
    cote: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_cotes_participation_time", "participation_id", "time"),
    )


# ─────────────────────────────────────────────
# Météo
# ─────────────────────────────────────────────
class MeteoCourse(Base):
    __tablename__ = "meteo_courses"

    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), primary_key=True)
    terrain_officiel: Mapped[str | None] = mapped_column(String(30))
    terrain_code: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(Float)
    vent_vitesse: Mapped[float | None] = mapped_column(Float)
    vent_direction: Mapped[str | None] = mapped_column(String(5))
    pluie_24h: Mapped[float | None] = mapped_column(Float)
    humidite: Mapped[float | None] = mapped_column(Float)
    pression: Mapped[float | None] = mapped_column(Float)
    visibilite: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─────────────────────────────────────────────
# Résultats
# ─────────────────────────────────────────────
class Resultat(Base):
    __tablename__ = "resultats"

    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), primary_key=True)
    classement: Mapped[dict] = mapped_column(JSON)  # [{numero, cheval, position, temps, ...}]
    rapports: Mapped[dict | None] = mapped_column(JSON)  # {gagnant, place, couple, ...} (agrégat)
    # Détail complet PUBLIÉ par le PMU : {type: [{combinaison, rapport}, …]} — ex.
    # Simple Placé par cheval, 2sur4 par combinaison. Aucune valeur inventée.
    rapports_detail: Mapped[dict | None] = mapped_column(JSON)
    temps_gagnant: Mapped[str | None] = mapped_column(String(20))
    incidents: Mapped[str | None] = mapped_column(Text)
    commentaire: Mapped[str | None] = mapped_column(Text)       # narratif post-course (PMU/GENY)
    duree_course: Mapped[int | None] = mapped_column(Integer)   # durée course (ms)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# ELO historique
# ─────────────────────────────────────────────
class EloHistorique(Base):
    __tablename__ = "elo_historique"

    elo_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    cheval_id: Mapped[str] = mapped_column(ForeignKey("chevaux.cheval_id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"))
    date_course: Mapped[datetime] = mapped_column(Date)
    discipline: Mapped[str] = mapped_column(String(20))

    elo_avant: Mapped[float] = mapped_column(Float)
    elo_apres: Mapped[float] = mapped_column(Float)
    delta_elo: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_elo_cheval_date", "cheval_id", "date_course"),
    )


# ─────────────────────────────────────────────
# Features ML
# ─────────────────────────────────────────────
class FeatureML(Base):
    __tablename__ = "features_ml"

    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.participation_id"), primary_key=True)
    features: Mapped[dict] = mapped_column(JSON)  # 80+ features sérialisées
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# Prédictions & Value Bets
# ─────────────────────────────────────────────
class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.participation_id"), unique=True, index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.version_id"))

    proba_top1: Mapped[float] = mapped_column(Float)
    proba_top3: Mapped[float] = mapped_column(Float)
    # Intervalle de confiance sur proba_top1 (désaccord des 3 modèles de base)
    proba_top1_low: Mapped[float | None] = mapped_column(Float)
    proba_top1_high: Mapped[float | None] = mapped_column(Float)
    rang_predit: Mapped[int] = mapped_column(Integer)
    score_borda: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)  # 0-100

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValueBet(Base):
    __tablename__ = "value_bets"

    vb_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    prediction_id: Mapped[str] = mapped_column(ForeignKey("predictions.prediction_id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    participation_id: Mapped[str] = mapped_column(
        ForeignKey("participations.participation_id"), unique=True
    )  # unique → upsert ON CONFLICT (un value bet actif par partant)

    ev_pmu: Mapped[float | None] = mapped_column(Float)
    ev_geny: Mapped[float | None] = mapped_column(Float)
    ev_bzh: Mapped[float | None] = mapped_column(Float)
    ev_max: Mapped[float] = mapped_column(Float)
    meilleure_source: Mapped[str | None] = mapped_column(String(10))  # pmu/geny/bzh

    niveau: Mapped[int] = mapped_column(Integer)  # 1-4 étoiles
    spi_detected: Mapped[bool] = mapped_column(Boolean, default=False)  # Steam Money Indicator: cote drop > 15% / 30min
    spi_score: Mapped[float | None] = mapped_column(Float)  # amplitude de chute de cote
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    notifie: Mapped[bool] = mapped_column(Boolean, default=False)
    detecte_a: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_valuebets_actif_time", "actif", "detecte_a"),
    )


class Recommandation(Base):
    __tablename__ = "recommandations"

    reco_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.version_id"))

    niveau: Mapped[str] = mapped_column(String(15))  # safe/equilibre/audacieux/jackpot
    type_pari: Mapped[str] = mapped_column(String(30))  # Simple Gagnant/Couplé Placé/...
    chevaux_selectionnes: Mapped[dict] = mapped_column(JSON)  # [{"numero": 3, "nom": "..."}, ...]
    mise_suggeree: Mapped[float | None] = mapped_column(Float)
    ev_calcule: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    texte_explication: Mapped[str | None] = mapped_column(Text)
    nb_combinaisons: Mapped[int | None] = mapped_column(Integer)
    cout_total: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# Utilisateurs & Abonnements
# ─────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    nom: Mapped[str | None] = mapped_column(String(100))
    prenom: Mapped[str | None] = mapped_column(String(100))
    profil_risque: Mapped[str] = mapped_column(String(15), default="equilibre")  # conservateur/equilibre/agressif

    # Auth
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    google_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Plan
    plan: Mapped[str] = mapped_column(String(10), default="free")  # free/standard/expert (legacy: starter/pro)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)

    # Push notifications
    push_subscription: Mapped[dict | None] = mapped_column(JSON)

    # Bankroll de référence
    bankroll_initiale: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    sub_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(100), unique=True)
    plan: Mapped[str] = mapped_column(String(10))  # standard/expert (legacy: starter/pro)
    periodicite: Mapped[str] = mapped_column(String(10))  # monthly/annual
    statut: Mapped[str] = mapped_column(String(20))  # active/past_due/canceled
    periode_debut: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    periode_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    essai_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─────────────────────────────────────────────
# Bankroll
# ─────────────────────────────────────────────
class Bankroll(Base):
    __tablename__ = "bankrolls"

    bankroll_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    nom: Mapped[str] = mapped_column(String(100))  # "Plat", "Obstacle", "Trot", "Principal"
    discipline: Mapped[str | None] = mapped_column(String(20))  # None = all disciplines
    montant_initial: Mapped[float] = mapped_column(Float, default=0.0)
    est_principale: Mapped[bool] = mapped_column(Boolean, default=False)  # one default per user
    couleur: Mapped[str | None] = mapped_column(String(10))  # hex color for UI
    est_supprime: Mapped[bool] = mapped_column(Boolean, default=False)  # soft delete
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_bankrolls_user", "user_id"),)


class BankrollEntry(Base):
    __tablename__ = "bankroll_entries"

    entry_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    bankroll_id: Mapped[str | None] = mapped_column(ForeignKey("bankrolls.bankroll_id"), nullable=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.course_id"))
    reco_id: Mapped[str | None] = mapped_column(ForeignKey("recommandations.reco_id"))

    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    type_pari: Mapped[str] = mapped_column(String(50))
    chevaux: Mapped[str | None] = mapped_column(String(200))
    mise: Mapped[float] = mapped_column(Float)
    cote: Mapped[float | None] = mapped_column(Float)
    resultat: Mapped[str | None] = mapped_column(String(10))  # gagne/perd/annule
    gain_perte: Mapped[float | None] = mapped_column(Float)
    suivi_reco_ia: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_bankroll_user_date", "user_id", "date"),
    )


# ─────────────────────────────────────────────
# Stratégies
# ─────────────────────────────────────────────
class Strategie(Base):
    __tablename__ = "strategies"

    strategie_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    nom: Mapped[str] = mapped_column(String(100))
    filtres: Mapped[dict] = mapped_column(JSON)
    indicateurs: Mapped[dict] = mapped_column(JSON)
    alerte_email: Mapped[bool] = mapped_column(Boolean, default=False)
    partage_communaute: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─────────────────────────────────────────────
# Versions du modèle ML
# ─────────────────────────────────────────────
class ModelVersion(Base):
    __tablename__ = "model_versions"

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    version_num: Mapped[int] = mapped_column(Integer, unique=True)
    nom_fichier: Mapped[str] = mapped_column(String(200))
    auc_roc: Mapped[float] = mapped_column(Float)
    brier_score: Mapped[float] = mapped_column(Float)
    precision_top3: Mapped[float] = mapped_column(Float)
    roi_simule: Mapped[float] = mapped_column(Float)
    nb_courses_train: Mapped[int] = mapped_column(Integer)
    est_actif: Mapped[bool] = mapped_column(Boolean, default=False)
    est_rollback: Mapped[bool] = mapped_column(Boolean, default=False)
    est_synthetique: Mapped[bool] = mapped_column(Boolean, default=False)  # prior cold-start
    walk_forward_auc: Mapped[float | None] = mapped_column(Float)
    walk_forward_variance: Mapped[float | None] = mapped_column(Float)
    feature_importance: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# Logs & Alertes
# ─────────────────────────────────────────────
class AlerteLog(Base):
    __tablename__ = "alertes_log"

    alerte_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    type_alerte: Mapped[str] = mapped_column(String(50))
    canal: Mapped[str] = mapped_column(String(20))  # push/email/in-app
    payload: Mapped[dict | None] = mapped_column(JSON)
    envoye: Mapped[bool] = mapped_column(Boolean, default=False)
    lue: Mapped[bool] = mapped_column(Boolean, default=False)
    erreur: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScrapeLog(Base):
    __tablename__ = "scrape_log"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source: Mapped[str] = mapped_column(String(30))
    statut: Mapped[str] = mapped_column(String(10))  # ok/erreur
    nb_courses: Mapped[int] = mapped_column(Integer, default=0)
    nb_partants: Mapped[int] = mapped_column(Integer, default=0)
    erreur: Mapped[str | None] = mapped_column(Text)
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# Adaptive Learning — Tables d'apprentissage continu
# ─────────────────────────────────────────────

class RaceLearningLog(Base):
    """
    Journal d'apprentissage post-course.
    Chaque course analysée génère une entrée : métriques, autopsie, signaux manqués.
    """
    __tablename__ = "race_learning_log"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.course_id"), unique=True)
    # Métriques d'accuracy
    brier_score: Mapped[float | None] = mapped_column(Float)           # 0–1, plus bas = meilleur
    log_loss: Mapped[float | None] = mapped_column(Float)
    was_surprise: Mapped[bool] = mapped_column(Boolean, default=False)  # gagnant proba < 20%
    gagnant_proba_ia: Mapped[float | None] = mapped_column(Float)       # proba donnée au gagnant
    gagnant_rang_predit: Mapped[int | None] = mapped_column(Integer)    # rang prédit du gagnant
    # Contexte course
    discipline: Mapped[str | None] = mapped_column(String(30))
    terrain: Mapped[str | None] = mapped_column(String(30))
    hippodrome: Mapped[str | None] = mapped_column(String(100))
    nb_partants: Mapped[int | None] = mapped_column(Integer)
    # Autopsie des features manquées
    feature_autopsy: Mapped[dict | None] = mapped_column(JSON)          # {signal: {valeur, description}}
    # Signal envoyé à AdaptiveLearning
    learning_signal: Mapped[dict | None] = mapped_column(JSON)
    # Recommandations d'action (retrain, ajustement T, etc.)
    actions_recommandees: Mapped[list | None] = mapped_column(JSON)
    # Résultat des updates appliqués
    adaptive_updates: Mapped[dict | None] = mapped_column(JSON)         # {temperature, weight_updates}
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BiasMatrix(Base):
    """
    Matrice de biais systématiques par contexte (discipline × terrain × hippodrome).
    Stocke la correction à appliquer aux probas calibrées.
    """
    __tablename__ = "bias_matrix"

    bias_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    # Clé composite : "plat|lourd|Longchamp"
    bias_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    discipline: Mapped[str | None] = mapped_column(String(30))
    terrain: Mapped[str | None] = mapped_column(String(30))
    hippodrome: Mapped[str | None] = mapped_column(String(100))
    # Stats cumulées
    nb_courses: Mapped[int] = mapped_column(Integer, default=0)
    nb_surprises: Mapped[int] = mapped_column(Integer, default=0)
    brier_moyen: Mapped[float | None] = mapped_column(Float)
    # Facteur de correction calculé (–0.15 à +0.15)
    correction_factor: Mapped[float] = mapped_column(Float, default=0.0)
    # Distribution des favoris gagnants (% de fois où le favori gagne dans ce contexte)
    favori_win_rate: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_bias_matrix_key", "bias_key"),
    )


class AdaptiveLearningState(Base):
    """
    Persistance de l'état du moteur d'apprentissage adaptatif.
    Singleton (state_id = 'singleton').
    """
    __tablename__ = "adaptive_learning_state"

    state_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # 'singleton'
    temperature: Mapped[float] = mapped_column(Float, default=1.0)
    feature_weights_json: Mapped[dict | None] = mapped_column(JSON)
    n_races: Mapped[int] = mapped_column(Integer, default=0)
    brier_ema: Mapped[float] = mapped_column(Float, default=0.20)
    surprise_ema: Mapped[float] = mapped_column(Float, default=0.30)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DriftDetectorState(Base):
    """
    Persistance de l'état du détecteur de drift (ADWIN + Page-Hinkley).
    Singleton (state_id = 'singleton').
    """
    __tablename__ = "drift_detector_state"

    state_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # 'singleton'
    state_json: Mapped[dict | None] = mapped_column(JSON)  # Sérialisation complète de l'état
    severity: Mapped[str] = mapped_column(String(20), default="none")   # none/warning/critical
    n_updates: Mapped[int] = mapped_column(Integer, default=0)
    last_drift_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─────────────────────────────────────────────
# Nouvelles tables — sources enrichies
# ─────────────────────────────────────────────

class CoteBookmaker(Base):
    """
    Cotes des bookmakers alternatifs : Winamax, Betclic, Unibet, Betfair Exchange.
    Stockées dans la même timeseries que CoteHistorique via source=winamax/betclic/...
    Table dédiée pour les cotes d'ouverture et l'historique bookmaker.
    """
    __tablename__ = "cotes_bookmakers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.participation_id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    source: Mapped[str] = mapped_column(String(20))           # winamax/betclic/unibet/betfair
    cote: Mapped[float] = mapped_column(Float)
    est_cote_ouverture: Mapped[bool] = mapped_column(Boolean, default=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_cotes_bookmakers_participation_source", "participation_id", "source"),
        Index("ix_cotes_bookmakers_course", "course_id"),
    )


class PoolPMUHistorique(Base):
    """
    Évolution du pool PMU pour chaque course — timeseries.
    Mise à jour toutes les 5 min avant départ.
    Signal de 'smart money' : augmentation rapide = argent professionnel.
    """
    __tablename__ = "pool_pmu_historique"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    pool_total_centimes: Mapped[int | None] = mapped_column(BigInteger)
    pool_gagnant_centimes: Mapped[int | None] = mapped_column(BigInteger)
    pool_place_centimes: Mapped[int | None] = mapped_column(BigInteger)
    nb_parieurs: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_pool_course_time", "course_id", "scraped_at"),
    )


class SuspensionProfessionnel(Base):
    """
    Suspensions officielles de jockeys et entraîneurs.
    Sources : France Galop (galop) et LeTrot (trot).
    Permet de savoir si un pro est suspendu le jour de la course.
    """
    __tablename__ = "suspensions_professionnels"

    suspension_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nom: Mapped[str] = mapped_column(String(100), index=True)
    type_pro: Mapped[str] = mapped_column(String(20))         # jockey / entraineur / driver
    source: Mapped[str] = mapped_column(String(20))           # france_galop / letrot
    date_debut: Mapped[datetime] = mapped_column(Date, index=True)
    date_fin: Mapped[datetime | None] = mapped_column(Date)
    nb_jours: Mapped[int | None] = mapped_column(Integer)
    motif: Mapped[str | None] = mapped_column(Text)
    est_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("nom", "source", "date_debut"),
        Index("ix_suspensions_nom_active", "nom", "est_active"),
    )


class PenetrometreLog(Base):
    """
    Historique des coefficients de pénétromètre par hippodrome (France Galop).
    Échelle officielle 0–9 : <3.0 = bon ferme, 3.0–4.5 = bon souple, 4.5–6.5 = souple,
    6.5–7.5 = très souple, >7.5 = lourd.
    """
    __tablename__ = "penetrometre_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    reunion_id: Mapped[str] = mapped_column(ForeignKey("reunions.reunion_id"), index=True)
    hippodrome: Mapped[str] = mapped_column(String(100))
    date_mesure: Mapped[datetime] = mapped_column(Date, index=True)
    coefficient: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(30))      # Bon / Souple / Lourd etc.
    heure_mesure: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("reunion_id"),
        Index("ix_penetrometre_hippodrome_date", "hippodrome", "date_mesure"),
    )


class TempsPassage(Base):
    """
    Temps de passage (splits) par partant et par course.
    Source : France Galop (galop/plat) et résultats PMU enrichis.
    Feature ML clé : 'ferme fort en fin de course' → signal positif sur longue distance.
    """
    __tablename__ = "temps_passage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    participation_id: Mapped[str | None] = mapped_column(ForeignKey("participations.participation_id"))
    numero: Mapped[int] = mapped_column(Integer)
    nom_cheval: Mapped[str] = mapped_column(String(100))

    passage_400m: Mapped[str | None] = mapped_column(String(15))
    passage_800m: Mapped[str | None] = mapped_column(String(15))
    passage_1000m: Mapped[str | None] = mapped_column(String(15))
    passage_1600m: Mapped[str | None] = mapped_column(String(15))
    passage_dernier_400m: Mapped[str | None] = mapped_column(String(15))
    vitesse_max_kmh: Mapped[float | None] = mapped_column(Float)
    position_500m: Mapped[int | None] = mapped_column(Integer)   # position à 500m du poteau
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("course_id", "numero"),
        Index("ix_temps_passage_course", "course_id"),
    )


class PronosticPresse(Base):
    """
    Pronostics de journalistes / experts presse spécialisée.
    Sources : Paris-Turf, CanalTurf, Geny Expert.
    Feature ML : 'consensus presse' — si 3+ journalistes sélectionnent le même cheval.
    """
    __tablename__ = "pronostics_presse"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.course_id"), index=True)
    source: Mapped[str] = mapped_column(String(30))           # paris_turf / canalturf / geny_expert
    journaliste: Mapped[str | None] = mapped_column(String(100))
    selection: Mapped[dict] = mapped_column(JSON)             # [{"numero": 3, "nom": "X", "rang": 1}]
    commentaire: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("course_id", "source", "journaliste"),
        Index("ix_pronostics_course", "course_id"),
    )


class AssociationJockeyEntraineur(Base):
    """
    Stats de la paire jockey × entraîneur sur une saison.
    Calculé en interne depuis les participations + résultats.
    Feature ML haute valeur : certaines associations = +15% win rate.
    """
    __tablename__ = "associations_jockey_entraineur"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    jockey_id: Mapped[str] = mapped_column(ForeignKey("jockeys.jockey_id"), index=True)
    entraineur_id: Mapped[str] = mapped_column(ForeignKey("entraineurs.entraineur_id"), index=True)
    saison: Mapped[int] = mapped_column(Integer)

    nb_courses: Mapped[int] = mapped_column(Integer, default=0)
    nb_victoires: Mapped[int] = mapped_column(Integer, default=0)
    nb_places: Mapped[int] = mapped_column(Integer, default=0)
    taux_victoire: Mapped[float] = mapped_column(Float, default=0.0)
    taux_place: Mapped[float] = mapped_column(Float, default=0.0)
    roi: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("jockey_id", "entraineur_id", "saison"),
        Index("ix_asso_jockey_entraineur", "jockey_id", "entraineur_id"),
    )
