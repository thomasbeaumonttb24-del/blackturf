"""Les signaux stockes dans features_ml doivent atteindre le scenario DELTA."""

from api.routes.courses import _portfolio_market_signals
from ml.portfolio import BetPortfolioEngine


def test_portfolio_transmet_les_signaux_de_marche_au_scenario_delta():
    features = {
        "spi_score": 0.3,
        "mouvement_30min": 0.25,
        "valeur_latente": 0.2,
        "decote_detectee": 0.1,
    }
    outsider = {
        "numero": 7,
        "proba_top3": 0.2,
        "proba_top1": 0.08,
        "cote_pmu": 15.0,
        **_portfolio_market_signals(features),
    }
    candidates = BetPortfolioEngine()._detect_delta_candidates([outsider])
    assert len(candidates) == 1
    assert candidates[0]["force_signal"] == 0.235
    assert candidates[0]["signal_principal"] == "SPI — Argent professionnel détecté"
