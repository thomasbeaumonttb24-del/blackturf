"""Correctifs algo du 2026-10-07 : probabilités honnêtes et EV cohérente.

Ce que ces tests verrouillent :
  1. une cote absente n'est jamais remplacée par la cote de repli des features
     (5,0) hors du vecteur du modèle ;
  2. les facteurs `cote_calibration` (appris sur la proba BRUTE) ne s'appliquent
     plus à la proba servie ;
  3. P(top3) ≥ P(top1) par partant, somme du champ conservée ;
  4. `roi_simule` et la confiance comparent une P(victoire) à la cote ;
  5. le ranker n'est entraîné que si BT_RANKER_BLEND est actif ;
  6. le gagnant est `position == 1` (dead-heat compris), pas `classement->0` ;
  7. edge_monitor règle au rapport officiel quand il est publié.
"""
import asyncio
import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from ml import melange_arrivees as ma
from ml.pipeline import cotes_reelles_de, imposer_top3_sup_top1
from ml.valuebets import detect_value_bet


def _run(coro):
    """Exécute une coroutine SANS toucher à la boucle courante : `asyncio.run`
    la remet à None en sortant, ce qui casse les tests suivants qui appellent
    `asyncio.get_event_loop()` (tests/test_ml_units.py)."""
    boucle = asyncio.new_event_loop()
    try:
        return boucle.run_until_complete(coro)
    finally:
        boucle.close()


# ─────────────────────────────────────────────────────────────
# 1. Cotes réelles
# ─────────────────────────────────────────────────────────────

FEAT_REPLI = {  # ce que produit ml.features quand le PMU n'a pas de cote
    "cote_pmu": 5.0, "cote_geny": 5.0, "cote_bzh": 5.0, "cote_winamax": 5.0,
    "cote_betclic": 5.0, "cote_unibet": 5.0, "cote_betfair_exchange": 5.0,
}


def test_cote_pmu_absente_ne_devient_pas_5():
    c = cotes_reelles_de(FEAT_REPLI, {"cote_pmu": None, "cote_geny": 7.5})
    assert c["cote_pmu"] is None
    assert c["cote_geny"] == 7.5           # vraie cote publiée : gardée
    assert c["cote_bzh"] is None and c["cote_betfair_exchange"] is None


def test_partant_absent_de_participations_n_a_aucune_cote():
    assert all(v is None for v in cotes_reelles_de(FEAT_REPLI, {}).values())


def test_cote_pmu_reelle_garde_les_valeurs_des_features():
    feat = dict(FEAT_REPLI, cote_pmu=3.2, cote_geny=3.2, cote_winamax=3.4)
    c = cotes_reelles_de(feat, {"cote_pmu": 3.2})
    assert c["cote_pmu"] == 3.2 and c["cote_winamax"] == 3.4


def test_lecture_impossible_retombe_sur_les_features():
    assert cotes_reelles_de(FEAT_REPLI, None)["cote_pmu"] == 5.0


def test_pas_de_pari_de_valeur_sans_cote_reelle():
    c = cotes_reelles_de(FEAT_REPLI, {})
    vb = detect_value_bet(0.5, cote_pmu=c["cote_pmu"], cote_geny=c["cote_geny"],
                          cote_bzh=c["cote_bzh"], cote_winamax=c["cote_winamax"],
                          cote_betclic=c["cote_betclic"], cote_unibet=c["cote_unibet"],
                          cote_betfair=c["cote_betfair_exchange"])
    assert vb is None
    # Avec la cote fabriquée, le même partant sortait en pari de valeur.
    assert detect_value_bet(0.5, cote_pmu=5.0) is not None


def test_melange_appris_ne_s_applique_pas_a_un_champ_partiellement_cote():
    p = [0.5, 0.3, 0.2]
    assert ma.probas_marche([2.0, 0.0, 4.0]) is None
    assert ma.probas_marche([2.0, None, 4.0]) is None
    assert ma.appliquer(p, [2.0, 0.0, 4.0], 0.3, 0.7) is None
    assert ma.appliquer(p, [2.0, 3.0, 4.0], 0.3, 0.7) is not None


# ─────────────────────────────────────────────────────────────
# 2. cote_calibration : domaine brut uniquement
# ─────────────────────────────────────────────────────────────

CALIB_ECRASANTE = {"buckets": [
    {"lo": lo, "hi": None, "n": 1000, "win_factor": 0.4, "top3_factor": 1.0}
    for lo in (1.0, 2.0, 4.0, 7.0, 12.0, 25.0)
]}


def test_cote_calibration_ignoree_sur_la_proba_servie():
    sans = detect_value_bet(0.25, cote_pmu=6.0)
    avec = detect_value_bet(0.25, cote_pmu=6.0, cote_calib=CALIB_ECRASANTE)
    assert sans is not None and avec is not None
    assert math.isclose(sans["ev_max"], avec["ev_max"])


def test_cote_calibration_appliquee_sur_proba_brute():
    vb = detect_value_bet(0.25, cote_pmu=6.0, cote_calib=CALIB_ECRASANTE,
                          proba_brute=True)
    assert vb is None  # 0,25 × 0,4 × 6 − 1 < 0


def test_ev_du_pari_coherente_avec_la_proba_passee():
    p, cote = 0.22, 6.0
    vb = detect_value_bet(p, cote_pmu=cote)
    assert vb is not None
    assert p * cote >= 1.0 + vb["ev_max"] - 1e-12


# ─────────────────────────────────────────────────────────────
# 3. P(top3) ≥ P(top1)
# ─────────────────────────────────────────────────────────────

def test_top3_identite_quand_rien_n_est_viole():
    p1 = np.array([0.4, 0.3, 0.2, 0.1])
    p3 = np.array([0.9, 0.8, 0.7, 0.6])
    out = imposer_top3_sup_top1(p1, p3)
    assert np.array_equal(out, p3)


def test_top3_releve_et_somme_conservee():
    p1 = np.array([0.55, 0.15, 0.1, 0.1, 0.05, 0.05])
    p3 = np.array([0.45, 0.6, 0.55, 0.6, 0.4, 0.4])   # Σ = 3, favori incohérent
    out = imposer_top3_sup_top1(p1, p3)
    assert (out >= p1 - 1e-12).all()
    assert math.isclose(out.sum(), p3.sum(), abs_tol=1e-9)
    assert (out <= 0.99).all()
    assert math.isclose(out[0], 0.55, abs_tol=1e-9)    # relevé au minimum


# ─────────────────────────────────────────────────────────────
# 4. models : P(victoire) contre la cote
# ─────────────────────────────────────────────────────────────

def _ensemble_factice(p_top3, p_win):
    from ml.models import BlackTurfEnsemble
    m = BlackTurfEnsemble()
    m.predict_proba = lambda X: np.asarray(p_top3, dtype=float)
    m.predict_win_proba = lambda X: (None if p_win is None
                                     else np.asarray(p_win, dtype=float))
    return m


def test_normaliser_par_course():
    from ml.models import _normaliser_par_course
    out = _normaliser_par_course([1, 1, 2, 2, 6], ["a", "a", "b", "b", "b"])
    assert np.allclose(out, [0.5, 0.5, 0.2, 0.2, 0.6])


def test_roi_simule_recoit_une_proba_de_victoire():
    n = 8
    X = pd.DataFrame({"cote_pmu": [3.0] * n, "f": np.arange(n, dtype=float)})
    cids = pd.Series(["c1"] * 4 + ["c2"] * 4)
    m = _ensemble_factice([0.5] * n, [0.3] * n)
    vu = {}

    def _espion(X_, probas, y_win=None):
        vu["probas"] = np.asarray(probas)
        return 0.0
    m._simulate_roi = _espion
    y = pd.Series([1, 1, 1, 0, 1, 1, 1, 0])
    yw = pd.Series([1, 0, 0, 0, 1, 0, 0, 0])
    m._evaluate(X, y, cids, y_win_test=yw)
    assert np.allclose(vu["probas"], 0.25)            # Σ = 1 par course
    assert not np.allclose(vu["probas"], 0.5)          # plus la P(top3)


def test_confiance_compare_victoire_a_la_cote_devigee():
    m = _ensemble_factice([0.6, 0.4, 0.3, 0.2], [0.4, 0.3, 0.2, 0.1])
    X = pd.DataFrame({"prob_implicite": [0.44, 0.33, 0.22, 0.11],
                      "course_id": ["c"] * 4})
    m._aligned_features = lambda X_: X_.drop(columns=["course_id"])
    m._get_l0_predictions = lambda Xf: (np.full(4, 0.3),) * 3
    _, conf = m.predict_with_confidence(X)
    # Modèle (0.4/0.3/0.2/0.1) = marché dé-viggé (0.44…/1.1) : accord parfait.
    assert np.allclose(conf, 1.0)


# ─────────────────────────────────────────────────────────────
# 5. Ranker seulement si BT_RANKER_BLEND
# ─────────────────────────────────────────────────────────────

def _jeu(n=300):
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(n, 6)), columns=[f"feat_{i}" for i in range(6)])
    y = pd.Series((rng.random(n) < 0.3).astype(int))
    X["course_id"] = [f"course_{i // 10:03d}" for i in range(n)]
    yw = pd.Series(np.zeros(n, dtype=int), index=y.index)
    yw.loc[y[y == 1].index[::3]] = 1
    return X, y, yw


@pytest.mark.parametrize("actif", [False, True])
def test_ranker_entraine_seulement_si_drapeau(tmp_path, monkeypatch, actif):
    monkeypatch.chdir(tmp_path)
    import ml.algo_flags as af
    monkeypatch.setattr(af, "FLAGS", dataclasses.replace(af.FLAGS, ranker_blend=actif))
    from ml.models import BlackTurfEnsemble
    X, y, yw = _jeu()
    m = BlackTurfEnsemble()
    m.train(X, y, y_win=yw)
    assert (m.ranker is not None) is actif


# ─────────────────────────────────────────────────────────────
# 6. Gagnant = position 1
# ─────────────────────────────────────────────────────────────

class _Vide:
    def fetchall(self):
        return []

    def first(self):
        return None

    def all(self):
        return []


class _Enregistreuse:
    def __init__(self):
        self.requetes = []

    async def execute(self, statement, *_a, **_k):
        self.requetes.append(" ".join(str(statement).lower().split()))
        return _Vide()


def test_sql_est_gagnant_lit_la_position():
    from ml.signal_performance import sql_est_gagnant
    sql = " ".join(sql_est_gagnant("pa.numero").lower().split())
    assert "(e->>'position')::int = 1" in sql
    assert "classement->0" not in sql


@pytest.mark.parametrize("module, fn", [
    ("ml.cote_calibration", "compute_cote_calibration"),
    ("ml.clv_monitor", "compute_clv_monitor"),
    ("ml.signal_performance", "compute_ev_band_performance"),
])
def test_agregats_nocturnes_sans_classement_index_0(module, fn):
    import importlib
    session = _Enregistreuse()
    _run(getattr(importlib.import_module(module), fn)(session))
    assert session.requetes
    for q in session.requetes:
        assert "classement->0->>" not in q
        if "classement" in q:
            assert "(e->>'position')::int = 1" in q


def test_servi_vs_marche_lit_la_position_et_gere_le_dead_heat():
    from ml import servi_vs_marche as svm
    assert "classement->0->>" not in str(svm._REQUETE)

    def ligne(num, p1, rang, cote, gagnants):
        return ("C1", None, "plat", num, p1, rang, cote, cote, gagnants)
    lignes = [ligne(1, 0.5, 1, 2.0, [1, 2]), ligne(2, 0.3, 2, 3.0, [1, 2]),
              ligne(3, 0.2, 3, 6.0, [1, 2])]
    m = svm._mesure_course(lignes)
    assert m is not None
    assert math.isclose(m["ll_servi"], (-math.log(0.5) - math.log(0.3)) / 2)
    assert m["top1_servi"] == 1
    # Un des gagnants hors des partants scorés : course invalide.
    assert svm._mesure_course([ligne(1, 0.6, 1, 2.0, [1, 9]),
                               ligne(2, 0.4, 2, 3.0, [1, 9])]) is None


# ─────────────────────────────────────────────────────────────
# 7. edge_monitor au rapport officiel
# ─────────────────────────────────────────────────────────────

class _FluxResultat:
    def __init__(self, lignes):
        self._lignes = lignes

    async def partitions(self, taille):
        for i in range(0, len(self._lignes), taille):
            yield self._lignes[i:i + taille]


class _FluxSession:
    def __init__(self, lignes):
        self._lignes = lignes
        self.requete = None

    async def stream(self, statement, *_a, **_k):
        self.requete = str(statement)
        return _FluxResultat(self._lignes)


def test_edge_monitor_regle_au_rapport_publie():
    from ml.edge_monitor import compute_edge_monitor
    detail = {"simple_gagnant": [{"combinaison": "1", "rapport": 2.0}]}
    # Cote scrapée 10,0 ; rapport payé 2,0. Un gagnant sur deux.
    lignes = [({"elo_vs_moyenne": 0.0}, 10.0, i % 2, detail, 1) for i in range(600)]
    session = _FluxSession(lignes)
    out = _run(compute_edge_monitor(session))
    assert "classement->0->>" not in session.requete
    assert out["roi_base"] == 0.0              # 2,0 × 50 % − 1 = 0 (à la cote : +400 %)
    assert out["n_regle_cote"] == 0


def test_edge_monitor_repli_cote_sans_rapport_publie():
    from ml.edge_monitor import compute_edge_monitor
    lignes = [({"elo_vs_moyenne": 0.0}, 4.0, i % 2, {}, 1) for i in range(600)]
    out = _run(compute_edge_monitor(_FluxSession(lignes)))
    assert out["roi_base"] == 100.0
    assert out["n_regle_cote"] == 300
