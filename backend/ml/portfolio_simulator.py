"""
portfolio_simulator.py — Validation Monte-Carlo d'un portefeuille (Phase 5).

Le simulateur historique (ml/monte_carlo.py) tire chaque pari en Bernoulli
INDÉPENDANT — incorrect : dans une course il n'y a qu'UNE arrivée, et les paris
sur des chevaux différents sont corrélés (si A gagne, B ne gagne pas).

Ici on simule des ARRIVÉES COMPLÈTES cohérentes via le modèle de Plackett-Luce
(échantillonné par l'astuce de Gumbel, vectorisé numpy), puis on règle le
portefeuille ENTIER contre chaque arrivée. On mesure alors la vraie couverture :
  - coverage     : P(profit du portefeuille > 0)
  - prob_ruine   : P(perte de toute la mise)
  - EV / ROI moyen, p5/p95, VaR/CVaR
  - field_entropy: incertitude du champ → combien de paris diversifiés viser

Payouts : paris simples gagnant/placé réglés à la cote RÉELLE ; combinés estimés
à la cote ÉQUITABLE issue des probas simulées (× rétention PMU). Ces estimations
de combinés sont des espérances de modèle, explicitement étiquetées — pas des
rapports réels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import structlog

log = structlog.get_logger()

RETENTION_PMU = 0.25   # prélèvement moyen PMU sur les combinés (cote équitable × (1-ret))
EPS = 1e-9


@dataclass
class CoverageResult:
    n_simulations: int = 0
    n_bets: int = 0
    total_stake: float = 0.0
    coverage: float = 0.0          # P(profit > 0)
    prob_ruine: float = 0.0        # P(profit <= -total_stake, i.e. tout perdu)
    mean_roi: float = 0.0
    p5_roi: float = 0.0
    p95_roi: float = 0.0
    var_95: float = 0.0            # perte au 5e percentile (positif)
    cvar_95: float = 0.0
    expected_profit: float = 0.0
    field_entropy: float = 0.0     # 0 (favori écrasant) → 1 (course ouverte)
    bet_win_probs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def field_entropy(win_probs: np.ndarray) -> float:
    """Entropie de Shannon normalisée du champ (0 = certitude, 1 = ouvert)."""
    p = np.asarray(win_probs, dtype=np.float64)
    p = p[p > 0]
    if p.size <= 1:
        return 0.0
    p = p / p.sum()
    h = -(p * np.log(p)).sum()
    return float(h / np.log(len(p)))


def sample_rankings(strengths: np.ndarray, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    """
    Échantillonne n_sims arrivées via Plackett-Luce (astuce de Gumbel).

    strengths : forces relatives (proba de victoire non normalisée), shape (k,).
    Retourne positions : (n_sims, k), positions[s, h] = place d'arrivée (1 = 1er).
    """
    k = len(strengths)
    s = np.asarray(strengths, dtype=np.float64).clip(min=EPS)
    log_s = np.log(s)
    # Gumbel(0,1) : -log(-log(U)). argsort décroissant de (log s + Gumbel) = tirage PL.
    u = rng.random((n_sims, k)).clip(EPS, 1 - EPS)
    gumbel = -np.log(-np.log(u))
    scores = log_s[np.newaxis, :] + gumbel
    order = np.argsort(-scores, axis=1)             # indices triés du 1er au dernier
    positions = np.empty((n_sims, k), dtype=np.int64)
    rows = np.arange(n_sims)[:, np.newaxis]
    positions[rows, order] = np.arange(1, k + 1)[np.newaxis, :]
    return positions


# Types simples réglés à la cote réelle (cf. ml/backtest).
_SIMPLE = {"gagnant", "simple gagnant", "place", "placé", "simple place", "simple placé"}


def _norm(t: str) -> str:
    import unicodedata
    x = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return " ".join(x.lower().split())


def _bet_win_mask(bet: dict, positions: np.ndarray, idx_of: dict, places: int) -> Optional[np.ndarray]:
    """Masque booléen (n_sims,) : le pari gagne-t-il dans chaque simulation ? None si non géré."""
    t = _norm(bet["type"])
    nums = bet["numeros"]
    cols = [idx_of.get(n) for n in nums]
    if any(c is None for c in cols):
        return None
    P = positions[:, cols]   # (n_sims, len(nums)) positions des chevaux sélectionnés

    if t in ("gagnant", "simple gagnant"):
        return P[:, 0] == 1
    if t in ("place", "placé", "simple place", "simple placé"):
        return P[:, 0] <= places
    if t == "couple gagnant":
        return (P <= 2).all(axis=1)
    if t == "couple ordre":
        return (P[:, 0] == 1) & (P[:, 1] == 2)
    if t == "couple place":
        return (P <= places).all(axis=1)
    if t in ("trio", "tierce", "tierce desordre"):
        return (P <= 3).all(axis=1)
    if t in ("tierce ordre", "trio ordre"):
        return (P == np.array([1, 2, 3])).all(axis=1)
    if t in ("2sur4", "deux sur quatre"):
        return (P <= 4).sum(axis=1) >= 2
    if t in ("quarte", "quarte desordre"):
        return (P <= 4).all(axis=1)
    if t == "quarte ordre":
        return (P == np.array([1, 2, 3, 4])).all(axis=1)
    if t in ("quinte", "quinte+", "quinte plus", "quinte desordre"):
        return (P <= 5).all(axis=1)
    if t == "quinte ordre":
        return (P == np.array([1, 2, 3, 4, 5])).all(axis=1)
    return None


def simulate_portfolio_coverage(
    bets: list,
    numeros: list,
    win_probs: list,
    *,
    nb_partants: Optional[int] = None,
    n_simulations: int = 10_000,
    seed: Optional[int] = None,
) -> CoverageResult:
    """
    Simule n arrivées cohérentes et règle le portefeuille entier contre chacune.

    bets       : [{type, numeros:[int], stake:float, cote:float}]
    numeros     : numéros des partants (ordre aligné avec win_probs)
    win_probs   : force/proba de victoire par partant (même ordre que numeros)
    """
    from ml.backtest import place_paid

    bets = [b for b in bets if b.get("stake", 0) > 0 and b.get("numeros")]
    res = CoverageResult(n_bets=len(bets))
    if not bets or not numeros:
        return res

    rng = np.random.default_rng(seed)
    idx_of = {num: i for i, num in enumerate(numeros)}
    strengths = np.asarray(win_probs, dtype=np.float64)
    res.field_entropy = round(field_entropy(strengths), 4)

    positions = sample_rankings(strengths, n_simulations, rng)
    places = place_paid(nb_partants if nb_partants is not None else len(numeros))

    stakes = np.array([float(b["stake"]) for b in bets])
    total_stake = float(stakes.sum())
    res.total_stake = round(total_stake, 2)
    res.n_simulations = n_simulations

    # 1er passage : masques de gain + proba de gain de chaque pari (modèle)
    masks = []
    valid_bets = []
    for b in bets:
        m = _bet_win_mask(b, positions, idx_of, places)
        if m is None:
            continue  # type non simulable → ignoré (pas d'invention)
        masks.append(m)
        valid_bets.append(b)
    if not masks:
        return res

    pnl = np.zeros(n_simulations, dtype=np.float64)
    for b, m in zip(valid_bets, masks):
        stake = float(b["stake"])
        p_win = float(m.mean())
        res.bet_win_probs[f"{b['type']}:{'-'.join(map(str, b['numeros']))}"] = round(p_win, 4)
        if _norm(b["type"]) in _SIMPLE and b.get("cote", 0) > 1.0:
            payout_mult = float(b["cote"])               # cote réelle
        else:
            fair = (1.0 / max(p_win, EPS)) * (1.0 - RETENTION_PMU)  # cote équitable estimée
            payout_mult = max(fair, 1.0)
        # gain net si gagné = stake*(mult-1), sinon -stake
        pnl += np.where(m, stake * (payout_mult - 1.0), -stake)

    roi = pnl / total_stake if total_stake > 0 else np.zeros_like(pnl)
    res.coverage = round(float((pnl > 0).mean()), 4)
    res.prob_ruine = round(float((pnl <= -total_stake + EPS).mean()), 4)
    res.mean_roi = round(float(roi.mean()), 4)
    res.p5_roi = round(float(np.percentile(roi, 5)), 4)
    res.p95_roi = round(float(np.percentile(roi, 95)), 4)
    res.var_95 = round(-min(0.0, float(np.percentile(roi, 5))), 4)
    tail = roi[roi <= np.percentile(roi, 5)]
    res.cvar_95 = round(-float(tail.mean()) if tail.size else res.var_95, 4)
    res.expected_profit = round(float(pnl.mean()), 2)
    return res


def recommend_bet_count(entropy: float, *, base: int = 2, span: int = 6) -> int:
    """
    Nombre de paris diversifiés recommandé selon l'incertitude du champ.
    Favori écrasant (entropie basse) → peu de paris. Course ouverte → davantage,
    pour couvrir l'éventail des surprises.
    """
    e = max(0.0, min(1.0, float(entropy)))
    return int(round(base + span * e))


def validate_diversification(
    result: CoverageResult,
    *,
    coverage_cible: float = 0.6,
    ev_min: float = 0.0,
) -> dict:
    """
    Le portefeuille atteint-il la couverture + l'EV visées ? Sinon, diagnostic.
    """
    ok_cov = result.coverage >= coverage_cible
    ok_ev = result.mean_roi > ev_min
    reco_paris = recommend_bet_count(result.field_entropy)
    suggestions = []
    if not ok_cov:
        suggestions.append(
            f"Couverture {result.coverage:.0%} < cible {coverage_cible:.0%} : "
            f"ajouter des paris (placé/couplé) — champ suggère ~{reco_paris} paris."
        )
    if not ok_ev:
        suggestions.append(
            f"ROI espéré {result.mean_roi:+.1%} ≤ {ev_min:.0%} : retirer les paris à EV négative."
        )
    if result.prob_ruine > 0.5:
        suggestions.append(
            f"Risque de tout perdre {result.prob_ruine:.0%} élevé : diversifier davantage."
        )
    return {
        "valide": ok_cov and ok_ev,
        "coverage_ok": ok_cov,
        "ev_ok": ok_ev,
        "reco_nb_paris": reco_paris,
        "suggestions": suggestions,
    }


def evaluate_portfolio(
    predictions: list,
    course_info: dict,
    *,
    bankroll: float = 100.0,
    profil: str = "equilibre",
    coverage_cible: float = 0.6,
    n_simulations: int = 10_000,
    seed: Optional[int] = None,
) -> dict:
    """
    Pipeline complet P5 : construit un portefeuille diversifié, simule sa couverture
    sur des arrivées cohérentes, et le valide.

    predictions : format BetPortfolioEngine ({numero, nom, proba_top3, proba_top1,
                  cote_pmu, ev_max, niveau_vb, ...}).
    Retourne {portfolio, coverage, validation}.
    """
    from ml.portfolio import get_portfolio_engine

    engine = get_portfolio_engine()
    portfolio = engine.build_portfolio(predictions, course_info, bankroll=bankroll, profil=profil)
    if not portfolio:
        return {"portfolio": {}, "coverage": CoverageResult().to_dict(), "validation": {"valide": False}}

    # Aplatir tous les paris de tous les scénarios
    bets = []
    cote_by_num = {p["numero"]: float(p.get("cote_pmu") or 0) for p in predictions}
    for scen in (portfolio.get("scenarios") or {}).values():
        if not scen:
            continue
        for pari in scen.get("paris", []):
            nums = [c["numero"] for c in pari.get("chevaux", []) if c.get("numero") is not None]
            mise = float(pari.get("mise") or 0)
            if not nums or mise <= 0:
                continue
            t = _norm(pari["type"])
            bets.append({
                "type": pari["type"], "numeros": nums, "stake": mise,
                "cote": cote_by_num.get(nums[0], 0.0) if t in _SIMPLE else 0.0,
            })

    numeros = [p["numero"] for p in predictions]
    win_probs = [float(p.get("proba_top1") or p.get("proba_top3") or 0.0) for p in predictions]

    cov = simulate_portfolio_coverage(
        bets, numeros, win_probs,
        nb_partants=course_info.get("nb_partants"),
        n_simulations=n_simulations, seed=seed,
    )
    validation = validate_diversification(cov, coverage_cible=coverage_cible)
    return {"portfolio": portfolio, "coverage": cov.to_dict(), "validation": validation}
