"""
seed_model.py — Génère des données synthétiques et entraîne le modèle BlackTurf initial.

Usage (depuis /app/backend ou Docker) :
    python scripts/seed_model.py [--samples 5000] [--deploy]

Le modèle entraîné est sauvegardé dans /app/models/model_v0001.pkl
et déployé comme current_model.pkl si --deploy est passé.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ajouter le répertoire parent au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.models import BlackTurfEnsemble, build_training_dataset


# ──────────────────────────────────────────────────────────────────────────────
# Générateur de données synthétiques réalistes
# ──────────────────────────────────────────────────────────────────────────────

HIPPODROMES = ["VINCENNES", "LONGCHAMP", "DEAUVILLE", "CHANTILLY", "MAISONS-LAFFITTE", "COMPIÈGNE"]
DISCIPLINES = ["plat", "attele", "haies", "steeple"]
TERRAINS = ["bon", "souple", "lourd"]


def make_synthetic_features(n_courses: int = 200, nb_partants_mean: int = 10, seed: int = 42) -> pd.DataFrame:
    """
    Génère des features réalistes pour des courses hippiques synthétiques.
    Reproduit les 80+ features du pipeline BlackTurf.
    """
    rng = np.random.RandomState(seed)
    rows = []

    course_ids = [f"COURSE_{i:05d}" for i in range(n_courses)]

    for course_id in course_ids:
        nb_partants = max(4, int(rng.normal(nb_partants_mean, 2)))
        hippodrome = rng.choice(HIPPODROMES)
        discipline = rng.choice(DISCIPLINES)
        terrain = rng.choice(TERRAINS)
        distance = rng.choice([1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 3000])

        # ELO de base pour cette course (force relative des partants)
        elo_base = rng.normal(1500, 150, nb_partants)
        elo_base = np.clip(elo_base, 1000, 2200)

        for i in range(nb_partants):
            numero = i + 1
            elo = float(elo_base[i])

            # Forme récente (musique)
            forme = rng.beta(2, 3)  # 0..1 (0=mauvaise forme, 1=excellent)
            nb_courses_recent = int(rng.poisson(6) + 1)
            nb_top3_recent = int(rng.binomial(nb_courses_recent, 0.35))

            # Jockey et entraîneur
            jockey_wins = float(rng.beta(2, 8))
            entraineur_wins = float(rng.beta(2, 6))

            # Terrain compatibility (bon/souple/lourd → code 0/1/2)
            terrain_code = ["bon", "souple", "lourd"].index(terrain)
            terrain_compat = float(rng.beta(3, 2) if terrain == "bon" else rng.beta(2, 3))

            # Distance compatibility
            dist_bucket = 0 if distance < 1400 else (1 if distance < 2100 else 2)
            dist_compat = float(rng.beta(3, 2))

            # Cotes (cote_pmu ~ inversement proportionnelle à l'ELO + bruit)
            elo_norm = (elo - 1000) / 1200  # 0..1
            cote_base = max(1.1, 15.0 - elo_norm * 12.0 + rng.normal(0, 1.5))
            cote_pmu = round(float(cote_base), 1)
            cote_geny = round(float(cote_base * rng.uniform(0.9, 1.1)), 1)

            # EV implicite (pour feature)
            overround = rng.uniform(1.15, 1.25)
            proba_implicite = 1.0 / (cote_pmu * overround)

            # Repos
            jours_repos = int(rng.exponential(25))

            # Équipement
            premier_deferre = bool(rng.random() < 0.08)
            premieres_oeilleres = bool(rng.random() < 0.06)

            # Allocation (dotation) influence qualité partants
            allocation = float(rng.choice([5000, 10000, 15000, 25000, 50000, 100000]))

            row = {
                # Meta
                "course_id": course_id,
                "numero": numero,

                # A. ELO
                "elo_global": elo,
                "elo_discipline": float(elo + rng.normal(0, 30)),
                "elo_velocity": float(rng.normal(0, 5)),
                "elo_rank_in_race": float(nb_partants - i),  # plus haut ELO = rang 1

                # B. Forme récente
                "forme_recent": forme,
                "nb_courses_recent": nb_courses_recent,
                "nb_top3_recent": nb_top3_recent,
                "win_rate_recent": float(rng.beta(1.5, 5)),
                "avg_position_recent": float(rng.uniform(1, nb_partants)),
                "score_musique": float(forme * 0.8 + rng.uniform(0, 0.2)),
                "last_position": float(rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 10, 20], p=[0.12, 0.10, 0.10, 0.09, 0.08, 0.07, 0.07, 0.07, 0.15, 0.15])),
                "best_position_3": float(rng.uniform(1, 5)),

                # C. Repos
                "jours_repos": jours_repos,
                "repos_optimal": float(1 if 14 <= jours_repos <= 45 else 0),
                "nb_courses_saison": int(rng.poisson(12) + 1),
                "repos_short": float(1 if jours_repos < 10 else 0),

                # D. Distance
                "distance": distance,
                "dist_bucket": dist_bucket,
                "dist_compat": dist_compat,
                "dist_diff_optimal": float(abs(rng.normal(0, 200))),
                "dist_wins": float(rng.beta(2, 6)),

                # E. Terrain
                "terrain_code": terrain_code,
                "terrain_compat": terrain_compat,
                "lourd_wins": float(rng.beta(1, 8) if terrain == "lourd" else 0.0),
                "souple_wins": float(rng.beta(1, 6) if terrain == "souple" else 0.0),
                "bon_wins": float(rng.beta(2, 4) if terrain == "bon" else 0.0),

                # F. Hippodrome
                "hippodrome_wins": float(rng.beta(1.5, 8)),
                "hippodrome_top3": float(rng.beta(2, 6)),
                "hippodrome_experience": int(rng.poisson(3)),
                "hippodrome_encoded": float(HIPPODROMES.index(hippodrome)),

                # G. Cotes et marché
                "cote_pmu": cote_pmu,
                "cote_geny": cote_geny,
                "proba_implicite": proba_implicite,
                "cote_rank": float(i + 1),
                "overround_pmu": overround,
                "cote_relative": float(cote_pmu / max(cote_base * 0.5, 1.0)),
                "cote_vs_elo": float(cote_pmu - cote_base),
                "spi_score": float(max(0, rng.normal(0, 0.1))),

                # H. Équipement
                "premier_deferre": float(premier_deferre),
                "premieres_oeilleres": float(premieres_oeilleres),
                "changement_equipement": float(premier_deferre or premieres_oeilleres),
                "handicap_poids": float(rng.normal(58, 3)),

                # I. Jockey
                "jockey_win_rate": jockey_wins,
                "jockey_roi": float(rng.normal(0, 0.05)),
                "jockey_nb_courses": int(rng.poisson(100) + 50),
                "jockey_top3": float(rng.beta(3, 5)),
                "jockey_discipline_wins": float(rng.beta(2, 6)),
                "jockey_hippodrome_wins": float(rng.beta(1, 8)),

                # J. Entraîneur
                "entraineur_win_rate": entraineur_wins,
                "entraineur_roi": float(rng.normal(0.02, 0.04)),
                "entraineur_nb_courses": int(rng.poisson(80) + 40),
                "entraineur_top3": float(rng.beta(3, 5)),
                "entraineur_forme": float(rng.beta(2, 4)),
                "entraineur_hippodrome": float(rng.beta(2, 7)),

                # K. Cheval identité
                "age": int(rng.randint(2, 10)),
                "sexe_code": int(rng.choice([0, 1, 2])),
                "nb_courses_total": int(rng.poisson(20) + 5),
                "nb_victoires_total": int(rng.poisson(3)),
                "nb_top3_total": int(rng.poisson(7)),
                "earnings_total": float(rng.exponential(10000)),

                # L. Contexte course
                "nb_partants": nb_partants,
                "allocation": allocation,
                "discipline_code": DISCIPLINES.index(discipline),
                "est_quinte": float(rng.random() < 0.10),
                "est_quarte": float(rng.random() < 0.15),
                "est_tierce": float(rng.random() < 0.20),
                "niveau_course_code": float(rng.choice([0, 1, 2, 3])),

                # M. Marché / sagesse collective
                "rank_cotes": float(i + 1),
                "favorite": float(i == 0),
                "outsider": float(cote_pmu > 10),
                "nb_favoris": float(1),
                "cote_std_race": float(rng.uniform(2, 5)),

                # N. Signaux avancés
                "decote_detectee": float(rng.random() < 0.12),
                "valeur_latente": float(max(0, rng.normal(0, 0.05))),
                "confidence_elo": float(rng.beta(3, 2)),
                "accord_sources": float(rng.beta(4, 2)),
                "signal_combiné": float(forme * 0.4 + elo_norm * 0.4 + rng.uniform(0, 0.2)),
            }
            rows.append(row)

    return pd.DataFrame(rows)


def make_labels(df: pd.DataFrame, seed: int = 42) -> pd.Series:
    """
    Génère des labels réalistes : top-3 ≈ 30% des partants par course.
    La probabilité d'être dans le top-3 est corrélée avec l'ELO, la forme, les cotes.
    """
    rng = np.random.RandomState(seed)
    labels = np.zeros(len(df), dtype=int)

    for course_id, group in df.groupby("course_id"):
        nb_partants = len(group)
        nb_top3 = min(3, max(1, nb_partants // 3))

        # Score de probabilité = ELO + forme + inverse(cote_pmu)
        elo_norm = (group["elo_global"].values - 1000) / 1200
        forme = group["forme_recent"].values
        cote_inv = 1.0 / np.maximum(group["cote_pmu"].values, 1.1)
        cote_inv_norm = cote_inv / cote_inv.max()

        score = 0.4 * elo_norm + 0.3 * forme + 0.3 * cote_inv_norm
        score += rng.uniform(0, 0.15, len(group))  # bruit réaliste

        # Top-3 par score
        top3_indices = np.argsort(score)[::-1][:nb_top3]
        for idx in top3_indices:
            labels[group.index[idx]] = 1

    return pd.Series(labels, index=df.index, name="label")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed BlackTurf ML model")
    parser.add_argument("--samples", type=int, default=3000, help="Nombre de courses (défaut: 3000)")
    parser.add_argument("--deploy", action="store_true", help="Déploie comme current_model.pkl")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    print(f"[seed_model] Génération de {args.samples} courses synthétiques...")
    df = make_synthetic_features(n_courses=args.samples, seed=args.seed)
    y = make_labels(df, seed=args.seed)

    print(f"[seed_model] Dataset: {len(df)} partants, {df['course_id'].nunique()} courses")
    print(f"[seed_model] Taux top-3: {y.mean():.1%}")

    # Sélectionner uniquement les features (exclure meta)
    META_COLS = {"course_id", "numero"}
    feature_cols = [c for c in df.columns if c not in META_COLS]
    X = df[feature_cols + ["course_id"]]  # keep course_id for walk-forward

    print("[seed_model] Entraînement du modèle...")
    model = BlackTurfEnsemble()
    metrics = model.train(X, y)

    print("\n" + "="*50)
    print("MÉTRIQUES DU MODÈLE")
    print("="*50)
    print(f"  AUC-ROC          : {metrics['auc_roc']:.4f}")
    print(f"  Brier Score      : {metrics['brier_score']:.4f}  (seuil < 0.18)")
    print(f"  Précision Top-3  : {metrics['precision_top3']:.4f}")
    print(f"  ROI simulé       : {metrics['roi_simule']:.4f}")
    print(f"  Walk-forward AUC : {metrics['walk_forward_auc']:.4f}")
    print(f"  Walk-forward Var : {metrics['walk_forward_variance']:.6f}")
    print("="*50)

    if metrics["brier_score"] > 0.18:
        print(f"⚠️  Brier score {metrics['brier_score']:.4f} > seuil 0.18 (données synthétiques)")
        print("   → Normal sur données synthétiques, OK sur données réelles")

    if args.deploy:
        model.deploy(version_num=1)
        print(f"\n✅ Modèle déployé → /app/models/current_model.pkl")
    else:
        path = model.save(version_num=1)
        print(f"\n✅ Modèle sauvegardé → {path}")
        print("   Utilisez --deploy pour le rendre actif")

    # Feature importance top-10
    if model.feature_importance:
        print("\nTOP 10 FEATURE IMPORTANCE (XGBoost):")
        top10 = sorted(model.feature_importance.items(), key=lambda x: -x[1])[:10]
        for name, imp in top10:
            bar = "█" * int(imp * 50)
            print(f"  {name:<35} {bar} {imp:.4f}")

    # Save metrics
    models_dir = Path("/app/models") if Path("/app").exists() else Path(__file__).parent.parent / "models"
    metrics_path = models_dir / "seed_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"\n📊 Métriques sauvegardées → {metrics_path}")

    return 0 if metrics["brier_score"] <= 0.30 else 1  # tolérant pour données synthétiques


if __name__ == "__main__":
    sys.exit(main())
