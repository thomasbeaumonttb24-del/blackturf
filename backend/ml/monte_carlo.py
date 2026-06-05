"""
Monte Carlo simulation engine for horse racing bet portfolio validation.

BlackTurf project — pure computation module, no DB access.
All heavy work is vectorized via numpy for performance.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PortfolioMetrics:
    """
    Aggregated statistics returned by MonteCarloSimulator.simulate_portfolio.

    Fields
    ------
    mean_roi : float
        Mean return on investment across all simulations.
        ROI = (total_return - total_stake) / total_stake
    median_roi : float
        Median ROI across all simulations.
    p5_roi : float
        5th-percentile ROI (worst-case band).
    p95_roi : float
        95th-percentile ROI (best-case band).
    max_drawdown : float
        Mean maximum drawdown across all simulations.
        Drawdown_t = (peak_t - value_t) / peak_t
    win_rate_portfolio : float
        Fraction of simulations where final PnL > 0.
    sharpe_ratio : float
        Sharpe ratio of per-simulation ROI distribution.
        Sharpe = E[ROI] / std(ROI)  (risk-free rate assumed 0)
    var_95 : float
        Value at Risk at 95 % confidence level (loss expressed as positive).
    cvar_95 : float
        Conditional VaR (Expected Shortfall) at 95 % — mean of worst 5 % outcomes.
    n_simulations : int
        Number of Monte Carlo paths used.
    n_bets : int
        Number of scenario bets in the portfolio.
    total_stake : float
        Total capital deployed across all bets in one simulation path.
    """

    mean_roi: float = 0.0
    median_roi: float = 0.0
    p5_roi: float = 0.0
    p95_roi: float = 0.0
    max_drawdown: float = 0.0
    win_rate_portfolio: float = 0.0
    sharpe_ratio: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    n_simulations: int = 0
    n_bets: int = 0
    total_stake: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Main simulator
# ---------------------------------------------------------------------------


class MonteCarloSimulator:
    """
    Vectorized Monte Carlo simulation engine for bet portfolio validation.

    All probabilistic draws are done in bulk via numpy, so the hot path for
    simulate_portfolio runs in O(n_simulations * n_bets) without any Python
    loops over individual paths.

    Parameters
    ----------
    seed : int | None
        Optional random seed for reproducibility.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._rng = np.random.default_rng(seed)
        self._log = logger.bind(module="MonteCarloSimulator")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate_portfolio(
        self,
        portfolio: dict,
        n_simulations: int = 10_000,
    ) -> dict:
        """
        Run N Monte Carlo paths over a bet portfolio and return aggregated stats.

        The portfolio format is the output of BetPortfolioEngine.  The method
        expects the following keys (extra keys are ignored):

        portfolio = {
            "bets": [
                {
                    "proba_top3": float,   # estimated win probability in [0, 1]
                    "cote":       float,   # decimal odds (e.g. 4.5)
                    "mise":       float,   # stake in euros / units
                },
                ...
            ]
        }

        Algorithm
        ---------
        For each of the N simulations:
          1. For each bet i, draw Bernoulli(p_i) to decide win/loss.
          2. PnL_i = mise_i * (cote_i - 1)  if win
                   = -mise_i               if loss
          3. Cumulative PnL path = cumsum(PnL_i  for i in bets)
          4. Max drawdown = max( (peak - trough) / peak )  over the path.

        Metrics are then aggregated across all N paths.

        Sharpe ratio:  S = E[ROI] / σ(ROI),  risk-free rate = 0.

        VaR_95  = -percentile_5(ROI_distribution)      (loss expressed positive)
        CVaR_95 = -mean( ROI | ROI < -VaR_95 )         (Expected Shortfall)

        Parameters
        ----------
        portfolio : dict
            BetPortfolioEngine output dict containing a "bets" list.
        n_simulations : int
            Number of Monte Carlo paths.  Default 10 000.

        Returns
        -------
        dict
            Serialised PortfolioMetrics (all fields as plain Python scalars).

        Raises
        ------
        ValueError
            If the portfolio contains no valid bets.
        """
        bets: list[dict] = portfolio.get("bets", [])
        if not bets:
            raise ValueError("Portfolio contains no bets to simulate.")

        probas = np.array([b["proba_top3"] for b in bets], dtype=np.float64)
        cotes  = np.array([b["cote"]       for b in bets], dtype=np.float64)
        mises  = np.array([b["mise"]       for b in bets], dtype=np.float64)

        n_bets      = len(bets)
        total_stake = float(mises.sum())

        self._log.info(
            "simulate_portfolio.start",
            n_bets=n_bets,
            n_simulations=n_simulations,
            total_stake=total_stake,
        )

        # Shape: (n_simulations, n_bets)
        # Each cell is 1.0 if bet i wins in simulation s, else 0.0
        outcomes = (
            self._rng.random((n_simulations, n_bets)) < probas[np.newaxis, :]
        ).astype(np.float64)

        # PnL per bet per simulation
        # win  ->  mise * (cote - 1)
        # loss -> -mise
        win_pnl  = mises * (cotes - 1.0)   # shape (n_bets,)
        loss_pnl = -mises                   # shape (n_bets,)

        pnl_matrix = (
            outcomes * win_pnl[np.newaxis, :]
            + (1.0 - outcomes) * loss_pnl[np.newaxis, :]
        )  # shape (n_simulations, n_bets)

        # Total PnL per simulation path
        total_pnl = pnl_matrix.sum(axis=1)  # shape (n_simulations,)

        # ROI per simulation
        roi = total_pnl / total_stake  # shape (n_simulations,)

        # Max drawdown per simulation  ----------------------------------------
        # Cumulative PnL path within each simulation
        cum_pnl = np.cumsum(pnl_matrix, axis=1)  # (n_simulations, n_bets)

        # We work on the equity curve: start at 0, grow by PnL
        # Peak at each step
        running_max = np.maximum.accumulate(cum_pnl, axis=1)
        drawdown    = (running_max - cum_pnl) / (total_stake + 1e-10)
        max_dd_per_sim = drawdown.max(axis=1)  # shape (n_simulations,)
        mean_max_dd    = float(max_dd_per_sim.mean())

        # Sharpe ratio -----------------------------------------------------------
        roi_mean = float(roi.mean())
        roi_std  = float(roi.std())
        sharpe   = roi_mean / roi_std if roi_std > 1e-10 else 0.0

        # VaR and CVaR -----------------------------------------------------------
        p5 = float(np.percentile(roi, 5))
        var_95  = -p5  # express as positive loss
        tail    = roi[roi < p5]
        cvar_95 = float(-tail.mean()) if tail.size > 0 else var_95

        metrics = PortfolioMetrics(
            mean_roi            = roi_mean,
            median_roi          = float(np.median(roi)),
            p5_roi              = p5,
            p95_roi             = float(np.percentile(roi, 95)),
            max_drawdown        = mean_max_dd,
            win_rate_portfolio  = float((total_pnl > 0).mean()),
            sharpe_ratio        = sharpe,
            var_95              = var_95,
            cvar_95             = cvar_95,
            n_simulations       = n_simulations,
            n_bets              = n_bets,
            total_stake         = total_stake,
        )

        self._log.info(
            "simulate_portfolio.done",
            mean_roi=round(metrics.mean_roi, 4),
            sharpe=round(metrics.sharpe_ratio, 4),
            win_rate=round(metrics.win_rate_portfolio, 4),
        )

        return metrics.to_dict()

    # ------------------------------------------------------------------

    def simulate_single_bet(
        self,
        proba: float,
        cote: float,
        mise: float,
        n: int = 10_000,
    ) -> dict:
        """
        Simulate a single independent bet N times and return statistics.

        Model
        -----
        Return_i = mise * (cote - 1)   with probability p
                 = -mise               with probability (1 - p)

        Expected value: E[R] = p * mise * (cote - 1) - (1 - p) * mise
                             = mise * (p * cote - 1)

        Kelly fraction: f* = (p * cote - 1) / (cote - 1)

        Breakeven probability: p_be = 1 / cote

        Parameters
        ----------
        proba : float
            Estimated win probability, in (0, 1).
        cote : float
            Decimal odds (must be > 1).
        mise : float
            Stake per bet.
        n : int
            Number of simulated bets.

        Returns
        -------
        dict with keys:
            mean_return     — average monetary return
            std_return      — standard deviation of return
            win_rate        — empirical win frequency
            breakeven_proba — minimum probability for positive EV
            kelly_fraction  — full Kelly criterion fraction of bankroll
        """
        if not (0.0 < proba < 1.0):
            raise ValueError(f"proba must be in (0, 1), got {proba}")
        if cote <= 1.0:
            raise ValueError(f"cote must be > 1, got {cote}")
        if mise <= 0.0:
            raise ValueError(f"mise must be > 0, got {mise}")

        wins    = self._rng.random(n) < proba
        returns = np.where(wins, mise * (cote - 1.0), -mise)

        kelly_fraction   = (proba * cote - 1.0) / (cote - 1.0)
        breakeven_proba  = 1.0 / cote

        result = {
            "mean_return"    : float(returns.mean()),
            "std_return"     : float(returns.std()),
            "win_rate"       : float(wins.mean()),
            "breakeven_proba": breakeven_proba,
            "kelly_fraction" : max(0.0, kelly_fraction),
        }

        self._log.info("simulate_single_bet.done", **{k: round(v, 4) for k, v in result.items()})
        return result

    # ------------------------------------------------------------------

    def estimate_ruin_probability(
        self,
        bankroll: float,
        mise_par_course: float,
        win_rate: float,
        cote_moyenne: float,
        n_courses: int = 100,
    ) -> float:
        """
        Estimate the probability of gambler's ruin over a fixed number of races.

        Definition
        ----------
        Ruin occurs when the bankroll drops to <= 0 at any point in the sequence
        of n_courses bets.

        Each race: bet mise_par_course at decimal odds cote_moyenne.
          Bankroll_t+1 = Bankroll_t + mise_par_course * (cote_moyenne - 1)  if win
                       = Bankroll_t - mise_par_course                       if loss

        The simulation uses N = 10 000 independent paths and returns the fraction
        of paths that reach ruin.

        Parameters
        ----------
        bankroll : float
            Starting capital.
        mise_par_course : float
            Fixed stake per race.
        win_rate : float
            Probability of winning each race, in (0, 1).
        cote_moyenne : float
            Average decimal odds.
        n_courses : int
            Number of races to simulate.

        Returns
        -------
        float
            Estimated ruin probability in [0, 1].
        """
        n_paths = 10_000

        wins_per_race = self._rng.random((n_paths, n_courses)) < win_rate
        pnl_per_race  = np.where(
            wins_per_race,
            mise_par_course * (cote_moyenne - 1.0),
            -mise_par_course,
        )

        # Equity curves: shape (n_paths, n_courses)
        equity = bankroll + np.cumsum(pnl_per_race, axis=1)

        # Ruin if equity touches <= 0 at any step
        ruined          = (equity <= 0.0).any(axis=1)
        ruin_probability = float(ruined.mean())

        self._log.info(
            "estimate_ruin_probability.done",
            ruin_probability=round(ruin_probability, 4),
            n_courses=n_courses,
        )
        return ruin_probability

    # ------------------------------------------------------------------

    def optimize_kelly_fraction(
        self,
        proba: float,
        cote: float,
        risk_tolerance: float = 0.5,
    ) -> dict:
        """
        Compute Kelly-based staking fractions and their expected performance.

        Kelly Criterion
        ---------------
        The full Kelly fraction maximises the expected logarithm of wealth:

            f* = (p * b - q) / b

        where:
            p = win probability
            q = 1 - p
            b = net odds = cote - 1

        Fractional Kelly variants reduce variance at the cost of growth rate:
            half_kelly    = f* / 2
            quarter_kelly = f* / 4
            optimal       = f* * risk_tolerance   (caller-defined blend)

        For each fraction f, the one-race expected ROI and a rough max-drawdown
        estimate (via simulation of 1 000 paths × 200 races) are provided.

        Parameters
        ----------
        proba : float
            Estimated win probability, in (0, 1).
        cote : float
            Decimal odds (must be > 1).
        risk_tolerance : float
            Multiplier applied to full Kelly to derive the optimal fraction.
            0.5 = half Kelly, 0.25 = quarter Kelly, etc.

        Returns
        -------
        dict with keys:
            full_kelly, half_kelly, quarter_kelly, optimal_fraction
            Each maps to a nested dict:
                fraction        — the f value
                expected_roi    — E[ROI] per bet at that fraction
                max_drawdown_estimate — estimated mean max drawdown over 200 bets
        """
        if not (0.0 < proba < 1.0):
            raise ValueError(f"proba must be in (0, 1), got {proba}")
        if cote <= 1.0:
            raise ValueError(f"cote must be > 1, got {cote}")
        if not (0.0 < risk_tolerance <= 1.0):
            raise ValueError(f"risk_tolerance must be in (0, 1], got {risk_tolerance}")

        b = cote - 1.0
        q = 1.0 - proba

        full_kelly_frac = max(0.0, (proba * b - q) / b)

        fractions = {
            "full_kelly"      : full_kelly_frac,
            "half_kelly"      : full_kelly_frac / 2.0,
            "quarter_kelly"   : full_kelly_frac / 4.0,
            "optimal_fraction": full_kelly_frac * risk_tolerance,
        }

        n_paths  = 1_000
        n_races  = 200
        bankroll = 1.0  # normalised

        wins_matrix = self._rng.random((n_paths, n_races)) < proba  # (paths, races)

        result: dict[str, Any] = {}

        for name, f in fractions.items():
            if f <= 0.0:
                result[name] = {
                    "fraction"             : 0.0,
                    "expected_roi"         : 0.0,
                    "max_drawdown_estimate": 0.0,
                }
                continue

            mise = f  # fraction of unit bankroll

            pnl_matrix = np.where(wins_matrix, mise * b, -mise)   # (paths, races)

            # Expected ROI per single bet
            expected_roi = float(proba * b - q) * f  # = f * (p*b - q)

            # Equity paths for drawdown estimate
            equity = bankroll + np.cumsum(pnl_matrix, axis=1)  # (paths, races)
            running_peak = np.maximum.accumulate(equity, axis=1)
            drawdown     = (running_peak - equity) / (running_peak + 1e-10)
            mean_max_dd  = float(drawdown.max(axis=1).mean())

            result[name] = {
                "fraction"             : round(f, 6),
                "expected_roi"         : round(expected_roi, 6),
                "max_drawdown_estimate": round(mean_max_dd, 6),
            }

        self._log.info(
            "optimize_kelly_fraction.done",
            full_kelly=round(full_kelly_frac, 4),
            optimal=round(fractions["optimal_fraction"], 4),
        )

        return result
