"""Régression : la sévérité DB doit refléter la dernière détection réelle."""

import json

import pytest

from ml.drift_detector import (
    DRIFT_WARMUP_MIN,
    SEVERITY_CRITICAL,
    SEVERITY_NONE,
    SEVERITY_WARNING,
    DriftDetector,
    persisted_state_corruption_reasons,
)


class _RecordingSession:
    def __init__(self):
        self.params = None

    async def execute(self, _statement, params):
        self.params = params


def _force_signals(monkeypatch, detector, *, brier, confidence):
    monkeypatch.setattr(detector._brier_adwin, "add", lambda _value: brier)
    monkeypatch.setattr(detector._surprise_ph, "add", lambda _value: False)
    monkeypatch.setattr(
        detector,
        "_compute_confidence_gap",
        lambda: (0.4 if confidence else 0.0, confidence),
    )
    monkeypatch.setattr(detector, "_compute_temporal_drift", lambda: (0.0, False))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("brier_signal", "confidence_signal", "expected"),
    [
        (False, False, SEVERITY_NONE),
        (True, False, SEVERITY_WARNING),
        (True, True, SEVERITY_CRITICAL),
    ],
)
async def test_save_state_persists_exact_update_severity(
    monkeypatch, brier_signal, confidence_signal, expected
):
    detector = DriftDetector()
    detector._total_observations = DRIFT_WARMUP_MIN
    _force_signals(
        monkeypatch,
        detector,
        brier=brier_signal,
        confidence=confidence_signal,
    )

    result = detector.update(
        brier_score=0.2,
        was_surprise=False,
        prediction_confidence=0.6,
    )
    session = _RecordingSession()
    await detector.save_state(session)

    assert result["severity"] == expected
    assert session.params["sev"] == expected
    assert json.loads(session.params["sj"])["current_severity"] == expected


@pytest.mark.asyncio
async def test_healthy_update_clears_live_severity_but_keeps_event_history(monkeypatch):
    detector = DriftDetector()
    detector._total_observations = DRIFT_WARMUP_MIN

    _force_signals(monkeypatch, detector, brier=True, confidence=False)
    detector.update(0.2, False, 0.6)
    assert detector._last_drift_type == "brier_adwin"

    _force_signals(monkeypatch, detector, brier=False, confidence=False)
    result = detector.update(0.2, False, 0.6)
    session = _RecordingSession()
    await detector.save_state(session)

    assert result["severity"] == SEVERITY_NONE
    assert detector._last_drift_type == "brier_adwin"
    assert detector.get_drift_report()["status"] == "healthy"
    assert session.params["sev"] == SEVERITY_NONE


def test_reset_clears_current_severity():
    detector = DriftDetector()
    detector._current_severity = SEVERITY_CRITICAL
    detector.reset()
    assert detector._current_severity == SEVERITY_NONE


class _StaticResult:
    def __init__(self, blob):
        self.blob = blob

    def first(self):
        return (self.blob,)


class _LoadingSession:
    def __init__(self, blob):
        self.blob = blob

    async def execute(self, _statement):
        return _StaticResult(self.blob)


@pytest.mark.asyncio
async def test_load_legacy_state_without_current_severity_is_safe():
    source = DriftDetector()
    source._current_severity = SEVERITY_WARNING
    recording_session = _RecordingSession()
    await source.save_state(recording_session)
    legacy_blob = json.loads(recording_session.params["sj"])
    legacy_blob.pop("current_severity")

    restored = DriftDetector()
    restored._current_severity = SEVERITY_CRITICAL
    assert await restored.load_state(_LoadingSession(legacy_blob)) is True
    assert restored._current_severity == SEVERITY_NONE


def test_detects_production_corruption_signatures():
    blob = {
        "conf_gap_window": [[26.8, False], [63.6, True], [99.0, False]],
        "brier_adwin": {"window": [0.20] * 100},
    }
    assert persisted_state_corruption_reasons(blob) == [
        "confidence_outside_0_1",
        "constant_fallback_brier_0_20",
    ]


def test_clean_state_has_no_corruption_signature():
    blob = {
        "conf_gap_window": [[0.268, False], [0.636, True], [0.99, False]],
        "brier_adwin": {"window": [0.12, 0.18, 0.23] * 20},
    }
    assert persisted_state_corruption_reasons(blob) == []


@pytest.mark.asyncio
async def test_load_rejects_corrupted_state_without_applying_it():
    source = DriftDetector()
    recording_session = _RecordingSession()
    await source.save_state(recording_session)
    blob = json.loads(recording_session.params["sj"])
    blob["conf_gap_window"] = [[63.6, False]]

    restored = DriftDetector()
    assert await restored.load_state(_LoadingSession(blob)) is False
    assert restored._total_observations == 0
