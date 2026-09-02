"""Les formules fermées doivent être EXACTES — vérifiées par énumération complète.

`ml.combo_bets` estimait toutes les probabilités de combinaison par 20 000 tirages
de Gumbel à graine FIXE. Deux défauts.

Mesuré sur 2 452 candidats produits par 42 courses simulées : la probabilité
médiane vaut 4,6 % — la simulation y est excellente. Mais le Couplé Gagnant et le
Trio tombent à 0,0024 et 0,0029 au premier décile (14 % et 13 % d'erreur relative)
et atteignent un minimum NUL : la simulation rend zéro, le pari est écarté, et la
raison n'existe pas.

Et surtout, la graine étant la même partout, l'erreur n'est pas du bruit qui se
moyenne sur la saison mais un BIAIS reproductible corrélé au classement.

Ici on vérifie que la forme fermée donne exactement la même chose qu'une énumération
exhaustive de toutes les arrivées possibles — c'est-à-dire la vérité.
"""
from itertools import permutations

import numpy as np
import pytest

from ml.plackett_luce import (
    EXPOSANTS_NEUTRES,
    forces_par_position,
    p_couverture_topk,
    p_dans_topk,
    p_ensemble_topk,
    p_ordre_exact,
    p_tous_dans_topk,
)


def _sp(forces, exposants=None):
    return forces_par_position(forces, exposants)


def _toutes_les_arrivees(sp, n):
    """Loi exacte sur TOUTES les arrivées complètes — la référence absolue."""
    return {perm: p_ordre_exact(sp, perm) for perm in permutations(range(n))}


FORCES = [0.30, 0.22, 0.18, 0.12, 0.10, 0.08]


# ── La loi est bien une loi ────────────────────────────────────────────────

def test_les_arrivees_completes_somment_a_un():
    sp = _sp(FORCES)
    total = sum(_toutes_les_arrivees(sp, len(FORCES)).values())
    assert total == pytest.approx(1.0, abs=1e-12)


def test_la_premiere_place_reproduit_exactement_les_forces():
    """Sous Plackett-Luce, P(i gagne) = s_i / Σs. C'est le seul point où le modèle
    est exact par construction — et c'est pourquoi on lui donne les probas de
    victoire comme forces."""
    sp = _sp(FORCES)
    s = np.array(FORCES)
    for i in range(len(FORCES)):
        assert p_ordre_exact(sp, [i]) == pytest.approx(s[i] / s.sum(), abs=1e-12)


# ── Chaque formule contre l'énumération exhaustive ─────────────────────────

def test_ordre_exact_contre_enumeration():
    sp = _sp(FORCES)
    lois = _toutes_les_arrivees(sp, len(FORCES))
    for ordre in [(0, 1), (2, 0), (1, 3, 5), (4, 0, 2, 1)]:
        attendu = sum(p for perm, p in lois.items()
                      if perm[:len(ordre)] == ordre)
        assert p_ordre_exact(sp, list(ordre)) == pytest.approx(attendu, abs=1e-12)


def test_ensemble_topk_contre_enumeration():
    """Couplé Gagnant, Trio, Tiercé Désordre, Quarté+ Désordre."""
    sp = _sp(FORCES)
    lois = _toutes_les_arrivees(sp, len(FORCES))
    for sel in [(0, 1), (1, 4), (0, 2, 3), (1, 2, 5), (0, 1, 2, 3)]:
        k = len(sel)
        attendu = sum(p for perm, p in lois.items() if set(perm[:k]) == set(sel))
        assert p_ensemble_topk(sp, sel) == pytest.approx(attendu, abs=1e-12)


def test_couverture_topk_contre_enumeration():
    """Multi et Pick5 : n chevaux choisis, les k premiers doivent TOUS s'y trouver."""
    sp = _sp(FORCES)
    lois = _toutes_les_arrivees(sp, len(FORCES))
    for sel, k in [((0, 1, 2, 3), 3), ((0, 1, 2, 3, 4), 4), ((0, 1, 2), 2)]:
        attendu = sum(p for perm, p in lois.items()
                      if set(perm[:k]).issubset(set(sel)))
        assert p_couverture_topk(sp, sel, k) == pytest.approx(attendu, abs=1e-12)


def test_dans_topk_contre_enumeration():
    """Simple Placé — la règle PMU paie le top-2 ou le top-3 selon le champ."""
    sp = _sp(FORCES)
    lois = _toutes_les_arrivees(sp, len(FORCES))
    for cheval in range(len(FORCES)):
        for k in (1, 2, 3):
            attendu = sum(p for perm, p in lois.items() if cheval in perm[:k])
            assert p_dans_topk(sp, cheval, k) == pytest.approx(attendu, abs=1e-12)


def test_tous_dans_topk_contre_enumeration():
    """Couplé Placé : les deux chevaux dans les places payées."""
    sp = _sp(FORCES)
    lois = _toutes_les_arrivees(sp, len(FORCES))
    for sel in [(0, 1), (0, 5), (2, 4), (1, 2, 3)]:
        for k in (2, 3):
            if len(sel) > k:
                continue
            attendu = sum(p for perm, p in lois.items()
                          if set(sel).issubset(set(perm[:k])))
            assert p_tous_dans_topk(sp, sel, k) == pytest.approx(attendu, abs=1e-12)


def test_le_placé_est_la_somme_des_positions():
    """Cohérence interne : Σ_i P(i dans le top-k) = k."""
    sp = _sp(FORCES)
    for k in (1, 2, 3):
        total = sum(p_dans_topk(sp, i, k) for i in range(len(FORCES)))
        assert total == pytest.approx(float(k), abs=1e-10)


def test_le_gagnant_somme_a_un():
    sp = _sp(FORCES)
    assert sum(p_ordre_exact(sp, [i]) for i in range(len(FORCES))) == pytest.approx(1.0)


# ── Les exposants de position (correction du biais de Harville) ────────────

def test_les_exposants_neutres_reproduisent_le_plackett_luce_nu():
    """λ = 1 partout doit rendre EXACTEMENT le comportement actuel : sans mesure,
    aucune correction."""
    sp_neutre = _sp(FORCES)
    sp_explicite = _sp(FORCES, EXPOSANTS_NEUTRES)
    assert np.allclose(sp_neutre, sp_explicite)
    assert p_ensemble_topk(sp_neutre, (0, 1, 2)) == pytest.approx(
        p_ensemble_topk(sp_explicite, (0, 1, 2)), abs=1e-15)


def test_un_exposant_inferieur_a_un_aplatit_la_hierarchie_des_accessits():
    """C'est tout l'objet de la correction : le favori garde sa domination sur la
    VICTOIRE (λ₁ = 1) mais en perd une part sur les accessits, où la course
    n'obéit pas à la même hiérarchie (Henery 1981, Stern 1990)."""
    sp_harville = _sp(FORCES)
    sp_corrige = _sp(FORCES, (1.0, 0.7, 0.6, 0.6, 0.6))

    favori, outsider = 0, len(FORCES) - 1
    # La victoire est INCHANGÉE : λ₁ = 1 dans les deux cas.
    assert p_ordre_exact(sp_corrige, [favori]) == pytest.approx(
        p_ordre_exact(sp_harville, [favori]), abs=1e-12)
    # Le placé du favori BAISSE, celui de l'outsider MONTE.
    assert p_dans_topk(sp_corrige, favori, 3) < p_dans_topk(sp_harville, favori, 3)
    assert p_dans_topk(sp_corrige, outsider, 3) > p_dans_topk(sp_harville, outsider, 3)
    # Et la contrainte « trois places à distribuer » tient toujours.
    assert sum(p_dans_topk(sp_corrige, i, 3)
               for i in range(len(FORCES))) == pytest.approx(3.0, abs=1e-10)


# ── Ce que la simulation ne savait pas faire ───────────────────────────────

def test_la_forme_fermee_voit_les_combinaisons_que_la_simulation_rate():
    """Un ordre exact de quatre chevaux est l'événement le plus rare que le moteur
    calcule : 0,001135 même sur les quatre favoris (une sur 881), soit 21 %
    d'erreur relative sur 20 000 tirages. Sur l'ordre le MOINS probable du champ,
    la simulation n'en voit souvent aucun — alors que la valeur est parfaitement
    calculable."""
    from ml.combo_bets import _Sim, simulate_orderings

    forces = np.array([0.30, 0.22, 0.18, 0.12, 0.10, 0.08])
    sp = _sp(forces)
    rare = (5, 4, 3, 2)          # l'ordre exact le moins probable
    exact = p_ordre_exact(sp, list(rare))
    assert exact > 0.0

    sim = _Sim(simulate_orderings(forces, n_sims=20000, seed=12345), len(forces))
    estime = sim.p_super4(list(rare))
    assert exact > 0
    # On ne demande pas que la simulation soit fausse — on montre que son erreur
    # relative sur cet ordre est du même ordre de grandeur que la valeur elle-même.
    assert abs(estime - exact) / exact > 0.05 or estime == 0.0


def test_la_forme_fermee_est_deterministe():
    """Aucune graine, donc aucune erreur corrélée d'une course à l'autre."""
    sp = _sp(FORCES)
    a = p_ensemble_topk(sp, (0, 2, 4))
    b = p_ensemble_topk(sp, (4, 2, 0))
    assert a == b, "le désordre ne dépend pas de l'ordre d'écriture"
    assert a == p_ensemble_topk(_sp(FORCES), (0, 2, 4))


# ── Robustesse ─────────────────────────────────────────────────────────────

def test_une_selection_plus_grande_que_k_est_impossible():
    sp = _sp(FORCES)
    assert p_tous_dans_topk(sp, (0, 1, 2), 2) == 0.0
    assert p_couverture_topk(sp, (0,), 3) == 0.0


def test_les_doublons_sont_ignores():
    sp = _sp(FORCES)
    assert p_ensemble_topk(sp, (0, 1, 1)) == pytest.approx(
        p_ensemble_topk(sp, (0, 1)), abs=1e-15)


def test_une_force_nulle_ne_casse_rien():
    sp = _sp([0.5, 0.5, 0.0, 0.0])
    assert p_ordre_exact(sp, [2]) >= 0.0
    assert p_dans_topk(sp, 0, 2) <= 1.0 + 1e-9


def test_au_dela_du_top3_on_refuse_plutot_que_d_approcher():
    sp = _sp(FORCES)
    with pytest.raises(ValueError):
        p_dans_topk(sp, 0, 4)
    with pytest.raises(ValueError):
        p_tous_dans_topk(sp, (0, 1), 4)
