"""
seed_model.py — Entraîne le modèle BlackTurf initial sur des données synthétiques
dont les NOMS DE FEATURES correspondent EXACTEMENT à la sortie du builder de
production (ml.features.compute_all_features_for_course → 156 features).

C'est un PRIOR de démarrage à froid (cold-start). Il n'invente aucune donnée réelle :
il sert uniquement de point de départ raisonnable (favori = plus de chances) tant que
les vrais résultats de courses ne sont pas accumulés. L'apprentissage adaptatif
réajuste ensuite sur données réelles.

Usage (dans le conteneur api) :
    python scripts/seed_model.py [--samples 3000] [--deploy]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.models import BlackTurfEnsemble


# ──────────────────────────────────────────────────────────────────────────────
# Schéma canonique : les 156 features produites par le builder de production.
# (ordre/nom identiques à compute_all_features_for_course)
# ──────────────────────────────────────────────────────────────────────────────
CANON_FEATURES = [
    "elo_global", "elo_discipline", "elo_vs_moyenne", "elo_vs_max", "elo_pct_rank",
    "delta_elo_5courses", "velocity_elo", "elo_trend_30j",
    "forme_1_course", "forme_3_courses", "forme_5_courses", "forme_10_courses",
    "forme_tendance", "regularite", "taux_top3", "taux_victoire_5c",
    "dyn_taux_accelere", "dyn_taux_faiblit", "dyn_finit_fort", "dyn_nb_data",
    "dyn_reduction_km_best", "dyn_reduction_km_moy",
    "conf_nb_rencontres", "conf_taux_victoire", "conf_bilan_net",
    "conf_nb_rivaux_battus", "conf_nb_rivaux_bourreaux", "conf_nb_data",
    "jours_repos", "fraicheur_score", "nb_courses_90j", "surmenage_score",
    "jours_depuis_derniere_db",
    "pref_dist_longue", "nb_courses_distance", "delta_dist_prefere",
    "pref_distance_actuelle", "dist_code",
    "pref_terrain_bon", "nb_courses_terrain", "pref_terrain_actuel", "terrain_code",
    "humidite_piste", "penetrometre_coef",
    "pref_hippodrome", "nb_courses_hippodrome", "record_hippodrome", "corde_preference",
    "cote_pmu", "cote_geny", "cote_bzh", "cote_winamax", "cote_betclic",
    "cote_unibet", "cote_betfair_exchange", "cote_marche_min", "spread_bookmakers",
    "gap_pmu_betfair", "steam_move_betclic", "ratio_pmu_geny", "mouvement_30min",
    "mouvement_bm_pct", "rang_cote", "est_favori", "prob_implicite", "pool_gagnant_ratio",
    "changement_equipement", "premier_deferre", "nouvelles_oeilleres", "equipement_score",
    "jockey_taux_victoire_global", "jockey_taux_place_global", "jockey_roi",
    "jockey_montes_30j", "jockey_victoires_saison", "jockey_forme_30j", "changement_jockey",
    "asso_jockey_entraineur_taux", "asso_jockey_entraineur_nb", "asso_jockey_entraineur_fiable",
    "entraineur_taux_global", "entraineur_taux_place", "entraineur_roi",
    "entraineur_victoires_saison", "combo_jockey_entraineur", "entraineur_forme_30j",
    "age", "age_squared", "sexe_code", "gains_log", "retard_gains", "indice_valeur",
    "running_style_code", "taux_en_tete", "prix_vente_log",
    "nb_partants", "log_nb_partants", "discipline_code", "niveau_course_code",
    "dotation_log", "course_designee", "heure_course", "nb_courses_reunion",
    "rang_popularite", "rang_pronostic_geny", "pronostic_expert_rang",
    "sagesse_foules_score", "consensus_sources", "nb_experts_presse", "nb_premier_presse",
    "presse_consensus_score", "momentum_3j", "variance_cotes_7j", "spi_score",
    "decote_detectee", "valeur_latente", "field_hhi", "nb_outsiders", "ecart_proba_top2",
    "rang_cote_relatif", "mois_course", "saison_code", "saison_form", "market_timing_score",
    "pace_conflict_score", "running_style_terrain_fit", "nb_meneurs_course",
    "sire_dist_winrate", "sire_terrain_winrate",
    "jockey_cheval_synergy_nb", "jockey_cheval_synergy_score",
    "course_fingerprint_nb", "course_fingerprint_score",
    "time_decay_form", "opposition_quality", "vitesse_theorique", "stamina_index",
    "discipline_coherence", "class_drop_ratio", "class_jump_score",
    "class_drop_flag", "class_rise_flag", "bounce_score", "current_form_vs_best",
    "career_trajectory", "draw_bias_score", "trainer_return_bonus",
    "career_momentum", "form_vs_career_rate", "career_win_rate", "recent_win_rate",
    "data_completeness", "signal_agreement", "composite_confidence",
]


def _clip01(x):
    return float(np.clip(x, 0.0, 1.0))


def make_synthetic_features(n_courses: int = 3000, nb_partants_mean: int = 11, seed: int = 42) -> pd.DataFrame:
    """Génère des features avec les NOMS EXACTS du builder, corrélées à une force latente."""
    rng = np.random.RandomState(seed)
    rows = []

    for ci in range(n_courses):
        course_id = f"COURSE_{ci:05d}"
        nb = max(5, int(rng.normal(nb_partants_mean, 2)))
        nb = min(nb, 18)
        # contexte course
        discipline_code = int(rng.randint(0, 4))
        terrain_code = int(rng.randint(0, 3))
        niveau = int(rng.randint(0, 4))
        dist_code = int(rng.randint(0, 5))
        penetro = float(rng.uniform(2.5, 4.5))
        dotation_log = float(np.log1p(rng.choice([5000, 10000, 25000, 50000, 100000])))
        heure = int(rng.randint(11, 21))
        mois = int(rng.randint(1, 13))
        saison = int((mois % 12) // 3)

        # force latente par cheval
        strengths = rng.beta(2, 2, nb)
        # cotes dérivées de la force (fort → cote basse)
        cote_raw = np.clip(1.2 + (1 - strengths) * 20 + rng.normal(0, 1.2, nb), 1.1, 99)
        rang_cote = (np.argsort(np.argsort(cote_raw)) + 1)  # 1 = plus petite cote
        overround = rng.uniform(1.15, 1.25)

        elo_vals = np.clip(1000 + strengths * 1000 + rng.normal(0, 40, nb), 900, 2200)
        elo_mean = float(elo_vals.mean())
        elo_max = float(elo_vals.max())

        for i in range(nb):
            s = float(strengths[i])
            cote = float(round(cote_raw[i], 1))
            rc = int(rang_cote[i])
            elo = float(elo_vals[i])
            forme5 = _clip01(s + rng.normal(0, 0.12))
            prob_imp = 1.0 / (cote * overround)

            row = {k: 0.0 for k in CANON_FEATURES}
            row.update({
                "course_id": course_id,
                # ELO
                "elo_global": elo,
                "elo_discipline": float(elo + rng.normal(0, 25)),
                "elo_vs_moyenne": float(elo - elo_mean),
                "elo_vs_max": float(elo - elo_max),
                "elo_pct_rank": _clip01(1 - (np.sum(elo_vals > elo) / nb)),
                "delta_elo_5courses": float(rng.normal(0, 8)),
                "velocity_elo": float(rng.normal(0, 4)),
                "elo_trend_30j": float(rng.normal(0, 5)),
                # Forme
                "forme_1_course": _clip01(s + rng.normal(0, 0.18)),
                "forme_3_courses": _clip01(s + rng.normal(0, 0.14)),
                "forme_5_courses": forme5,
                "forme_10_courses": _clip01(s + rng.normal(0, 0.12)),
                "forme_tendance": float(np.clip(rng.normal(0, 0.5), -1, 1)),
                "regularite": _clip01(rng.beta(2, 2)),
                "taux_top3": _clip01(s * 0.7 + rng.uniform(0, 0.3)),
                "taux_victoire_5c": _clip01(s * 0.5 + rng.uniform(0, 0.2)),
                # Dynamique (souvent peu de data)
                "dyn_taux_accelere": _clip01(rng.beta(2, 5)),
                "dyn_taux_faiblit": _clip01(rng.beta(2, 5)),
                "dyn_finit_fort": _clip01(rng.beta(2, 5)),
                "dyn_nb_data": int(rng.poisson(3)),
                "dyn_reduction_km_best": float(rng.uniform(0, 1.2)),
                "dyn_reduction_km_moy": float(rng.uniform(0, 1.2)),
                # Confrontations
                "conf_nb_rencontres": float(rng.poisson(2)),
                "conf_taux_victoire": _clip01(rng.beta(2, 3)),
                "conf_bilan_net": float(rng.normal(0, 2)),
                "conf_nb_rivaux_battus": float(rng.poisson(2)),
                "conf_nb_rivaux_bourreaux": float(rng.poisson(2)),
                "conf_nb_data": float(rng.poisson(3)),
                # Repos
                "jours_repos": int(rng.exponential(25) + 5),
                "fraicheur_score": _clip01(rng.beta(3, 2)),
                "nb_courses_90j": int(rng.poisson(3)),
                "surmenage_score": _clip01(rng.beta(1, 6)),
                "jours_depuis_derniere_db": int(rng.exponential(25) + 5),
                # Distance
                "pref_dist_longue": _clip01(rng.beta(2, 2)),
                "nb_courses_distance": int(rng.poisson(4)),
                "delta_dist_prefere": float(rng.normal(0, 200)),
                "pref_distance_actuelle": _clip01(s * 0.4 + rng.uniform(0, 0.4)),
                "dist_code": dist_code,
                # Terrain
                "pref_terrain_bon": _clip01(rng.beta(2, 2)),
                "nb_courses_terrain": int(rng.poisson(4)),
                "pref_terrain_actuel": _clip01(s * 0.3 + rng.uniform(0, 0.4)),
                "terrain_code": terrain_code,
                "humidite_piste": float(rng.uniform(0, 1)),
                "penetrometre_coef": penetro,
                # Hippodrome
                "pref_hippodrome": _clip01(rng.beta(2, 2)),
                "nb_courses_hippodrome": int(rng.poisson(3)),
                "record_hippodrome": _clip01(rng.beta(1, 6)),
                "corde_preference": _clip01(rng.beta(2, 2)),
                # Cotes / marché
                "cote_pmu": cote,
                "cote_geny": float(round(cote * rng.uniform(0.92, 1.08), 1)),
                "cote_bzh": float(round(cote * rng.uniform(0.92, 1.08), 1)),
                "cote_winamax": float(round(cote * rng.uniform(0.92, 1.08), 1)),
                "cote_betclic": float(round(cote * rng.uniform(0.92, 1.08), 1)),
                "cote_unibet": float(round(cote * rng.uniform(0.92, 1.08), 1)),
                "cote_betfair_exchange": float(round(cote * rng.uniform(0.95, 1.1), 1)),
                "cote_marche_min": float(round(cote * rng.uniform(0.9, 0.99), 1)),
                "spread_bookmakers": float(abs(rng.normal(0, 0.5))),
                "gap_pmu_betfair": float(rng.normal(0, 0.05)),
                "steam_move_betclic": float(rng.normal(0, 0.05)),
                "ratio_pmu_geny": float(rng.uniform(0.9, 1.1)),
                "mouvement_30min": float(np.clip(rng.normal(0, 0.3), -1, 1)),
                "mouvement_bm_pct": float(rng.normal(0, 0.05)),
                "rang_cote": rc,
                "est_favori": int(rc == 1),
                "prob_implicite": float(prob_imp),
                "pool_gagnant_ratio": float(prob_imp * rng.uniform(0.8, 1.2)),
                # Équipement
                "changement_equipement": float(rng.random() < 0.15),
                "premier_deferre": float(rng.random() < 0.08),
                "nouvelles_oeilleres": float(rng.random() < 0.06),
                "equipement_score": float(rng.beta(1, 6)),
                # Jockey
                "jockey_taux_victoire_global": _clip01(rng.beta(2, 8) + s * 0.05),
                "jockey_taux_place_global": _clip01(rng.beta(3, 5)),
                "jockey_roi": float(rng.normal(0, 0.05)),
                "jockey_montes_30j": int(rng.poisson(20)),
                "jockey_victoires_saison": int(rng.poisson(8)),
                "jockey_forme_30j": _clip01(rng.beta(2, 6)),
                "changement_jockey": int(rng.random() < 0.1),
                "asso_jockey_entraineur_taux": _clip01(rng.beta(2, 6)),
                "asso_jockey_entraineur_nb": int(rng.poisson(5)),
                "asso_jockey_entraineur_fiable": int(rng.random() < 0.3),
                # Entraîneur
                "entraineur_taux_global": _clip01(rng.beta(2, 6) + s * 0.05),
                "entraineur_taux_place": _clip01(rng.beta(3, 5)),
                "entraineur_roi": float(rng.normal(0.02, 0.04)),
                "entraineur_victoires_saison": int(rng.poisson(15)),
                "combo_jockey_entraineur": _clip01(rng.beta(2, 5)),
                "entraineur_forme_30j": _clip01(rng.beta(2, 5)),
                # Cheval identité
                "age": int(rng.randint(2, 11)),
                "age_squared": 0,  # rempli après
                "sexe_code": int(rng.randint(0, 3)),
                "gains_log": float(9 + s * 7 + rng.normal(0, 0.8)),
                "retard_gains": float(abs(rng.normal(0, 0.3))),
                "indice_valeur": float(rng.normal(0, 0.2)),
                "running_style_code": int(rng.randint(0, 5)),
                "taux_en_tete": _clip01(rng.beta(2, 5)),
                "prix_vente_log": float(rng.choice([0, 0, 0, np.log1p(rng.exponential(30000))])),
                # Contexte course
                "nb_partants": nb,
                "log_nb_partants": float(np.log(nb)),
                "discipline_code": discipline_code,
                "niveau_course_code": niveau,
                "dotation_log": dotation_log,
                "course_designee": int(rng.random() < 0.2),
                "heure_course": heure,
                "nb_courses_reunion": int(rng.poisson(8)),
                # Sagesse des foules
                "rang_popularite": rc,
                "rang_pronostic_geny": int(np.clip(rc + rng.randint(-2, 3), 1, nb)),
                "pronostic_expert_rang": int(np.clip(rc + rng.randint(-2, 3), 1, nb)),
                "sagesse_foules_score": _clip01(1 - (rc - 1) / max(nb - 1, 1)),
                "consensus_sources": _clip01(rng.beta(3, 2)),
                "nb_experts_presse": int(rng.poisson(2)),
                "nb_premier_presse": int(rng.binomial(3, 0.2)),
                "presse_consensus_score": _clip01(rng.beta(2, 4)),
                "momentum_3j": float(np.clip(rng.normal(0, 0.3), -1, 1)),
                "variance_cotes_7j": float(abs(rng.normal(10, 10))),
                "spi_score": float(max(0, rng.normal(0, 0.1))),
                "decote_detectee": float(rng.random() < 0.12),
                "valeur_latente": float(max(0, rng.normal(0, 0.05))),
                # Champ
                "field_hhi": float(rng.uniform(0.1, 0.6)),
                "nb_outsiders": int(rng.binomial(nb, 0.3)),
                "ecart_proba_top2": float(abs(rng.normal(0.1, 0.1))),
                "rang_cote_relatif": float(rc / nb * 10),
                "mois_course": mois,
                "saison_code": saison,
                "saison_form": _clip01(rng.beta(2, 2)),
                "market_timing_score": float(np.clip(rng.normal(0, 0.3), -1, 1)),
                "pace_conflict_score": _clip01(rng.beta(2, 5)),
                "running_style_terrain_fit": _clip01(rng.beta(2, 2)),
                "nb_meneurs_course": int(rng.poisson(2)),
                "sire_dist_winrate": _clip01(rng.beta(2, 3)),
                "sire_terrain_winrate": _clip01(rng.beta(2, 3)),
                "jockey_cheval_synergy_nb": int(rng.poisson(2)),
                "jockey_cheval_synergy_score": _clip01(rng.beta(2, 5)),
                "course_fingerprint_nb": int(rng.poisson(2)),
                "course_fingerprint_score": _clip01(rng.beta(2, 2)),
                "time_decay_form": _clip01(s * 0.5 + rng.uniform(0, 0.3)),
                "opposition_quality": _clip01(rng.beta(2, 2)),
                "vitesse_theorique": float(rng.uniform(10, 16)),
                "stamina_index": _clip01(rng.beta(2, 3)),
                "discipline_coherence": _clip01(rng.beta(3, 2)),
                "class_drop_ratio": float(rng.uniform(0.7, 1.3)),
                "class_jump_score": float(rng.normal(0, 0.3)),
                "class_drop_flag": int(rng.random() < 0.2),
                "class_rise_flag": int(rng.random() < 0.2),
                "bounce_score": _clip01(rng.beta(1, 6)),
                "current_form_vs_best": _clip01(s + rng.normal(0, 0.15)),
                "career_trajectory": float(np.clip(rng.normal(0, 0.5), -1, 1)),
                "draw_bias_score": float(rng.normal(0, 0.2)),
                "trainer_return_bonus": float(rng.beta(1, 8)),
                "career_momentum": float(np.clip(rng.normal(0, 0.4), -1, 1)),
                "form_vs_career_rate": float(np.clip(rng.normal(0, 0.2), -0.5, 0.5)),
                "career_win_rate": _clip01(s * 0.3 + rng.beta(1, 8)),
                "recent_win_rate": _clip01(s * 0.4 + rng.uniform(0, 0.2)),
                "data_completeness": _clip01(rng.beta(3, 2)),
                "signal_agreement": _clip01(rng.beta(2, 2)),
                "composite_confidence": _clip01(rng.beta(2, 2)),
                # latent (non utilisé comme feature, sert au label)
                "_strength": s,
            })
            row["age_squared"] = int(row["age"] ** 2)
            rows.append(row)

    return pd.DataFrame(rows)


def make_labels(df: pd.DataFrame, seed: int = 42) -> pd.Series:
    """Top-3 ≈ corrélé à la force latente + forme + cote (réaliste, bruité)."""
    rng = np.random.RandomState(seed + 1)
    labels = np.zeros(len(df), dtype=int)
    for course_id, group in df.groupby("course_id"):
        nb = len(group)
        nb_top3 = min(3, max(1, nb // 3))
        s = group["_strength"].values
        forme = group["forme_5_courses"].values
        cote_inv = 1.0 / np.maximum(group["cote_pmu"].values, 1.1)
        cote_inv_norm = cote_inv / cote_inv.max()
        score = 0.5 * s + 0.2 * forme + 0.3 * cote_inv_norm + rng.uniform(0, 0.18, nb)
        top_idx = np.argsort(score)[::-1][:nb_top3]
        for idx in top_idx:
            labels[group.index[idx]] = 1
    return pd.Series(labels, index=df.index, name="label")


def main():
    parser = argparse.ArgumentParser(description="Seed BlackTurf ML model (feature names alignés sur le builder)")
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"[seed_model] Génération de {args.samples} courses synthétiques (schéma builder)...")
    df = make_synthetic_features(n_courses=args.samples, seed=args.seed)
    y = make_labels(df, seed=args.seed)
    df = df.drop(columns=["_strength"])

    print(f"[seed_model] Dataset: {len(df)} partants, {df['course_id'].nunique()} courses, top3={y.mean():.1%}")
    print(f"[seed_model] Features: {len(CANON_FEATURES)} (alignées builder)")

    # X = uniquement les features canoniques + course_id (walk-forward)
    X = df[CANON_FEATURES + ["course_id"]]

    print("[seed_model] Entraînement...")
    model = BlackTurfEnsemble()
    metrics = model.train(X, y)

    print("=" * 50)
    print(f"  AUC-ROC          : {metrics['auc_roc']:.4f}")
    print(f"  Brier Score      : {metrics['brier_score']:.4f}")
    print(f"  Précision Top-3  : {metrics['precision_top3']:.4f}")
    print(f"  Walk-forward AUC : {metrics['walk_forward_auc']:.4f}")
    print("=" * 50)

    if args.deploy:
        model.deploy(version_num=1)
        print("✅ Modèle déployé → current_model.pkl")
    else:
        path = model.save(version_num=1)
        print(f"✅ Modèle sauvegardé → {path}  (utilisez --deploy pour activer)")

    if model.feature_importance:
        print("TOP 12 FEATURE IMPORTANCE:")
        for name, imp in sorted(model.feature_importance.items(), key=lambda x: -x[1])[:12]:
            print(f"  {name:<32} {imp:.4f}")

    models_dir = Path("/app/models") if Path("/app").exists() else Path(__file__).parent.parent / "models"
    (models_dir / "seed_metrics.json").write_text(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
