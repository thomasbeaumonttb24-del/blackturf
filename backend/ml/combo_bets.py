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
        # Rapport pari-mutuel ≈ TRJ / proba_marché de la combinaison. On plancher la
        # proba marché (1e-3) et on plafonne le rapport : sinon une proba simulée
        # minuscule fait exploser le rapport → EV absurde (+19000%) non crédible.
        trj = TRJ.get(type_pari, 0.70)
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
        trj = TRJ.get(type_pari, 0.80 if "Simple" in type_pari else 0.70)
        rapport = float(min(max(trj / max(p_market, 1e-3), 1.1), 5000.0))
        cands.append({
            "niveau": niveau,
            "type_pari": type_pari,
            "chevaux": [H(i) for i in sel],
            "proba_gain": round(float(proba), 4),
            "rapport_estime": round(rapport, 1),
            "ev": round(_ev(proba, rapport), 3),
            "edge": round(float(sum(edge_by_idx[i] for i in sel) / len(sel)), 4),
            "texte_explication": texte,
        })

    nb_partants = course_info.get("nb_partants", len(parts))
    est_quinte = bool(course_info.get("est_quinte"))
    est_quarte = bool(course_info.get("est_quarte"))
    est_tierce = bool(course_info.get("est_tierce"))

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
        if edge_pl <= 0 and ev <= 0:                  # ni valeur ni EV → on ne propose pas
            continue
        key = ("Simple Placé", (i,))
        if key in seen:
            continue
        seen.add(key)
        cands.append({
            "niveau": "securite", "type_pari": "Simple Placé", "chevaux": [H(i)],
            "proba_gain": round(p_pl, 4), "rapport_estime": round(rapport, 1),
            "ev": round(ev, 3), "edge": round(float(edge_pl), 4),
            "texte_explication": (
                f"N°{numeros[i]} {noms[i]} placé à VALEUR — {p_pl*100:.0f}% d'être dans "
                f"les 3 (cote {cotes[i]:.1f}, rapport ~{rapport:.1f}×) : le modèle le place "
                f"plus haut que le marché."
            ),
        })

    # ── 3-4 COUPLÉ GAGNANT différents ──
    pairs = []
    if len(by_p1) >= 2: pairs.append((by_p1[0], by_p1[1]))
    if len(by_p1) >= 3: pairs.append((by_p1[0], by_p1[2]))
    if len(by_p1) >= 3: pairs.append((by_p1[1], by_p1[2]))
    if out1 is not None: pairs.append((by_p1[0], out1))   # favori + surprise
    for a, b in pairs:
        niv = "surprise" if (out1 is not None and b == out1) else "rendement"
        add(niv, "Couplé Gagnant", [a, b], sim.p_couple_gagnant([a, b]), sim_m.p_couple_gagnant([a, b]),
            f"N°{numeros[a]} + N°{numeros[b]} aux 2 premières places.")

    # ── Couplé Placé (sécurité) ──
    if len(by_p1) >= 2:
        add("securite", "Couplé Placé", [by_p1[0], by_p1[1]],
            sim.p_couple_place([by_p1[0], by_p1[1]]), sim_m.p_couple_place([by_p1[0], by_p1[1]]),
            f"N°{numeros[by_p1[0]]} + N°{numeros[by_p1[1]]} tous deux dans les 3 premiers.")
    if len(by_p1) >= 3:
        add("securite", "Couplé Placé", [by_p1[0], by_p1[2]],
            sim.p_couple_place([by_p1[0], by_p1[2]]), sim_m.p_couple_place([by_p1[0], by_p1[2]]),
            f"N°{numeros[by_p1[0]]} + N°{numeros[by_p1[2]]} tous deux dans les 3 premiers.")
    # Couplé Placé favori + OUTSIDER à valeur : placer une grosse cote dans le top-3.
    if out1 is not None and by_p1 and out1 != by_p1[0]:
        add("surprise", "Couplé Placé", [by_p1[0], out1],
            sim.p_couple_place([by_p1[0], out1]), sim_m.p_couple_place([by_p1[0], out1]),
            f"Favori N°{numeros[by_p1[0]]} + outsider N°{numeros[out1]} (cote {cotes[out1]:.1f}) "
            f"tous deux placés — placement d'une grosse cote.")

    # ── Trios (favoris + surprise) ──
    trios = []
    if len(by_p1) >= 3: trios.append((by_p1[0], by_p1[1], by_p1[2]))
    if len(by_p1) >= 4: trios.append((by_p1[0], by_p1[1], by_p1[3]))
    if out1 is not None and len(by_p1) >= 2: trios.append((by_p1[0], by_p1[1], out1))
    for t in trios:
        niv = "surprise" if (out1 is not None and out1 in t) else "coup"
        add(niv, "Trio", list(t), sim.p_trio(list(t)), sim_m.p_trio(list(t)),
            f"N°{'+N°'.join(str(numeros[i]) for i in t)} aux 3 premières places (sans ordre).")

    # ── 2sur4 ──
    if len(by_p1) >= 4 and nb_partants >= 8:
        sel = list(by_p1[:4])
        add("rendement", "2sur4", sel, sim.p_2sur4(sel), sim_m.p_2sur4(sel),
            f"2 des 4 chevaux N°{','.join(str(numeros[i]) for i in sel)} dans les 4 premiers.")
        # 2sur4 avec OUTSIDER : 3 favoris + une grosse cote à valeur → vise le
        # placement d'un outsider dans le top-4 (gain rehaussé, proba encore bonne).
        if out1 is not None and out1 not in by_p1[:3]:
            sel_o = list(by_p1[:3]) + [out1]
            add("surprise", "2sur4", sel_o, sim.p_2sur4(sel_o), sim_m.p_2sur4(sel_o),
                f"3 favoris + outsider N°{numeros[out1]} (cote {cotes[out1]:.1f}) — 2 dans "
                f"les 4 premiers (placement grosse cote dans le top-4).")

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

    order = simulate_orderings(p1, n_sims=n_sims, seed=12345)
    sim = _Sim(order, len(parts))
    order_m = simulate_orderings(pm, n_sims=n_sims, seed=67890)
    sim_m = _Sim(order_m, len(parts))

    by_p1 = list(np.argsort(-p1))      # favoris modèle
    by_pm = list(np.argsort(-pm))      # favoris marché (pour le rapport modal)
    implied = pm
    edge_by_idx = p1 - implied

    nb_partants = course_info.get("nb_partants", len(parts))
    est_quinte = bool(course_info.get("est_quinte"))
    est_quarte = bool(course_info.get("est_quarte"))
    est_tierce = bool(course_info.get("est_tierce"))

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

    # ── 2sur4 (≥ 2 des 4 favoris dans le top-4) ──
    if nb_partants >= 8 and len(by_p1) >= 4:
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
