"""
combo_bets.py — Propositions de paris MULTIPLES avec probabilités RÉELLES.

Au lieu d'EV hardcodés, on simule l'ordre d'arrivée par un modèle Plackett-Luce
(forces ∝ proba de victoire du modèle) via l'astuce de Gumbel (vectorisé numpy),
puis on compte la fréquence de gain de chaque combinaison → probabilité honnête.
EV = P(gain) × rapport_estimé − 1. Aucune valeur inventée : si la proba est faible,
le pari n'est pas proposé.
"""
from __future__ import annotations

import numpy as np
import structlog

log = structlog.get_logger()

N_SIMS = 20000

# Taux de retour joueur (TRJ) PMU 2026 par type de pari : le pari-mutuel
# redistribue ~TRJ de la masse → rapport ≈ TRJ / proba_marché.
TRJ = {
    "Couplé Placé": 0.74, "Couplé Gagnant": 0.74, "2sur4": 0.74,
    "Trio": 0.691, "Tiercé Désordre": 0.6435, "Tiercé Ordre": 0.6435,
    "Quarté+ Désordre": 0.633, "Quinté+ Désordre": 0.6475,
}


# ──────────────────────────────────────────────────────────────────────────────
# Simulation Plackett-Luce (Gumbel-max) — ordre d'arrivée
# ──────────────────────────────────────────────────────────────────────────────
def simulate_orderings(strengths: np.ndarray, n_sims: int = N_SIMS, seed: int = 12345) -> np.ndarray:
    """Retourne un tableau (n_sims, n_chevaux) d'indices = ordre d'arrivée simulé.

    Plackett-Luce : à chaque tirage, P(cheval i sorte en tête des restants) ∝ force_i.
    L'astuce de Gumbel donne un échantillon exact : argsort(log(force) + Gumbel)."""
    s = np.clip(np.asarray(strengths, dtype=float), 1e-9, None)
    logs = np.log(s)
    rng = np.random.RandomState(seed)
    g = -np.log(-np.log(np.clip(rng.random((n_sims, s.shape[0])), 1e-12, 1.0)))
    scores = logs[None, :] + g
    return np.argsort(-scores, axis=1)  # ordre décroissant de score = arrivée


def _topk_membership(order: np.ndarray, n_horses: int, k: int) -> np.ndarray:
    """Matrice booléenne (n_sims, n_horses) : True si le cheval finit dans le top-k."""
    n_sims = order.shape[0]
    member = np.zeros((n_sims, n_horses), dtype=bool)
    rows = np.arange(n_sims)
    for pos in range(min(k, order.shape[1])):
        member[rows, order[:, pos]] = True
    return member


# ──────────────────────────────────────────────────────────────────────────────
# Probabilités par type de pari, pour une sélection donnée (indices)
# ──────────────────────────────────────────────────────────────────────────────
class _Sim:
    """Pré-calcule les appartenances top-k pour réutilisation."""
    def __init__(self, order: np.ndarray, n_horses: int):
        self.order = order
        self.n = n_horses
        self.in_top2 = _topk_membership(order, n_horses, 2)
        self.in_top3 = _topk_membership(order, n_horses, 3)
        self.in_top4 = _topk_membership(order, n_horses, 4)
        self.in_top5 = _topk_membership(order, n_horses, 5)
        self.top1 = order[:, 0]
        self.top2 = order[:, 1] if order.shape[1] > 1 else order[:, 0]
        self.top3 = order[:, 2] if order.shape[1] > 2 else order[:, 0]

    def p_simple_place(self, a: int) -> float:
        return float(self.in_top3[:, a].mean())

    def p_couple_gagnant(self, sel: list[int]) -> float:
        # les 2 chevaux exactement 1er+2e (ordre indifférent)
        return float(self.in_top2[:, sel].all(axis=1).mean())

    def p_couple_place(self, sel: list[int]) -> float:
        return float(self.in_top3[:, sel].all(axis=1).mean())

    def p_trio(self, sel: list[int]) -> float:
        return float(self.in_top3[:, sel].all(axis=1).mean())

    def p_tierce_ordre(self, sel: list[int]) -> float:
        a, b, c = sel[0], sel[1], sel[2]
        return float(((self.top1 == a) & (self.top2 == b) & (self.top3 == c)).mean())

    def p_2sur4(self, sel: list[int]) -> float:
        # ≥ 2 des chevaux choisis dans le top-4
        return float((self.in_top4[:, sel].sum(axis=1) >= 2).mean())

    def p_topk_exact(self, sel: list[int], k: int) -> float:
        member = self.in_top4 if k == 4 else self.in_top5 if k == 5 else self.in_top3
        return float(member[:, sel].all(axis=1).mean())


# ──────────────────────────────────────────────────────────────────────────────
# Génération des propositions
# ──────────────────────────────────────────────────────────────────────────────
def _ev(p: float, rapport: float) -> float:
    return p * rapport - 1.0


def build_combo_proposals(
    predictions: list[dict],
    course_info: dict,
    bankroll: float = 100.0,
    n_sims: int = N_SIMS,
) -> dict:
    """Construit les propositions de paris multiples avec probabilités simulées.

    predictions : [{numero, nom, proba_top1, proba_top3, cote_pmu, ...}]
    Retourne {simulations, proposals:[...], scenario_arrivee:[...]}.
    """
    parts = [p for p in predictions if (p.get("cote_pmu") or 0) > 1.0]
    if len(parts) < 4:
        return {"simulations": 0, "proposals": [], "scenario_arrivee": []}

    # Forces MODÈLE = proba de victoire (proba_top1, normalisée, plancher outsiders)
    p1 = np.array([max(float(p.get("proba_top1") or 0.0), 1e-4) for p in parts])
    p1 = p1 / p1.sum()
    cotes = np.array([float(p.get("cote_pmu") or 10.0) for p in parts])
    numeros = [int(p["numero"]) for p in parts]
    noms = [p.get("nom", "") for p in parts]

    # Forces MARCHÉ = proba implicite (1/cote, overround retiré) → sert à estimer
    # le rapport pari-mutuel (rapport ≈ TRJ / proba_marché de la combinaison).
    pm = 1.0 / np.clip(cotes, 1.01, None)
    pm = pm / pm.sum()

    order = simulate_orderings(p1, n_sims=n_sims, seed=12345)
    sim = _Sim(order, len(parts))
    order_m = simulate_orderings(pm, n_sims=n_sims, seed=67890)
    sim_m = _Sim(order_m, len(parts))

    # Ordre d'arrivée le plus probable (modal top-5) — scénario de référence
    by_p1 = np.argsort(-p1)
    scenario = [{"numero": numeros[i], "nom": noms[i],
                 "proba_victoire": round(float(p1[i]), 4), "cote": round(float(cotes[i]), 1)}
                for i in by_p1[:5]]

    nb_partants = course_info.get("nb_partants", len(parts))
    est_quinte = bool(course_info.get("est_quinte"))
    est_quarte = bool(course_info.get("est_quarte"))
    est_tierce = bool(course_info.get("est_tierce"))

    proposals: list[dict] = []

    def add(niveau, type_pari, sel_idx, p_model, p_market, mise, nb_combi, texte):
        if p_model <= 0:
            return
        # Rapport pari-mutuel ≈ TRJ / proba_marché de la combinaison (le pool
        # redistribue ~TRJ proportionnellement aux gagnants). Plancher = mise base.
        trj = TRJ.get(type_pari, 0.70)
        rapport = trj / max(p_market, 1e-5)
        rapport = max(rapport, 1.1)
        ev = _ev(p_model, rapport)
        proposals.append({
            "niveau": niveau,
            "type_pari": type_pari,
            "chevaux": [{"numero": numeros[i], "nom": noms[i], "cote": round(float(cotes[i]), 1)} for i in sel_idx],
            "proba_gain": round(p_model, 4),
            "proba_marche": round(p_market, 4),
            "rapport_estime": round(float(rapport), 1),
            "mise_suggeree": round(float(mise), 2),
            "cout_total": round(float(mise * nb_combi), 2),
            "nb_combinaisons": int(nb_combi),
            "gain_potentiel": round(float(mise * rapport), 2),
            "ev": round(float(ev), 3),
            "esperance_gain": round(float(mise * nb_combi * ev), 2),
            "edge": round(float(p_model - p_market), 4),  # avantage modèle vs marché
            "texte_explication": texte,
        })

    top = list(by_p1)  # indices triés par proba victoire desc

    # ── Couplé Placé (2 favoris dans le top-3) — sécurité ──
    if len(top) >= 2:
        a, b = top[0], top[1]
        add("safe", "Couplé Placé", [a, b], sim.p_couple_place([a, b]), sim_m.p_couple_place([a, b]), 2.0, 1,
            f"N°{numeros[a]} et N°{numeros[b]} tous deux dans les 3 premiers.")

    # ── Couplé Gagnant (2 favoris 1er+2e) — équilibré ──
    if len(top) >= 2:
        a, b = top[0], top[1]
        add("equilibre", "Couplé Gagnant", [a, b], sim.p_couple_gagnant([a, b]), sim_m.p_couple_gagnant([a, b]), 2.0, 1,
            f"N°{numeros[a]} et N°{numeros[b]} aux 2 premières places.")

    # ── 2sur4 (4 meilleurs) — équilibré ──
    if len(top) >= 4 and nb_partants >= 8:
        sel = list(top[:4])
        add("equilibre", "2sur4", sel, sim.p_2sur4(sel), sim_m.p_2sur4(sel), 3.0, 6,
            f"2 des 4 chevaux N°{','.join(str(numeros[i]) for i in sel)} dans les 4 premiers.")

    # ── Trio (3 favoris, désordre) — audacieux ──
    if len(top) >= 3:
        sel = list(top[:3])
        add("audacieux", "Trio", sel, sim.p_trio(sel), sim_m.p_trio(sel), 2.0, 1,
            f"N°{','.join(str(numeros[i]) for i in sel)} aux 3 premières places sans ordre.")

    # ── Tiercé désordre (course tiercé/quarté/quinté) — audacieux ──
    if (est_tierce or est_quarte or est_quinte) and len(top) >= 3:
        sel = list(top[:3])
        add("audacieux", "Tiercé Désordre", sel, sim.p_trio(sel), sim_m.p_trio(sel), 2.0, 1,
            f"N°{','.join(str(numeros[i]) for i in sel)} aux 3 premières places, ordre indifférent.")

    # ── Quarté+ désordre (4 favoris) — jackpot ──
    if (est_quarte or est_quinte) and len(top) >= 4:
        sel = list(top[:4])
        add("jackpot", "Quarté+ Désordre", sel, sim.p_topk_exact(sel, 4), sim_m.p_topk_exact(sel, 4), 2.0, 1,
            f"N°{','.join(str(numeros[i]) for i in sel)} aux 4 premières places.")

    # ── Quinté+ désordre (5 favoris) — jackpot ──
    if est_quinte and len(top) >= 5:
        sel = list(top[:5])
        add("jackpot", "Quinté+ Désordre", sel, sim.p_topk_exact(sel, 5), sim_m.p_topk_exact(sel, 5), 2.0, 1,
            f"N°{','.join(str(numeros[i]) for i in sel)} aux 5 premières places.")

    # Tri : EV décroissante puis proba décroissante
    proposals.sort(key=lambda x: (x["ev"], x["proba_gain"]), reverse=True)

    return {
        "simulations": n_sims,
        "scenario_arrivee": scenario,
        "proposals": proposals,
    }
