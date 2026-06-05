"""
Tests dynamique de course (Phase 1) — module de calcul pur.
Vérifie surtout l'intégrité : aucune valeur fabriquée, None si douteux.
"""
import pytest

from ml.race_dynamics import (
    parse_temps_to_seconds,
    compute_reduction_km,
    compute_acceleration,
    aggregate_dynamics,
    DYNAMICS_FEATURE_KEYS,
)


def test_aggregate_dynamics_cles_toujours_presentes():
    # Aucune donnée → toutes les clés présentes, valeurs neutres, nb_data=0.
    out = aggregate_dynamics([])
    assert set(out.keys()) == set(DYNAMICS_FEATURE_KEYS)
    assert out["dyn_nb_data"] == 0
    assert out["dyn_taux_accelere"] == 0.0
    assert out["dyn_reduction_km_best"] == 0.0


def test_aggregate_dynamics_finit_fort():
    rows = [("accelere", 75.0), ("accelere", 76.0), ("regulier", 78.0)]
    out = aggregate_dynamics(rows)
    assert out["dyn_taux_accelere"] > out["dyn_taux_faiblit"]
    assert out["dyn_finit_fort"] > 0
    assert out["dyn_nb_data"] == 3
    assert out["dyn_reduction_km_best"] == 75.0


def test_aggregate_dynamics_ignore_none():
    # Lignes sans label ni réduction → ignorées, pas de faux signal.
    rows = [(None, None), ("faiblit", None), (None, 80.0)]
    out = aggregate_dynamics(rows)
    assert out["dyn_taux_faiblit"] == 1.0       # seul label valide = faiblit
    assert out["dyn_finit_fort"] < 0
    assert out["dyn_reduction_km_best"] == 80.0
    assert out["dyn_nb_data"] == 2              # faiblit + la réduction 80.0


@pytest.mark.parametrize("raw,expected", [
    ("1'12\"3", 72.3),
    ("1'12\"30", 72.30),
    ("1'12", 72.0),
    ("12\"3", 12.3),
    ("1:12.3", 72.3),
    ("1:12", 72.0),
    ("72.3", 72.3),
    ("72,3", 72.3),
    ("0'59\"5", 59.5),
])
def test_parse_temps_formats(raw, expected):
    assert parse_temps_to_seconds(raw) == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize("bad", [None, "", "   ", "abc", "--", "1'", "tombe"])
def test_parse_temps_invalides_donnent_none(bad):
    assert parse_temps_to_seconds(bad) is None


def test_reduction_km_trot():
    # 2700 m en 3'24" (204 s) → 204 / 2.7 = 75.56 s/km
    assert compute_reduction_km("3'24\"", 2700) == pytest.approx(75.56, abs=0.01)


def test_reduction_km_accepte_secondes_float():
    assert compute_reduction_km(204.0, 2700) == pytest.approx(75.56, abs=0.01)


def test_reduction_km_none_si_donnees_manquantes():
    assert compute_reduction_km(None, 2700) is None
    assert compute_reduction_km("3'24\"", None) is None
    assert compute_reduction_km("3'24\"", 300) is None       # distance trop courte
    assert compute_reduction_km("0\"1", 2700) is None        # aberrant (trop rapide)


def test_acceleration_accelere():
    # Course 2000 m en 120 s → vitesse moy 16.67 m/s.
    # Dernier 400 m en 22 s → vitesse finale 18.18 m/s. index ≈ 1.09 → accelere.
    r = compute_acceleration("22", "120", 2000)
    assert r is not None
    assert r["acceleration_label"] == "accelere"
    assert r["acceleration_index"] > 1.05


def test_acceleration_faiblit():
    # Dernier 400 m en 26 s → vitesse finale 15.38 m/s < moyenne 16.67 → faiblit.
    r = compute_acceleration("26", "120", 2000)
    assert r is not None
    assert r["acceleration_label"] == "faiblit"
    assert r["acceleration_index"] < 0.95


def test_acceleration_regulier():
    # Dernier 400 m à allure ≈ moyenne.
    r = compute_acceleration("24", "120", 2000)
    assert r is not None
    assert r["acceleration_label"] == "regulier"


def test_acceleration_none_si_incomplet():
    assert compute_acceleration(None, "120", 2000) is None
    assert compute_acceleration("22", None, 2000) is None
    assert compute_acceleration("22", "120", None) is None
    assert compute_acceleration("22", "120", 200) is None     # distance < 400
    assert compute_acceleration("0", "120", 2000) is None     # temps nul


def test_acceleration_rejette_vitesse_aberrante():
    # Dernier 400 m en 5 s → 80 m/s, impossible → None (pas de stockage de faux).
    assert compute_acceleration("5", "120", 2000) is None
