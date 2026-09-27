"""Le champ qui court, pas le champ déclaré (`courses.nb_partants` compte les NP)."""
import inspect

from ml import signal_performance
from services.mise_calculator import champ_reel


def test_non_partants_retires_du_champ_declare():
    preds = [{"numero": i, "non_partant": i == 8} for i in range(1, 9)]
    assert champ_reel(8, preds) == 7


def test_sans_non_partant_champ_inchange():
    assert champ_reel(12, [{"numero": 1}, {"numero": 2}]) == 12


def test_sans_nombre_declare_compte_les_partants_predits():
    preds = [{"numero": 1}, {"numero": 2, "non_partant": True}, {"numero": 3}]
    assert champ_reel(None, preds) == 2


def test_rien_de_connu():
    assert champ_reel(None, []) is None


def test_apprentissage_du_place_compte_les_partants_reels():
    src = inspect.getsource(signal_performance.compute_signal_performance_by_profile)
    assert "c.nb_partants >= 8" not in src
    assert "non_partant = false" in src
