"""
Tests tuner de stratégie (optimisation ROI backtesté + validation out-of-sample).
"""
from datetime import datetime, timezone

import pytest

from db.models import Course, Participation, Prediction, Resultat
from ml.strategy_tuner import (
    make_grid, rank_configs, tune_strategy, TuneRow, MIN_BETS_FIABLE,
)


def test_make_grid_value_bet():
    g = make_grid("value_bet")
    assert len(g) == 12   # 3 kelly × 4 ev_min
    assert all("kelly_fraction" in c and "ev_min" in c for c in g)


def test_make_grid_portfolio():
    g = make_grid("portfolio")
    assert {c["profil"] for c in g} == {"conservateur", "equilibre", "agressif"}


def test_rank_configs_fiables_dabord():
    rows = [
        TuneRow({"a": 1}, roi=0.5, profit=10, nb_bets=5, hit_rate=0.5, max_drawdown=2, fiable=False),
        TuneRow({"a": 2}, roi=0.1, profit=5, nb_bets=50, hit_rate=0.4, max_drawdown=3, fiable=True),
        TuneRow({"a": 3}, roi=0.3, profit=8, nb_bets=40, hit_rate=0.45, max_drawdown=2, fiable=True),
    ]
    ranked = rank_configs(rows)
    # Fiables d'abord, puis ROI décroissant → config 3 (0.3) avant 2 (0.1), non-fiable en dernier
    assert ranked[0].config == {"a": 3}
    assert ranked[1].config == {"a": 2}
    assert ranked[-1].config == {"a": 1}


async def _seed(db, cid, day, win, cote=3.0, proba=0.5):
    db.add(Course(
        course_id=cid, reunion_id="R1", numero=1, nom="T",
        date_heure=datetime(2026, 1, day, 13, 0, tzinfo=timezone.utc),
        hippodrome_nom="Pau", discipline="Plat", distance=2000,
        nb_partants=10, statut="termine",
    ))
    db.add(Participation(participation_id=f"p-{cid}", course_id=cid,
                         cheval_id=f"ch-{cid}", numero=1, cote_pmu=cote))
    db.add(Prediction(prediction_id=f"pr-{cid}", participation_id=f"p-{cid}",
                      course_id=cid, proba_top1=proba / 2, proba_top3=proba, rang_predit=1))
    autre = 1 if not win else 2
    db.add(Resultat(course_id=cid, classement=[
        {"numero": 1, "position": 1 if win else 5},
        {"numero": 2, "position": autre},
    ]))


@pytest.mark.asyncio
async def test_tune_strategy_value_bet(db):
    # 8 courses, le favori (#1) gagne souvent → config EV+Kelly doit ressortir.
    for i in range(8):
        await _seed(db, f"C{i}", day=i + 1, win=(i % 3 != 0))  # ~2/3 gagnent
    await db.commit()

    out = await tune_strategy(
        db, [f"C{i}" for i in range(8)], strategy="value_bet",
        grid=[{"kelly_fraction": 0.25, "ev_min": 0.0},
              {"kelly_fraction": 0.5, "ev_min": 0.1}],
    )
    assert out["strategy"] == "value_bet"
    assert out["train_n"] + out["test_n"] == 8
    assert len(out["results"]) == 2
    assert out["best"] is not None
    assert "roi_train" in out["best"] and "roi_test" in out["best"]
    assert "surapprentissage" in out["best"]


@pytest.mark.asyncio
async def test_tune_strategy_trop_peu_de_courses(db):
    await _seed(db, "X1", 1, win=True)
    await _seed(db, "X2", 2, win=False)
    await db.commit()
    out = await tune_strategy(db, ["X1", "X2"], strategy="value_bet")
    assert "error" in out
