"""Le modèle de victoire lisait la cote (41 % de son importance, corrélation 0,92) :
un cheval sous-évalué par les parieurs le restait dans le classement.
`ml.modele_technique` apprend sans aucune information de marché. Ces tests
verrouillent ce qui fait sa promesse : il ne voit jamais la cote, son placement
reste une distribution cohérente, et il n'est servi que retenu."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import modele_technique as mt
from ml.models import COLONNES_MARCHE


def test_aucune_colonne_de_marche_n_est_apprise():
    colonnes = sorted(COLONNES_MARCHE | mt.COLONNES_PARIEURS | {
        "elo_global", "forme_5_courses", "risque_galop_trot", "course_id", "numero"})
    garde = mt.colonnes_techniques(colonnes)
    assert set(garde) == {"elo_global", "forme_5_courses", "risque_galop_trot"}
    assert COLONNES_MARCHE <= mt.COLONNES_PARIEURS


def test_le_placement_somme_a_trois_et_reste_borne():
    p3 = [0.95, 0.6, 0.4, 0.3, 0.2, 0.1, 0.05, 0.02]
    cotes = [1.3, 4.0, 6.0, 9.0, 12.0, 25.0, 40.0, 80.0]
    p = mt.probas_place(p3, cotes, [0.4, 0.7, -0.4, 2.0])
    assert p is not None
    assert float(p.sum()) == pytest.approx(3.0, abs=1e-6)
    assert (p <= 0.99 + 1e-12).all() and (p > 0).all()


def test_placement_petit_champ_et_entrees_invalides():
    p = mt.probas_place([0.9, 0.8, 0.7], [2.0, 3.0, 4.0], [0.4, 0.7, -0.4, 2.0])
    assert p is not None and (p <= 0.99 + 1e-12).all()
    assert mt.probas_place([0.5, 0.4], [2.0, None], [0.4, 0.7, -0.4, 2.0]) is None
    assert mt.probas_place([0.5, 0.4], [2.0, 3.0], [1, 2]) is None


def _courses_place(n, seed=5, informatif=True):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        k = int(rng.integers(7, 14))
        force = rng.normal(0, 1, k)
        bruit = rng.normal(0, 1, k)
        q = np.exp(0.8 * force + 0.5 * bruit)
        q /= q.sum()
        ordre = np.argsort(-(force + rng.gumbel(size=k)))
        top3 = np.zeros(k)
        top3[ordre[:3]] = 1
        signal = force if informatif else rng.normal(0, 1, k)
        p3 = 1 / (1 + np.exp(-(signal - 0.5)))
        servi = np.clip(q * 3 / q.sum(), 1e-4, 0.99)
        out.append({"p3": p3, "q": q, "cotes": list(1 / (q * 1.15)), "top3": top3,
                    "servi3": servi})
    return out


def test_un_placement_informatif_est_retenu_contre_la_cote():
    v = mt.evaluer_place(_courses_place(1200))
    assert v["retenu"] is True, v
    assert v["logloss_partant_nouveau"] < v["logloss_partant_servi"]


def test_sous_le_volume_minimal_le_placement_n_est_pas_retenu():
    v = mt.evaluer_place(_courses_place(mt.MIN_COURSES_VALIDATION - 50))
    assert v["retenu"] is False


def test_seuls_les_deux_etoiles_non_confirmes_sont_retrogrades():
    assert mt.confirmer_valeur(2, 0.08, 10.0) == (1, False)      # 0,8 < 1
    assert mt.confirmer_valeur(2, 0.12, 10.0) == (2, True)       # 1,2 ≥ 1
    assert mt.confirmer_valeur(4, 0.01, 10.0) == (4, None)       # ★★★★ jamais touché
    assert mt.confirmer_valeur(3, 0.01, 10.0) == (3, None)
    assert mt.confirmer_valeur(2, None, 10.0) == (2, None)       # pas de modèle : inchangé
    assert mt.confirmer_valeur(2, 0.2, None) == (2, None)


def test_rien_n_est_servi_sans_verdict_retenu():
    m = mt.ModeleTechnique(["a"])
    assert m.servir(pd.DataFrame({"a": [1.0, 2.0]}), [2.0, 3.0]) == (None, None)


def test_entrainement_service_et_rechargement_du_fichier(tmp_path, monkeypatch):
    """Un vrai modèle, entraîné, sauvé, relu par `en_service()` — et relu À NOUVEAU
    quand le nocturne réécrit le fichier (le scraper ne redémarre pas)."""
    import os
    import time

    monkeypatch.setenv("BT_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(mt, "_instance", None)
    monkeypatch.setattr(mt, "_mtime", None)
    monkeypatch.setattr(mt, "PARAMS_XGB", {**mt.PARAMS_XGB, "n_estimators": 20})
    rng = np.random.default_rng(1)
    n = 2000
    X = pd.DataFrame({"elo_global": rng.normal(1500, 100, n), "forme_5_courses": rng.random(n),
                      "cote_pmu": rng.random(n) * 20})
    yw = pd.Series((X.elo_global + rng.normal(0, 80, n) > 1620).astype(int))
    y3 = pd.Series((X.elo_global + rng.normal(0, 80, n) > 1540).astype(int))
    m = mt.ModeleTechnique(mt.colonnes_techniques(X.columns))
    assert "cote_pmu" not in m.colonnes
    m.entrainer(X, y3, yw)
    m.melange = {"retenu": True, "beta_modele": 0.45, "beta_marche": 0.72}
    m.placement = {"retenu": True, "poids": [0.4, 0.7, -0.4, 2.0]}
    m.train_fin = "v1"
    m.sauver()

    servi = mt.en_service()
    assert servi is not None and servi.train_fin == "v1"
    course = pd.DataFrame({"elo_global": [1700, 1500, 1400, 1300],
                           "forme_5_courses": [0.8, 0.5, 0.4, 0.2]})
    win, place = servi.servir(course, [3.0, 3.0, 5.0, 8.0])
    assert win is not None and float(win.sum()) == pytest.approx(1.0)
    assert win[0] > win[1], "à cote égale, le meilleur cheval technique passe devant"
    assert place is not None and float(place.sum()) == pytest.approx(3.0, abs=1e-6)

    m.train_fin = "v2"
    m.sauver()
    futur = time.time() + 5
    os.utime(tmp_path / mt.NOM_FICHIER, (futur, futur))
    assert mt.en_service().train_fin == "v2"
