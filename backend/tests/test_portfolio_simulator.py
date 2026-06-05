"""
Tests simulateur portefeuille Monte-Carlo (Phase 5) — arrivées cohérentes.
"""
import numpy as np
import pytest

from ml.portfolio_simulator import (
    field_entropy, sample_rankings, simulate_portfolio_coverage,
    recommend_bet_count, validate_diversification, CoverageResult,
    evaluate_portfolio,
)


def test_field_entropy_bornes():
    assert field_entropy([1.0]) == 0.0
    # favori écrasant → entropie basse
    assert field_entropy([0.9, 0.05, 0.05]) < 0.5
    # champ uniforme → entropie ≈ 1
    assert field_entropy([0.25, 0.25, 0.25, 0.25]) == pytest.approx(1.0, abs=0.001)


def test_sample_rankings_coherence():
    rng = np.random.default_rng(42)
    pos = sample_rankings(np.array([0.6, 0.3, 0.1]), 5000, rng)
    # Chaque ligne est une permutation de 1..3
    assert pos.shape == (5000, 3)
    for s in range(10):
        assert sorted(pos[s].tolist()) == [1, 2, 3]
    # Le plus fort gagne le plus souvent
    win_rate = (pos[:, 0] == 1).mean()
    assert win_rate > (pos[:, 1] == 1).mean()
    assert win_rate > 0.45  # cohérent avec force 0.6/1.0


def test_simulate_gagnant_favori_couverture():
    # Pari gagnant sur le favori (force 0.6) à cote 2.0.
    bets = [{"type": "gagnant", "numeros": [1], "stake": 10.0, "cote": 2.0}]
    res = simulate_portfolio_coverage(
        bets, numeros=[1, 2, 3], win_probs=[0.6, 0.3, 0.1],
        nb_partants=8, n_simulations=20000, seed=1,
    )
    assert isinstance(res, CoverageResult)
    # P(victoire favori) ≈ 0.6 → couverture proche
    assert 0.5 < res.coverage < 0.7
    assert res.n_bets == 1


def test_simulate_correlation_paris_meme_course():
    # Deux paris GAGNANT sur deux chevaux différents : ne peuvent gagner ensemble.
    bets = [
        {"type": "gagnant", "numeros": [1], "stake": 10.0, "cote": 2.5},
        {"type": "gagnant", "numeros": [2], "stake": 10.0, "cote": 4.0},
    ]
    res = simulate_portfolio_coverage(
        bets, numeros=[1, 2, 3], win_probs=[0.5, 0.3, 0.2],
        nb_partants=8, n_simulations=20000, seed=7,
    )
    # win_probs des 2 paris ≈ proba de victoire individuelle, jamais simultanés
    probs = list(res.bet_win_probs.values())
    assert all(0.1 < p < 0.6 for p in probs)
    # 2 paris gagnant = mutuellement exclusifs → couverture = somme (et NON l'union
    # indépendante 1-(1-p1)(1-p2), plus faible). Prouve la corrélation capturée.
    union_independante = 1 - (1 - probs[0]) * (1 - probs[1])
    assert res.coverage == pytest.approx(sum(probs), abs=0.01)
    assert res.coverage > union_independante


def test_simulate_placement_diversifie_augmente_couverture():
    # Placé sur le favori (champ de 8 → 3 payés) doit avoir une couverture élevée.
    bets = [{"type": "place", "numeros": [1], "stake": 10.0, "cote": 1.5}]
    res = simulate_portfolio_coverage(
        bets, numeros=[1, 2, 3, 4, 5, 6, 7, 8],
        win_probs=[0.4, 0.2, 0.15, 0.1, 0.05, 0.05, 0.03, 0.02],
        nb_partants=8, n_simulations=20000, seed=3,
    )
    assert res.coverage > 0.6   # favori souvent dans les 3


def test_recommend_bet_count_scale_avec_incertitude():
    assert recommend_bet_count(0.0) < recommend_bet_count(1.0)
    assert recommend_bet_count(0.0) >= 2


def test_validate_diversification_diagnostic():
    res = CoverageResult(coverage=0.4, mean_roi=-0.1, field_entropy=0.8, prob_ruine=0.6)
    v = validate_diversification(res, coverage_cible=0.6, ev_min=0.0)
    assert v["valide"] is False
    assert v["coverage_ok"] is False
    assert v["ev_ok"] is False
    assert len(v["suggestions"]) >= 2
    assert v["reco_nb_paris"] >= 2


def test_simulate_vide():
    res = simulate_portfolio_coverage([], numeros=[1, 2], win_probs=[0.5, 0.5])
    assert res.n_bets == 0
    assert res.coverage == 0.0


def test_evaluate_portfolio_pipeline_complet():
    predictions = [
        {"numero": 1, "nom": "FAVORI", "proba_top3": 0.55, "proba_top1": 0.30,
         "cote_pmu": 2.5, "ev_max": 0.3, "niveau_vb": 3},
        {"numero": 2, "nom": "SECOND", "proba_top3": 0.42, "proba_top1": 0.18,
         "cote_pmu": 3.5, "ev_max": 0.1, "niveau_vb": 2},
        {"numero": 3, "nom": "OUTSIDER", "proba_top3": 0.15, "proba_top1": 0.05,
         "cote_pmu": 12.0, "ev_max": 0.05, "niveau_vb": 1},
    ]
    course_info = {"course_id": "C1", "nb_partants": 10, "est_tierce": True,
                   "est_quarte": False, "est_quinte": False}
    out = evaluate_portfolio(predictions, course_info, bankroll=200.0,
                             n_simulations=5000, seed=11)
    assert "portfolio" in out and "coverage" in out and "validation" in out
    cov = out["coverage"]
    assert cov["n_simulations"] == 5000
    assert 0.0 <= cov["coverage"] <= 1.0
    assert 0.0 <= cov["field_entropy"] <= 1.0
    assert "reco_nb_paris" in out["validation"]
