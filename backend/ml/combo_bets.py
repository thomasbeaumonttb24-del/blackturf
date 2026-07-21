"""
combo_bets.py — Propositions de paris MULTIPLES avec probabilités RÉELLES.

Au lieu d'EV hardcodés, on simule l'ordre d'arrivée par un modèle Plackett-Luce
(forces ∝ proba de victoire du modèle) via l'astuce de Gumbel (vectorisé numpy),
puis on compte la fréquence de gain de chaque combinaison → probabilité honnête.
EV = P(gain) × rapport_estimé − 1. Aucune valeur inventée : si la proba est faible,
le pari n'est pas proposé.
"""
from __future__ import annotations

import math
import numpy as np
import structlog

log = structlog.get_logger()

N_SIMS = 20000

# Taux de retour joueur (TRJ) PMU 2026 par type de pari : le pari-mutuel
# redistribue ~TRJ de la masse → rapport ≈ TRJ / proba_marché.
TRJ = {
    "Couplé Placé": 0.74, "Couplé Gagnant": 0.74, "2sur4": 0.74,
    "Couplé Ordre": 0.74, "Trio Ordre": 0.691, "Super 4": 0.65,
    "Trio": 0.691, "Tiercé Désordre": 0.6435, "Tiercé Ordre": 0.6435,
    "Quarté+ Désordre": 0.633, "Quinté+ Désordre": 0.6475,
    # Multi (top-4 désordre, mise plate 3€, sélection 4→7 chevaux) et Pick5 (top-5
    # désordre, mise 1€, SANS bonus). TRJ PMU officiels 2026.
    "Multi": 0.75, "Pick5": 0.6475,
}

# Multi PMU : on sélectionne 4 à 7 chevaux pour trouver les 4 PREMIERS (désordre),
# mise PLATE quel que soit le nombre (le PMU couvre TOUTES les combis de la sélection
# pour le même prix — pas de C(n,4) à payer). Plus on prend de chevaux, plus on gagne
# SOUVENT, mais le rapport baisse (on attrape surtout les arrivées « logiques »).
# Le rapport décroissant avec n est encodé HONNÊTEMENT par p_coverage marché (un champ
# large ⇒ proba marché plus haute ⇒ rapport ≈ TRJ/p_market plus faible), pas par un
# facteur arbitraire. Mini Multi (10-13 partants) = même mécanique, label distinct.
MULTI_UNIT = 3.0
PICK5_UNIT = 1.0


def _bet_flags(course_info: dict) -> dict:
    """Drapeaux de disponibilité des paris (vérité PMU ou fallback). Robuste : si la
    route a déjà injecté les drapeaux canoniques (est_couple_ordre…) on les utilise,
    sinon on les dérive de paris_disponibles / des booléens est_* présents."""
    if "est_couple_gagnant" in course_info:
        return course_info
    from services.bet_catalog import derive_bet_flags
    flags = derive_bet_flags(
        course_info.get("paris_disponibles"),
        est_tierce=bool(course_info.get("est_tierce")),
        est_quarte=bool(course_info.get("est_quarte")),
        est_quinte=bool(course_info.get("est_quinte")),
        est_2sur4=bool(course_info.get("est_2sur4")),
    )
    merged = dict(course_info)
    merged.update(flags)
    return merged


# Cap modèle/marché (flag combo_market_cap, audit ROI 2026-07-02) : même seuil que
# le gate value bet (valuebets.MAX_MODEL_MARKET_RATIO) appliqué aux probas CHEVAUX
# qui alimentent la simulation des combos. Cotes ≥ CAP_COTE_MIN uniquement (sur les
# favoris un fort écart au marché peut être un vrai edge).
CAP_RATIO = 1.55
CAP_COTE_MIN = 4.0


def _cap_model_probas(p1: np.ndarray, pm: np.ndarray, cotes: np.ndarray) -> np.ndarray:
    """Cape la proba modèle de chaque cheval (cote ≥ 4) à CAP_RATIO × sa proba marché
    dé-viguée, puis renormalise Σ=1. Mesuré (edge_monitor) : conviction modèle >1.1×
    le marché → ROI −42.9% (pire que base) ; sans ce cap les combos d'outsiders
    héritent de probas sur-évaluées que le gate 1.55 ne filtrait qu'en Simple
    Gagnant → P(gain)/EV des Trio/Couplé gonflées. Flag off → probas inchangées."""
    try:
        from ml.algo_flags import FLAGS as _AF
        if not _AF.combo_market_cap:
            return p1
    except Exception:
        pass
    capped = np.where(cotes >= CAP_COTE_MIN, np.minimum(p1, CAP_RATIO * pm), p1)
    s = capped.sum()
    return capped / s if s > 0 else p1


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
        # Règle PMU du « placé » : top-2 si 4-7 partants, top-3 si ≥8, top-1 si <4.
        # Le « placé » N'EST PAS toujours top-3 → sur 4-7 partants, P(placé) doit être
        # P(top-2) sinon les probas/EV des Simple & Couplé Placé sont surestimées.
        self._place_k = 2 if 4 <= n_horses <= 7 else (3 if n_horses >= 8 else 1)
        self.in_place = _topk_membership(order, n_horses, self._place_k)
        self.top1 = order[:, 0]
        self.top2 = order[:, 1] if order.shape[1] > 1 else order[:, 0]
        self.top3 = order[:, 2] if order.shape[1] > 2 else order[:, 0]
        self.top4 = order[:, 3] if order.shape[1] > 3 else order[:, 0]
        self.top5p = order[:, 4] if order.shape[1] > 4 else order[:, 0]

    def p_simple_place(self, a: int) -> float:
        # Placé selon la règle PMU (top-2 ou top-3 selon le nombre de partants).
        return float(self.in_place[:, a].mean())

    def p_couple_ordre(self, sel: list[int]) -> float:
        """Couplé ORDRE : sel[0] 1er ET sel[1] 2e, dans CET ordre exact."""
        a, b = sel[0], sel[1]
        return float(((self.top1 == a) & (self.top2 == b)).mean())

    def p_trio_ordre(self, sel: list[int]) -> float:
        """Trio ORDRE : les 3 premiers dans l'ordre exact."""
        a, b, c = sel[0], sel[1], sel[2]
        return float(((self.top1 == a) & (self.top2 == b) & (self.top3 == c)).mean())

    def p_super4(self, sel: list[int]) -> float:
        """Super 4 : les 4 premiers dans l'ordre exact."""
        a, b, c, d = sel[0], sel[1], sel[2], sel[3]
        return float(((self.top1 == a) & (self.top2 == b)
                      & (self.top3 == c) & (self.top4 == d)).mean())

    def p_couple_gagnant(self, sel: list[int]) -> float:
        # les 2 chevaux exactement 1er+2e (ordre indifférent)
        return float(self.in_top2[:, sel].all(axis=1).mean())

    def p_couple_place(self, sel: list[int]) -> float:
        # Couplé Placé : les 2 chevaux dans les places payées (règle PMU top-2/top-3).
        return float(self.in_place[:, sel].all(axis=1).mean())

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

    def p_coverage(self, sel: list[int], k: int) -> float:
        """P(les k premiers ⊆ sélection) — couverture désordre avec |sel| ≥ k.

        Le ticket gagne si les k chevaux arrivés aux k premières places sont TOUS
        dans la sélection (peu importe l'ordre). Exactement k des |sel| colonnes
        doivent appartenir au top-k de la simulation."""
        member = self.in_top4 if k == 4 else self.in_top5 if k == 5 else self.in_top3
        return float((member[:, sel].sum(axis=1) == k).mean())


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
    p1 = _cap_model_probas(p1, pm, cotes)   # cap 1.55× marché sur cote ≥ 4 (flag)

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
    _flp = _bet_flags(course_info)
    est_quinte = bool(_flp.get("est_quinte"))
    est_quarte = bool(_flp.get("est_quarte"))
    est_tierce = bool(_flp.get("est_tierce"))
    est_2sur4 = bool(_flp.get("est_2sur4"))   # 2sur4 réellement offert PMU
    est_multi = bool(_flp.get("est_multi"))
    est_pick5 = bool(_flp.get("est_pick5"))
    is_mini = est_multi and 10 <= int(nb_partants or 0) <= 13

    proposals: list[dict] = []

    def add(niveau, type_pari, sel_idx, p_model, p_market, mise, nb_combi, texte):
        if p_model <= 0:
            return
        # Rapport pari-mutuel ≈ TRJ / proba_marché de la combinaison. On plancher la
        # proba marché (1e-3) et on plafonne le rapport : sinon une proba simulée
        # minuscule fait exploser le rapport → EV absurde (+19000%) non crédible.
        trj = 0.75 if "Multi" in type_pari else TRJ.get(type_pari, 0.70)
        rapport = trj / max(p_market, 1e-3)
        rapport = float(min(max(rapport, 1.1), 5000.0))
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

    # ── 2sur4 (4 meilleurs) — équilibré ── (uniquement si offert par le PMU)
    if len(top) >= 4 and est_2sur4:
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

    # ── Multi en 4→7 (top-4 désordre, mise plate 3€) — « gagner souvent » ──
    if est_multi and len(top) >= 4:
        _lab = "Mini Multi" if is_mini else "Multi"
        for nn in range(4, min(7, len(top)) + 1):
            sel = list(top[:nn])
            niv = "jackpot" if nn <= 5 else "equilibre"
            add(niv, f"{_lab} en {nn}", sel, sim.p_coverage(sel, 4), sim_m.p_coverage(sel, 4),
                3.0, 1,
                f"{_lab} en {nn} — les 4 premiers (désordre) parmi N°"
                f"{','.join(str(numeros[i]) for i in sel)}.")

    # ── Pick5 (top-5 désordre, mise 1€) ──
    if est_pick5 and len(top) >= 5:
        sel = list(top[:5])
        add("jackpot", "Pick5", sel, sim.p_topk_exact(sel, 5), sim_m.p_topk_exact(sel, 5),
            1.0, 1,
            f"Pick5 — N°{','.join(str(numeros[i]) for i in sel)} : les 5 premiers (désordre).")

    # Tri : EV décroissante puis proba décroissante
    proposals.sort(key=lambda x: (x["ev"], x["proba_gain"]), reverse=True)

    return {
        "simulations": n_sims,
        "scenario_arrivee": scenario,
        "proposals": proposals,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Énumération de candidats DIVERSES pour le plan de mise
# ──────────────────────────────────────────────────────────────────────────────
def enumerate_bet_candidates(
    predictions: list[dict],
    course_info: dict,
    n_sims: int = N_SIMS,
) -> list[dict]:
    """Génère BEAUCOUP de paris candidats variés (plusieurs Simple Gagnant, 3-4
    Couplé Gagnant différents, Trios, dont des scénarios SURPRISE avec outsider),
    chacun avec proba RÉELLE (simulation Plackett-Luce) + rapport + EV + edge.

    niveau : "securite" (forte proba) / "rendement" (EV+ favoris) /
             "surprise" (outsider que le modèle aime > marché) / "coup" (gros lot).
    Retour trié par (niveau prioritaire, EV décroissante).
    """
    parts = [p for p in predictions if (p.get("cote_pmu") or 0) > 1.0]
    if len(parts) < 3:
        return []

    p1 = np.array([max(float(p.get("proba_top1") or 0.0), 1e-4) for p in parts])
    p1 = p1 / p1.sum()
    cotes = np.array([float(p.get("cote_pmu") or 10.0) for p in parts])
    numeros = [int(p["numero"]) for p in parts]
    noms = [p.get("nom", "") for p in parts]

    pm = 1.0 / np.clip(cotes, 1.01, None)
    pm = pm / pm.sum()
    p1 = _cap_model_probas(p1, pm, cotes)   # cap 1.55× marché sur cote ≥ 4 (flag)

    order = simulate_orderings(p1, n_sims=n_sims, seed=12345)
    sim = _Sim(order, len(parts))
    order_m = simulate_orderings(pm, n_sims=n_sims, seed=67890)
    sim_m = _Sim(order_m, len(parts))

    by_p1 = list(np.argsort(-p1))                 # favoris modèle
    implied = pm                                   # proba marché par cheval
    edge_by_idx = p1 - implied                     # avantage modèle vs marché

    # Outsider(s) à VALEUR : grosse cote où le modèle a un edge positif. Plage large
    # (6-200) pour que les GROSSES cotes que le modèle classe haut (ex. un cheval à
    # cote 180 vu top-3) entrent dans les combos surprise/coup — le profil risqué les
    # joue en petite mise. C'est la cohérence demandée : tout pick du modèle est jouable.
    outsiders = sorted(
        [i for i in range(len(parts)) if 6.0 <= cotes[i] <= 200.0 and edge_by_idx[i] > 0],
        key=lambda i: edge_by_idx[i], reverse=True,
    )
    out1 = outsiders[0] if outsiders else None
    # Picks GROSSE COTE du modèle : chevaux que le modèle classe dans son top-5 (par
    # proba de victoire) MAIS à cote élevée (≥ 8). Ils DOIVENT être proposables (en
    # Simple Gagnant coup + dans les combos top-k), sinon on ignore notre propre analyse.
    big_model_picks = [i for i in by_p1[:5] if cotes[i] >= 8.0]
    # GROSSES COTES jouables pour le profil RISQUÉ : cote ≥ 12 que le modèle ne déclasse
    # PAS (edge > 0 OU classé dans son top-8 par proba de victoire). Servent à FABRIQUER
    # un large spectre de combos à gros rapport (plusieurs duos/trios d'outsiders) : le
    # profil risqué exige une cote plancher élevée → sans ces combos il manque de paris
    # à jouer (cause du « risqué pauvre »). Triés par proba modèle (ordre de by_p1).
    gros_cote = [i for i in by_p1
                 if cotes[i] >= 12.0 and (edge_by_idx[i] > 0 or i in by_p1[:8])][:4]

    cands: list[dict] = []
    seen: set = set()

    def H(i):
        return {"numero": numeros[i], "nom": noms[i], "cote": round(float(cotes[i]), 1)}

    def add(niveau, type_pari, sel, proba, p_market, texte):
        if len(set(sel)) != len(sel):       # pas de cheval en double dans une combinaison
            return
        key = (type_pari, tuple(sorted(sel)))
        if key in seen or proba <= 0:
            return
        seen.add(key)
        trj = (0.75 if "Multi" in type_pari
               else TRJ.get(type_pari, 0.80 if "Simple" in type_pari else 0.70))
        rapport = float(min(max(trj / max(p_market, 1e-3), 1.1), 5000.0))
        # FLAG combo_ev_none : l'EV d'un combo = _ev(p_model, trj/p_market) est
        # MÉCANIQUEMENT positive dès que modèle>marché (rapport calculé sur p_market,
        # EV sur p_model) — un faux +EV qui faisait passer tout combo par les gates EV.
        # Le rapport parimutuel réel dépend du pool, inconnu avant la course. On neutralise
        # donc l'EV des combos (0.0) → ils n'entrent plus comme "value" mais seulement
        # comme coup/spéculatif plafonné. Simple Gagnant/Placé gardent leur EV (cote réelle).
        try:
            from ml.algo_flags import FLAGS as _AF
            _ev_val = _ev(proba, rapport) if (not _AF.combo_ev_none or "Simple" in type_pari) else 0.0
        except Exception:
            _ev_val = _ev(proba, rapport)
        cands.append({
            "niveau": niveau,
            "type_pari": type_pari,
            "chevaux": [H(i) for i in sel],
            "proba_gain": round(float(proba), 4),
            "rapport_estime": round(rapport, 1),
            "ev": round(_ev_val, 3),
            "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
            "texte_explication": texte,
        })

    nb_partants = course_info.get("nb_partants", len(parts))
    fl = _bet_flags(course_info)
    est_quinte = bool(fl.get("est_quinte"))
    est_quarte = bool(fl.get("est_quarte"))
    est_tierce = bool(fl.get("est_tierce"))
    est_2sur4 = bool(fl.get("est_2sur4"))            # 2sur4 réellement offert PMU
    # Disponibilité fine des paris (un champ réduit n'offre QUE l'ordre).
    est_cg = bool(fl.get("est_couple_gagnant"))
    est_cp = bool(fl.get("est_couple_place"))
    est_co = bool(fl.get("est_couple_ordre"))        # couplé ORDRE (champ réduit)
    est_trio = bool(fl.get("est_trio"))
    est_to = bool(fl.get("est_trio_ordre"))          # trio ORDRE (champ réduit)
    est_s4 = bool(fl.get("est_super4"))              # Super 4 (top-4 ordre exact)
    est_multi = bool(fl.get("est_multi"))            # Multi (top-4 désordre, champ 4→7)
    est_pick5 = bool(fl.get("est_pick5"))            # Pick5 (top-5 désordre, sans bonus)
    # Mini Multi = même pari sur une course de 10-13 partants (PMU). Le flag est_multi
    # vaut pour les deux ; on distingue le LABEL selon le nb de partants pour l'utilisateur.
    is_mini = est_multi and 10 <= int(nb_partants or 0) <= 13

    # ── SIMPLE GAGNANT — uniquement sur cote >= 3. Sous 3, le gain est trop
    # faible pour le risque (surtout en petite mise) : un favori court se joue
    # mieux en Couplé/Trio comme base. On privilégie la VALEUR : edge positif
    # (modèle > marché) d'abord, puis proba modèle.
    SG_COTE_MIN = 3.0
    # On inclut TOUS les picks grosse cote du modèle dans le pool (pas juste les 3
    # meilleurs par proba) pour ne JAMAIS écarter un cheval que l'analyse classe haut.
    sg_pool = [i for i in by_p1 if cotes[i] >= SG_COTE_MIN]
    sg_pool.sort(key=lambda i: (1 if edge_by_idx[i] > 0 else 0, p1[i]), reverse=True)
    sg_take = list(dict.fromkeys(sg_pool[:3] + big_model_picks))  # top-3 + grosses cotes du modèle
    for i in sg_take:
        p_win = float(p1[i]); rap = float(cotes[i])
        ev = rap * p_win - 1
        if ev <= -0.45:                 # franchement perdant → on évite
            continue
        has_edge = edge_by_idx[i] > 0
        # Niveau selon la cote : grosse cote = COUP (petite mise spéculative), cote
        # moyenne à edge = SURPRISE, cote raisonnable = RENDEMENT. Une grosse cote ne
        # doit jamais passer en "rendement" (mise franche) — c'est un coup à tenter.
        if rap >= 25:
            niv = "coup"
        elif rap >= 9:
            niv = "surprise" if has_edge else "coup"
        else:
            niv = "rendement"
        cands.append({
            "niveau": niv, "type_pari": "Simple Gagnant", "chevaux": [H(i)],
            "proba_gain": round(p_win, 4), "rapport_estime": round(rap, 1),
            "ev": round(ev, 3), "edge": round(float(edge_by_idx[i]), 4),
            "texte_explication": f"N°{numeros[i]} {noms[i]} — {p_win*100:.0f}% de gagner, cote {cotes[i]:.1f}"
                                 + (" · le modèle le classe au-dessus du marché (grosse cote à tenter)" if has_edge and rap >= 9
                                    else " · valeur détectée (modèle > marché)" if has_edge else "") + ".",
        })
        seen.add(("Simple Gagnant", (i,)))
    if out1 is not None and ("Simple Gagnant", (out1,)) not in seen:
        p_win = float(p1[out1]); rap = float(cotes[out1])
        cands.append({
            "niveau": "surprise", "type_pari": "Simple Gagnant", "chevaux": [H(out1)],
            "proba_gain": round(p_win, 4), "rapport_estime": round(rap, 1),
            "ev": round(rap * p_win - 1, 3), "edge": round(float(edge_by_idx[out1]), 4),
            "texte_explication": f"SURPRISE — N°{numeros[out1]} {noms[out1]} (cote {cotes[out1]:.1f}) : "
                                 f"le modèle le voit plus haut que le marché.",
        })
    # SIMPLE GAGNANT grosse cote (spectre RISQUÉ) : chaque grosse cote crédible en coup
    # à petite mise — permet « 2 (ou +) simple gagnant à grosse cote » sur une course.
    for g in gros_cote:
        if ("Simple Gagnant", (g,)) in seen:
            continue
        p_win = float(p1[g]); rap = float(cotes[g])
        if rap * p_win - 1 <= -0.55:          # franchement perdant même pour un coup
            continue
        has_edge = edge_by_idx[g] > 0
        cands.append({
            "niveau": "coup", "type_pari": "Simple Gagnant", "chevaux": [H(g)],
            "proba_gain": round(p_win, 4), "rapport_estime": round(rap, 1),
            "ev": round(rap * p_win - 1, 3), "edge": round(float(edge_by_idx[g]), 4),
            "texte_explication": f"N°{numeros[g]} {noms[g]} — coup grosse cote {cotes[g]:.1f} "
                                 f"({p_win*100:.0f}% de gagner)"
                                 + (" · le modèle le classe au-dessus du marché" if has_edge else "") + ".",
        })
        seen.add(("Simple Gagnant", (g,)))

    # ── SIMPLE PLACÉ à VALEUR — socle du profil PRUDENT. ──────────────────────
    # On NE veut PAS l'ultra-favori placé (rapport ~1.1× = argent mort même gagné).
    # On veut un placé qui (1) tombe souvent (proba ≥ 0.25), (2) RAPPORTE (rapport
    # ≥ 1.3×), (3) a une VRAIE valeur : le modèle place le cheval PLUS que le marché
    # (edge placé > 0) OU EV placé positive. C'est le placé qui fait vraiment gagner.
    TRJ_PLACE = 0.85
    for i in by_p1[:6]:                               # champ élargi, pas que les 3 favoris
        p_pl = float(sim.p_simple_place(i))
        if p_pl < 0.25:
            continue
        p_pl_m = max(float(sim_m.p_simple_place(i)), 1e-3)   # proba placé marché
        rapport = float(min(max(TRJ_PLACE / p_pl_m, 1.1), 50.0))
        if rapport < 1.3:                            # ultra-favori qui ne rapporte rien → skip
            continue
        edge_pl = p_pl - p_pl_m                       # edge PLACÉ (modèle vs marché)
        ev = p_pl * rapport - 1.0
        # ANCRE FRÉQUENCE (mode engagement) : on émet aussi le placé d'un FAVORI MARCHÉ
        # (proba placé marché ≥ 0.50 = se place très souvent) MÊME sans edge/EV → ancre
        # « gagne souvent » du prudent (DONNÉE : favori marché se place ~72% vs ~60% pick
        # modèle vs ~29% mid-cote). Sans ça le placé favori est jeté (modèle sous-cote le
        # favori → edge<0, + marge PMU → -EV). L'ancre reste PRUDENTE (bande ×1.8-4) : en
        # modéré le rapport <4 la filtre (seul un placé d'outsider ≥×4 y entre). Proba affichée = max(modèle, marché) : le
        # marché est PLUS JUSTE sur les favoris (mesuré).
        is_anchor = p_pl_m >= 0.50
        if edge_pl <= 0 and ev <= 0 and not is_anchor:
            continue
        p_aff = max(p_pl, p_pl_m) if is_anchor else p_pl
        key = ("Simple Placé", (i,))
        if key in seen:
            continue
        seen.add(key)
        cands.append({
            "niveau": "securite", "type_pari": "Simple Placé", "chevaux": [H(i)],
            "proba_gain": round(p_aff, 4), "rapport_estime": round(rapport, 1),
            "ev": round(ev, 3), "edge": round(float(edge_pl), 4), "_anchor": is_anchor,
            "texte_explication": (
                (f"N°{numeros[i]} {noms[i]} FAVORI — {p_aff*100:.0f}% d'être dans les 3 "
                 f"(cote {cotes[i]:.1f}, rapport ~{rapport:.1f}×) : le placé qui tombe souvent.")
                if is_anchor else
                (f"N°{numeros[i]} {noms[i]} placé à VALEUR — {p_aff*100:.0f}% d'être dans "
                 f"les 3 (cote {cotes[i]:.1f}, rapport ~{rapport:.1f}×) : le modèle le place "
                 f"plus haut que le marché.")
            ),
        })

    # ── ANCRE PLACÉ « GAGNE SOUVENT » DANS LA CONTRAINTE ≥1.8× (prudent) ──────────
    # Le prudent veut un MAX de victoires MAIS en respectant le multiplicateur ≥1.8 (un placé
    # à 1.1× = gain dérisoire, inutile à jouer). On ANCRE donc le Simple Placé du cheval le
    # PLUS susceptible de se placer PARMI ceux dont le placé paie ≥1.8× (typiquement cote ~5).
    # Backtest : 44% de réussite (vs 28%), chaque gain ≥1.8×. Sans cette ancre, ce placé est
    # jeté (sans edge/EV). Bande de rapport ×1.8-4 → cette ancre ne touche que le prudent.
    # On ne se base PAS QUE sur la cote (user) : on classe par proba_top3 du MODÈLE → un cheval
    # à grosse cote (jusqu'à 20) n'est ancré QUE si le modèle le « sent » vraiment (proba_top3
    # la plus haute parmi les placés ≥1.8). + bonus VALUE : si proba_top3 > implicite marché,
    # le modèle voit un placé sous-coté (outsider à valeur) → on le privilégie.
    best_i, best_p = None, -1.0
    for i in range(len(cotes)):
        if float(cotes[i]) > 20.0:                   # garde-fou longshot absurde, pas un cap "favori"
            continue
        _ppm = max(float(sim_m.p_simple_place(i)), 1e-3)
        _rap = float(min(max(TRJ_PLACE / _ppm, 1.1), 50.0))
        if _rap < 1.9:                               # buffer → multiplicateur réel ≥1.8 garanti
            continue
        _p3 = float(parts[i].get("proba_top3") or 0.0)   # proba PLACÉ du MODÈLE (analyse, pas cote)
        _value = 1.0 + 0.5 * max(0.0, _p3 - _ppm)    # bonus si modèle > marché (placé à valeur)
        _score = _p3 * _value
        if _score > best_p:
            best_p, best_i = _score, i
    if best_i is not None and ("Simple Placé", (best_i,)) not in seen:
        _ppm = max(float(sim_m.p_simple_place(best_i)), 1e-3)
        _rap = float(min(max(TRJ_PLACE / _ppm, 1.1), 50.0))
        _pp = max(float(parts[best_i].get("proba_top3") or 0.0), float(sim.p_simple_place(best_i)))
        seen.add(("Simple Placé", (best_i,)))
        cands.append({
            "niveau": "securite", "type_pari": "Simple Placé", "chevaux": [H(best_i)],
            "proba_gain": round(_pp, 4), "rapport_estime": round(_rap, 1),
            "ev": round(_pp * _rap - 1.0, 3),
            "edge": round(float(_pp - _ppm), 4), "_anchor": True,
            "texte_explication": (
                f"N°{numeros[best_i]} {noms[best_i]} placé — {_pp*100:.0f}% d'être dans les 3 "
                f"(cote {cotes[best_i]:.1f}, rapport ~{_rap:.1f}×) : le placé le plus SÛR qui paie ≥1.8×."
            ),
        })

    # ── COUPLÉ GAGNANT — large spectre (favoris + duos d'outsiders à grosse cote) ──
    pairs = []
    if len(by_p1) >= 2: pairs.append((by_p1[0], by_p1[1]))
    if len(by_p1) >= 3: pairs.append((by_p1[0], by_p1[2]))
    if len(by_p1) >= 3: pairs.append((by_p1[1], by_p1[2]))
    if out1 is not None: pairs.append((by_p1[0], out1))   # favori + surprise
    # Duos GAGNANT à GROSSE COTE pour le risqué : chaque grosse cote couplée aux 2
    # premiers favoris, plus les paires d'outsiders entre eux → « 4 duo gagnant ».
    for g in gros_cote:
        if by_p1[0] != g: pairs.append((by_p1[0], g))
        if len(by_p1) >= 2 and by_p1[1] != g: pairs.append((by_p1[1], g))
    for gi in range(len(gros_cote)):
        for gj in range(gi + 1, len(gros_cote)):
            pairs.append((gros_cote[gi], gros_cote[gj]))
    if est_cg:
        for a, b in pairs:
            mx = max(float(cotes[a]), float(cotes[b]))
            niv = "coup" if mx >= 25 else "surprise" if mx >= 12 else "rendement"
            add(niv, "Couplé Gagnant", [a, b], sim.p_couple_gagnant([a, b]), sim_m.p_couple_gagnant([a, b]),
                f"N°{numeros[a]} + N°{numeros[b]} aux 2 premières places.")

    # ── Couplé ORDRE (champ réduit : le PMU n'offre QUE l'ordre) — gros rapport. ──
    # Le pari ne gagne que si l'ordre exact (a 1er, b 2e) est trouvé → rapport bien
    # plus élevé qu'en désordre. On émet les 2 sens (a,b) et (b,a) pour les meilleurs
    # duos (favoris + grosses cotes) : un large spectre pour le profil risqué.
    if est_co:
        ord_pairs = []
        if len(by_p1) >= 2:
            ord_pairs += [(by_p1[0], by_p1[1]), (by_p1[1], by_p1[0])]
        if len(by_p1) >= 3:
            ord_pairs += [(by_p1[0], by_p1[2]), (by_p1[1], by_p1[2])]
        if out1 is not None and by_p1 and out1 != by_p1[0]:
            ord_pairs += [(by_p1[0], out1), (out1, by_p1[0])]
        for g in gros_cote:
            if by_p1[0] != g:
                ord_pairs += [(by_p1[0], g), (g, by_p1[0])]
        for a, b in ord_pairs:
            mx = max(float(cotes[a]), float(cotes[b]))
            niv = "coup" if mx >= 15 else "surprise"
            add(niv, "Couplé Ordre", [a, b], sim.p_couple_ordre([a, b]), sim_m.p_couple_ordre([a, b]),
                f"N°{numeros[a]} 1er puis N°{numeros[b]} 2e (ordre exact) — gros rapport.")

    # ── Couplé Placé (sécurité) ──
    if est_cp and len(by_p1) >= 2:
        add("securite", "Couplé Placé", [by_p1[0], by_p1[1]],
            sim.p_couple_place([by_p1[0], by_p1[1]]), sim_m.p_couple_place([by_p1[0], by_p1[1]]),
            f"N°{numeros[by_p1[0]]} + N°{numeros[by_p1[1]]} tous deux dans les 3 premiers.")
    if est_cp and len(by_p1) >= 3:
        add("securite", "Couplé Placé", [by_p1[0], by_p1[2]],
            sim.p_couple_place([by_p1[0], by_p1[2]]), sim_m.p_couple_place([by_p1[0], by_p1[2]]),
            f"N°{numeros[by_p1[0]]} + N°{numeros[by_p1[2]]} tous deux dans les 3 premiers.")
    # Couplé Placé favori + OUTSIDER à valeur : placer une grosse cote dans le top-3.
    if est_cp and out1 is not None and by_p1 and out1 != by_p1[0]:
        add("surprise", "Couplé Placé", [by_p1[0], out1],
            sim.p_couple_place([by_p1[0], out1]), sim_m.p_couple_place([by_p1[0], out1]),
            f"Favori N°{numeros[by_p1[0]]} + outsider N°{numeros[out1]} (cote {cotes[out1]:.1f}) "
            f"tous deux placés — placement d'une grosse cote.")

    # ── Trios — large spectre (favoris + grosses cotes) pour viser « 5 trio » ──
    trios = []
    if len(by_p1) >= 3: trios.append((by_p1[0], by_p1[1], by_p1[2]))
    if len(by_p1) >= 4: trios.append((by_p1[0], by_p1[1], by_p1[3]))
    if out1 is not None and len(by_p1) >= 2: trios.append((by_p1[0], by_p1[1], out1))
    # Trios à GROS RAPPORT : 2 favoris + une grosse cote, et 1 favori + 2 grosses cotes.
    for g in gros_cote:
        if len(by_p1) >= 2 and g not in (by_p1[0], by_p1[1]):
            trios.append((by_p1[0], by_p1[1], g))
        if len(by_p1) >= 3 and g not in (by_p1[0], by_p1[2]):
            trios.append((by_p1[0], by_p1[2], g))
    for gi in range(len(gros_cote)):
        for gj in range(gi + 1, len(gros_cote)):
            if by_p1 and by_p1[0] not in (gros_cote[gi], gros_cote[gj]):
                trios.append((by_p1[0], gros_cote[gi], gros_cote[gj]))
    if est_trio:
        for t in trios:
            mx = max(float(cotes[i]) for i in t)
            has_val_out = any(edge_by_idx[i] > 0 and cotes[i] >= 8 for i in t)
            niv = "surprise" if has_val_out and mx < 40 else "coup"
            add(niv, "Trio", list(t), sim.p_trio(list(t)), sim_m.p_trio(list(t)),
                f"N°{'+N°'.join(str(numeros[i]) for i in t)} aux 3 premières places (sans ordre).")

    # ── Trio ORDRE (champ réduit) — les 3 premiers dans l'ordre exact, gros rapport. ──
    if est_to and len(by_p1) >= 3:
        for t in trios[:4]:
            mx = max(float(cotes[i]) for i in t)
            add("coup", "Trio Ordre", list(t), sim.p_trio_ordre(list(t)), sim_m.p_trio_ordre(list(t)),
                f"N°{'+N°'.join(str(numeros[i]) for i in t)} dans l'ORDRE exact — très gros rapport.")

    # ── 2sur4 ── (uniquement si le PMU propose ce pari pour la course)
    # RÈGLE (user) : un 2sur4 de 4 FAVORIS = dividende quasi nul → inutile. La base inclut
    # donc TOUJOURS un OUTSIDER à valeur (3 favoris + 1 grosse cote que le modèle aime) pour
    # un gain qui vaut la peine, en gardant une proba correcte. Repli sur 4 favoris seulement
    # si aucun outsider à valeur n'est détecté.
    if len(by_p1) >= 4 and est_2sur4:
        if out1 is not None and out1 not in by_p1[:3]:
            sel = list(by_p1[:3]) + [out1]
            add("rendement", "2sur4", sel, sim.p_2sur4(sel), sim_m.p_2sur4(sel),
                f"3 favoris + outsider N°{numeros[out1]} (cote {cotes[out1]:.1f}) — 2 dans les 4 "
                f"premiers : gain rehaussé par la grosse cote, proba encore bonne.")
            # 2e outsider pour un gain encore plus gros si le modèle en aime un autre
            if len(outsiders) >= 2 and outsiders[1] not in by_p1[:2]:
                sel2 = list(by_p1[:2]) + [out1, outsiders[1]]
                add("surprise", "2sur4", sel2, sim.p_2sur4(sel2), sim_m.p_2sur4(sel2),
                    f"2 favoris + 2 outsiders (N°{numeros[out1]}, N°{numeros[outsiders[1]]}) — "
                    f"gros gain si 2 dans les 4 premiers.")
        else:
            sel = list(by_p1[:4])
            add("rendement", "2sur4", sel, sim.p_2sur4(sel), sim_m.p_2sur4(sel),
                f"2 des 4 chevaux N°{','.join(str(numeros[i]) for i in sel)} dans les 4 premiers.")

    # ── Super 4 (champ réduit) — les 4 premiers dans l'ordre EXACT, jackpot. ──
    if est_s4 and len(by_p1) >= 4:
        sel = list(by_p1[:4])
        add("coup", "Super 4", sel, sim.p_super4(sel), sim_m.p_super4(sel),
            f"Super 4 — N°{'+N°'.join(str(numeros[i]) for i in sel)} dans l'ordre exact (gros lot).")

    # ── Jackpots désordre (Tiercé/Quarté+/Quinté+) — gros lot, 1 combinaison ──
    # Proba RÉELLE (simulation) du top-k exact des favoris modèle ; rapport ≈ TRJ /
    # proba marché de la combi. Espérance souvent négative (TRJ ~65%) mais gros lot.
    if (est_tierce or est_quarte or est_quinte) and len(by_p1) >= 3:
        sel = list(by_p1[:3])
        add("coup", "Tiercé Désordre", sel, sim.p_topk_exact(sel, 3), sim_m.p_topk_exact(sel, 3),
            f"Tiercé désordre N°{'+N°'.join(str(numeros[i]) for i in sel)} — gros lot.")
    if (est_quarte or est_quinte) and len(by_p1) >= 4:
        sel = list(by_p1[:4])
        add("coup", "Quarté+ Désordre", sel, sim.p_topk_exact(sel, 4), sim_m.p_topk_exact(sel, 4),
            f"Quarté+ désordre N°{'+N°'.join(str(numeros[i]) for i in sel)} — gros lot.")
    if est_quinte and len(by_p1) >= 5:
        sel = list(by_p1[:5])
        add("coup", "Quinté+ Désordre", sel, sim.p_topk_exact(sel, 5), sim_m.p_topk_exact(sel, 5),
            f"Quinté+ désordre N°{'+N°'.join(str(numeros[i]) for i in sel)} — gros lot.")

    # ── MULTI (top-4 DÉSORDRE, champ 4→7 chevaux, mise plate) ────────────────────
    # On émet le spectre complet : en 4/5 = GROS RAPPORT (peu de chevaux, gros lot,
    # profil risqué) ; en 6/7 = TOMBE SOUVENT (large filet, profils prudent/modéré).
    # Le rapport décroît honnêtement avec n via p_coverage marché. C'est LE pari
    # « gagner souvent » demandé (Multi en 7 ≈ 30-70% de toucher sur un bon champ).
    if est_multi and len(by_p1) >= 4:
        _label = "Mini Multi" if is_mini else "Multi"
        for n in range(4, min(7, len(by_p1)) + 1):
            sel = list(by_p1[:n])
            p_mod = sim.p_coverage(sel, 4)
            p_mkt = sim_m.p_coverage(sel, 4)
            # en 4/5 → coup (gros rapport) ; en 6/7 → rendement (fréquent, filet large).
            niv = "coup" if n <= 5 else "rendement"
            nums = ",".join(str(numeros[i]) for i in sel)
            add(niv, f"{_label} en {n}", sel, p_mod, p_mkt,
                f"{_label} en {n} — N°{nums} : les 4 PREMIERS (ordre indifférent) parmi "
                f"ces {n} chevaux. " + ("Gros rapport (champ serré)." if n <= 5
                                        else f"Large filet — {p_mod*100:.0f}% de toucher."))

    # ── PICK5 (top-5 DÉSORDRE, sans bonus, mise 1€) ──────────────────────────────
    # Champ tendu (5) = gros lot ; champ 6/7 = couverture désordre plus probable.
    if est_pick5 and len(by_p1) >= 5:
        for n in range(5, min(7, len(by_p1)) + 1):
            sel = list(by_p1[:n])
            p_mod = sim.p_coverage(sel, 5)
            p_mkt = sim_m.p_coverage(sel, 5)
            nums = ",".join(str(numeros[i]) for i in sel)
            add("coup", "Pick5", sel, p_mod, p_mkt,
                f"Pick5 — N°{nums} : les 5 PREMIERS dans le désordre"
                + (f" (champ {n}, plus de chances de toucher)" if n > 5 else "") + ".")

    niv_order = {"securite": 0, "rendement": 1, "surprise": 2, "coup": 3}
    cands.sort(key=lambda c: (niv_order.get(c["niveau"], 9), -c["ev"]))
    return cands


# ──────────────────────────────────────────────────────────────────────────────
# Couverture JACKPOT (base + champ) — viser les gros rapports
# ──────────────────────────────────────────────────────────────────────────────
# Mise unitaire de base par combinaison (€), avant Flexi.
_JACKPOT_UNIT = 2.0
# Plancher Flexi (PMU autorise des fractions ; on ne descend pas sous 10%).
_FLEXI_MIN = 0.10
# Plafond du rapport estimé (les rapports jackpot peuvent être énormes mais on
# borne pour ne pas afficher une espérance non crédible sur proba minuscule).
_RAPPORT_MAX_JACKPOT = 100000.0


def build_coverage_bets(
    predictions: list[dict],
    course_info: dict,
    bankroll: float = 100.0,
    budget: float | None = None,
    n_sims: int = N_SIMS,
) -> dict:
    """Propose une COUVERTURE multi-combinaisons pour viser les jackpots.

    Pour chaque pari jackpot disponible (Tiercé / Quarté+ / Quinté+ désordre,
    2sur4), on construit une sélection de N chevaux (base des favoris modèle +
    champ) et on calcule, par simulation Plackett-Luce :
      - proba_gain  = P(les k arrivants du top-k ⊆ sélection)   [réelle, pas inventée]
      - n_combinaisons = C(N, k)
      - coût = n_combis × mise_unitaire × flexi   (Flexi calé sur le budget)
      - rapport_estime = TRJ / proba_marché de la combinaison MODALE (≈ gain par €)
      - ev = proba_gain × rapport / n_combis − 1   (espérance nette du ticket)

    On émet, par type, une version « tendue » (N = k) et une « couverture élargie »
    (N = k+1 ou k+2 selon budget). Aucune valeur fabriquée : tout dérive des probas
    du modèle, des cotes marché et des TRJ réels.

    Retour : {proposals:[...], coup_a_tenter: {...}|None}.
    """
    parts = [p for p in predictions if (p.get("cote_pmu") or 0) > 1.0]
    if len(parts) < 3:
        return {"proposals": [], "coup_a_tenter": None}

    p1 = np.array([max(float(p.get("proba_top1") or 0.0), 1e-4) for p in parts])
    p1 = p1 / p1.sum()
    cotes = np.array([float(p.get("cote_pmu") or 10.0) for p in parts])
    numeros = [int(p["numero"]) for p in parts]
    noms = [p.get("nom", "") for p in parts]

    pm = 1.0 / np.clip(cotes, 1.01, None)
    pm = pm / pm.sum()
    p1 = _cap_model_probas(p1, pm, cotes)   # cap 1.55× marché sur cote ≥ 4 (flag)

    order = simulate_orderings(p1, n_sims=n_sims, seed=12345)
    sim = _Sim(order, len(parts))
    order_m = simulate_orderings(pm, n_sims=n_sims, seed=67890)
    sim_m = _Sim(order_m, len(parts))

    by_p1 = list(np.argsort(-p1))      # favoris modèle
    by_pm = list(np.argsort(-pm))      # favoris marché (pour le rapport modal)
    implied = pm
    edge_by_idx = p1 - implied

    nb_partants = course_info.get("nb_partants", len(parts))
    fl_cov = _bet_flags(course_info)
    est_quinte = bool(fl_cov.get("est_quinte"))
    est_quarte = bool(fl_cov.get("est_quarte"))
    est_tierce = bool(fl_cov.get("est_tierce"))
    est_2sur4 = bool(fl_cov.get("est_2sur4"))   # 2sur4 réellement offert PMU
    est_multi = bool(fl_cov.get("est_multi"))   # Multi (top-4 désordre, champ 4→7)
    est_pick5 = bool(fl_cov.get("est_pick5"))   # Pick5 (top-5 désordre)
    is_mini = est_multi and 10 <= int(nb_partants or 0) <= 13

    budget = budget if budget and budget > 0 else max(bankroll * 0.10, 10.0)

    def H(i):
        return {"numero": numeros[i], "nom": noms[i], "cote": round(float(cotes[i]), 1)}

    proposals: list[dict] = []

    def add_coverage(label, k, trj, n_sel):
        """Ajoute une proposition de couverture de N=n_sel chevaux pour un top-k."""
        if n_sel < k or len(by_p1) < n_sel:
            return
        sel = list(by_p1[:n_sel])
        p_model = sim.p_coverage(sel, k)
        if p_model <= 0:
            return
        n_combis = math.comb(n_sel, k)
        # Rapport ≈ TRJ / proba marché de la combinaison MODALE (le top-k marché).
        sel_m = list(by_pm[:k])
        p_market_modal = max(sim_m.p_coverage(sel_m, k), 1e-5)
        rapport = float(min(max(trj / p_market_modal, 1.1), _RAPPORT_MAX_JACKPOT))
        # Flexi calé sur le budget : full_cost = n_combis × unit
        full_cost = n_combis * _JACKPOT_UNIT
        flexi = 1.0 if full_cost <= budget else max(_FLEXI_MIN, budget / full_cost)
        unit_eff = _JACKPOT_UNIT * flexi
        cout_total = max(round(n_combis * unit_eff, 2), 2.0)
        gain_potentiel = round(rapport * unit_eff, 2)        # gain de la combi gagnante
        ev = float(p_model * rapport / n_combis - 1.0)
        niveau = "jackpot" if n_sel == k else "couverture"
        couv = "tendue" if n_sel == k else f"champ {n_sel} chevaux"
        proposals.append({
            "niveau": niveau,
            "type_pari": f"{label} Désordre",
            "couverture": couv,
            "chevaux": [H(i) for i in sel],
            "proba_gain": round(p_model, 4),
            "nb_combinaisons": int(n_combis),
            "flexi_pct": round(flexi * 100),
            "mise_unitaire": round(unit_eff, 2),
            "cout_total": cout_total,
            "rapport_estime": round(rapport, 1),
            "gain_potentiel": gain_potentiel,
            "ev": round(ev, 3),
            "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
            "texte_explication": (
                f"{label} {couv} — N°{','.join(str(numeros[i]) for i in sel)} "
                f"({n_combis} comb." + (f", Flexi {round(flexi*100)}%" if flexi < 1 else "")
                + f") · {p_model*100:.1f}% de toucher · gain ~{gain_potentiel:.0f}€."
            ),
        })

    # ── Tiercé désordre (k=3) : tendu (3) + couverture (4, 5) ──
    if est_tierce or est_quarte or est_quinte:
        for n_sel in (3, 4, 5):
            add_coverage("Tiercé", 3, TRJ["Trio"], n_sel)
    # ── Quarté+ désordre (k=4) : tendu (4) + couverture (5, 6) ──
    if est_quarte or est_quinte:
        for n_sel in (4, 5, 6):
            add_coverage("Quarté+", 4, TRJ["Quarté+ Désordre"], n_sel)
    # ── Quinté+ désordre (k=5) : tendu (5) + couverture (6, 7) ──
    if est_quinte:
        for n_sel in (5, 6, 7):
            add_coverage("Quinté+", 5, TRJ["Quinté+ Désordre"], n_sel)

    # ── 2sur4 (≥ 2 des 4 favoris dans le top-4) ── (si offert par le PMU)
    if est_2sur4 and len(by_p1) >= 4:
        sel = list(by_p1[:4])
        p_model = sim.p_2sur4(sel)
        p_market = max(sim_m.p_2sur4(sel), 1e-4)
        rapport = float(min(max(TRJ["2sur4"] / p_market, 1.1), 5000.0))
        cout = max(round(math.comb(4, 2) * _JACKPOT_UNIT, 2), 2.0)
        proposals.append({
            "niveau": "couverture",
            "type_pari": "2sur4",
            "couverture": "4 chevaux",
            "chevaux": [H(i) for i in sel],
            "proba_gain": round(p_model, 4),
            "nb_combinaisons": math.comb(4, 2),
            "flexi_pct": 100,
            "mise_unitaire": _JACKPOT_UNIT,
            "cout_total": cout,
            "rapport_estime": round(rapport, 1),
            "gain_potentiel": round(rapport * _JACKPOT_UNIT, 2),
            "ev": round(float(p_model * rapport / math.comb(4, 2) - 1.0), 3),
            "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
            "texte_explication": (
                f"2sur4 — 2 des N°{','.join(str(numeros[i]) for i in sel)} dans les 4 "
                f"premiers · {p_model*100:.0f}% de toucher."
            ),
        })

    # ── MULTI (top-4 désordre, champ 4→7, mise plate) — « gagner souvent » ──
    if est_multi and len(by_p1) >= 4:
        _label = "Mini Multi" if is_mini else "Multi"
        for n in range(4, min(7, len(by_p1)) + 1):
            sel = list(by_p1[:n])
            p_model = sim.p_coverage(sel, 4)
            if p_model <= 0:
                continue
            p_market = max(sim_m.p_coverage(sel, 4), 1e-4)
            rapport = float(min(max(TRJ["Multi"] / p_market, 1.1), 5000.0))
            niveau = "jackpot" if n == 4 else "couverture"
            proposals.append({
                "niveau": niveau,
                "type_pari": f"{_label} en {n}",
                "couverture": f"{n} chevaux",
                "chevaux": [H(i) for i in sel],
                "proba_gain": round(p_model, 4),
                "nb_combinaisons": 1,            # mise PLATE : le PMU couvre toutes les combis
                "flexi_pct": 100,
                "mise_unitaire": MULTI_UNIT,
                "cout_total": MULTI_UNIT,
                "rapport_estime": round(rapport, 1),
                "gain_potentiel": round(rapport * MULTI_UNIT, 2),
                "ev": round(float(p_model * rapport - 1.0), 3),
                "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
                "texte_explication": (
                    f"{_label} en {n} — N°{','.join(str(numeros[i]) for i in sel)} : les 4 "
                    f"premiers (désordre) dans ces {n} chevaux · {p_model*100:.0f}% de toucher "
                    f"· gain ~{rapport*MULTI_UNIT:.0f}€ pour {MULTI_UNIT:.0f}€."
                ),
            })

    # ── PICK5 (top-5 désordre, mise 1€, sans bonus) ──
    if est_pick5 and len(by_p1) >= 5:
        for n in range(5, min(7, len(by_p1)) + 1):
            sel = list(by_p1[:n])
            p_model = sim.p_coverage(sel, 5)
            if p_model <= 0:
                continue
            p_market = max(sim_m.p_coverage(sel, 5), 1e-5)
            rapport = float(min(max(TRJ["Pick5"] / p_market, 1.1), _RAPPORT_MAX_JACKPOT))
            n_combis = math.comb(n, 5)
            cout = round(n_combis * PICK5_UNIT, 2)
            proposals.append({
                "niveau": "jackpot" if n == 5 else "couverture",
                "type_pari": "Pick5",
                "couverture": f"{n} chevaux",
                "chevaux": [H(i) for i in sel],
                "proba_gain": round(p_model, 4),
                "nb_combinaisons": int(n_combis),
                "flexi_pct": 100,
                "mise_unitaire": PICK5_UNIT,
                "cout_total": cout,
                "rapport_estime": round(rapport, 1),
                "gain_potentiel": round(rapport * PICK5_UNIT, 2),
                "ev": round(float(p_model * rapport / n_combis - 1.0), 3),
                "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
                "texte_explication": (
                    f"Pick5 (champ {n}) — N°{','.join(str(numeros[i]) for i in sel)} : les 5 "
                    f"premiers dans le désordre · {p_model*100:.1f}% de toucher."
                ),
            })

    # Tri : niveau (jackpot tendu d'abord) puis EV décroissante
    niv_order = {"jackpot": 0, "couverture": 1}
    proposals.sort(key=lambda c: (niv_order.get(c["niveau"], 9), -c["ev"]))

    # ── « Coup à tenter » : meilleur EV sur un outsider à VRAIE valeur (edge>0,
    # cote ≥ 6) — Simple Gagnant ou Couplé Gagnant favori+outsider. Honnête : on
    # n'invente pas, on prend la combi à plus forte espérance crédible.
    coup = _best_coup(parts, p1, pm, cotes, numeros, noms, edge_by_idx, by_p1, sim, sim_m)

    return {"proposals": proposals, "coup_a_tenter": coup}


def _best_coup(parts, p1, pm, cotes, numeros, noms, edge_by_idx, by_p1, sim, sim_m):
    """Sélectionne le meilleur « coup » : outsider (cote ≥ 6) que le modèle aime plus
    que le marché (edge > 0), en Simple Gagnant ou Couplé Gagnant favori+outsider.
    Retourne None si aucun candidat crédible."""
    outsiders = sorted(
        [i for i in range(len(parts)) if 6.0 <= cotes[i] <= 60.0 and edge_by_idx[i] > 0.005],
        key=lambda i: edge_by_idx[i], reverse=True,
    )
    if not outsiders:
        return None
    o = outsiders[0]
    candidates = []
    # Simple Gagnant outsider
    p_win = float(p1[o]); rap = float(cotes[o])
    candidates.append({
        "type_pari": "Simple Gagnant",
        "chevaux": [{"numero": numeros[o], "nom": noms[o], "cote": round(rap, 1)}],
        "proba_gain": round(p_win, 4), "rapport_estime": round(rap, 1),
        "ev": round(rap * p_win - 1.0, 3), "edge": round(float(edge_by_idx[o]), 4),
        "texte_explication": (
            f"N°{numeros[o]} {noms[o]} (cote {rap:.1f}) : le modèle le voit nettement "
            f"au-dessus du marché — {p_win*100:.0f}% de gagner, gain ~{rap:.0f}× la mise."
        ),
    })
    # Couplé Gagnant favori + outsider
    if by_p1 and by_p1[0] != o:
        fav = by_p1[0]
        p_cg = sim.p_couple_gagnant([fav, o])
        p_cg_m = max(sim_m.p_couple_gagnant([fav, o]), 1e-4)
        rap_cg = float(min(max(TRJ["Couplé Gagnant"] / p_cg_m, 1.1), 5000.0))
        if p_cg > 0:
            candidates.append({
                "type_pari": "Couplé Gagnant",
                "chevaux": [
                    {"numero": numeros[fav], "nom": noms[fav], "cote": round(float(cotes[fav]), 1)},
                    {"numero": numeros[o], "nom": noms[o], "cote": round(float(cotes[o]), 1)},
                ],
                "proba_gain": round(p_cg, 4), "rapport_estime": round(rap_cg, 1),
                "ev": round(p_cg * rap_cg - 1.0, 3), "edge": round(float(edge_by_idx[o]), 4),
                "texte_explication": (
                    f"Favori N°{numeros[fav]} + outsider à valeur N°{numeros[o]} aux 2 "
                    f"premières places — rapport ~{rap_cg:.0f}× pour {p_cg*100:.0f}%."
                ),
            })
    candidates.sort(key=lambda c: -c["ev"])
    best = candidates[0]
    # On ne propose un « coup » que s'il est crédible : EV non franchement négative
    # et rapport intéressant (≥ 5). Sinon pas de coup (intégrité, pas de faux espoir).
    if best["ev"] <= -0.40 or best["rapport_estime"] < 5.0:
        return None
    best["niveau"] = "coup"
    return best
