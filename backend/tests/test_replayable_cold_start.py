"""Une cohorte replayable trop petite ne remplace jamais un état validé."""

from unittest.mock import AsyncMock

import pytest

from ml import cote_calibration, isotonic_calibration
from ml import isotonic_calibration_top3, longshot_calibration, signal_performance
from ml.prediction_evaluation import evaluation_coverage


class _NoWriteSession:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("aucune écriture SQL autorisée sous le seuil")

    async def commit(self):
        raise AssertionError("aucun commit autorisé sous le seuil")


@pytest.mark.asyncio
async def test_isotonic_top1_preserve_l_etat_sous_le_seuil(monkeypatch):
    old = {"x": [0.1, 0.5], "y": [0.08, 0.4], "n_obs": 500}
    monkeypatch.setattr(isotonic_calibration, "_cached_curve", old)
    monkeypatch.setattr(
        isotonic_calibration, "_fetch_proba_outcomes",
        AsyncMock(return_value=[(0.2, 0, "plat:small")]),
    )

    out = await isotonic_calibration.compute_and_store(_NoWriteSession())

    assert out["status"] == "skipped_insufficient_replayable_data"
    assert isotonic_calibration._cached_curve is old


@pytest.mark.asyncio
async def test_isotonic_top3_preserve_l_etat_sous_le_seuil(monkeypatch):
    old = {"x": [0.2, 0.7], "y": [0.18, 0.65], "n_obs": 500}
    monkeypatch.setattr(isotonic_calibration_top3, "_cached_curve", old)
    monkeypatch.setattr(
        isotonic_calibration_top3, "_fetch_proba_top3_outcomes",
        AsyncMock(return_value=[(0.4, 1)]),
    )

    out = await isotonic_calibration_top3.compute_and_store(_NoWriteSession())

    assert out["status"] == "skipped_insufficient_replayable_data"
    assert isotonic_calibration_top3._cached_curve is old


@pytest.mark.asyncio
async def test_longshot_preserve_l_etat_sous_le_seuil(monkeypatch):
    old = {"[1 – 1.5)": 0.91}
    monkeypatch.setattr(longshot_calibration, "_cached_factors", old)
    monkeypatch.setattr(longshot_calibration, "fetch_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(longshot_calibration, "fetch_winners", AsyncMock(return_value={}))
    monkeypatch.setattr(
        longshot_calibration, "compute_bucket_stats",
        lambda *_: [{"bucket": "x", "n": 10, "reliable": False,
                     "proba_moy": None, "freq": None}],
    )

    out = await longshot_calibration.compute_and_store(_NoWriteSession())

    assert out is old
    assert longshot_calibration._cached_factors is old


@pytest.mark.asyncio
async def test_persistences_neutres_sont_interdites_sous_le_seuil():
    session = _NoWriteSession()
    assert await cote_calibration.persist_cote_calibration(
        session, {"n_total": 10, "buckets": []}
    ) is False
    assert await signal_performance.persist_ev_band_performance(
        session, {"n_total": 10, "bands": {}}
    ) is False


class _CoverageSession:
    """Sert la ligne d agregat puis la ligne des causes d absence."""

    def __init__(self):
        self.calls = 0

    async def execute(self, statement, *_args, **_kwargs):
        assert "is_replayable" in str(statement)
        self.calls += 1
        if self.calls == 1:
            return _Rows([(100, 35, 65, 20, 7, None, None, 13)])
        return _Rows([(65, 40, 15, 10, 13)])


@pytest.mark.asyncio
async def test_couverture_separe_replayable_et_legacy():
    out = await evaluation_coverage(_CoverageSession())
    assert out["coverage_pct"] == 35.0
    assert out["n_replayable"] == 35
    assert out["n_legacy"] == 65
    assert out["courses_replayable"] == 7
    # 20 courses au total, 13 contiennent au moins une ligne legacy.
    assert out["courses_fully_replayable"] == 7
    assert out["missing_causes"]["no_snapshot_row"] == 40


# ── Persistances qui écrasaient un état appris par une structure neutre ──────

class _RecordingSession:
    """Session qui journalise le SQL exécuté et sert des lignes à la demande."""

    def __init__(self, rows_for: dict | None = None):
        self.statements: list[str] = []
        self.committed = 0
        self._rows_for = rows_for or {}

    async def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        self.statements.append(sql)
        rows = []
        for needle, value in self._rows_for.items():
            if needle in sql:
                rows = value
                break
        return _Rows(rows)

    async def commit(self):
        self.committed += 1

    def wrote(self, table: str) -> bool:
        return any(f"INSERT INTO {table}" in s for s in self.statements)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchone(self):
        return self._rows[0] if self._rows else None


@pytest.mark.asyncio
async def test_signal_performance_ne_persiste_pas_sous_le_seuil():
    from ml.prediction_evaluation import MIN_SIGNAL_PERF_OBS

    assert await signal_performance.persist_signal_performance(
        _NoWriteSession(), {"signals": {}, "n_total": MIN_SIGNAL_PERF_OBS - 1}
    ) is False


@pytest.mark.asyncio
async def test_signal_performance_reprend_au_seuil():
    from ml.prediction_evaluation import MIN_SIGNAL_PERF_OBS

    session = _RecordingSession()
    ok = await signal_performance.persist_signal_performance(
        session, {"signals": {"elo": {"multiplier": 1.2}}, "n_total": MIN_SIGNAL_PERF_OBS}
    )
    assert ok is True
    assert session.wrote("signal_performance")
    assert session.committed == 1


@pytest.mark.asyncio
async def test_rapport_calibration_ne_persiste_pas_sous_le_seuil():
    from ml.prediction_evaluation import MIN_RAPPORT_CALIB_RUNS

    assert await signal_performance.persist_rapport_calibration(
        _NoWriteSession(), {"profils": {}, "global": {},
                            "n_runs": MIN_RAPPORT_CALIB_RUNS - 1}
    ) is False


@pytest.mark.asyncio
async def test_rapport_calibration_reprend_au_seuil():
    from ml.prediction_evaluation import MIN_RAPPORT_CALIB_RUNS

    session = _RecordingSession()
    ok = await signal_performance.persist_rapport_calibration(
        session, {"profils": {}, "global": {"Placé": {"facteur": 0.8}},
                  "n_runs": MIN_RAPPORT_CALIB_RUNS}
    )
    assert ok is True
    assert session.wrote("rapport_calibration")


@pytest.mark.asyncio
async def test_cote_et_ev_band_reprennent_au_seuil():
    from ml.prediction_evaluation import (
        MIN_COTE_REPLAYABLE_OBS, MIN_EV_BAND_REPLAYABLE_OBS,
    )

    s1 = _RecordingSession()
    assert await cote_calibration.persist_cote_calibration(
        s1, {"n_total": MIN_COTE_REPLAYABLE_OBS, "buckets": [{"lo": 1.0, "hi": 2.0}]}
    ) is True
    assert s1.wrote("cote_calibration")

    s2 = _RecordingSession()
    assert await signal_performance.persist_ev_band_performance(
        s2, {"n_total": MIN_EV_BAND_REPLAYABLE_OBS, "bands": {"0-5": {"n": 40}}}
    ) is True
    assert s2.wrote("ev_band_performance")


@pytest.mark.asyncio
async def test_profil_weights_preserve_l_etat_sous_le_seuil():
    """Une cohorte de plans émis amputée ne doit pas neutraliser les poids appris."""
    from ml import profil_learning
    from ml.prediction_evaluation import MIN_PROFIL_WEIGHTS_RUNS

    appris = {"profils": {"equilibre": {"type_weights": {"Placé": 1.4},
                                        "suppressed": ["Quinté+ Désordre|plat|med"]}},
              "n_total_runs": 900}
    session = _RecordingSession(rows_for={
        "FROM profil_run_log r": [],
        "FROM profil_learning_state": [(appris,)],
    })

    out = await profil_learning.compute_profil_weights(session)

    assert out["status"] == "skipped_insufficient_replayable_data"
    assert out["n_observed_runs"] == 0
    assert out["min_runs"] == MIN_PROFIL_WEIGHTS_RUNS
    # L'état appris est renvoyé intact et AUCUNE réécriture n'a eu lieu.
    assert out["profils"] == appris["profils"]
    assert not session.wrote("profil_learning_state")


@pytest.mark.asyncio
async def test_couverture_expose_les_causes_d_absence():
    from ml.prediction_evaluation import missing_snapshot_causes

    session = _RecordingSession(rows_for={
        "FROM prediction_evaluation pe": [(65, 40, 15, 10, 12)],
    })
    out = await missing_snapshot_causes(session)
    assert out == {"n_legacy": 65, "no_snapshot_row": 40, "post_course_only": 15,
                   "not_replayable": 10, "courses_legacy": 12}
    assert "is_replayable = false" in session.statements[0]
