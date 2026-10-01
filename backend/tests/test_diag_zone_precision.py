"""Tests des fonctions PURES de scripts/diag_zone_precision — sans DB, données synthétiques."""
import math

from scripts.diag_zone_precision import (
    HIST_MIN_COURSES, MIN_COURSES, MIN_PARTANTS, agreger, famille_discipline,
    mesurer_course, positions_depuis_classement, segmenter, tranche_couverture,
)


def _partants(probas, cotes=None, n_avant=10):
    cotes = cotes or [None] * len(probas)
    return [{"numero": i + 1, "proba": p, "cote": c, "n_avant": n_avant}
            for i, (p, c) in enumerate(zip(probas, cotes))]


def test_famille_discipline():
    assert famille_discipline("Attelé") == "trot"
    assert famille_discipline("Monté") == "trot"
    assert famille_discipline("Plat") == "galop"
    assert famille_discipline("Steeple") == "galop"
    assert famille_discipline(None) == "inconnu"


def test_tranche_couverture_bornes():
    assert tranche_couverture(0.0) == "0-25 %"
    assert tranche_couverture(0.25) == "25-50 %"
    assert tranche_couverture(0.74) == "50-75 %"
    assert tranche_couverture(1.0) == "75-100 %"


def test_positions_depuis_classement_formats():
    assert positions_depuis_classement([{"numero": 3, "position": 1}, {"numero": 1, "position": 2}]) == {3: 1, 1: 2}
    assert positions_depuis_classement({"classement": [{"num": "2", "place": "1"}]}) == {2: 1}
    assert positions_depuis_classement(None) == {}


def test_course_trop_petite_ou_sans_gagnant_ignoree():
    assert mesurer_course(_partants([0.5] * (MIN_PARTANTS - 1)), {1: 1}) is None
    # Gagnant absent des partants évalués : non mesurable.
    assert mesurer_course(_partants([0.25] * 4), {9: 1}) is None


def test_mesures_modele_et_marche():
    p = _partants([0.4, 0.3, 0.2, 0.1], cotes=[5.0, 2.0, 4.0, 10.0])
    m = mesurer_course(p, {2: 1, 1: 2, 3: 3})
    assert not m["modele_top1_gagne"]           # n°1 du modèle = cheval 1, arrivé 2e
    assert m["modele_top1_place"]
    assert m["gagnant_dans_top3_modele"]
    assert math.isclose(m["modele_logloss"], -math.log(0.3))
    assert m["marche"]["top1_gagne"]            # favori marché = cheval 2 (cote 2,0)
    impl = [1 / 5, 1 / 2, 1 / 4, 1 / 10]
    assert math.isclose(m["marche"]["logloss"], -math.log(impl[1] / sum(impl)))


def test_marche_absent_si_une_cote_manque():
    m = mesurer_course(_partants([0.4, 0.3, 0.2, 0.1], cotes=[5.0, None, 4.0, 10.0]), {1: 1})
    assert m["marche"] is None
    assert m["modele_top1_gagne"]


def test_couverture_compte_les_chevaux_sous_le_seuil():
    p = _partants([0.25] * 4)
    p[0]["n_avant"] = p[1]["n_avant"] = HIST_MIN_COURSES - 1
    assert mesurer_course(p, {1: 1})["part_couverts"] == 0.5


def test_agreger_sous_seuil_est_null():
    m = mesurer_course(_partants([0.4, 0.3, 0.2, 0.1]), {1: 1})
    a = agreger([m] * (MIN_COURSES - 1))
    assert a == {"n_courses": MIN_COURSES - 1, "fiable": False}


def test_agreger_et_segmenter():
    gagne = mesurer_course(_partants([0.4, 0.3, 0.2, 0.1], cotes=[2.0, 3.0, 5.0, 9.0]), {1: 1})
    perd = mesurer_course(_partants([0.4, 0.3, 0.2, 0.1], cotes=[2.0, 3.0, 5.0, 9.0], n_avant=0), {4: 1})
    courses = ([{"zone": "FRA", "pays": "FRA", "famille": "trot", "mesure": gagne}] * MIN_COURSES
               + [{"zone": "ETR", "pays": "USA", "famille": "galop", "mesure": perd}] * MIN_COURSES)
    seg = segmenter(courses)
    fra, etr = seg["zone"]["FRA"], seg["zone"]["ETR"]
    assert fra["modele_top1_gagne_pct"] == 100.0 and etr["modele_top1_gagne_pct"] == 0.0
    assert fra["couverture_moy_pct"] == 100.0 and etr["couverture_moy_pct"] == 0.0
    assert math.isclose(fra["ecart_logloss_ic95"], 0.0, abs_tol=1e-12)  # écart constant
    assert set(seg["pays_etranger"]) == {"USA"}
    assert "ETR · 0-25 %" in seg["zone_couverture"]
    assert "FRA · 75-100 %" in seg["zone_couverture"]
