"""
strategy_tuner.py — Optimisation des paramètres de stratégie sur le ROI backtesté.

Grid search sur les paramètres (fraction de Kelly, EV minimum, profil portefeuille)
en mesurant le ROI RÉEL via ml/backtest. Split chronologique train/test pour éviter
le surapprentissage : on choisit la meilleure config sur le train, on la VALIDE sur
le test (out-of-sample). Un écart train≫test est signalé comme surapprentissage.

But : ne plus régler les scénarios à l'intuition mais sur des données réelles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Optional

import structlog

log = structlog.get_logger()

# Seuil de fiabilité : en dessous, le ROI n'est pas significatif.
MIN_BETS_FIABLE = 20
# Écart train-test au-delà duquel on alerte sur le surapprentissage.
OVERFIT_GAP = 0.10


def make_grid(strategy: str) -> list:
    """Grille de configs à tester pour une stratégie."""
    if strategy == "portfolio":
        return [{"profil": p} for p in ("conservateur", "equilibre", "agressif")]
    # value_bet
    grid = []
    for kelly, ev_min in product((0.1, 0.25, 0.5), (0.0, 0.05, 0.1, 0.2)):
        grid.append({"kelly_fraction": kelly, "ev_min": ev_min})
    return grid


@dataclass
class TuneRow:
    config: dict
    roi: float
    profit: float
    nb_bets: int
    hit_rate: float
    max_drawdown: float
    fiable: bool

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def rank_configs(rows: list) -> list:
    """
    Classe les configs : fiables d'abord (nb_bets >= seuil), puis ROI décroissant.
    Les configs non fiables (trop peu de paris) sont reléguées.
    """
    return sorted(rows, key=lambda r: (r.fiable, r.roi), reverse=True)


def _result_to_row(config: dict, res) -> TuneRow:
    return TuneRow(
        config=config,
        roi=res.roi,
        profit=res.profit,
        nb_bets=res.nb_bets,
        hit_rate=res.hit_rate,
        max_drawdown=res.max_drawdown,
        fiable=res.nb_bets >= MIN_BETS_FIABLE,
    )


async def _ordered_course_ids(session, course_ids: list) -> list:
    """Ordonne les course_ids par date_heure croissante."""
    from sqlalchemy import select
    from db.models import Course
    r = await session.execute(
        select(Course.course_id).where(Course.course_id.in_(course_ids)).order_by(Course.date_heure)
    )
    return [row[0] for row in r.fetchall()]


async def tune_strategy(
    session,
    course_ids: list,
    *,
    strategy: str = "value_bet",
    grid: Optional[list] = None,
    bankroll: float = 100.0,
    train_frac: float = 0.7,
) -> dict:
    """
    Grid search du ROI backtesté avec validation out-of-sample.

    Retourne {strategy, train_n, test_n, results (triés, sur train), best}.
    `best` inclut roi_train, roi_test et un drapeau de surapprentissage.
    """
    from ml.backtest import run_backtest, value_bet_strategy, portfolio_strategy

    strat_fn = portfolio_strategy if strategy == "portfolio" else value_bet_strategy
    grid = grid or make_grid(strategy)

    ordered = await _ordered_course_ids(session, course_ids)
    if len(ordered) < 4:
        return {"strategy": strategy, "error": "Pas assez de courses pour tuner (min 4)."}

    cut = max(1, int(len(ordered) * train_frac))
    train_ids, test_ids = ordered[:cut], ordered[cut:]

    rows = []
    for config in grid:
        res = await run_backtest(
            session, train_ids, strategy=strat_fn, bankroll=bankroll, strategy_kwargs=config,
        )
        rows.append(_result_to_row(config, res))

    ranked = rank_configs(rows)
    best_row = ranked[0] if ranked else None

    best = None
    if best_row is not None:
        # Validation out-of-sample
        test_res = await run_backtest(
            session, test_ids, strategy=strat_fn, bankroll=bankroll,
            strategy_kwargs=best_row.config,
        )
        gap = best_row.roi - test_res.roi
        best = {
            "config": best_row.config,
            "roi_train": best_row.roi,
            "roi_test": test_res.roi,
            "profit_test": test_res.profit,
            "nb_bets_test": test_res.nb_bets,
            "overfit_gap": round(gap, 4),
            "surapprentissage": gap > OVERFIT_GAP,
            "fiable": best_row.fiable,
        }

    return {
        "strategy": strategy,
        "train_n": len(train_ids),
        "test_n": len(test_ids),
        "results": [r.to_dict() for r in ranked],
        "best": best,
    }
