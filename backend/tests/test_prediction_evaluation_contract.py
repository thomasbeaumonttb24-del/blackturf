import os
from pathlib import Path


_BACKEND_OVERRIDE = os.environ.get("BLACKTURF_BACKEND_DIR")
BACKEND = Path(_BACKEND_OVERRIDE) if _BACKEND_OVERRIDE else Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "db/migrations/versions/0030_prediction_evaluation_view.py"


def test_view_prefers_latest_replayable_pre_course_snapshot():
    sql = " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())
    assert "distinct on (ps.participation_id)" in sql
    assert "ps.is_pre_course = true and ps.is_replayable = true" in sql
    assert "order by ps.participation_id, ps.observed_at desc" in sql


def test_view_legacy_fallback_is_explicitly_not_replayable():
    sql = " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())
    assert "'legacy_mutable_row'::varchar(30)" in sql
    assert "false as is_snapshot" in sql
    assert "false as is_replayable" in sql
    assert "where not exists" in sql


def test_historical_learning_readers_use_canonical_view():
    readers = [
        "ml/calibration_eval.py",
        "ml/isotonic_calibration.py",
        "ml/isotonic_calibration_top3.py",
        "ml/cote_calibration.py",
        "ml/clv_monitor.py",
        "ml/signal_performance.py",
        "ml/backtest.py",
        "scripts/calibration_longshots.py",
        "scripts/backtest_mise.py",
    ]
    for relative in readers:
        source = (BACKEND / relative).read_text(encoding="utf-8").lower()
        assert "prediction_evaluation" in source, relative


def test_learning_readers_filter_out_the_legacy_cohort():
    """Aucun apprentissage causal ne doit lire une ligne is_replayable=false.

    Contrôle statique : toute requête d'apprentissage sur le read-model doit
    porter le filtre explicite. Un ajout de lecteur sans filtre casse ce test.
    """
    readers = [
        "ml/calibration_eval.py",
        "ml/isotonic_calibration.py",
        "ml/isotonic_calibration_top3.py",
        "ml/cote_calibration.py",
        "ml/clv_monitor.py",
        "ml/signal_performance.py",
        "ml/meta_learner.py",
        "ml/post_race_analyzer.py",
        "ml/backtest.py",
        "scripts/calibration_longshots.py",
        "scripts/backtest_mise.py",
    ]
    for relative in readers:
        source = " ".join((BACKEND / relative).read_text(encoding="utf-8").lower().split())
        assert "is_replayable = true" in source, relative


def test_cold_start_thresholds_are_declared_centrally():
    """Chaque persistance remplaçant un état appris a un seuil documenté."""
    source = (BACKEND / "ml/prediction_evaluation.py").read_text(encoding="utf-8")
    for name in (
        "MIN_LONGSHOT_REPLAYABLE_OBS",
        "MIN_COTE_REPLAYABLE_OBS",
        "MIN_COTE_BUCKET_OBS",
        "MIN_EV_BAND_REPLAYABLE_OBS",
        "MIN_EV_BAND_OBS",
        "MIN_SIGNAL_PERF_OBS",
        "MIN_PROFIL_WEIGHTS_RUNS",
        "MIN_RAPPORT_CALIB_RUNS",
    ):
        assert f"{name} = " in source, name


def test_singleton_persistences_are_guarded():
    """Les upserts singleton d'état appris renvoient un booléen de garde."""
    guarded = {
        "ml/signal_performance.py": [
            "async def persist_signal_performance(session: AsyncSession, perf: dict) -> bool:",
            "async def persist_ev_band_performance(session: AsyncSession, perf: dict) -> bool:",
            "async def persist_rapport_calibration(session: AsyncSession, perf: dict) -> bool:",
        ],
        "ml/cote_calibration.py": [
            "async def persist_cote_calibration(session: AsyncSession, calib: dict) -> bool:",
        ],
    }
    for relative, signatures in guarded.items():
        source = (BACKEND / relative).read_text(encoding="utf-8")
        for signature in signatures:
            assert signature in source, f"{relative}: {signature}"
