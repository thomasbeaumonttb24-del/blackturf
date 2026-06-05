"""
Tests validation de plausibilité à l'écriture (intégrité données).
"""
import pytest

from scraper.validation import (
    valid_cote, valid_distance, valid_position, valid_nb_partants,
    valid_proba, valid_penetrometre,
)


@pytest.mark.parametrize("v,exp", [
    (3.5, 3.5), (1.01, 1.01), (999.0, 999.0), ("4.2", 4.2),
    (1.0, None), (0.5, None), (-2, None), (5000, None), ("abc", None), (None, None),
])
def test_valid_cote(v, exp):
    assert valid_cote(v) == exp


@pytest.mark.parametrize("v,exp", [
    (2000, 2000), (800, 800), (8000, 8000), ("2700", 2700),
    (100, None), (50000, None), (0, None), (None, None),
])
def test_valid_distance(v, exp):
    assert valid_distance(v) == exp


@pytest.mark.parametrize("v,exp", [
    (1, 1), (40, 40), (99, 99), (90, 90),
    (0, None), (41, None), (50, None), ("x", None),
])
def test_valid_position(v, exp):
    assert valid_position(v) == exp


def test_valid_position_sans_incident():
    assert valid_position(99, incident_ok=False) is None
    assert valid_position(3, incident_ok=False) == 3


@pytest.mark.parametrize("v,exp", [
    (12, 12), (1, 1), (30, 30), (0, None), (40, None),
])
def test_valid_nb_partants(v, exp):
    assert valid_nb_partants(v) == exp


@pytest.mark.parametrize("v,exp", [
    (0.5, 0.5), (0.0, 0.0), (1.0, 1.0), (1.5, None), (-0.1, None),
])
def test_valid_proba(v, exp):
    assert valid_proba(v) == exp


@pytest.mark.parametrize("v,exp", [
    (4.5, 4.5), (0.0, 0.0), (9.0, 9.0), (12.0, None), (-1, None),
])
def test_valid_penetrometre(v, exp):
    assert valid_penetrometre(v) == exp
