"""
BlackTurf ML package — exports principaux.

Architecture de prédiction (3 couches) :
  L1 : BlackTurfEnsemble (XGBoost + LightGBM + CatBoost + stacking meta-learner)
  L2 : AdaptiveLearning (temperature scaling + feature weights adaptatifs)
  L3 : MetaLearner (correction contextuelle apprise) + ContextualCorrector (fallback)

Apprentissage continu :
  PostRaceAnalyzer  → autopsie post-course + signal d'apprentissage
  AdaptiveLearning  → calibration online (température, poids features)
  DriftDetector     → ADWIN + Page-Hinkley : détection de dérive de distribution

Portfolio :
  BetPortfolioEngine → 5 scénarios (ALPHA/BETA/GAMMA/DELTA/OMEGA)
  MonteCarloSimulator → validation statistique des scénarios (10k simulations)
"""
from ml.adaptive_learning import get_adaptive_learning, initialize_adaptive_learning, AdaptiveLearning
from ml.post_race_analyzer import PostRaceAnalyzer
from ml.portfolio import BetPortfolioEngine
from ml.drift_detector import get_drift_detector, initialize_drift_detector, DriftDetector
from ml.meta_learner import get_meta_learner, get_contextual_corrector, initialize_meta_learner
from ml.monte_carlo import MonteCarloSimulator

__all__ = [
    # Adaptive learning
    "get_adaptive_learning",
    "initialize_adaptive_learning",
    "AdaptiveLearning",
    # Post-race analysis
    "PostRaceAnalyzer",
    # Portfolio
    "BetPortfolioEngine",
    "MonteCarloSimulator",
    # Drift detection
    "get_drift_detector",
    "initialize_drift_detector",
    "DriftDetector",
    # Meta-learner
    "get_meta_learner",
    "get_contextual_corrector",
    "initialize_meta_learner",
]
