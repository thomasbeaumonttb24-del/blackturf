"""Gate marché rebranché sur le produit SERVI (chantier C, 2026-09-24).

L'ancien gate exigeait que le modèle NU batte la cote. Rejoué sur l'historique, il
aurait bloqué les 17 promotions v528-v544 (delta nu de −0,035 à −0,017) et gelé le
modèle sur v527, alors que le produit servi est à parité avec la cote. Le nouveau
gate bloque seulement un RECUL prouvé et matériel du classement servi du
challenger face à la cote, par rapport au champion, sur les mêmes courses.
"""
import re

import numpy as np
import pandas as pd
import pytest

from ml import algo_flags
from ml.avantage_marche import (
    GATE_MIN_COURSES, GATE_TOLERANCE, auc_marche_par_course, auc_servie_par_course,
    gate_servi_bloque, mesure_gate_servi, proba_servie)
from ml.pipeline import (
    _arrondir_marche_servi, _marche_servi_bloque, _mesure_marche_servi, _should_deploy)


# ── Mesures par course ──────────────────────────────────────────────────────

def _deux_courses():
    # Course A : 3 partants, le 2e gagne. Course B : 2 partants, le 1er gagne.
    groupes = np.array(["A", "A", "A", "B", "B"])
    y = np.array([0, 1, 0, 1, 0], dtype=float)
    cotes = np.array([2.0, 4.0, 9.0, 1.5, 3.0])
    return groupes, y, cotes


def test_auc_marche_par_course():
    g, y, c = _deux_courses()
    auc = auc_marche_par_course(y, g, c)
    assert auc["A"] == pytest.approx(0.5)   # gagnant 2e favori : 1 perdant sur 2 dessous
    assert auc["B"] == pytest.approx(1.0)


def test_auc_marche_sans_cotes_ne_mesure_rien():
    g, y, _ = _deux_courses()
    assert auc_marche_par_course(y, g, None) == {}


def test_course_sans_gagnant_unique_est_absente_pas_comptee_un_demi():
    g = np.array(["A", "A", "B", "B"])
    y = np.array([1, 1, 0, 1], dtype=float)          # A : dead heat
    c = np.array([2.0, 3.0, 2.0, 3.0])
    assert set(auc_marche_par_course(y, g, c)) == {"B"}


def test_proba_servie_suit_le_melange_appris_quand_beta_est_en_service():
    from ml import melange_arrivees as ma
    p = np.array([0.5, 0.3, 0.2])
    c = np.array([3.0, 2.0, 6.0])
    attendu = ma.appliquer(p, c, 0.3, 0.7)
    assert np.allclose(proba_servie(p, c, betas=(0.3, 0.7)), attendu)


def test_proba_servie_repli_sur_le_melange_lineaire():
    from ml.blend_calibration import melange
    p = np.array([0.5, 0.3, 0.2])
    c = np.array([3.0, 2.0, 6.0])
    assert np.allclose(proba_servie(p, c, betas=None, alpha_max=0.42),
                       melange(p, c, alpha_max=0.42))


def test_proba_servie_sans_cote_exploitable():
    assert proba_servie([0.5, 0.5], None) is None
    assert proba_servie([0.5, 0.5], [1.0, 3.0]) is None      # cote ≤ 1 : illisible


def test_le_melange_peut_retourner_le_classement_du_modele():
    """C'est toute la raison d'être du gate : ce qui est SERVI n'est pas le brut."""
    g = np.array(["A", "A"])
    y = np.array([1, 0], dtype=float)
    cotes = np.array([1.5, 8.0])
    p_brut = np.array([0.45, 0.55])                  # le brut place le gagnant 2e
    brut = auc_servie_par_course(p_brut, y, g, cotes, betas=(1.0, 0.0001))
    servi = auc_servie_par_course(p_brut, y, g, cotes, betas=(0.3, 0.7))
    assert brut["A"] == 0.0 and servi["A"] == 1.0


# ── Verdict ─────────────────────────────────────────────────────────────────

def _dicts(n, ecart_challenger, ecart_champion=0.0, graine=0):
    rng = np.random.default_rng(graine)
    marche = {i: float(rng.uniform(0.3, 1.0)) for i in range(n)}
    bruit = {i: float(rng.normal(0, 0.01)) for i in range(n)}
    champion = {i: marche[i] + ecart_champion + bruit[i] for i in range(n)}
    challenger = {i: champion[i] + (ecart_challenger - ecart_champion)
                  + float(rng.normal(0, 0.01)) for i in range(n)}
    return champion, challenger, marche


def test_un_recul_prouve_et_materiel_bloque():
    champ, chal, m = _dicts(600, ecart_challenger=-0.01)
    mesure = mesure_gate_servi(champ, chal, m)
    assert mesure["regression"] < -GATE_TOLERANCE
    assert mesure["ic95_regression"][1] < 0
    assert mesure["bloque"] is True and gate_servi_bloque(mesure) is True


def test_un_recul_prouve_mais_minuscule_ne_bloque_pas():
    """Sous la tolérance, un recul « significatif » reste du bruit de modèle : le
    bloquer gèlerait l'apprentissage, comme en juin-août."""
    champ, chal, m = _dicts(5000, ecart_challenger=-0.001)
    mesure = mesure_gate_servi(champ, chal, m)
    assert mesure["ic95_regression"][1] < 0          # prouvé…
    assert mesure["bloque"] is False                 # …mais pas matériel


def test_sans_recul_ne_bloque_pas():
    champ, chal, m = _dicts(600, ecart_challenger=0.0)
    assert mesure_gate_servi(champ, chal, m)["bloque"] is False


def test_n_exige_pas_de_battre_la_cote():
    """Champion ET challenger sous la cote, sans recul de l'un à l'autre : on
    promeut. `sous_la_cote` alerte, il ne bloque pas."""
    champ, chal, m = _dicts(600, ecart_challenger=-0.02, ecart_champion=-0.02)
    mesure = mesure_gate_servi(champ, chal, m)
    assert mesure["sous_la_cote"] is True
    assert mesure["bloque"] is False


def test_echantillon_trop_court_ne_bloque_jamais():
    champ, chal, m = _dicts(GATE_MIN_COURSES - 1, ecart_challenger=-0.05)
    mesure = mesure_gate_servi(champ, chal, m)
    assert mesure["suffisant"] is False and mesure["bloque"] is False


def test_mesure_absente_ne_bloque_pas():
    assert gate_servi_bloque(None) is False
    assert mesure_gate_servi({}, {}, {}) is None


def test_la_regression_est_l_ecart_des_deux_avantages():
    champ, chal, m = _dicts(800, ecart_challenger=0.004, ecart_champion=0.001)
    mesure = mesure_gate_servi(champ, chal, m)
    assert mesure["regression"] == pytest.approx(
        mesure["avantage_challenger"] - mesure["avantage_champion"], abs=2e-4)


# ── Branchement dans le pipeline ────────────────────────────────────────────

def test_mesure_pipeline_sans_les_deux_modeles():
    assert _mesure_marche_servi({"champion": {}}, np.array([1.0]), ["A"], None) is None
    assert _mesure_marche_servi({}, None, [], None) is None


def test_mesure_pipeline_bout_a_bout():
    champ, chal, _ = _dicts(400, ecart_challenger=-0.03)
    # Marché : une vraie colonne de cotes, deux partants par course.
    groupes = np.repeat([f"C{i}" for i in range(400)], 2)
    y = np.tile([1.0, 0.0], 400)
    cotes = np.tile([2.0, 3.0], 400)
    mesure = _mesure_marche_servi({"champion": {f"C{i}": v for i, v in champ.items()},
                                   "challenger": {f"C{i}": v for i, v in chal.items()}},
                                  y, groupes, cotes)
    assert mesure is not None and mesure["n_courses"] == 400
    assert mesure["bloque"] is True
    h2h = {"marche_servi": mesure}
    assert _marche_servi_bloque(h2h) is True
    assert _marche_servi_bloque(None) is False
    resume = _arrondir_marche_servi(h2h)
    assert resume["bloque"] is True and "regression" in resume
    assert _arrondir_marche_servi({}) is None


class _FakeWinModel:
    def __init__(self, skill):
        self.skill = skill

    def predict_proba(self, X):
        y = X["truth"].to_numpy().astype(float)
        bruit = ((np.arange(len(X)) * 7919) % 1000) / 1000.0
        return self.skill * y + (1 - self.skill) * bruit

    def predict_win_proba(self, X):
        return np.clip(self.predict_proba(X), 1e-3, None)


class _FakeSession:
    def __init__(self, course_ids):
        self._rows = [(c,) for c in course_ids]

    async def execute(self, _stmt, params=None):
        return self._rows


class _FakeMV:
    def __init__(self, created_at):
        self.created_at = created_at


def _holdout_cote(n_courses=400):
    """Marché imparfait : le gagnant est tantôt favori, tantôt 4e cote."""
    cid, truth, cotes = [], [], []
    for i in range(n_courses):
        for j in range(6):
            cid.append(f"C{i}")
            truth.append(1 if j == 0 else 0)
            cotes.append(2.0 + ((j + i) % 6) * 1.5)
    X = pd.DataFrame({"course_id": cid, "truth": truth, "cote_pmu": cotes})
    return X, pd.Series(truth)


@pytest.mark.asyncio
async def test_h2h_expose_le_verdict_du_gate_servi(monkeypatch):
    """Un challenger nettement moins bon que le champion fait reculer le produit
    servi : le h2h le mesure et le verdict bloquerait (si le drapeau est actif)."""
    from ml import pipeline as pl
    X, y = _holdout_cote(400)
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeWinModel(0.95)))
    res = await pl._head_to_head_auc(_FakeSession(X["course_id"].unique()),
                                     _FakeWinModel(0.05), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")), y_win_hold=y)
    ms = res["marche_servi"]
    assert ms is not None and ms["n_courses"] == 400
    assert ms["regression"] < 0 and ms["bloque"] is True
    assert pl._marche_servi_bloque(res) is True


@pytest.mark.asyncio
async def test_h2h_sans_cotes_pas_de_verdict_servi(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout_cote(400)
    X = X.drop(columns=["cote_pmu"])
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeWinModel(0.95)))
    res = await pl._head_to_head_auc(_FakeSession(X["course_id"].unique()),
                                     _FakeWinModel(0.05), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")), y_win_hold=y)
    assert res["marche_servi"] is None
    assert pl._marche_servi_bloque(res) is False


# ── Décision de promotion ───────────────────────────────────────────────────

BASE = dict(current_wf=0.70, current_is_synth=False, no_current=False,
            current_unreliable=False, data_jump=False)


def test_should_deploy_bloque_seulement_si_le_drapeau_est_actif():
    assert _should_deploy(0.75, market_gate_enabled=True, marche_servi_bloque=True,
                          **BASE) is False
    assert _should_deploy(0.75, market_gate_enabled=False, marche_servi_bloque=True,
                          **BASE) is True


def test_should_deploy_h2h_positif_ne_rachete_pas_un_recul_servi():
    """Mieux classer le top 3 nu ne suffit pas si le produit servi recule."""
    assert _should_deploy(0.75, market_gate_enabled=True, marche_servi_bloque=True,
                          h2h_delta=+0.01, **BASE) is False


# ── Configuration ───────────────────────────────────────────────────────────

def test_tolerance_par_defaut_et_ancienne_marge_abandonnee(monkeypatch):
    monkeypatch.setenv("BT_MARKET_GATE_MARGIN", "0.5")
    monkeypatch.delenv("BT_MARKET_GATE_TOLERANCE", raising=False)
    f = algo_flags.AlgoFlags()
    assert f.market_gate_tolerance == GATE_TOLERANCE == 0.002
    assert not hasattr(f, "market_gate_margin")
    assert "market_gate_tolerance" in f.as_dict()


def test_la_production_active_le_gate_servi_partout():
    """Activé par Thomas le 2026-09-24 : chaque service du compose de production
    porte `${BT_MARKET_GATE:-1}`. Une valeur divergente entre services ferait
    juger une promotion différemment selon le processus qui l'évalue."""
    from ._descripteurs_deploiement import COMPOSE_PROD, exiger
    compose = exiger(COMPOSE_PROD)
    valeurs = re.findall(r"BT_MARKET_GATE=\$\{BT_MARKET_GATE:-(\d)\}", compose)
    assert valeurs and set(valeurs) == {"1"}
    refit = re.findall(r"BT_REFIT_FULL=\$\{BT_REFIT_FULL:-(\d)\}", compose)
    assert refit and set(refit) == {"1"}
