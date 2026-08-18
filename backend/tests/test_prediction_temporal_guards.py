"""Les calibrateurs ne peuvent jamais apprendre sur une prédiction post-course."""

import pytest

from ml import calibration_eval, clv_monitor, cote_calibration
from ml import isotonic_calibration, isotonic_calibration_top3
from scripts import calibration_longshots
from scripts import backtest_mise


class _EmptyResult:
    def fetchall(self):
        return []

    def first(self):
        return None


class _RecordingSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, *_args, **_kwargs):
        self.statements.append(str(statement))
        return _EmptyResult()


def _assert_pre_course_guard(statement: str):
    normalized = " ".join(statement.lower().split())
    assert "prediction_evaluation" in normalized
    assert "join courses c" in normalized
    assert "created_at is not null" in normalized
    assert "created_at < c.date_heure" in normalized
    assert "is_replayable = true" in normalized


@pytest.mark.asyncio
async def test_calibration_eval_is_always_pre_course():
    session = _RecordingSession()
    await calibration_eval._fetch_proba_outcomes(session)
    _assert_pre_course_guard(session.statements[0])


@pytest.mark.asyncio
async def test_longshot_calibration_is_always_pre_course():
    session = _RecordingSession()
    await calibration_longshots.fetch_rows(session, "cote_pmu")
    _assert_pre_course_guard(session.statements[0])


@pytest.mark.asyncio
async def test_cote_calibration_is_always_pre_course():
    session = _RecordingSession()
    await cote_calibration.compute_cote_calibration(session)
    _assert_pre_course_guard(session.statements[0])
    assert "coalesce(pr.cote_figee, pa.cote_pmu)" in " ".join(
        session.statements[0].lower().split()
    )


@pytest.mark.asyncio
async def test_isotonic_top1_is_always_pre_course():
    session = _RecordingSession()
    await isotonic_calibration._fetch_proba_outcomes(session)
    _assert_pre_course_guard(session.statements[0])


@pytest.mark.asyncio
async def test_isotonic_top3_is_always_pre_course():
    session = _RecordingSession()
    await isotonic_calibration_top3._fetch_proba_top3_outcomes(session)
    _assert_pre_course_guard(session.statements[0])


@pytest.mark.asyncio
async def test_clv_and_contrarian_segment_are_always_pre_course():
    session = _RecordingSession()
    await clv_monitor.compute_clv_monitor(session)
    assert len(session.statements) == 2
    for statement in session.statements:
        _assert_pre_course_guard(statement)


@pytest.mark.asyncio
async def test_plan_de_mise_backtest_exige_une_cohorte_replayable():
    session = _RecordingSession()
    assert await backtest_mise._load(session, 20) == []
    normalized = " ".join(session.statements[0].lower().split())
    assert "prediction_evaluation" in normalized
    assert "is_replayable = true" in normalized
