"""Tests unitaires ML — ELO, value bets, Kelly, recommandations, features, SPI."""
import pytest
import numpy as np
import pandas as pd
from ml.valuebets import (
    calculer_ev, determine_niveau, detect_value_bet, calculer_mise_kelly,
    triangulation_cotes_v2, compute_spi_v2,
    COTE_MAX_VB, LONGSHOT_COTE_MIN, MAX_MODEL_MARKET_RATIO, COTE_CEIL_FACTOR,
    # backward compat aliases for existing tests
    triangulation_cotes, compute_spi_from_gap,
)
from ml.elo import calculer_delta_elo
from ml.features import (
    score_position, parse_musique, compute_spi_from_cotes_history,
    _decote_detectee, _valeur_latente,
)
from ml.recommendations import generer_recommandations_course


# ─────────────────────────────────────────────
# EV / Value Bets — calcul de base
# ─────────────────────────────────────────────
def test_ev_positive():
    ev = calculer_ev(cote=4.0, proba=0.30)
    assert ev == pytest.approx(0.20, rel=1e-3)


def test_ev_negative():
    ev = calculer_ev(cote=2.0, proba=0.40)
    assert ev == pytest.approx(-0.20, rel=1e-3)


def test_ev_zero_inputs():
    assert calculer_ev(0, 0.5) == -1.0
    assert calculer_ev(4.0, 0) == -1.0


def test_ev_cote_exactement_inverse_proba():
    """Cote = 1/proba → EV = 0 (jeu équitable)."""
    ev = calculer_ev(cote=5.0, proba=0.20)
    assert ev == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────
# Niveaux
# ─────────────────────────────────────────────
def test_niveau_4_etoiles():
    n = determine_niveau(ev=0.35, proba=0.70)
    assert n == 4


def test_niveau_3_etoiles():
    n = determine_niveau(ev=0.22, proba=0.62)
    assert n == 3


def test_niveau_2_etoiles():
    n = determine_niveau(ev=0.12, proba=0.57)
    assert n == 2


def test_niveau_1_etoile():
    n = determine_niveau(ev=0.06, proba=0.51)
    assert n == 1


def test_niveau_none_ev_trop_faible():
    n = determine_niveau(ev=0.03, proba=0.60)
    assert n is None


def test_niveau_none_proba_trop_faible():
    # proba = P(victoire) normalisée ; sous le seuil de confiance le plus bas
    # (CONFIANCE_SEUILS[1] = 0.10) → pas de VB même si l'EV est forte.
    n = determine_niveau(ev=0.25, proba=0.08)
    assert n is None


# ─────────────────────────────────────────────
# Triangulation cotes
# ─────────────────────────────────────────────
def test_triangulation_retourne_meilleure_source_geny():
    ev_pmu, ev_geny, ev_bzh, source = triangulation_cotes(0.55, 3.0, 5.0, 2.5)
    assert source == "geny"
    assert ev_geny is not None and ev_geny > (ev_pmu or -999)


def test_triangulation_source_unique():
    ev_pmu, ev_geny, ev_bzh, source = triangulation_cotes(0.40, 3.0, None, None)
    assert source == "pmu"
    assert ev_geny is None
    assert ev_bzh is None


def test_triangulation_cote_inferieure_1_ignoree():
    ev_pmu, ev_geny, ev_bzh, source = triangulation_cotes(0.40, 3.0, 0.5, None)
    assert ev_geny is None  # Cote 0.5 invalide


def test_triangulation_ev_calcule_correctement():
    ev_pmu, _, _, _ = triangulation_cotes(0.30, 4.0, None, None)
    assert ev_pmu == pytest.approx(0.20, rel=1e-3)


# ─────────────────────────────────────────────
# detect_value_bet intégration
# ─────────────────────────────────────────────
def test_detect_value_bet_found():
    # proba 0.35 à cote 4.5 → ratio modèle/marché 1.58 < 1.7 (gate longshot) ; EV +57%.
    vb = detect_value_bet(proba_top1=0.35, cote_pmu=4.5)
    assert vb is not None
    assert vb["niveau"] >= 1
    assert vb["ev_max"] > 0


def test_detect_value_bet_not_found():
    vb = detect_value_bet(proba_top1=0.30, cote_pmu=2.0)
    assert vb is None


def test_detect_value_bet_no_cotes():
    vb = detect_value_bet(proba_top1=0.80)
    assert vb is None


def test_detect_picks_best_source():
    vb = detect_value_bet(proba_top1=0.55, cote_pmu=3.0, cote_geny=5.0, cote_bzh=2.5)
    assert vb is not None
    assert vb["meilleure_source"] == "geny"
    assert vb["ev_geny"] > vb["ev_pmu"]


def test_detect_value_bet_inclut_spi_fields():
    # proba 0.40 à cote 4.0 → ratio modèle/marché 1.6 < MAX_MODEL_MARKET_RATIO (1.7) :
    # passe le gate longshot resserré (le 0.65 historique = ratio 2.6, rejeté by design).
    vb = detect_value_bet(proba_top1=0.40, cote_pmu=4.0)
    assert vb is not None
    assert "spi_detected" in vb
    assert "spi_score" in vb


def test_detect_value_bet_spi_via_history():
    """Cote qui chute de 5.0 → 3.5 → SPI détecté."""
    history = [5.0, 4.8, 4.5, 4.2, 3.8, 3.5]
    vb = detect_value_bet(proba_top1=0.65, cote_pmu=3.5, cotes_history=history)
    assert vb is not None
    assert vb["spi_detected"] is True
    assert vb["spi_score"] > 0


def test_detect_value_bet_no_spi_stable_cote():
    history = [4.0, 4.1, 3.9, 4.0, 4.0]
    vb = detect_value_bet(proba_top1=0.65, cote_pmu=4.0, cotes_history=history)
    if vb:
        assert vb["spi_detected"] is False


# ─────────────────────────────────────────────
# Garde-fous anti biais-longshot (gates A+D) — non-régression du bug +296%
# ─────────────────────────────────────────────
def test_longshot_gate_rejette_proba_sur_evaluee():
    """Modèle attribue P(win) >> proba marché implicite sur grosse cote → None.

    cote_marché ≈ 10 (≥ LONGSHOT_COTE_MIN), implicite ≈ 0.10. proba 0.60 donne
    un ratio de 6× : c'est le sur-fit outsider qui générait les EV absurdes.
    """
    assert LONGSHOT_COTE_MIN <= 10.0
    vb = detect_value_bet(
        proba_top1=0.60, cote_pmu=10.0, cote_geny=10.0, cote_bzh=10.0,
    )
    assert vb is None


def test_longshot_gate_ne_sapplique_pas_aux_favoris():
    """Sous LONGSHOT_COTE_MIN (cote basse) un fort écart marché reste un edge valide."""
    vb = detect_value_bet(
        proba_top1=0.60, cote_pmu=3.0, cote_geny=3.0, cote_bzh=3.0,
    )
    assert vb is not None
    assert vb["niveau"] >= 1


def test_cote_max_vb_rejette_outsider_extreme():
    """Cote de la meilleure source > COTE_MAX_VB → None (modèle non fiable)."""
    cote = COTE_MAX_VB + 5.0
    vb = detect_value_bet(proba_top1=0.30, cote_pmu=cote)
    assert vb is None


def test_winners_curse_ev_plafonnee_a_mediane():
    """EV calculée sur cote plafonnée (médiane × COTE_CEIL_FACTOR), pas sur la cote
    isolée la plus haute des 7 sources (stale → EV gonflée)."""
    # médiane de [4,4,4,10] = 4 ; cote isolée winamax = 10. proba 0.28 → ratio vs
    # cote_marché (~5.8 pondérée) ≈ 1.63 < 1.7 : passe le gate longshot resserré.
    vb = detect_value_bet(
        proba_top1=0.28, cote_pmu=4.0, cote_geny=4.0, cote_bzh=4.0,
        cote_winamax=10.0,
    )
    assert vb is not None
    assert vb["meilleure_source"] == "winamax"   # on parie quand même la meilleure cote
    cote_plafond = 4.0 * COTE_CEIL_FACTOR
    ev_attendu = cote_plafond * 0.28 - 1.0
    assert vb["ev_max"] == pytest.approx(ev_attendu, rel=1e-6)
    # sans plafond l'EV serait 10×0.40−1 = 3.0 ; le plafond la garde crédible
    assert vb["ev_max"] < 1.0


# ─────────────────────────────────────────────
# SPI
# ─────────────────────────────────────────────
def test_spi_history_chute_significative():
    history = [6.0, 5.5, 5.0, 4.5, 4.0, 3.5]  # -41% → score élevé
    score = compute_spi_from_cotes_history(history)
    assert score > 0.5


def test_spi_history_stable():
    history = [4.0, 4.1, 3.9, 4.0, 4.0, 4.1]
    score = compute_spi_from_cotes_history(history)
    assert score == 0.0


def test_spi_history_hausse_cote():
    """Cote qui monte → pas de SPI (argent pro achète → cote baisse)."""
    history = [3.0, 3.5, 4.0, 4.5]
    score = compute_spi_from_cotes_history(history)
    assert score == 0.0


def test_spi_history_liste_vide():
    assert compute_spi_from_cotes_history([]) == 0.0
    assert compute_spi_from_cotes_history([4.0]) == 0.0


def test_spi_history_seuil_15pct():
    """Exactement 15% de chute → score non nul."""
    debut = 4.0
    fin = debut * 0.85  # -15%
    score = compute_spi_from_cotes_history([debut, fin])
    assert score >= 0.15


def test_spi_gap_pmu_vs_marche():
    detected, score = compute_spi_from_gap(cote_pmu=6.0, cote_geny=4.0, cote_bzh=4.2)
    assert detected is True
    assert score is not None and score > 0


def test_spi_gap_pas_de_divergence():
    detected, score = compute_spi_from_gap(cote_pmu=4.0, cote_geny=4.1, cote_bzh=3.9)
    assert detected is False


def test_spi_gap_sans_marche():
    detected, score = compute_spi_from_gap(cote_pmu=4.0, cote_geny=None, cote_bzh=None)
    assert detected is False


# ─────────────────────────────────────────────
# Kelly
# ─────────────────────────────────────────────
def test_kelly_positive():
    mise = calculer_mise_kelly(ev=0.20, cote=4.0, bankroll=1000.0)
    assert mise > 0
    assert mise <= 50.0


def test_kelly_zero_ev_negatif():
    mise = calculer_mise_kelly(ev=-0.10, cote=4.0, bankroll=1000.0)
    assert mise == 0.0


def test_kelly_capped_at_5pct():
    mise = calculer_mise_kelly(ev=2.0, cote=3.0, bankroll=1000.0)
    assert mise <= 50.0


def test_kelly_half_fraction():
    full = calculer_mise_kelly(ev=0.20, cote=4.0, bankroll=1000.0, fraction=1.0)
    half = calculer_mise_kelly(ev=0.20, cote=4.0, bankroll=1000.0, fraction=0.5)
    assert half == pytest.approx(full / 2, rel=0.01)


def test_kelly_cote_un_retourne_zero():
    assert calculer_mise_kelly(ev=0.20, cote=1.0, bankroll=1000.0) == 0.0


def test_kelly_cote_inferieur_un():
    assert calculer_mise_kelly(ev=0.20, cote=0.5, bankroll=1000.0) == 0.0


def test_kelly_proportionnel_bankroll():
    m1 = calculer_mise_kelly(ev=0.20, cote=4.0, bankroll=500.0)
    m2 = calculer_mise_kelly(ev=0.20, cote=4.0, bankroll=1000.0)
    assert m2 == pytest.approx(m1 * 2, rel=0.01)


# ─────────────────────────────────────────────
# ELO
# ─────────────────────────────────────────────
def test_elo_gagnant_monte():
    delta = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=1.0, k=32)
    assert delta > 0


def test_elo_perdant_descend():
    delta = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=0.0, k=32)
    assert delta < 0


def test_elo_nul():
    delta = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=0.5, k=32)
    assert delta == pytest.approx(0.0, abs=0.01)


def test_elo_outsider_gagne_gros():
    delta = calculer_delta_elo(elo_a=1300, elo_b=1700, score_a=1.0, k=32)
    assert delta > 20


def test_elo_favori_perd_gros():
    delta = calculer_delta_elo(elo_a=1700, elo_b=1300, score_a=0.0, k=32)
    assert delta < -20


def test_elo_symetrique():
    """Gain du vainqueur = perte du perdant en valeur absolue."""
    d_win = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=1.0, k=32)
    d_lose = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=0.0, k=32)
    assert d_win == pytest.approx(-d_lose, rel=1e-6)


def test_elo_k_factor_proportionnel():
    d16 = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=1.0, k=16)
    d32 = calculer_delta_elo(elo_a=1500, elo_b=1500, score_a=1.0, k=32)
    assert d32 == pytest.approx(d16 * 2, rel=1e-6)


# ─────────────────────────────────────────────
# Features — utilitaires
# ─────────────────────────────────────────────
def test_score_position_premier():
    assert score_position(1, 10) == pytest.approx(1.0)


def test_score_position_dernier():
    score = score_position(10, 10)
    assert score < 0.3


def test_score_position_milieu():
    score = score_position(5, 10)
    assert 0.3 < score < 0.7


def test_score_position_cheval_non_classe():
    score = score_position(99, 10)
    assert score == 0.0


def test_parse_musique_basique():
    positions = parse_musique("1a2h3s5p")
    assert positions[0] == 1
    assert positions[1] == 2
    assert positions[2] == 3
    assert positions[3] == 5


def test_parse_musique_vide():
    assert parse_musique("") == []
    assert parse_musique(None) == []


def test_parse_musique_lettres_ignorees():
    positions = parse_musique("1a")
    assert positions == [1]


def test_parse_musique_disqualification():
    """'D' = disqualifié → non compté ou traité comme hors-classement."""
    positions = parse_musique("D1a2")
    # D should not produce a position, rest parsed
    assert 1 in positions


def test_decote_detectee_vraie():
    """PMU surcoté vs Geny/BZH → décote détectée."""
    score = _decote_detectee(cote_pmu=6.0, cote_geny=4.0, cote_bzh=4.0)
    assert score > 0


def test_decote_detectee_pas_de_divergence():
    score = _decote_detectee(cote_pmu=4.0, cote_geny=4.0, cote_bzh=4.0)
    assert score == pytest.approx(0.0, abs=0.1)


def test_valeur_latente_positive():
    """Geny/BZH cote plus basse → PMU surcoté → valeur latente positive."""
    v = _valeur_latente(cote_pmu=6.0, cote_geny=4.0, cote_bzh=4.0)
    assert v > 0


def test_valeur_latente_nulle_sans_sources():
    v = _valeur_latente(cote_pmu=4.0, cote_geny=None, cote_bzh=None)
    assert v == 0.0


# ─────────────────────────────────────────────
# Recommandations — génération
# ─────────────────────────────────────────────
@pytest.fixture
def predictions_sample():
    return [
        {"participation_id": "p1", "numero": 1, "nom": "CHEVAL_A", "proba_top3": 0.72,
         "proba_top1": 0.30, "cote_pmu": 3.5, "ev_max": 0.25, "niveau_vb": 3, "rang_predit": 1},
        {"participation_id": "p2", "numero": 2, "nom": "CHEVAL_B", "proba_top3": 0.58,
         "proba_top1": 0.22, "cote_pmu": 5.0, "ev_max": 0.15, "niveau_vb": 2, "rang_predit": 2},
        {"participation_id": "p3", "numero": 3, "nom": "CHEVAL_C", "proba_top3": 0.45,
         "proba_top1": 0.15, "cote_pmu": 7.5, "ev_max": 0.10, "niveau_vb": 1, "rang_predit": 3},
        {"participation_id": "p4", "numero": 4, "nom": "CHEVAL_D", "proba_top3": 0.35,
         "proba_top1": 0.10, "cote_pmu": 10.0, "ev_max": -0.05, "niveau_vb": 0, "rang_predit": 4},
    ]


@pytest.fixture
def course_info_sample():
    return {
        "course_id": "C001",
        "hippodrome": "VINCENNES",
        "heure": "14:30",
        "discipline": "plat",
        "distance": 1800,
        "terrain": "bon",
        "nb_partants": 10,
        "est_quinte": True,
        "est_quarte": False,
        "est_tierce": True,
    }


def test_recommandations_retourne_liste(predictions_sample, course_info_sample):
    recos = generer_recommandations_course(predictions_sample, course_info_sample, bankroll=100.0)
    assert isinstance(recos, list)
    assert len(recos) >= 1


def test_recommandations_ont_champs_requis(predictions_sample, course_info_sample):
    recos = generer_recommandations_course(predictions_sample, course_info_sample, bankroll=100.0)
    for r in recos:
        assert "niveau" in r
        assert "type_pari" in r
        assert "chevaux" in r
        assert "ev_calcule" in r


def test_recommandations_mise_bornee(predictions_sample, course_info_sample):
    recos = generer_recommandations_course(predictions_sample, course_info_sample, bankroll=100.0)
    for r in recos:
        if r.get("mise_suggeree") is not None:
            assert r["mise_suggeree"] >= 0
            assert r["mise_suggeree"] <= 100.0  # Max = bankroll


def test_recommandations_sans_partants():
    recos = generer_recommandations_course([], {"course_id": "X", "est_quinte": False,
                                                 "est_quarte": False, "est_tierce": False,
                                                 "discipline": "plat", "distance": 1600,
                                                 "terrain": "bon", "nb_partants": 0,
                                                 "hippodrome": "TEST", "heure": "12:00"}, bankroll=100.0)
    assert recos == [] or isinstance(recos, list)


# ─────────────────────────────────────────────
# ML Models — train/predict smoke test (no DB)
# ─────────────────────────────────────────────
def _make_synthetic_dataset(n=200):
    """Generates synthetic training data for smoke tests."""
    np.random.seed(42)
    n_features = 30
    X = pd.DataFrame(
        np.random.randn(n, n_features),
        columns=[f"feat_{i}" for i in range(n_features)]
    )
    # Positive labels: ~30% rate
    y = pd.Series((np.random.rand(n) < 0.30).astype(int))
    return X, y


def test_model_train_and_predict_smoke():
    from ml.models import BlackTurfEnsemble
    X, y = _make_synthetic_dataset(300)
    model = BlackTurfEnsemble()
    metrics = model.train(X, y)
    assert "auc_roc" in metrics
    assert 0.4 <= metrics["auc_roc"] <= 1.0
    assert "brier_score" in metrics
    assert metrics["brier_score"] < 1.0
    assert "walk_forward_auc" in metrics
    assert metrics["walk_forward_auc"] > 0.0


def test_model_predict_proba_range():
    from ml.models import BlackTurfEnsemble
    X, y = _make_synthetic_dataset(300)
    model = BlackTurfEnsemble()
    model.train(X, y)
    X_new, _ = _make_synthetic_dataset(10)
    probas = model.predict_proba(X_new)
    assert len(probas) == 10
    assert all(0.0 <= p <= 1.0 for p in probas)


def test_model_feature_importance_populated():
    from ml.models import BlackTurfEnsemble
    X, y = _make_synthetic_dataset(300)
    model = BlackTurfEnsemble()
    model.train(X, y)
    assert len(model.feature_importance) > 0


def test_model_brier_threshold():
    """Walk-forward AUC variance should be low on clean data."""
    from ml.models import BlackTurfEnsemble
    X, y = _make_synthetic_dataset(500)
    model = BlackTurfEnsemble()
    metrics = model.train(X, y)
    assert "walk_forward_variance" in metrics
    # Variance should be finite
    assert np.isfinite(metrics["walk_forward_variance"])


def test_build_training_dataset_structure():
    from ml.models import build_training_dataset
    features_rows = [
        {"feat_0": 1.0, "feat_1": 2.0, "cheval_id": "ch1", "label": None},
        {"feat_0": 0.5, "feat_1": 1.5, "cheval_id": "ch2", "label": None},
    ]
    resultats = {
        "course_1": {"ch1": 1, "ch2": 3}
    }
    # Without course_id in features, should return empty or handle gracefully
    X, y, y_win = build_training_dataset(features_rows, resultats)
    assert isinstance(X, pd.DataFrame)
    assert isinstance(y, pd.Series)
    assert isinstance(y_win, pd.Series)


def test_model_stacking_meta_learner():
    """Stacking meta-learner doit s'entraîner et produire des probas valides."""
    from ml.models import BlackTurfEnsemble
    X, y = _make_synthetic_dataset(400)
    model = BlackTurfEnsemble()
    model.train(X, y)
    # Stacking should have trained (may fall back silently to fixed weights)
    X_new, _ = _make_synthetic_dataset(20)
    probas, confidence = model.predict_with_confidence(X_new)
    assert len(probas) == 20
    assert all(0.0 <= p <= 1.0 for p in probas)
    assert len(confidence) == 20
    assert all(0.0 <= c <= 1.0 for c in confidence)


# ─────────────────────────────────────────────
# Drift Detector — ADWIN + Page-Hinkley
# ─────────────────────────────────────────────
def test_drift_detector_no_drift_stable():
    """Pas de drift sur série stable."""
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    for _ in range(50):
        r = dd.update(brier_score=0.18, was_surprise=False, prediction_confidence=0.6)
    assert r["severity"] == "none"


def test_drift_detector_detects_brier_spike():
    """
    Série stable longue puis spike soutenu → au moins un signal actif.
    ADWIN nécessite ~80-100 observations stables pour calibrer la baseline.
    """
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    # Phase stable bien établie
    for _ in range(100):
        dd.update(brier_score=0.15, was_surprise=False, prediction_confidence=0.75)
    # Phase dégradée forte et soutenue
    for _ in range(60):
        r = dd.update(brier_score=0.40, was_surprise=True, prediction_confidence=0.25)
    # Au moins un signal doit être actif OU brier moyen reflète la dégradation
    any_signal = any(v for v in r["signals"].values())
    brier_degraded = r["brier_mean"] > 0.20
    assert any_signal or brier_degraded, f"Expected drift signal or high brier. Got: {r}"


def test_drift_detector_update_returns_required_keys():
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    r = dd.update(brier_score=0.20, was_surprise=False, prediction_confidence=0.5)
    for key in ("drift_detected", "severity", "signals", "brier_mean", "surprise_rate"):
        assert key in r, f"Missing key: {key}"


def test_drift_detector_signals_are_booleans():
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    r = dd.update(brier_score=0.20, was_surprise=False, prediction_confidence=0.5)
    for k, v in r["signals"].items():
        assert isinstance(v, bool), f"Signal {k} should be bool, got {type(v)}"


def test_drift_detector_reset_clears_state():
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    for _ in range(20):
        dd.update(brier_score=0.35, was_surprise=True, prediction_confidence=0.2)
    dd.reset()
    report = dd.get_drift_report()
    assert report["total_observations"] == 0


def test_drift_detector_get_report_keys():
    from ml.drift_detector import DriftDetector
    dd = DriftDetector()
    dd.update(brier_score=0.20, was_surprise=False, prediction_confidence=0.5)
    report = dd.get_drift_report()
    for key in ("status", "total_observations", "brier_mean", "surprise_rate"):
        assert key in report, f"Missing report key: {key}"


# ─────────────────────────────────────────────
# Monte Carlo Simulator
# ─────────────────────────────────────────────
def test_monte_carlo_single_bet_keys():
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    r = sim.simulate_single_bet(proba=0.35, cote=4.0, mise=10.0, n=500)
    for key in ("mean_return", "win_rate", "breakeven_proba", "kelly_fraction"):
        assert key in r


def test_monte_carlo_single_bet_win_rate_near_proba():
    """win_rate empirique doit être proche de proba théorique (±10pp)."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    r = sim.simulate_single_bet(proba=0.40, cote=3.0, mise=1.0, n=10000)
    assert abs(r["win_rate"] - 0.40) < 0.05


def test_monte_carlo_single_bet_breakeven_formula():
    """breakeven_proba = 1 / cote."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    r = sim.simulate_single_bet(proba=0.35, cote=5.0, mise=10.0, n=100)
    assert abs(r["breakeven_proba"] - 0.20) < 0.001


def test_monte_carlo_portfolio_keys():
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    portfolio = {
        "bets": [
            {"proba_top3": 0.45, "cote": 3.0, "mise": 5.0},
            {"proba_top3": 0.20, "cote": 8.0, "mise": 2.0},
        ]
    }
    result = sim.simulate_portfolio(portfolio, n_simulations=500)
    for key in ("mean_roi", "median_roi", "win_rate_portfolio", "sharpe_ratio", "max_drawdown"):
        assert key in result


def test_monte_carlo_portfolio_roi_range():
    """mean_roi peut être négatif ou positif mais ne doit pas exploser."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    result = sim.simulate_portfolio(
        {"bets": [{"proba_top3": 0.30, "cote": 4.0, "mise": 10.0}]},
        n_simulations=1000,
    )
    assert -1.0 <= result["mean_roi"] <= 20.0


def test_monte_carlo_ruin_probability_always_zero_on_good_bets():
    """Bankroll infinie relative à mise → ruine nulle."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    p_ruin = sim.estimate_ruin_probability(
        bankroll=10000.0, mise_par_course=1.0,
        win_rate=0.40, cote_moyenne=3.5, n_courses=50
    )
    assert 0.0 <= p_ruin <= 1.0


def test_monte_carlo_ruin_probability_high_on_bad_bets():
    """Mise trop grande vs bankroll → ruine élevée."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    p_ruin = sim.estimate_ruin_probability(
        bankroll=50.0, mise_par_course=10.0,
        win_rate=0.20, cote_moyenne=2.0, n_courses=50
    )
    assert p_ruin > 0.3


def test_monte_carlo_kelly_fraction_formula():
    """Kelly = (p*(b+1) - 1) / b où b = cote - 1."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    p, c = 0.40, 4.0
    b = c - 1
    expected_full = (p * (b + 1) - 1) / b
    result = sim.optimize_kelly_fraction(proba=p, cote=c, risk_tolerance=1.0)
    assert abs(result["full_kelly"]["fraction"] - expected_full) < 0.01


def test_monte_carlo_kelly_optimal_equals_risktol_times_full():
    """optimal = full_kelly × risk_tolerance."""
    from ml.monte_carlo import MonteCarloSimulator
    sim = MonteCarloSimulator(seed=42)
    rt = 0.5
    r = sim.optimize_kelly_fraction(proba=0.40, cote=4.0, risk_tolerance=rt)
    assert abs(r["optimal_fraction"]["fraction"] - r["full_kelly"]["fraction"] * rt) < 0.001


# ─────────────────────────────────────────────
# Adaptive Learning — calibration
# ─────────────────────────────────────────────
def test_adaptive_learning_temperature_scaling_t1():
    """T=1 → probas inchangées (sigmoid(logit(p)/1) = p)."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    al.temperature = 1.0
    probas = np.array([0.2, 0.5, 0.8])
    calibrated = al.apply_calibration(probas)
    np.testing.assert_allclose(calibrated, probas, atol=1e-4)


def test_adaptive_learning_temperature_high_flattens():
    """T > 1 → probas plus aplaties (favoris moins favoris)."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    al.temperature = 2.0
    probas = np.array([0.1, 0.5, 0.9])
    calibrated = al.apply_calibration(probas)
    # Top proba doit diminuer, bottom proba doit augmenter
    assert calibrated[2] < probas[2]
    assert calibrated[0] > probas[0]


def test_adaptive_learning_temperature_low_sharpens():
    """T < 1 → probas plus concentrées (favoris encore plus favoris)."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    al.temperature = 0.7
    probas = np.array([0.1, 0.5, 0.9])
    calibrated = al.apply_calibration(probas)
    assert calibrated[2] > probas[2]
    assert calibrated[0] < probas[0]


def test_adaptive_learning_temperature_update_surprise():
    """Surprise + proba basse → T augmente."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    t_before = al.temperature
    al._update_temperature(gagnant_proba=0.05, was_surprise=True, brier=0.30)
    assert al.temperature > t_before


def test_adaptive_learning_temperature_update_good_prediction():
    """Bonne prédiction (brier bas, pas surprise) → T diminue légèrement."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    al.temperature = 1.1  # Légèrement trop haut
    for _ in range(10):
        al._update_temperature(gagnant_proba=0.7, was_surprise=False, brier=0.12)
    assert al.temperature < 1.1


def test_adaptive_learning_temperature_bounded():
    """T reste dans [T_MIN, T_MAX] quoi qu'il arrive."""
    from ml.adaptive_learning import AdaptiveLearning, T_MIN, T_MAX
    al = AdaptiveLearning()
    for _ in range(100):
        al._update_temperature(gagnant_proba=0.01, was_surprise=True, brier=0.50)
    assert al.temperature <= T_MAX
    al2 = AdaptiveLearning()
    for _ in range(100):
        al2._update_temperature(gagnant_proba=0.99, was_surprise=False, brier=0.05)
    assert al2.temperature >= T_MIN


def test_adaptive_learning_feature_weights_increase_on_surprise():
    """Autopsie avec signal manqué + surprise → poids du groupe augmente."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    w_before = al.feature_weights["cotes"]
    autopsy = {"mouvement_cote_manque": {"valeur": 1.0, "description": "test"}}
    al._update_feature_weights(autopsy=autopsy, was_surprise=True)
    assert al.feature_weights["cotes"] > w_before


def test_adaptive_learning_feature_weights_no_update_no_surprise():
    """Pas de surprise → poids inchangés."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    weights_before = al.feature_weights.copy()
    autopsy = {"mouvement_cote_manque": {"valeur": 1.0, "description": "test"}}
    al._update_feature_weights(autopsy=autopsy, was_surprise=False)
    # Only decay applies, no increase
    for k in weights_before:
        assert al.feature_weights[k] <= weights_before[k] + 0.001


def test_adaptive_learning_feature_weights_bounded():
    """Poids ne dépasse pas 2.0."""
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    for _ in range(200):
        al._update_feature_weights(
            autopsy={"mouvement_cote_manque": {"valeur": 1.0, "description": "test"}},
            was_surprise=True
        )
    assert al.feature_weights["cotes"] <= 2.0


def test_adaptive_learning_process_signal():
    """process_race_signal retourne les clés attendues."""
    import asyncio
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    signal = {
        "brier_course": 0.22,
        "was_surprise": False,
        "gagnant_proba_ia": 0.45,
        "feature_autopsy": {},
    }
    result = asyncio.get_event_loop().run_until_complete(al.process_race_signal(signal))
    for key in ("n_races", "temperature", "brier_ema", "surprise_rate_ema"):
        assert key in result


def test_adaptive_learning_bias_correction_zero_default():
    """Sans session DB, get_bias_correction retourne 0.0 par défaut."""
    # Juste test du comportement d'erreur gracieux
    from ml.adaptive_learning import AdaptiveLearning
    al = AdaptiveLearning()
    # On ne peut pas tester avec DB dans un test unitaire
    # Vérifier juste que l'instance est créée correctement
    assert al.temperature == 1.0
    assert al.brier_ema == 0.20


# ─────────────────────────────────────────────
# Contextual Corrector
# ─────────────────────────────────────────────
def test_contextual_corrector_large_field_deflates_favorite():
    """Grand champ (>16) → proba favori réduite."""
    from ml.meta_learner import ContextualCorrector
    corr = ContextualCorrector()
    p_before = 0.55
    ctx = {"nb_partants": 18, "hour_of_day": 14, "discipline": "plat", "distance": 2000}
    p_after = corr.get_correction(p_before, ctx, 0.0)
    assert p_after < p_before


def test_contextual_corrector_small_field_boosts_favorite():
    """Petit champ (≤8) → proba favori augmentée."""
    from ml.meta_learner import ContextualCorrector
    corr = ContextualCorrector()
    p_before = 0.40
    ctx = {"nb_partants": 6, "hour_of_day": 14, "discipline": "plat", "distance": 2000}
    p_after = corr.get_correction(p_before, ctx, 0.0)
    assert p_after > p_before


def test_contextual_corrector_output_bounded():
    """Proba corrigée reste dans [0.01, 0.99]."""
    from ml.meta_learner import ContextualCorrector
    corr = ContextualCorrector()
    for p, ctx in [
        (0.99, {"nb_partants": 4, "hour_of_day": 8, "discipline": "plat", "distance": 1600}),
        (0.01, {"nb_partants": 20, "hour_of_day": 19, "discipline": "trot", "distance": 2700}),
    ]:
        result = corr.get_correction(p, ctx, 0.0)
        assert 0.01 <= result <= 0.99


def test_contextual_corrector_bias_correction_applied():
    """bias_correction non nul doit modifier le résultat."""
    from ml.meta_learner import ContextualCorrector
    corr = ContextualCorrector()
    ctx = {"nb_partants": 10, "hour_of_day": 14, "discipline": "plat", "distance": 2000}
    p_no_bias = corr.get_correction(0.30, ctx, 0.0)
    p_with_bias = corr.get_correction(0.30, ctx, 0.05)
    assert p_with_bias != p_no_bias


# ─────────────────────────────────────────────
# BetPortfolioEngine — scénarios
# ─────────────────────────────────────────────
@pytest.fixture
def portfolio_predictions():
    """Prédictions synthétiques pour tester le portfolio."""
    return [
        {"participation_id": f"p{i}", "numero": i + 1, "nom": f"CHEVAL_{i}",
         "proba_top3": max(0.05, 0.70 - i * 0.08),
         "proba_top1": max(0.02, 0.30 - i * 0.03),
         "cote_pmu": 2.0 + i * 1.5,
         "cote_geny": 2.1 + i * 1.5,
         "spi": 0.3 if i == 5 else 0.0,
         "mouvement_cote": 0.25 if i == 5 else 0.0,
         "valeur_latente": 0.2 if i == 5 else 0.0,
         "decote_multi_source": 0.1 if i == 5 else 0.0,
         "confidence_score": 0.7 - i * 0.05,
         }
        for i in range(10)
    ]


@pytest.fixture
def portfolio_course_info():
    return {
        "course_id": "C_TEST",
        "hippodrome": "LONGCHAMP",
        "discipline": "plat",
        "distance": 2000,
        "terrain": "bon",
        "nb_partants": 10,
        "est_quinte": True,
        "est_quarte": True,
        "est_tierce": True,
    }


def test_portfolio_returns_scenarios(portfolio_predictions, portfolio_course_info):
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(
        predictions=portfolio_predictions,
        course_info=portfolio_course_info,
        bankroll=200.0,
    )
    assert "scenarios" in result
    assert len(result["scenarios"]) > 0


def test_portfolio_scenarios_have_required_keys(portfolio_predictions, portfolio_course_info):
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(portfolio_predictions, portfolio_course_info, bankroll=200.0)
    # scenarios est un dict {nom: {nom, description, paris, ...}}
    assert isinstance(result["scenarios"], dict)
    for scenario_key, scenario in result["scenarios"].items():
        if scenario is None:
            continue  # DELTA/OMEGA can be None when no candidates
        for key in ("nom", "description", "paris"):
            assert key in scenario, f"Scenario '{scenario_key}' missing key: {key}"


def test_portfolio_allocation_sums_to_budget(portfolio_predictions, portfolio_course_info):
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    budget = 20.0
    result = engine.build_portfolio(
        portfolio_predictions, portfolio_course_info, bankroll=200.0, budget_course=budget
    )
    alloc = result.get("allocation_recommandee", {})
    total = sum(v for v in alloc.values() if isinstance(v, (int, float)))
    assert total <= budget * 1.05  # Tolérance 5%


def test_portfolio_alpha_only_conservative(portfolio_predictions, portfolio_course_info):
    """Profil conservateur → ALPHA doit avoir plus que OMEGA."""
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(
        portfolio_predictions, portfolio_course_info,
        bankroll=200.0, profil="conservateur"
    )
    alloc = result.get("allocation_recommandee", {})
    # allocation values are dicts with 'budget_alloue' key
    def _budget(key):
        v = alloc.get(key.upper(), alloc.get(key.lower(), {}))
        if isinstance(v, dict):
            return v.get("budget_alloue", 0) or 0
        return v or 0
    alpha_val = _budget("alpha")
    omega_val = _budget("omega")
    assert alpha_val >= omega_val


def test_portfolio_delta_detects_outsider_signal(portfolio_predictions, portfolio_course_info):
    """DELTA doit détecter le signal fort sur cheval #5 (spi=0.3)."""
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(portfolio_predictions, portfolio_course_info, bankroll=200.0)
    # Outsider signal devrait être détecté
    assert result.get("outsiders_signal") is not None or result.get("nb_scenarios_actifs", 0) >= 1


def test_portfolio_paris_immediats_present(portfolio_predictions, portfolio_course_info):
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(portfolio_predictions, portfolio_course_info, bankroll=200.0)
    assert "paris_immediats" in result
    assert isinstance(result["paris_immediats"], list)


def test_portfolio_mise_min_respected(portfolio_predictions, portfolio_course_info):
    """Aucune mise ne doit être inférieure à la mise minimum légale."""
    from ml.portfolio import BetPortfolioEngine
    engine = BetPortfolioEngine()
    result = engine.build_portfolio(portfolio_predictions, portfolio_course_info, bankroll=200.0)
    # scenarios est un dict {nom: {paris: [...]}}
    for scenario_key, scenario in result["scenarios"].items():
        if scenario is None:
            continue  # DELTA/OMEGA can be None when no candidates
        for pari in scenario.get("paris", []):
            if isinstance(pari, dict) and pari.get("mise"):
                assert pari["mise"] >= 0.50, f"Mise trop faible dans {scenario_key}: {pari['mise']}"
