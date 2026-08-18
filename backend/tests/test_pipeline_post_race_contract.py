"""Contrat entre l'analyse post-course et le détecteur de dérive."""

import pytest

from ml.pipeline import _extract_brier_course, _extract_prediction_confidence


def test_extract_brier_course_uses_analyzer_contract():
    assert _extract_brier_course({"brier_course": 0.137}) == pytest.approx(0.137)


def test_extract_brier_course_preserves_perfect_score():
    assert _extract_brier_course({"brier_course": 0.0}) == 0.0


@pytest.mark.parametrize(
    "analysis_result",
    [
        {},
        {"brier_score": 0.2},
        {"brier_course": -0.01},
        {"brier_course": 1.01},
        {"brier_course": float("nan")},
    ],
)
def test_extract_brier_course_rejects_missing_or_invalid_values(analysis_result):
    with pytest.raises(ValueError):
        _extract_brier_course(analysis_result)


@pytest.mark.parametrize("confidence", [0.0, 0.268, 0.636, 0.99, 1.0])
def test_extract_prediction_confidence_accepts_raw_probability(confidence):
    assert _extract_prediction_confidence({"gagnant_proba_ia": confidence}) == confidence


@pytest.mark.parametrize(
    "analysis_result",
    [
        {},
        {"gagnant_proba_ia_pct": 63.6},
        {"gagnant_proba_ia": -0.01},
        {"gagnant_proba_ia": 26.8},
        {"gagnant_proba_ia": 63.6},
        {"gagnant_proba_ia": 99.0},
        {"gagnant_proba_ia": float("nan")},
    ],
)
def test_extract_prediction_confidence_rejects_percent_or_invalid_values(
    analysis_result,
):
    with pytest.raises(ValueError):
        _extract_prediction_confidence(analysis_result)
