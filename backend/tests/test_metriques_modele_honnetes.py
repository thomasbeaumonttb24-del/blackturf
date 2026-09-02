"""Deux métriques publiées ne mesuraient pas ce que leur nom annonçait.

`precision_top3` — « le top-3 IA contient-il le vrai gagnant ? »
    Elle recevait `y_top3`, le label de l'ensemble. « Le gagnant » se réduisait
    donc au PREMIER des trois placés dans l'ordre de l'index. Le chiffre publié
    dans `model_versions.precision_top3` et dans l'admin mesurait « mon top-3
    contient-il un cheval arrivé dans les trois premiers, choisi arbitrairement ».

`roi_simule` — ROI flat-stake sur les value bets
    `ev = cote × proba − 1` avec `cote` = rapport du GAGNANT et `proba` = P(TOP-3).
    EV surestimée d'un facteur proche de trois, et un gain crédité chaque fois
    qu'un cheval PLACÉ « gagnait ».

Règle appliquée : sans le label victoire, ces deux métriques valent 0.0 — une
métrique qu'on ne sait pas calculer ne s'invente pas.
"""
import numpy as np
import pandas as pd
import pytest

from ml.models import BlackTurfEnsemble


@pytest.fixture
def modele():
    return BlackTurfEnsemble()


def _course(course_id, probas, cotes):
    return pd.DataFrame({
        "course_id": [course_id] * len(probas),
        "cote_pmu": cotes,
    }), np.asarray(probas, dtype=float)


# ── precision_top3 ─────────────────────────────────────────────────────────

def test_precision_top3_compte_le_vrai_gagnant(modele):
    """Cinq partants, le gagnant est le n°4 (index 3) — hors du top-3 IA."""
    X, probas = _course("C1", [0.9, 0.8, 0.7, 0.6, 0.1], [2, 3, 4, 5, 30])
    y_win = pd.Series([0, 0, 0, 1, 0])
    assert modele._compute_precision_top3(X, probas, X["course_id"], y_win) == 0.0


def test_precision_top3_reussie_quand_le_gagnant_est_dans_le_top3(modele):
    X, probas = _course("C1", [0.9, 0.8, 0.7, 0.6, 0.1], [2, 3, 4, 5, 30])
    y_win = pd.Series([0, 1, 0, 0, 0])
    assert modele._compute_precision_top3(X, probas, X["course_id"], y_win) == 1.0


def test_un_place_qui_n_est_pas_le_gagnant_ne_compte_plus_comme_une_reussite(modele):
    """Le défaut exact : avec `y_top3`, le 4e prédit arrivé 2e faisait passer la
    course pour réussie alors que le vrai gagnant n'était pas dans le top-3 IA."""
    X, probas = _course("C1", [0.9, 0.8, 0.7, 0.6, 0.1], [2, 3, 4, 5, 30])
    # Le 2e prédit s'est placé, le VRAI gagnant est le dernier prédit (hors top-3 IA).
    y_top3 = pd.Series([0, 1, 0, 0, 1])   # les placés
    y_win = pd.Series([0, 0, 0, 0, 1])    # le gagnant

    ancien = modele._compute_precision_top3(X, probas, X["course_id"], y_top3)
    nouveau = modele._compute_precision_top3(X, probas, X["course_id"], y_win)
    assert ancien == 1.0, "le label top-3 rendait la course « réussie »"
    assert nouveau == 0.0, "le vrai gagnant n'était pas dans le top-3 IA"


def test_une_course_sans_gagnant_identifie_ne_compte_pas(modele):
    """Elle était comptée au dénominateur comme un échec — une course non annulée
    dont l'arrivée manque n'est pas une prédiction ratée."""
    X, probas = _course("C1", [0.9, 0.5, 0.1], [2, 5, 20])
    assert modele._compute_precision_top3(
        X, probas, X["course_id"], pd.Series([0, 0, 0])) == 0.0


def test_precision_top3_sans_label_victoire_ne_fabrique_rien(modele):
    X, probas = _course("C1", [0.9, 0.5, 0.1], [2, 5, 20])
    assert modele._compute_precision_top3(X, probas, X["course_id"], None) == 0.0


# ── roi_simule ─────────────────────────────────────────────────────────────

def _jeu_roi(n=60):
    """n paris à cote 5 dont un tiers gagnent : ROI réel = 5/3 − 1 ≈ +66 %."""
    probas = np.full(n, 0.30)
    cotes = np.full(n, 5.0)
    win = np.array([1 if i % 3 == 0 else 0 for i in range(n)])
    top3 = np.ones(n, dtype=int)     # tous placés : le label qui gonflait tout
    X = pd.DataFrame({"cote_pmu": cotes})
    return X, probas, pd.Series(win), pd.Series(top3)


def test_le_roi_simule_se_calcule_sur_la_victoire(modele):
    X, probas, win, _top3 = _jeu_roi()
    roi = modele._simulate_roi(X, probas, win)
    # 60 paris de 1 €, 20 gagnants à 5 € → (100 − 60) / 60
    assert roi == pytest.approx((100 - 60) / 60, rel=1e-6)


def test_le_label_place_gonflait_le_roi(modele):
    """Preuve du défaut : avec `y_top3`, chaque placé encaissait le rapport du
    gagnant. Le ROI publié n'était pas approximatif, il était d'une autre nature."""
    X, probas, win, top3 = _jeu_roi()
    roi_vrai = modele._simulate_roi(X, probas, win)
    roi_gonfle = modele._simulate_roi(X, probas, top3)
    assert roi_gonfle > roi_vrai
    assert roi_gonfle == pytest.approx(4.0, rel=1e-6)   # 60 gagnants à ×5


def test_le_roi_simule_sans_label_victoire_ne_fabrique_rien(modele):
    X, probas, _win, _top3 = _jeu_roi()
    assert modele._simulate_roi(X, probas, None) == 0.0


def test_le_roi_simule_reste_muet_sous_le_seuil_de_significativite(modele):
    X, probas, win, _ = _jeu_roi(n=modele._ROI_MIN_BETS - 1)
    assert modele._simulate_roi(X, probas, win) == 0.0


# ── Câblage : `train` transmet bien le label victoire ──────────────────────

def test_l_entrainement_transmet_le_label_victoire_aux_metriques(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # catboost_info/ est écrit dans le cwd
    rng = np.random.RandomState(5)
    n_courses, n_partants = 60, 8
    lignes, top3, win = [], [], []
    for c in range(n_courses):
        force = rng.randn(n_partants)
        classement = np.argsort(-force)
        for i in range(n_partants):
            rang = int(np.where(classement == i)[0][0])
            lignes.append({"course_id": f"c{c:03d}",
                           "cote_pmu": float(np.clip(10 - 3 * force[i], 1.2, 50)),
                           "forme": float(force[i]),
                           "bruit": float(rng.randn())})
            top3.append(int(rang < 3))
            win.append(int(rang == 0))
    X = pd.DataFrame(lignes)
    metrics = BlackTurfEnsemble().train(X, pd.Series(top3), y_win=pd.Series(win))

    assert 0.0 < metrics["precision_top3"] <= 1.0, (
        "mesurée sur le vrai gagnant, elle doit rester calculable")
    assert metrics["roi_simule"] <= 3.0, (
        "un ROI simulé sur le label placé explosait mécaniquement")
