"""
seed_dev_data.py — Peuple la DB BlackTurf avec donnees realistes de dev.

Cree :
  - 1 admin + 2 users de test (free/expert)
  - 4 hippodromes
  - 10 jockeys + 6 entraineurs
  - 40 chevaux
  - 3 reunions (hier, aujourd'hui, demain)
  - ~18 courses variees (Plat/Attele/Haies, differents statuts)
  - ~180 participations
  - 1 ModelVersion active
  - Predictions + ValueBets pour courses a_venir
  - ScrapeLog recent
  - BankrollEntries historiques pour user expert

Usage :
    python scripts/seed_dev_data.py [--reset]
    --reset : vide les tables avant d'inserer
"""
import sys
import argparse
import asyncio
import uuid
import random
import os
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401 — populate Base.metadata
from db.database import AsyncSessionLocal as async_session
from db.models import (
    Hippodrome, Jockey, Entraineur, Cheval, Reunion, Course,
    Participation, Prediction, ValueBet, ModelVersion,
    User, BankrollEntry, ScrapeLog
)
from api.routes.auth import _hash

rng = random.Random(42)

# ─────────────────────────────────────────────
# Donnees de base
# ─────────────────────────────────────────────

HIPPODROMES_DATA = [
    {"nom": "Vincennes",       "code": "VIN",  "ville": "Vincennes",       "type_piste": "Trot"},
    {"nom": "Longchamp",       "code": "LON",  "ville": "Paris",           "type_piste": "Plat"},
    {"nom": "Deauville",       "code": "DEA",  "ville": "Deauville",       "type_piste": "Mixte"},
    {"nom": "Chantilly",       "code": "CHA",  "ville": "Chantilly",       "type_piste": "Plat"},
    {"nom": "Maisons-Laffitte","code": "MAI",  "ville": "Maisons-Laffitte","type_piste": "Plat"},
    {"nom": "Compiègne",       "code": "COM",  "ville": "Compiègne",       "type_piste": "Mixte"},
]

JOCKEYS_DATA = [
    "C. Soumillon", "O. Peslier", "T. Jarnet", "G. Benoist",
    "A. Lemaitre", "S. Pasquier", "M. Guyon", "P.-C. Boudot",
    "F. Blondel", "Y. Barberot",
]

ENTRAINEURS_DATA = [
    "A. Fabre", "E. Lellouche", "J-C. Rouget", "H-A. Pantall",
    "C. Head-Maarek", "Y. de Nicolay",
]

CHEVAUX_DATA = [
    ("Golden Storm",    "H", 5, 1650.0), ("Lady Versailles",  "F", 4, 1580.0),
    ("Roi du Desert",   "H", 6, 1720.0), ("Brise d'Automne",  "F", 3, 1510.0),
    ("Vendome Express", "H", 4, 1590.0), ("Nuit Etoilee",      "F", 5, 1640.0),
    ("Capitaine Feu",   "H", 7, 1480.0), ("Vent Solaire",      "H", 4, 1560.0),
    ("Eclair du Nord",  "H", 5, 1700.0), ("Belle Epoque",      "F", 6, 1530.0),
    ("Titan Rapide",    "H", 4, 1610.0), ("Perle Noire",       "F", 3, 1490.0),
    ("Maestro Bleu",    "H", 5, 1660.0), ("Fantome Blanc",     "H", 6, 1540.0),
    ("Diamant Rose",    "F", 4, 1575.0), ("Duc de Brest",      "H", 7, 1460.0),
    ("Marée Haute",     "H", 5, 1620.0), ("Tempête d'Argent",  "H", 4, 1585.0),
    ("Soleil Levant",   "H", 3, 1500.0), ("Reine du Pré",      "F", 5, 1635.0),
    ("Flèche d'Or",     "H", 4, 1595.0), ("Vague Bleue",       "F", 6, 1525.0),
    ("Centurion",       "H", 5, 1680.0), ("Aurora Borealis",   "F", 4, 1555.0),
    ("Foudre Noire",    "H", 6, 1515.0), ("Cascade Royale",    "F", 3, 1475.0),
    ("L'Indomptable",   "H", 7, 1450.0), ("Etoile Filante",    "F", 5, 1645.0),
    ("Mistral Fou",     "H", 4, 1600.0), ("Douce France",      "F", 6, 1520.0),
    ("Hercule du Val",  "H", 5, 1670.0), ("Perle d'Orient",    "F", 4, 1565.0),
    ("Zephyr Royal",    "H", 3, 1510.0), ("Lumière d'Espoir",  "F", 5, 1630.0),
    ("Ouragan Rouge",   "H", 6, 1490.0), ("Colombe d'Or",      "F", 4, 1570.0),
    ("Titan Vert",      "H", 4, 1605.0), ("Manon des Sources", "F", 5, 1640.0),
    ("Dragon d'Azur",   "H", 5, 1660.0), ("Sirène du Lac",     "F", 6, 1530.0),
]


# ─────────────────────────────────────────────
# Courses de dev
# ─────────────────────────────────────────────

COURSES_DATA = [
    # (num, nom, discipline, distance, statut, nb_partants, est_quinte, terrain, niveau)
    # HIER — terminees
    (1,  "Prix du Bois de Boulogne",   "Plat",   1600, "termine", 10, False, "Bon",    "Conditions"),
    (2,  "Prix de la Marne",            "Haies",  3200, "termine",  8, False, "Souple", "Conditions"),
    (3,  "Prix de la Seine",            "Plat",   1400, "termine", 12, False, "Bon",    "Listed"),
    (4,  "Grand Prix Quinté Test",      "Plat",   2000, "termine", 14, True,  "Bon",    "Group2"),
    (5,  "Prix Attele du Soir",         "Attelé", 2100, "termine",  9, False, "Bon",    "Conditions"),
    (6,  "Steeple Chase Sélectif",      "Steeple",3600, "termine",  7, False, "Lourd",  "Conditions"),
    # AUJOURD'HUI — mix a_venir/en_cours
    (1,  "Prix du Muguet",              "Plat",   1400, "a_venir", 11, False, "Bon",    "Listed"),
    (2,  "Prix de Diane Trial",         "Plat",   2100, "a_venir",  9, False, "Bon",    "Group3"),
    (3,  "Quinté+ du Jour",             "Plat",   1600, "a_venir", 15, True,  "Bon",    "Conditions"),
    (4,  "Prix Trot Vincennes",         "Attelé", 2700, "a_venir", 12, False, "Bon",    "Listed"),
    (5,  "Prix des Haies Printemps",    "Haies",  3800, "a_venir",  8, False, "Souple", "Conditions"),
    (6,  "Handicap des Plaines",        "Plat",   2400, "a_venir", 14, False, "Bon",    "Conditions"),
    # DEMAIN — a_venir uniquement
    (1,  "Prix du Palais Royal",        "Plat",   1600, "a_venir", 10, False, "Bon",    "Group3"),
    (2,  "Grand Critérium",             "Plat",   1400, "a_venir", 12, False, "Bon",    "Group1"),
    (3,  "Prix du Président",           "Attelé", 2150, "a_venir", 11, False, "Bon",    "Group2"),
    (4,  "Prix de la Côte Normande",    "Haies",  4200, "a_venir",  9, False, "Souple", "Conditions"),
    (5,  "Quinté+ du Lendemain",        "Plat",   2000, "a_venir", 16, True,  "Bon",    "Conditions"),
    (6,  "Handicap Printanier",         "Plat",   1800, "a_venir", 13, False, "Bon",    "Conditions"),
]


def gen_cote(elo: float, nb_partants: int, overround: float = 1.20) -> tuple[float, float, float]:
    """Génère cotes PMU/Geny/BZH cohérentes avec l'ELO."""
    proba_base = (elo - 1000) / 700 * 0.8 + 0.05
    proba_base = max(0.04, min(0.85, proba_base))
    cote_juste = 1.0 / proba_base
    cote_pmu = round(cote_juste * overround * rng.uniform(0.92, 1.08), 1)
    cote_pmu = max(1.1, cote_pmu)
    cote_geny = round(cote_pmu * rng.uniform(0.90, 1.10), 1)
    cote_bzh  = round(cote_pmu * rng.uniform(0.88, 1.12), 1)
    return cote_pmu, cote_geny, cote_bzh


def gen_musique() -> str:
    positions = []
    for _ in range(rng.randint(3, 8)):
        pos = rng.choices(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            weights=[8, 8, 8, 7, 7, 6, 5, 5, 4, 3]
        )[0]
        disc = rng.choice(["p", "h", "s", "a"])
        positions.append(f"{pos}{disc}")
    return "".join(positions)


# ─────────────────────────────────────────────
# Main seed
# ─────────────────────────────────────────────

def _assert_safe_target() -> None:
    """
    Garde-fou anti-prod : ce script insère 40 chevaux FICTIFS et des résultats
    aléatoires, et --reset VIDE les tables. Jamais sur une base réelle.

    Autorise uniquement si la cible est manifestement dev/test :
      - host localhost / 127.0.0.1 / @db: (docker compose dev), OU
      - ENVIRONMENT ∈ {dev, development, test, local, ""}, OU
      - override explicite BLACKTURF_ALLOW_SEED=1
    """
    url = os.environ.get("DATABASE_URL", "")
    env = os.environ.get("ENVIRONMENT", "").lower()
    override = os.environ.get("BLACKTURF_ALLOW_SEED") == "1"

    is_local = ("localhost" in url) or ("127.0.0.1" in url) or ("@db:" in url)
    is_dev_env = env in {"dev", "development", "test", "local", ""}

    if override or (is_local and is_dev_env):
        return

    host = url.split("@")[-1].split("/")[0] or "?"
    print("=" * 60, file=sys.stderr)
    print("REFUS : seed_dev_data injecte des donnees FICTIVES.", file=sys.stderr)
    print("Cible non reconnue comme dev/test — abandon pour proteger", file=sys.stderr)
    print("les donnees reelles.", file=sys.stderr)
    print(f"  DATABASE_URL host = {host}", file=sys.stderr)
    print(f"  ENVIRONMENT       = {env or '(non defini)'}", file=sys.stderr)
    print("Pour forcer sciemment : BLACKTURF_ALLOW_SEED=1", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(2)


async def seed(reset: bool = False):
    _assert_safe_target()
    async with async_session() as session:
        if reset:
            print("[seed] Reset tables...")
            from sqlalchemy import delete, text
            for tbl in ["value_bets", "predictions", "participations", "courses",
                        "reunions", "bankroll_entries", "scrape_log",
                        "model_versions", "chevaux", "jockeys", "entraineurs",
                        "hippodromes", "users"]:
                await session.execute(text(f"DELETE FROM {tbl}"))
            await session.commit()

        today = date.today()
        now = datetime.utcnow()

        # ── 1. Hippodromes ────────────────────────────────────────────────
        print("[seed] Hippodromes...")
        hippodrome_map = {}
        for hd in HIPPODROMES_DATA:
            h = Hippodrome(hippodrome_id=str(uuid.uuid4()), **hd)
            session.add(h)
            hippodrome_map[hd["nom"]] = h.hippodrome_id
        await session.flush()

        # ── 2. Jockeys ────────────────────────────────────────────────────
        print("[seed] Jockeys + Entraineurs...")
        jockey_ids = []
        for nom in JOCKEYS_DATA:
            j = Jockey(jockey_id=str(uuid.uuid4()), nom=nom)
            session.add(j)
            jockey_ids.append(j.jockey_id)

        entraineur_ids = []
        for nom in ENTRAINEURS_DATA:
            e = Entraineur(entraineur_id=str(uuid.uuid4()), nom=nom)
            session.add(e)
            entraineur_ids.append(e.entraineur_id)
        await session.flush()

        # ── 3. Chevaux ────────────────────────────────────────────────────
        print("[seed] Chevaux...")
        cheval_ids = []
        for nom, sexe, age, elo in CHEVAUX_DATA:
            c = Cheval(
                cheval_id=str(uuid.uuid4()),
                nom=nom, sexe=sexe, age=age,
                elo_score_global=elo + rng.uniform(-30, 30),
                elo_score_plat=elo + rng.uniform(-30, 30),
                elo_score_trot=elo + rng.uniform(-30, 30),
                elo_score_obstacle=elo + rng.uniform(-30, 30),
                entraineur_actuel=rng.choice(ENTRAINEURS_DATA),
            )
            session.add(c)
            cheval_ids.append((c.cheval_id, elo))
        await session.flush()

        # ── 4. ModelVersion ────────────────────────────────────────────────
        print("[seed] ModelVersion...")
        mv = ModelVersion(
            version_id=str(uuid.uuid4()),
            version_num=1,
            nom_fichier="model_v0001.pkl",
            auc_roc=0.9198,
            brier_score=0.1013,
            precision_top3=0.0,
            roi_simule=3.07,
            nb_courses_train=3000,
            est_actif=True,
            walk_forward_auc=0.9182,
            walk_forward_variance=0.000011,
            feature_importance={"elo_global": 0.18, "cote_pmu": 0.14, "forme_recent": 0.12},
        )
        session.add(mv)
        await session.flush()
        model_version_id = mv.version_id

        # ── 5. Reunions + Courses + Participations + Predictions ───────────
        print("[seed] Reunions / Courses / Participations...")

        days = [today - timedelta(days=1), today, today + timedelta(days=1)]
        hippo_names = ["Longchamp", "Vincennes", "Deauville"]
        course_idx = 0

        reunion_ids = []
        participation_records = []  # [(participation_id, cote_pmu, statut)]

        for day_i, (day, hippo_name) in enumerate(zip(days, hippo_names)):
            reunion_id = f"R{day.strftime('%Y%m%d')}{day_i+1}"
            hippo_id = hippodrome_map[hippo_name]
            reunion = Reunion(
                reunion_id=reunion_id,
                date=day,
                hippodrome_id=hippo_id,
                hippodrome_nom=hippo_name,
                numero=day_i + 1,
            )
            session.add(reunion)
            reunion_ids.append(reunion_id)
            await session.flush()  # commit reunion before courses FK

            # 6 courses per reunion
            day_courses = COURSES_DATA[day_i * 6:(day_i + 1) * 6]
            for c_num, (num, nom, discipline, distance, statut, nb_partants, est_quinte, terrain, niveau) in enumerate(day_courses):
                course_id = f"C{day.strftime('%Y%m%d')}{day_i+1}R{num}"
                heure = 12 + c_num * 90 // 60
                minute = (c_num * 90) % 60
                date_heure = datetime(day.year, day.month, day.day, heure, minute, 0)

                course = Course(
                    course_id=course_id,
                    reunion_id=reunion_id,
                    numero=num,
                    nom=nom,
                    date_heure=date_heure,
                    hippodrome_nom=hippo_name,
                    discipline=discipline,
                    distance=distance,
                    terrain_officiel=terrain,
                    terrain_code=["Bon", "Souple", "Lourd"].index(terrain),
                    nb_partants=nb_partants,
                    allocation=rng.choice([500000, 1000000, 1500000, 2500000, 5000000]),
                    niveau_course=niveau,
                    statut=statut,
                    est_quinte=est_quinte,
                    est_quarte=rng.random() < 0.1,
                    est_tierce=rng.random() < 0.15,
                )
                session.add(course)

                # Participations
                pool = list(cheval_ids)
                rng.shuffle(pool)
                selected = pool[:nb_partants]

                part_ids_for_course = []
                for i, (cheval_id, elo) in enumerate(selected):
                    cote_pmu, cote_geny, cote_bzh = gen_cote(elo, nb_partants)
                    part_id = str(uuid.uuid4())
                    part = Participation(
                        participation_id=part_id,
                        course_id=course_id,
                        cheval_id=cheval_id,
                        jockey_id=rng.choice(jockey_ids),
                        entraineur_id=rng.choice(entraineur_ids),
                        numero=i + 1,
                        poids_prevu=rng.uniform(54, 62),
                        cote_pmu=cote_pmu,
                        cote_geny=cote_geny,
                        cote_bzh=cote_bzh,
                        rang_pronostic_pmu=i + 1,
                        musique=gen_musique(),
                        non_partant=False,
                    )
                    session.add(part)
                    part_ids_for_course.append((part_id, elo, cote_pmu))
                    participation_records.append((part_id, course_id, elo, cote_pmu, statut))

                await session.flush()

                # Predictions + ValueBets uniquement pour courses a_venir
                if statut == "a_venir":
                    # Calculer rang par ELO
                    sorted_parts = sorted(part_ids_for_course, key=lambda x: -x[1])
                    for rang, (part_id, elo, cote_pmu) in enumerate(sorted_parts):
                        elo_norm = (elo - 1000) / 700
                        proba_top3 = max(0.05, min(0.90, elo_norm * 0.5 + rng.uniform(0.1, 0.4)))
                        proba_top1 = proba_top3 * rng.uniform(0.25, 0.45)

                        pred = Prediction(
                            prediction_id=str(uuid.uuid4()),
                            participation_id=part_id,
                            course_id=course_id,
                            model_version_id=model_version_id,
                            proba_top1=round(proba_top1, 4),
                            proba_top3=round(proba_top3, 4),
                            rang_predit=rang + 1,
                            confidence_score=round(proba_top3 * 100, 1),
                        )
                        session.add(pred)
                        await session.flush()

                        # Value bet si EV positif
                        ev_pmu = (cote_pmu * proba_top3) - 1.0
                        if ev_pmu >= 0.05 and proba_top3 >= 0.50:
                            cote_geny = rng.choice(part_ids_for_course)[2] * rng.uniform(0.85, 1.10)
                            ev_geny = (cote_geny * proba_top3) - 1.0

                            # Niveau 1-4 etoiles
                            if ev_pmu >= 0.30 and proba_top3 >= 0.65:
                                niveau_vb = 4
                            elif ev_pmu >= 0.20 and proba_top3 >= 0.60:
                                niveau_vb = 3
                            elif ev_pmu >= 0.10 and proba_top3 >= 0.55:
                                niveau_vb = 2
                            else:
                                niveau_vb = 1

                            vb = ValueBet(
                                vb_id=str(uuid.uuid4()),
                                prediction_id=pred.prediction_id,
                                course_id=course_id,
                                participation_id=part_id,
                                ev_pmu=round(ev_pmu, 4),
                                ev_geny=round(ev_geny, 4),
                                ev_bzh=None,
                                ev_max=round(max(ev_pmu, ev_geny), 4),
                                meilleure_source="pmu" if ev_pmu >= ev_geny else "geny",
                                niveau=niveau_vb,
                                spi_detected=rng.random() < 0.15,
                                spi_score=round(rng.uniform(0.15, 0.45), 3) if rng.random() < 0.15 else None,
                                actif=True,
                                detecte_a=now,
                            )
                            session.add(vb)

        await session.flush()

        # ── 6. Users ────────────────────────────────────────────────────────
        print("[seed] Users...")
        admin = User(
            user_id=str(uuid.uuid4()),
            email="admin@blackturf.fr",
            hashed_password=_hash("Admin123!"),
            nom="Admin", prenom="BlackTurf",
            plan="expert", is_admin=True, email_verified=True,
            bankroll_initiale=1000.0,
        )
        user_free = User(
            user_id=str(uuid.uuid4()),
            email="demo@blackturf.fr",
            hashed_password=_hash("Demo123!"),
            nom="Demo", prenom="User",
            plan="free", email_verified=True,
            bankroll_initiale=200.0,
        )
        user_expert = User(
            user_id=str(uuid.uuid4()),
            email="expert@blackturf.fr",
            hashed_password=_hash("Expert123!"),
            nom="Expert", prenom="User",
            plan="expert", email_verified=True,
            bankroll_initiale=500.0,
        )
        session.add_all([admin, user_free, user_expert])
        await session.flush()

        # ── 7. BankrollEntries (historique 30j pour user_expert) ────────────
        print("[seed] BankrollEntries...")
        for i in range(30):
            day_offset = 30 - i
            entry_date = now - timedelta(days=day_offset)
            won = rng.random() < 0.38
            mise = round(rng.uniform(5, 25), 2)
            cote = round(rng.uniform(2.0, 8.0), 1)
            gain = round(cote * mise - mise, 2) if won else round(-mise, 2)

            b = BankrollEntry(
                entry_id=str(uuid.uuid4()),
                user_id=user_expert.user_id,
                date=entry_date,
                type_pari=rng.choice(["Simple Gagnant", "Couplé Placé", "Tiercé"]),
                chevaux=f"{rng.randint(1,14)}-{rng.randint(1,14)}",
                mise=mise,
                cote=cote if won else None,
                gain_perte=gain,
                resultat="gagne" if won else "perd",
            )
            session.add(b)

        # ── 8. ScrapeLog ────────────────────────────────────────────────────
        print("[seed] ScrapeLogs...")
        for source in ["pmu", "geny", "bzh"]:
            for i in range(3):
                sl = ScrapeLog(
                    log_id=str(uuid.uuid4()),
                    source=source,
                    statut="ok",
                    nb_courses=rng.randint(4, 12),
                    nb_partants=rng.randint(40, 120),
                    duree_ms=rng.randint(800, 3500),
                    created_at=now - timedelta(hours=i * 4),
                )
                session.add(sl)

        await session.commit()
        print("[seed] Commit OK.")

    # Summary
    print()
    print("=" * 55)
    print("SEED TERMINE")
    print("=" * 55)
    print(f"  Hippodromes  : {len(HIPPODROMES_DATA)}")
    print(f"  Jockeys      : {len(JOCKEYS_DATA)}")
    print(f"  Chevaux      : {len(CHEVAUX_DATA)}")
    print(f"  Reunions     : 3  (hier / aujourd'hui / demain)")
    print(f"  Courses      : 18 (6 terminees / 12 a venir)")
    print(f"  Participations: ~{len(CHEVAUX_DATA) * 18 // 3} estimees")
    print("  Comptes de test :")
    print("    admin@blackturf.fr     / Admin123!  [admin, expert]")
    print("    expert@blackturf.fr    / Expert123! [expert]")
    print("    demo@blackturf.fr      / Demo123!   [free]")
    print("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Vider les tables avant seed")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))
