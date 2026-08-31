from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import create_engine, inspect

from db.models import Base
from ml.prediction_snapshots import (
    build_snapshot_values,
    canonical_json,
    is_missing_snapshot_table,
)


def _values(features: dict, *, start_delta: timedelta = timedelta(minutes=10)):
    observed = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    return build_snapshot_values(
        prediction_run_id="run-1",
        snapshot_id="snap-1",
        prediction_id="pred-1",
        participation_id="part-1",
        course_id="course-1",
        model_version_id="model-1",
        features=features,
        observed_at=observed,
        course_start_at=observed + start_delta,
        proba_top1=0.2,
        proba_top3=0.5,
        proba_top1_raw=0.22,
        proba_top3_raw=0.48,
        proba_top1_low=0.15,
        proba_top1_high=0.25,
        rang_predit=1,
        confidence_score=72.0,
        cote_figee=4.5,
    )


def test_snapshot_is_a_deep_frozen_copy_with_stable_hashes():
    source = {"b": np.int64(2), "nested": {"x": [1, 2]}, "a": 1.5}
    first = _values(source)
    second = _values({"a": 1.5, "nested": {"x": [1, 2]}, "b": 2})

    source["nested"]["x"].append(3)

    assert first["features"] == {"a": 1.5, "b": 2, "nested": {"x": [1, 2]}}
    assert first["features_hash"] == second["features_hash"]
    assert first["feature_schema_hash"] == second["feature_schema_hash"]
    assert first["is_pre_course"] is True
    assert first["odds_observed_at"] == first["observed_at"]


def test_snapshot_marks_post_start_state_as_not_pre_course():
    values = _values({"cote_pmu": 3.2}, start_delta=timedelta(minutes=-1))
    assert values["is_pre_course"] is False


def test_canonical_json_normalizes_non_finite_values_for_replay():
    assert canonical_json({"nan": float("nan"), "inf": np.float64("inf")}) == (
        '{"inf":null,"nan":null}'
    )


def test_only_targeted_postgres_undefined_table_is_compatibly_ignored():
    class DriverError(Exception):
        sqlstate = "42P01"

    missing_target = RuntimeError('relation "prediction_snapshots" does not exist')
    missing_target.orig = DriverError()
    missing_other = RuntimeError('relation "predictions" does not exist')
    missing_other.orig = DriverError()

    assert is_missing_snapshot_table(missing_target) is True
    assert is_missing_snapshot_table(missing_other) is False


def test_snapshot_model_is_creatable_for_sqlite_test_compatibility():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "prediction_snapshots" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("prediction_snapshots")}
    assert {"features_hash", "observed_at", "is_pre_course", "is_replayable"} <= columns
    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("prediction_snapshots")
    }
    assert ("prediction_run_id", "participation_id") in unique_columns
    engine.dispose()
