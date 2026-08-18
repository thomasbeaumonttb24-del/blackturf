"""
drift_detector.py — Concept Drift Detection for BlackTurf ML Prediction System.

This module implements statistical methods to detect when the horse racing model's
underlying data distribution has shifted, indicating that the model needs retraining.

Two core algorithms are used:

1. ADWIN (Adaptive Windowing) — Bifet & Gavalda, 2007.
   Maintains an adaptive window of recent observations. It detects drift by
   testing whether two sub-windows within the history have statistically
   different means. If the difference exceeds a threshold derived from
   Hoeffding's inequality, drift is declared and the older sub-window is
   discarded.

   The key inequality tested is:
       |mean(W0) - mean(W1)| >= epsilon_cut
   where:
       epsilon_cut = sqrt( (1 / (2 * m)) * ln(4 * n^2 / delta) )
       m = harmonic mean of the two sub-window sizes
       n = total window size
       delta = confidence parameter (ADWIN_DELTA)

2. Page-Hinkley (PH) Test — Page, 1954.
   A sequential change-point detection test for detecting a persistent shift
   in the mean of a signal. It accumulates the difference between each
   observation and a reference mean, raising an alarm when the cumulative
   sum minus its running minimum exceeds a threshold.

   Update rule:
       cumsum_t = cumsum_{t-1} + (x_t - mean_t - lambda)
       PH_t = cumsum_t - min(cumsum_s, s <= t)
   Drift is declared when PH_t > alpha.
"""

from __future__ import annotations

import json
import math
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADWIN_DELTA: float = 0.002
"""ADWIN confidence parameter. Smaller values → fewer false alarms, slower detection."""

PH_LAMBDA: float = 50.0
"""Page-Hinkley detection threshold. Higher → less sensitive, fewer false alarms."""

PH_ALPHA: float = 0.005
"""Page-Hinkley forgetting factor — tolerance for mean deviation before alarm."""

WINDOW_SIZE: int = 200
"""Maximum number of observations retained in the rolling window."""

SURPRISE_RATE_WINDOW: int = 100
"""Number of recent predictions to track for surprise rate computation."""

CONFIDENCE_GAP_WINDOW: int = 50
"""Window size for the confidence-accuracy gap detector."""

CONFIDENCE_HIGH_THRESHOLD: float = 0.75
"""Minimum model confidence to consider a prediction 'high-confidence'."""

TEMPORAL_WEEK_WINDOW: int = 7 * 10
"""Approximate number of observations per week (10 races/day assumed)."""

SEVERITY_NONE: str = "none"
SEVERITY_WARNING: str = "warning"
SEVERITY_CRITICAL: str = "critical"


def persisted_state_corruption_reasons(blob: dict[str, Any]) -> list[str]:
    """Détecte les signatures connues de l'ancien câblage post-course cassé."""
    reasons: list[str] = []

    confidence_values = []
    for item in blob.get("conf_gap_window") or []:
        if isinstance(item, (list, tuple)) and item:
            try:
                confidence_values.append(float(item[0]))
            except (TypeError, ValueError):
                reasons.append("invalid_confidence_value")
                break
    if any(not math.isfinite(v) or not 0.0 <= v <= 1.0 for v in confidence_values):
        reasons.append("confidence_outside_0_1")

    brier_values = (blob.get("brier_adwin") or {}).get("window") or []
    if len(brier_values) >= 50:
        try:
            parsed_brier = [float(v) for v in brier_values]
        except (TypeError, ValueError):
            reasons.append("invalid_brier_value")
        else:
            if all(math.isfinite(v) and v == 0.20 for v in parsed_brier):
                reasons.append("constant_fallback_brier_0_20")

    return reasons


# Détecter une dérive sous ce nombre d'observations est peu fiable (bruit) :
# en phase d'amorçage (peu de vraies courses), on ne déclare pas de dérive.
DRIFT_WARMUP_MIN: int = 200

logger = structlog.get_logger(__name__)

# Persistence note
# ---------------------------------------------------------------------------
# The detector state lives in the ``drift_detector_state`` table, defined
# canonically by ``backend/db/models.py`` (singleton row keyed by
# ``state_id = 'singleton'``: state_json, severity, n_updates, last_drift_at,
# updated_at). save_state()/load_state() below talk to it via raw SQL — there
# is intentionally NO local ORM model here. A previous local model declared an
# ``id`` integer PK that never existed in the real table, which broke
# initialisation; do not reintroduce one.

# ---------------------------------------------------------------------------
# Internal algorithm helpers
# ---------------------------------------------------------------------------


class _ADWINWindow:
    """
    Pure-Python / NumPy implementation of the ADWIN adaptive window.

    ADWIN maintains a compressed representation of a data stream using
    a list of *buckets* (exponential histogram). Each bucket stores the
    count and sum of observations it compresses. The window is scanned
    for sub-window pairs whose means differ significantly; when found,
    the older half is dropped and a drift flag is raised.

    This implementation uses a simple deque of raw values capped at
    ``WINDOW_SIZE`` for clarity and correctness, which is appropriate
    for the scale of a racing ML system (not a high-frequency stream).

    Args:
        delta: Confidence parameter. See module docstring.
        max_size: Maximum number of observations to retain.
    """

    def __init__(self, delta: float = ADWIN_DELTA, max_size: int = WINDOW_SIZE) -> None:
        self.delta = delta
        self.max_size = max_size
        self._window: deque[float] = deque(maxlen=max_size)
        self.drift_detected: bool = False
        self.n_detections: int = 0

    def add(self, value: float) -> bool:
        """
        Add a new observation to the window and test for drift.

        The test iterates over all possible split points i in [1, n-1] and
        checks whether the left sub-window W0 = window[:i] and right
        sub-window W1 = window[i:] have means that differ by more than
        epsilon_cut(i, n):

            epsilon_cut = sqrt( (1 / (2*m)) * ln(4 * n^2 / delta) )

        where m = (n0 * n1) / (n0 + n1) is the harmonic-weighted count.

        If drift is found, the window is truncated to keep only the newer
        sub-window (from split point onward).

        Args:
            value: New scalar observation (e.g. Brier score).

        Returns:
            True if drift was detected on this update, False otherwise.
        """
        self._window.append(value)
        self.drift_detected = False

        n = len(self._window)
        if n < 30:
            # Not enough data for a meaningful test.
            return False

        arr = np.array(self._window, dtype=np.float64)
        total_mean = arr.mean()

        # Scan cut points from oldest to newest.
        for i in range(1, n):
            n0 = i
            n1 = n - i
            if n0 < 5 or n1 < 5:
                continue

            mean0 = arr[:i].mean()
            mean1 = arr[i:].mean()

            # Harmonic combination of sizes.
            m = (n0 * n1) / (n0 + n1)
            # Hoeffding-based epsilon_cut (values assumed in [0, 1]).
            epsilon_cut = math.sqrt((1.0 / (2.0 * m)) * math.log(4.0 * n * n / self.delta))

            if abs(mean0 - mean1) >= epsilon_cut:
                # Drift: discard the older sub-window.
                new_window = deque(arr[i:], maxlen=self.max_size)
                self._window = new_window
                self.drift_detected = True
                self.n_detections += 1
                logger.debug(
                    "adwin_drift_detected",
                    split_point=i,
                    mean_old=round(float(mean0), 4),
                    mean_new=round(float(mean1), 4),
                    epsilon_cut=round(epsilon_cut, 4),
                )
                return True

        return False

    @property
    def mean(self) -> float:
        """Current mean of the adaptive window. Returns 0.0 if empty."""
        if not self._window:
            return 0.0
        return float(np.mean(self._window))

    @property
    def size(self) -> int:
        """Number of observations currently in the window."""
        return len(self._window)

    def to_dict(self) -> dict[str, Any]:
        """Serialise state to a JSON-safe dict."""
        return {
            "window": list(self._window),
            "delta": self.delta,
            "max_size": self.max_size,
            "n_detections": self.n_detections,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_ADWINWindow":
        """Restore from a serialised dict."""
        obj = cls(delta=data["delta"], max_size=data["max_size"])
        obj._window = deque(data["window"], maxlen=data["max_size"])
        obj.n_detections = data["n_detections"]
        return obj


class _PageHinkley:
    """
    Page-Hinkley sequential change-point test for upward mean shift.

    Tracks whether the mean of a stream has increased relative to a
    reference mean learned from the first observations.

    State variables:
        cumsum     — running sum of (x_t - mean_t - lambda)
        min_cumsum — running minimum of cumsum (tracks the lowest point)
        ph         — current PH statistic: cumsum - min_cumsum
        n          — number of observations seen
        sum_x      — running sum of raw values (to compute incremental mean)

    Drift criterion:
        ph > PH_LAMBDA  →  drift declared

    Args:
        lambda_: Detection threshold (higher = less sensitive).
        alpha:   Allowed deviation from the reference mean before accumulation
                 starts counting against the baseline.
    """

    def __init__(self, lambda_: float = PH_LAMBDA, alpha: float = PH_ALPHA) -> None:
        self.lambda_ = lambda_
        self.alpha = alpha
        self._cumsum: float = 0.0
        self._min_cumsum: float = 0.0
        self._n: int = 0
        self._sum_x: float = 0.0
        self.drift_detected: bool = False
        self.n_detections: int = 0

    def add(self, value: float) -> bool:
        """
        Update the PH statistic with a new observation.

        The mean is estimated incrementally:
            mean_t = sum_x_t / t

        Then:
            cumsum_t = cumsum_{t-1} + (value - mean_t - alpha)
            PH_t     = cumsum_t - min(cumsum_s, s <= t)

        Args:
            value: New scalar observation (e.g. rolling surprise rate).

        Returns:
            True if drift declared on this update.
        """
        self._n += 1
        self._sum_x += value
        mean_t = self._sum_x / self._n

        self._cumsum += value - mean_t - self.alpha
        if self._cumsum < self._min_cumsum:
            self._min_cumsum = self._cumsum

        ph = self._cumsum - self._min_cumsum
        self.drift_detected = ph > self.lambda_

        if self.drift_detected:
            self.n_detections += 1
            logger.debug(
                "page_hinkley_drift_detected",
                ph_stat=round(ph, 4),
                threshold=self.lambda_,
                n=self._n,
            )

        return self.drift_detected

    @property
    def ph_statistic(self) -> float:
        """Current value of the PH test statistic."""
        return self._cumsum - self._min_cumsum

    def reset_statistic(self) -> None:
        """
        Soft reset: zero the cumulative sums but keep the learned mean.

        Called after a drift event to restart accumulation without
        discarding the reference mean estimate.
        """
        self._cumsum = 0.0
        self._min_cumsum = 0.0
        self.drift_detected = False

    def to_dict(self) -> dict[str, Any]:
        """Serialise state to a JSON-safe dict."""
        return {
            "lambda_": self.lambda_,
            "alpha": self.alpha,
            "cumsum": self._cumsum,
            "min_cumsum": self._min_cumsum,
            "n": self._n,
            "sum_x": self._sum_x,
            "n_detections": self.n_detections,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_PageHinkley":
        """Restore from a serialised dict."""
        obj = cls(lambda_=data["lambda_"], alpha=data["alpha"])
        obj._cumsum = data["cumsum"]
        obj._min_cumsum = data["min_cumsum"]
        obj._n = data["n"]
        obj._sum_x = data["sum_x"]
        obj.n_detections = data["n_detections"]
        return obj


# ---------------------------------------------------------------------------
# Main DriftDetector class
# ---------------------------------------------------------------------------


class DriftDetector:
    """
    Multi-signal concept drift detector for the BlackTurf ML prediction system.

    Combines four complementary drift signals to robustly identify when the
    model's learned distribution no longer matches the current race data:

    Signal 1 — Brier Score ADWIN
        The Brier score (mean squared error of probability forecasts) for each
        prediction is fed into an ADWIN window. A detected drift means the
        model's calibration has significantly shifted.

    Signal 2 — Surprise Rate Page-Hinkley
        A "surprise" is a race whose outcome the model found highly unexpected
        (e.g. a heavy favourite losing). The rolling surprise rate is monitored
        with a PH test. Rising surprise rates indicate distributional shift in
        race outcomes.

    Signal 3 — Confidence-Accuracy Gap
        When the model frequently outputs high-confidence predictions that turn
        out to be wrong, the gap between confidence and realised accuracy exceeds
        a threshold. Tracked over a short window; high gap → model is overfit
        to stale patterns.

    Signal 4 — Temporal Drift
        Compares the mean Brier score of the most recent week's predictions
        against the longer historical baseline. A statistically significant
        degradation over time indicates gradual concept drift (e.g. changing
        track conditions, jockey form shifts, seasonal patterns).

    Severity Levels
    ---------------
    - "none"     : All signals nominal.
    - "warning"  : One signal is elevated; model performance may be declining.
    - "critical" : Two or more signals detect drift, or one critical signal
                   fires. Urgent retraining is recommended.

    Args:
        adwin_delta:  Confidence parameter for ADWIN windows.
        ph_lambda:    Detection threshold for Page-Hinkley.
        ph_alpha:     Mean tolerance for Page-Hinkley.
        window_size:  Maximum rolling window size for ADWIN.
    """

    def __init__(
        self,
        adwin_delta: float = ADWIN_DELTA,
        ph_lambda: float = PH_LAMBDA,
        ph_alpha: float = PH_ALPHA,
        window_size: int = WINDOW_SIZE,
    ) -> None:
        self._adwin_delta = adwin_delta
        self._ph_lambda = ph_lambda
        self._ph_alpha = ph_alpha
        self._window_size = window_size

        # Signal 1: Brier score ADWIN.
        self._brier_adwin = _ADWINWindow(delta=adwin_delta, max_size=window_size)

        # Signal 2: Surprise rate Page-Hinkley.
        self._surprise_ph = _PageHinkley(lambda_=ph_lambda, alpha=ph_alpha)
        self._surprise_window: deque[int] = deque(maxlen=SURPRISE_RATE_WINDOW)

        # Signal 3: Confidence-accuracy gap.
        self._conf_gap_window: deque[tuple[float, bool]] = deque(
            maxlen=CONFIDENCE_GAP_WINDOW
        )

        # Signal 4: Temporal drift — store (timestamp_ordinal, brier_score).
        self._temporal_window: deque[tuple[int, float]] = deque(
            maxlen=self._window_size
        )

        # Bookkeeping.
        self._total_observations: int = 0
        self._drift_events: list[dict[str, Any]] = []
        self._last_drift_type: Optional[str] = None
        self._last_drift_time: Optional[datetime] = None
        # Sévérité de la DERNIÈRE mise à jour, distincte de l'historique du
        # dernier événement. C'est cette valeur qui doit piloter l'état live DB.
        self._current_severity: str = SEVERITY_NONE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        brier_score: float,
        was_surprise: bool,
        prediction_confidence: float,
    ) -> dict[str, Any]:
        """
        Ingest a new prediction outcome and test all drift signals.

        Call this once per resolved prediction (i.e. after a race result is
        known).

        Args:
            brier_score:
                The Brier score for this prediction, in [0, 2]. Lower is
                better. Brier = (f - o)^2 where f is predicted probability
                and o is actual outcome (0 or 1).
            was_surprise:
                True if the race outcome was a statistical surprise given
                the model's predictions (e.g. favourite had p > 0.7 but lost).
            prediction_confidence:
                The model's maximum predicted probability for the winning
                outcome, in [0, 1].

        Returns:
            A dict with the following keys:

            drift_detected (bool)   : True if any signal detected drift.
            severity (str)          : "none", "warning", or "critical".
            signals (dict)          : Per-signal status flags.
            total_observations (int): Cumulative update count.
            brier_mean (float)      : Current mean Brier score.
            surprise_rate (float)   : Rolling surprise rate.
            ph_statistic (float)    : Current Page-Hinkley statistic.
            conf_gap (float)        : Current confidence-accuracy gap.
            temporal_delta (float)  : Brier score change vs. older baseline.
        """
        self._total_observations += 1
        now = datetime.now(timezone.utc)
        day_ordinal = now.toordinal()

        # -- Signal 1: Brier ADWIN ------------------------------------
        brier_drift = self._brier_adwin.add(brier_score)

        # -- Signal 2: Surprise rate PH --------------------------------
        self._surprise_window.append(1 if was_surprise else 0)
        surprise_rate = (
            float(np.mean(self._surprise_window)) if self._surprise_window else 0.0
        )
        surprise_drift = self._surprise_ph.add(surprise_rate)
        if surprise_drift:
            # Soft-reset PH to continue monitoring after alarm.
            self._surprise_ph.reset_statistic()

        # -- Signal 3: Confidence-accuracy gap -------------------------
        # A high-confidence prediction that was wrong is a "gap event".
        is_high_conf = prediction_confidence >= CONFIDENCE_HIGH_THRESHOLD
        # was_surprise is used as a proxy for "wrong when confident":
        # if the model was highly confident AND the outcome was a surprise,
        # the model was confidently wrong.
        self._conf_gap_window.append((prediction_confidence, was_surprise))
        conf_gap, conf_gap_drift = self._compute_confidence_gap()

        # -- Signal 4: Temporal drift ----------------------------------
        self._temporal_window.append((day_ordinal, brier_score))
        temporal_delta, temporal_drift = self._compute_temporal_drift()

        # -- Aggregate severity ----------------------------------------
        active_signals = {
            "brier_adwin": brier_drift,
            "surprise_rate_ph": surprise_drift,
            "confidence_gap": conf_gap_drift,
            "temporal": temporal_drift,
        }
        n_active = sum(active_signals.values())

        if n_active == 0:
            severity = SEVERITY_NONE
            drift_detected = False
        elif n_active == 1:
            severity = SEVERITY_WARNING
            drift_detected = True
        else:
            severity = SEVERITY_CRITICAL
            drift_detected = True

        # Warm-up : sous le seuil minimal d'observations, la détection est trop
        # bruitée (faux "critique" en amorçage du modèle) → on neutralise.
        if self._total_observations < DRIFT_WARMUP_MIN:
            severity = SEVERITY_NONE
            drift_detected = False
            self._last_drift_type = None  # garde save_state cohérent (severity=none)

        self._current_severity = severity

        if drift_detected:
            drift_type = next(k for k, v in active_signals.items() if v)
            self._last_drift_type = drift_type
            self._last_drift_time = now
            event = {
                "time": now.isoformat(),
                "severity": severity,
                "type": drift_type,
                "signals": active_signals,
                "brier_mean": self._brier_adwin.mean,
                "n": self._total_observations,
            }
            self._drift_events.append(event)

            if severity == SEVERITY_CRITICAL:
                logger.warning(
                    "CRITICAL_DRIFT_DETECTED — urgent model retraining recommended",
                    severity=severity,
                    active_signals=[k for k, v in active_signals.items() if v],
                    brier_mean=round(self._brier_adwin.mean, 4),
                    surprise_rate=round(surprise_rate, 4),
                    conf_gap=round(conf_gap, 4),
                    temporal_delta=round(temporal_delta, 4),
                    total_observations=self._total_observations,
                )
            else:
                logger.info(
                    "drift_warning_detected",
                    severity=severity,
                    signal=drift_type,
                    total_observations=self._total_observations,
                )

        return {
            "drift_detected": drift_detected,
            "severity": severity,
            "signals": active_signals,
            "total_observations": self._total_observations,
            "brier_mean": round(self._brier_adwin.mean, 4),
            "surprise_rate": round(surprise_rate, 4),
            "ph_statistic": round(self._surprise_ph.ph_statistic, 4),
            "conf_gap": round(conf_gap, 4),
            "temporal_delta": round(temporal_delta, 4),
        }

    def get_drift_report(self) -> dict[str, Any]:
        """
        Return a comprehensive status summary of the drift detector.

        This is intended for monitoring dashboards and health-check endpoints.

        Returns:
            A dict containing:

            status (str)               : "healthy", "warning", or "critical".
            total_observations (int)   : Total predictions processed.
            total_drift_events (int)   : Cumulative number of drift events.
            last_drift_type (str|None) : Most recent drift signal that fired.
            last_drift_time (str|None) : ISO timestamp of the last drift.
            brier_window_size (int)    : Current ADWIN window size.
            brier_mean (float)         : Mean Brier score in current window.
            brier_adwin_detections (int): Number of ADWIN drifts recorded.
            surprise_ph_detections (int): Number of PH alarms recorded.
            ph_statistic (float)       : Current PH test statistic.
            conf_gap (float)           : Current confidence-accuracy gap.
            temporal_delta (float)     : Brier score week-over-week delta.
            recent_drift_events (list) : Last 5 drift events.
            constants (dict)           : Active algorithm parameters.
        """
        conf_gap, _ = self._compute_confidence_gap()
        temporal_delta, _ = self._compute_temporal_drift()
        surprise_rate = (
            float(np.mean(self._surprise_window)) if self._surprise_window else 0.0
        )

        # Statut LIVE de la dernière observation. L'historique reste disponible
        # dans recent_drift_events, mais ne doit pas maintenir le scheduler en
        # critical après un retour à la normale.
        status = (
            self._current_severity
            if self._current_severity != SEVERITY_NONE
            else "healthy"
        )

        return {
            "status": status,
            "total_observations": self._total_observations,
            "total_drift_events": len(self._drift_events),
            "last_drift_type": self._last_drift_type,
            "last_drift_time": (
                self._last_drift_time.isoformat() if self._last_drift_time else None
            ),
            "brier_window_size": self._brier_adwin.size,
            "brier_mean": round(self._brier_adwin.mean, 4),
            "brier_adwin_detections": self._brier_adwin.n_detections,
            "surprise_ph_detections": self._surprise_ph.n_detections,
            "surprise_rate": round(surprise_rate, 4),
            "ph_statistic": round(self._surprise_ph.ph_statistic, 4),
            "conf_gap": round(conf_gap, 4),
            "temporal_delta": round(temporal_delta, 4),
            "recent_drift_events": self._drift_events[-5:],
            "constants": {
                "ADWIN_DELTA": self._adwin_delta,
                "PH_LAMBDA": self._ph_lambda,
                "PH_ALPHA": self._ph_alpha,
                "WINDOW_SIZE": self._window_size,
            },
        }

    def reset(self) -> None:
        """
        Full reset of all detector state after a model retraining.

        After the model is retrained, all accumulated statistics are invalid
        because the new model will have a different error distribution. This
        method wipes all windows and counters so the detector can learn the
        new baseline from scratch.

        The drift event history is preserved for audit purposes.
        """
        logger.info(
            "drift_detector_reset",
            previous_observations=self._total_observations,
            previous_drift_events=len(self._drift_events),
        )

        self._brier_adwin = _ADWINWindow(
            delta=self._adwin_delta, max_size=self._window_size
        )
        self._surprise_ph = _PageHinkley(
            lambda_=self._ph_lambda, alpha=self._ph_alpha
        )
        self._surprise_window.clear()
        self._conf_gap_window.clear()
        self._temporal_window.clear()

        self._total_observations = 0
        # Preserve history; just clear active state.
        self._last_drift_type = None
        self._last_drift_time = None
        self._current_severity = SEVERITY_NONE

    async def save_state(self, session: AsyncSession) -> None:
        """
        Persist the full detector state to the ``drift_detector_state`` table.

        The state is serialised as a JSON blob and upserted into a single row
        (id=1). Call this after each ``update()`` or at regular checkpoints to
        ensure the detector survives process restarts.

        Args:
            session: An open SQLAlchemy async session with write access.
        """
        state_blob = {
            "brier_adwin": self._brier_adwin.to_dict(),
            "surprise_ph": self._surprise_ph.to_dict(),
            "surprise_window": list(self._surprise_window),
            "conf_gap_window": list(self._conf_gap_window),
            "temporal_window": list(self._temporal_window),
            "total_observations": self._total_observations,
            "drift_events": self._drift_events,
            "last_drift_type": self._last_drift_type,
            "current_severity": self._current_severity,
            "last_drift_time": (
                self._last_drift_time.isoformat() if self._last_drift_time else None
            ),
        }
        json_blob = json.dumps(state_blob, default=str)

        # Upsert SQL brut sur la VRAIE table (schéma db.models : state_id 'singleton',
        # state_json JSON, severity, n_updates, last_drift_at). Évite le mismatch ORM
        # (ancienne classe locale attendait une colonne `id` inexistante → cassait
        # le commit de la boucle d'apprentissage).
        await session.execute(
            text("""
                INSERT INTO drift_detector_state
                    (state_id, state_json, severity, n_updates, last_drift_at, updated_at)
                VALUES ('singleton', CAST(:sj AS JSONB), :sev, :nu, :lda, now())
                ON CONFLICT (state_id) DO UPDATE SET
                    state_json = CAST(:sj AS JSONB),
                    severity   = :sev,
                    n_updates  = :nu,
                    last_drift_at = :lda,
                    updated_at = now()
            """),
            {
                "sj": json_blob,
                "sev": self._current_severity,
                "nu": int(self._total_observations),
                "lda": self._last_drift_time,
            },
        )
        logger.debug(
            "drift_detector_state_saved",
            total_observations=self._total_observations,
            drift_events=len(self._drift_events),
        )

    async def load_state(self, session: AsyncSession) -> bool:
        """
        Restore the detector state from the ``drift_detector_state`` table.

        If no persisted state is found, the detector remains in its initial
        state and False is returned. Call this during application startup
        before processing any new predictions.

        Args:
            session: An open SQLAlchemy async session with read access.

        Returns:
            True if state was successfully loaded, False if no state exists.
        """
        result = await session.execute(
            text("SELECT state_json FROM drift_detector_state WHERE state_id = 'singleton'")
        )
        row = result.first()

        if row is None or row[0] is None:
            logger.info("drift_detector_no_persisted_state_found")
            return False

        # Colonne JSON → asyncpg renvoie déjà un dict (ou une str selon le driver)
        blob = row[0] if isinstance(row[0], dict) else json.loads(row[0])

        corruption_reasons = persisted_state_corruption_reasons(blob)
        if corruption_reasons:
            logger.warning(
                "drift_detector_corrupted_state_rejected",
                reasons=corruption_reasons,
            )
            return False

        self._brier_adwin = _ADWINWindow.from_dict(blob["brier_adwin"])
        self._surprise_ph = _PageHinkley.from_dict(blob["surprise_ph"])
        self._surprise_window = deque(
            blob["surprise_window"], maxlen=SURPRISE_RATE_WINDOW
        )
        self._conf_gap_window = deque(
            [tuple(x) for x in blob["conf_gap_window"]],
            maxlen=CONFIDENCE_GAP_WINDOW,
        )
        self._temporal_window = deque(
            [tuple(x) for x in blob["temporal_window"]],
            maxlen=self._window_size,
        )
        self._total_observations = blob["total_observations"]
        self._drift_events = blob["drift_events"]
        self._last_drift_type = blob["last_drift_type"]
        persisted_severity = blob.get("current_severity", SEVERITY_NONE)
        self._current_severity = (
            persisted_severity
            if persisted_severity in {
                SEVERITY_NONE,
                SEVERITY_WARNING,
                SEVERITY_CRITICAL,
            }
            else SEVERITY_NONE
        )
        self._last_drift_time = (
            datetime.fromisoformat(blob["last_drift_time"])
            if blob["last_drift_time"]
            else None
        )

        logger.info(
            "drift_detector_state_loaded",
            total_observations=self._total_observations,
            drift_events=len(self._drift_events),
            last_drift_type=self._last_drift_type,
        )
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_confidence_gap(self) -> tuple[float, bool]:
        """
        Compute the confidence-accuracy gap over the recent window.

        For each high-confidence prediction, check whether the outcome was
        a surprise (i.e. the model was confidently wrong). The gap is
        defined as:

            gap = mean(confidence) − (1 − surprise_rate)
                = mean(confidence) − accuracy

        where accuracy is estimated as the fraction of high-confidence
        predictions that were NOT surprises.

        A gap > 0.25 (i.e. confidence exceeds realised accuracy by more
        than 25 percentage points) triggers a warning.

        Returns:
            Tuple of (gap_value, drift_flag).
        """
        if len(self._conf_gap_window) < 10:
            return 0.0, False

        data = [(conf, surp) for conf, surp in self._conf_gap_window
                if conf >= CONFIDENCE_HIGH_THRESHOLD]

        if len(data) < 5:
            return 0.0, False

        confidences = np.array([c for c, _ in data])
        surprises = np.array([s for _, s in data], dtype=float)

        mean_confidence = float(confidences.mean())
        surprise_rate = float(surprises.mean())
        accuracy = 1.0 - surprise_rate

        gap = mean_confidence - accuracy
        drift = gap > 0.25

        return gap, drift

    def _compute_temporal_drift(self) -> tuple[float, bool]:
        """
        Detect gradual performance degradation over rolling weekly windows.

        Splits the temporal window into two halves — an older baseline and
        a recent segment — and computes the difference in mean Brier scores.

        A Brier score increase > 0.05 in the recent week relative to the
        older baseline is flagged as temporal drift. This threshold is
        intentionally conservative to avoid false alarms from short-term
        variance.

        Returns:
            Tuple of (delta, drift_flag) where delta = recent_mean - old_mean.
            Positive delta means the model has gotten worse recently.
        """
        if len(self._temporal_window) < TEMPORAL_WEEK_WINDOW * 2:
            return 0.0, False

        arr = np.array([bs for _, bs in self._temporal_window], dtype=np.float64)
        n = len(arr)
        split = n - TEMPORAL_WEEK_WINDOW

        old_mean = float(arr[:split].mean())
        recent_mean = float(arr[split:].mean())
        delta = recent_mean - old_mean

        drift = delta > 0.05
        return delta, drift


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_drift_detector_instance: Optional[DriftDetector] = None


def get_drift_detector() -> DriftDetector:
    """
    Return the module-level singleton DriftDetector instance.

    Raises:
        RuntimeError: If ``initialize_drift_detector()`` has not been called.

    Returns:
        The singleton DriftDetector instance.
    """
    if _drift_detector_instance is None:
        raise RuntimeError(
            "DriftDetector has not been initialised. "
            "Call initialize_drift_detector(session) during application startup."
        )
    return _drift_detector_instance


async def initialize_drift_detector(session: AsyncSession) -> DriftDetector:
    """
    Initialise (or re-initialise) the singleton DriftDetector.

    Attempts to load persisted state from the database. If no state is found,
    a fresh detector is created with default parameters.

    This should be called once during application startup, after the database
    connection is established.

    Args:
        session: An open SQLAlchemy async session.

    Returns:
        The initialised DriftDetector singleton.
    """
    global _drift_detector_instance

    detector = DriftDetector()
    loaded = await detector.load_state(session)

    _drift_detector_instance = detector

    logger.info(
        "drift_detector_initialized",
        loaded_from_db=loaded,
        total_observations=detector._total_observations,
    )
    return detector
