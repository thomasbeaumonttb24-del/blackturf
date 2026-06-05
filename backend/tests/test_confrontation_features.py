"""
Tests features confrontations (Phase 1.3) — calcul pur depuis historique chargé.
"""
from datetime import date

from ml.confrontation_features import (
    compute_confrontation_features,
    CONFRONTATION_FEATURE_KEYS,
)


def _row(position, hippo, d):
    # (position, distance, terrain, hippodrome, date_course, ...)
    return (position, 2000, "Bon", hippo, d, 12, 5.0, "Plat", None)


def test_cles_toujours_presentes_et_neutres_sans_data():
    out = compute_confrontation_features({"A": [], "B": []}, ["A", "B"])
    assert set(out["A"].keys()) == set(CONFRONTATION_FEATURE_KEYS)
    assert out["A"]["conf_nb_data"] == 0.0
    assert out["A"]["conf_taux_victoire"] == 0.0


def test_duel_simple_A_bat_B():
    hist = {
        "A": [_row(1, "Vincennes", date(2026, 1, 10))],
        "B": [_row(3, "Vincennes", date(2026, 1, 10))],
    }
    out = compute_confrontation_features(hist, ["A", "B"])
    assert out["A"]["conf_nb_rencontres"] == 1.0
    assert out["A"]["conf_taux_victoire"] == 1.0
    assert out["A"]["conf_bilan_net"] == 1.0
    assert out["A"]["conf_nb_rivaux_battus"] == 1.0
    assert out["B"]["conf_bilan_net"] == -1.0
    assert out["B"]["conf_nb_rivaux_bourreaux"] == 1.0


def test_hippodrome_accents_casse_matchent():
    hist = {
        "A": [_row(2, "VINCÉNNES", date(2026, 2, 1))],
        "B": [_row(1, "vincennes", date(2026, 2, 1))],
    }
    out = compute_confrontation_features(hist, ["A", "B"])
    assert out["A"]["conf_nb_rencontres"] == 1.0  # match malgré accents/casse
    assert out["B"]["conf_taux_victoire"] == 1.0


def test_dates_differentes_pas_de_duel():
    hist = {
        "A": [_row(1, "Vincennes", date(2026, 1, 10))],
        "B": [_row(1, "Vincennes", date(2026, 3, 20))],
    }
    out = compute_confrontation_features(hist, ["A", "B"])
    assert out["A"]["conf_nb_rencontres"] == 0.0


def test_incident_exclu():
    hist = {
        "A": [_row(99, "Vincennes", date(2026, 1, 10))],  # disq.
        "B": [_row(1, "Vincennes", date(2026, 1, 10))],
    }
    out = compute_confrontation_features(hist, ["A", "B"])
    assert out["A"]["conf_nb_rencontres"] == 0.0
    assert out["B"]["conf_nb_rencontres"] == 0.0


def test_trois_chevaux_bilan_partiel():
    d = date(2026, 1, 10)
    hist = {
        "A": [_row(1, "Pau", d)],
        "B": [_row(2, "Pau", d)],
        "C": [_row(3, "Pau", d)],
    }
    out = compute_confrontation_features(hist, ["A", "B", "C"])
    # A bat B et C → 2 victoires, 2 rivaux battus
    assert out["A"]["conf_nb_rivaux_battus"] == 2.0
    assert out["A"]["conf_taux_victoire"] == 1.0
    # B : bat C, perd vs A → 1-1
    assert out["B"]["conf_bilan_net"] == 0.0
    # C perd contre A et B
    assert out["C"]["conf_nb_rivaux_bourreaux"] == 2.0
    assert out["C"]["conf_taux_victoire"] == 0.0


def test_champ_trop_petit():
    out = compute_confrontation_features({"A": [_row(1, "Pau", date(2026, 1, 1))]}, ["A"])
    assert out["A"]["conf_nb_data"] == 0.0
