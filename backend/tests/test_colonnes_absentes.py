"""Une colonne attendue par le modèle et absente des features est signalée."""
import pandas as pd

from ml import models as ml_models
from ml.models import BlackTurfEnsemble, COLONNES_CREUSES, colonnes_absentes


def test_colonnes_creuses_par_construction_ignorees():
    attendues = ["elo_global", "pref_dist_courte", "pref_dist_longue"]
    assert colonnes_absentes(attendues, ["elo_global", "pref_dist_moyenne"]) == []


def test_derive_de_schema_signalee():
    assert colonnes_absentes(["elo_global", "cote_pmu"], ["cote_pmu"]) == ["elo_global"]


def test_les_creuses_sont_bien_celles_de_la_distance():
    assert COLONNES_CREUSES == {"pref_dist_courte", "pref_dist_moyenne", "pref_dist_longue"}


def test_alignement_journalise_les_absentes(monkeypatch):
    vus = []
    monkeypatch.setattr(ml_models.log, "warning", lambda ev, **kw: vus.append((ev, kw)))
    m = BlackTurfEnsemble.__new__(BlackTurfEnsemble)
    m.feature_names = ["a", "b", "pref_dist_longue"]
    m.version_num = 548
    X = m._aligned_features(pd.DataFrame({"a": [1.0, 2.0]}))
    assert list(X.columns) == ["a", "b", "pref_dist_longue"]
    assert X["b"].tolist() == [0, 0]
    assert vus == [("model.colonnes_absentes", {"version": 548, "n": 1, "colonnes": ["b"]})]


def test_alignement_complet_silencieux(monkeypatch):
    vus = []
    monkeypatch.setattr(ml_models.log, "warning", lambda ev, **kw: vus.append(ev))
    m = BlackTurfEnsemble.__new__(BlackTurfEnsemble)
    m.feature_names = ["a"]
    m._aligned_features(pd.DataFrame({"a": [1.0]}))
    assert vus == []
