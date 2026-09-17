"""Le modèle de VICTOIRE produit la cote juste affichée : la promotion nocturne doit
refuser un challenger dont la cote juste servie est PROUVÉE moins juste — et
seulement dans ce cas (un contrôle qui bloque sur du bruit gèle le modèle)."""
import math

import numpy as np
import pytest

from ml import pipeline as pl

BASE = dict(current_is_synth=False, no_current=False, current_unreliable=False, data_jump=False)


def _hold(n_courses=400, partants=8, seed=0):
    rng = np.random.default_rng(seed)
    groupes, y, force = [], [], []
    for c in range(n_courses):
        f = rng.gamma(2.0, 1.0, partants)
        g = rng.choice(partants, p=f / f.sum())
        groupes += [f"c{c}"] * partants
        y += [1 if i == g else 0 for i in range(partants)]
        force += list(f)
    return np.array(force), np.array(y), np.array(groupes)


def test_vraisemblance_par_course_de_la_proba_normalisee():
    ll = pl._vraisemblance_victoire([0.2, 0.6, 0.2, 0.5, 0.5], [0, 1, 0, 1, 0],
                                    ["a", "a", "a", "b", "b"], None, None)
    assert ll["a"] == pytest.approx(-math.log(0.6))
    assert ll["b"] == pytest.approx(-math.log(0.5))


def test_course_sans_gagnant_unique_ignoree():
    ll = pl._vraisemblance_victoire([0.5, 0.5], [0, 0], ["a", "a"], None, None)
    assert ll == {}


def test_le_melange_en_service_est_applique():
    ll = pl._vraisemblance_victoire([0.5, 0.5], [1, 0], ["a", "a"], [2.0, 4.0], (0.0, 1.0))
    q = (1 / 2.0) / (1 / 2.0 + 1 / 4.0)
    assert ll["a"] == pytest.approx(-math.log(q))


def test_un_modele_de_victoire_nettement_moins_juste_bloque():
    force, y, g = _hold()
    bon = pl._vraisemblance_victoire(force, y, g, None, None)
    bruit = pl._vraisemblance_victoire(np.ones_like(force), y, g, None, None)
    ecart = pl._ecart_victoire(bon, bruit)           # challenger = bruit
    assert ecart["moyenne"] < 0 and ecart["ic95"][1] < 0
    assert pl._victoire_bloque(ecart) is True
    assert pl._should_deploy(0.79, 0.79, **BASE, h2h_delta=+0.01, victoire_bloque=True) is False
    # Remplacement structurel : jamais bloqué.
    assert pl._should_deploy(0.79, 0.79, **{**BASE, "current_is_synth": True},
                             victoire_bloque=True) is True


def test_un_ecart_non_prouve_ne_bloque_pas():
    force, y, g = _hold()
    a = pl._vraisemblance_victoire(force, y, g, None, None)
    b = pl._vraisemblance_victoire(force * 1.0001, y, g, None, None)
    assert pl._victoire_bloque(pl._ecart_victoire(a, b)) is False
    assert pl._victoire_bloque(None) is False
    # Trop peu de courses : pas de mesure.
    petit = {k: v for k, v in list(a.items())[:50]}
    assert pl._ecart_victoire(petit, petit) is None
