"""Probabilités d'arrivée Plackett-Luce — en FORME FERMÉE, sans Monte-Carlo.

Pourquoi ce module existe
─────────────────────────
`ml.combo_bets` estimait toutes les probabilités de combinaison par simulation :
20 000 tirages de Gumbel, avec une graine FIXE (12345 pour le modèle, 67890 pour le
marché). Deux défauts, et le second est le plus gênant :

1. **Précision sur les événements rares.** Mesuré sur 2 452 candidats produits par
   42 courses simulées (champs de 8 à 20 partants) : la probabilité MÉDIANE d'un
   candidat vaut 4,6 %, et 20 000 tirages y suffisent largement (1 % d'erreur
   relative). Le problème est la QUEUE, et deux types y descendent :

       type              n     médiane     1er décile   minimum   erreur à p10
       Couplé Gagnant   673    0,0194      0,0024       0,0000       14 %
       Trio             619    0,0133      0,0029       0,0000       13 %

   Le minimum est NUL : sur ces combinaisons, 20 000 tirages n'en produisent
   aucun, la probabilité ressort à zéro, et le pari est écarté pour une raison qui
   n'existe pas. Tous les autres types restent sous 4 % d'erreur au premier décile.

2. **La graine est fixe.** L'erreur de Monte-Carlo n'est donc PAS indépendante
   d'une course à l'autre : ce sont les mêmes 20 000 tirages partout, corrélés à
   la position dans le classement. Ce n'est pas du bruit qui se moyenne sur la
   saison, c'est un biais reproductible sur la SÉLECTION des paris.

Or pour les paris qui portent l'essentiel du catalogue — couplés, trios, tiercés,
quartés, quintés, Multi — la probabilité s'écrit EXACTEMENT :

    P(a 1er, b 2e, c 3e) = s_a/S · s_b/(S − s_a) · s_c/(S − s_a − s_b)

et une combinaison « dans le désordre » est la somme sur ses permutations. Zéro
variance, plus rapide que 20 000 tirages, et reproductible au bit près.

Le biais de Harville, et comment on le corrige
──────────────────────────────────────────────
Prendre les probabilités de VICTOIRE comme forces reproduit exactement la première
place, mais surestime systématiquement les places 2 et 3 du favori et sous-estime
celles des outsiders. C'est le biais de Harville, documenté depuis Henery (1981) et
Stern (1990) : la course pour la deuxième place n'obéit pas à la même hiérarchie que
celle pour la première.

La correction usuelle est un EXPOSANT par position : à la position j, les forces
valent `s^λ_j` avec `λ_1 = 1 ≥ λ_2 ≥ λ_3`. λ < 1 aplatit la hiérarchie — le favori
garde sa domination sur la victoire, mais la perd en partie sur les accessits.

Les exposants ne sont PAS inventés ici : ils valent 1,0 par défaut (soit exactement
le comportement du Plackett-Luce nu) et sont appris chaque nuit sur les arrivées
réelles, par `ml.harville_calibration`. Sans mesure, aucune correction.

Note d'implémentation — pourquoi du Python nu et pas du numpy
─────────────────────────────────────────────────────────────
Les champs font huit à vingt partants et les sommes portent sur deux à cinq
positions. À cette taille, le coût d'un appel numpy (allocation, indexation
fantaisiste) dépasse largement celui de l'arithmétique elle-même : une première
version en numpy rendait le moteur de plan 3,6× PLUS LENT que la simulation qu'elle
remplaçait. Les forces sont donc converties une fois en listes de flottants
Python, et les boucles internes n'allouent plus rien.
"""
from __future__ import annotations

from itertools import combinations, permutations
from typing import Optional, Sequence

import numpy as np

__all__ = [
    "ForcesPL",
    "forces_par_position",
    "p_ordre_exact",
    "p_ensemble_topk",
    "p_couverture_topk",
    "p_dans_topk",
    "p_dans_topk_tous",
    "p_tous_dans_topk",
    "EXPOSANTS_NEUTRES",
]

# Exposant par position, la première toujours à 1.0 : à force égale sur la victoire,
# ne rien changer. `EXPOSANTS_NEUTRES` reproduit le Plackett-Luce nu (Harville).
EXPOSANTS_NEUTRES: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0)

_EPS = 1e-12


class ForcesPL:
    """Forces `s^λ_j` par position, prêtes pour des sommes de permutations.

    Préparé une fois par course : les totaux par position sont pré-calculés, et les
    forces vivent en listes Python — cf. la note d'implémentation du module.
    """

    __slots__ = ("sp", "totaux", "n", "n_positions")

    def __init__(self, sp: list[list[float]]):
        self.sp = sp
        self.totaux = [sum(ligne) for ligne in sp]
        self.n_positions = len(sp)
        self.n = len(sp[0]) if sp else 0

    def ligne(self, rang: int) -> list[float]:
        return self.sp[min(rang, self.n_positions - 1)]

    def total(self, rang: int) -> float:
        return self.totaux[min(rang, self.n_positions - 1)]

    # Compatibilité tableau : `np.allclose(ForcesPL, ...)` et l'indexation restent
    # possibles dans les tests et le diagnostic.
    def __array__(self, dtype=None):
        a = np.asarray(self.sp, dtype=float)
        return a.astype(dtype) if dtype is not None else a

    def __getitem__(self, item):
        return np.asarray(self.sp, dtype=float)[item]

    @property
    def shape(self):
        return (self.n_positions, self.n)


def forces_par_position(forces: Sequence[float],
                        exposants: Optional[Sequence[float]] = None,
                        n_positions: int = 5) -> ForcesPL:
    """Forces `s^λ_j`, une ligne par position, avec leurs totaux."""
    s = np.clip(np.asarray(forces, dtype=float), _EPS, None)
    exps = list(exposants if exposants is not None else EXPOSANTS_NEUTRES)
    if not exps:
        exps = [1.0]
    while len(exps) < n_positions:
        exps.append(exps[-1])       # au-delà des positions mesurées, on prolonge
    lignes = []
    for j in range(n_positions):
        lam = float(exps[j])
        lignes.append((s if lam == 1.0 else s ** lam).tolist())
    return ForcesPL(lignes)


def p_ordre_exact(sp: ForcesPL, ordre: Sequence[int]) -> float:
    """P(les chevaux de `ordre` finissent exactement dans cet ordre-là).

    Produit des tirages successifs sans remise. Le dénominateur de chaque position
    est le total de SA ligne moins les chevaux déjà placés — recalculé par position
    parce que les forces changent d'une position à l'autre quand λ ≠ 1.
    """
    p = 1.0
    places: list[int] = []
    for rang, cheval in enumerate(ordre):
        ligne = sp.ligne(rang)
        reste = sp.total(rang)
        for deja in places:
            reste -= ligne[deja]
        if reste <= _EPS:
            return 0.0
        p *= ligne[cheval] / reste
        if p <= 0.0:
            return 0.0
        places.append(cheval)
    return p


def p_ensemble_topk(sp: ForcesPL, selection: Sequence[int]) -> float:
    """P(les chevaux de `selection` occupent les |selection| premières places,
    dans n'importe quel ordre) — somme sur les k! permutations.

    k! vaut 2, 6, 24 ou 120 : la somme est exacte et coûte moins que 20 000 tirages.
    """
    sel = list(dict.fromkeys(int(i) for i in selection))
    if not sel:
        return 0.0
    return float(sum(p_ordre_exact(sp, perm) for perm in permutations(sel)))


def p_couverture_topk(sp: ForcesPL, selection: Sequence[int], k: int) -> float:
    """P(les k premiers sont TOUS dans `selection`) — couverture « désordre ».

    C'est la mécanique du Multi et du Pick5 : on choisit n ≥ k chevaux, le ticket
    gagne si les k premières places leur reviennent toutes. Somme sur les C(n, k)
    sous-ensembles, chacun sur ses k! ordres.
    """
    sel = list(dict.fromkeys(int(i) for i in selection))
    if k <= 0 or len(sel) < k:
        return 0.0
    return float(sum(p_ensemble_topk(sp, sous) for sous in combinations(sel, k)))


def p_dans_topk_tous(sp: ForcesPL, k: int) -> list[float]:
    """P(chaque cheval finit dans les k premiers) — POUR TOUS d'un coup, k ≤ 3.

    Calculer cheval par cheval refaisait n fois les mêmes sommes sur les vainqueurs
    et les paires de tête : O(n³) au total pour k = 3. Ici on les factorise, et le
    coût retombe à O(n²).
    """
    if k > 3:
        raise ValueError("p_dans_topk : k ≤ 3 (au-delà, préférer la simulation)")
    n = sp.n
    l1, l2, l3 = sp.ligne(0), sp.ligne(1), sp.ligne(2)
    t1, t2, t3 = sp.total(0), sp.total(1), sp.total(2)
    if t1 <= _EPS:
        return [0.0] * n

    p = [l1[i] / t1 for i in range(n)]
    if k == 1:
        return p

    # Position 2 : pour chaque vainqueur a, chaque i ≠ a peut prendre la deuxième.
    for a in range(n):
        pa = l1[a] / t1
        if pa <= 0.0:
            continue
        reste2 = t2 - l2[a]
        if reste2 <= _EPS:
            continue
        facteur = pa / reste2
        for i in range(n):
            if i != a:
                p[i] += facteur * l2[i]
    if k == 2:
        return p

    # Position 3 : sur chaque paire de tête ordonnée (a, b).
    for a in range(n):
        pa = l1[a] / t1
        if pa <= 0.0:
            continue
        reste2 = t2 - l2[a]
        if reste2 <= _EPS:
            continue
        for b in range(n):
            if b == a:
                continue
            pab = pa * l2[b] / reste2
            if pab <= 0.0:
                continue
            reste3 = t3 - l3[a] - l3[b]
            if reste3 <= _EPS:
                continue
            facteur = pab / reste3
            for i in range(n):
                if i != a and i != b:
                    p[i] += facteur * l3[i]
    return p


def p_dans_topk(sp: ForcesPL, cheval: int, k: int) -> float:
    """P(ce cheval finit dans les k premiers), k ≤ 3."""
    return float(p_dans_topk_tous(sp, k)[int(cheval)])


def p_tous_dans_topk(sp: ForcesPL, selection: Sequence[int], k: int) -> float:
    """P(TOUS les chevaux de `selection` finissent dans les k premiers), k ≤ 3.

    C'est le Couplé Placé (deux chevaux dans les places payées). Chaque arrivée est
    décrite UNE SEULE FOIS par le triplet (positions occupées par la sélection,
    ordre de la sélection sur ces positions, remplissage ordonné des places
    restantes) : C(k,m) × m! × A(n−m, k−m) termes distincts.
    """
    sel = list(dict.fromkeys(int(i) for i in selection))
    if len(sel) > k:
        return 0.0
    if k > 3:
        raise ValueError("p_tous_dans_topk : k ≤ 3 (au-delà, préférer la simulation)")
    autres = [i for i in range(sp.n) if i not in sel]
    manquants = k - len(sel)
    total = 0.0
    for places in permutations(sel):
        if manquants == 0:
            total += p_ordre_exact(sp, places)
            continue
        for positions in combinations(range(k), len(places)):
            for remplissage in permutations(autres, manquants):
                arrivee: list[Optional[int]] = [None] * k
                for pos, cheval in zip(positions, places):
                    arrivee[pos] = cheval
                libres = [i for i in range(k) if arrivee[i] is None]
                for pos, cheval in zip(libres, remplissage):
                    arrivee[pos] = cheval
                total += p_ordre_exact(sp, [c for c in arrivee if c is not None])
    return float(total)
