"""Fonctions pures du script d'ablation hors temps (`scripts/ablation_cote_servi.py`).

Le script ne s'exécute que contre la base ; ce qui DÉCIDE des chiffres publiés —
mesures par course, écart apparié, verdict de réplication, filtre des courses
comparables — est verrouillé ici.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from scripts.ablation_cote_servi import (
    ajouter_melanges_croises, analyser, bande_favori, calibration_par_bande,
    discipline_normalisee, ecart_apparie, gagnants_et_rapport, metriques_course,
    preparer_courses, rang1, vecteur, verdict_replication)


def test_metriques_course_rang1_gagnant():
    m = metriques_course([0.5, 0.3, 0.2], 0, [2.0, 4.0, 8.0], rapport_sg=2.3)
    assert m["gagne_r1"] == 1.0
    assert m["logloss"] == pytest.approx(-np.log(0.5))
    assert m["auc"] == 1.0
    assert m["roi_fige"] == pytest.approx(1.0)       # cote figée 2,0 → +1 net
    assert m["roi_pmu"] == pytest.approx(1.3)        # rapport officiel 2,3


def test_metriques_course_rang1_perdant():
    m = metriques_course([0.2, 0.3, 0.5], 0, [2.0, 4.0, 8.0], rapport_sg=2.3)
    assert m["gagne_r1"] == 0.0 and m["roi_fige"] == -1.0 and m["roi_pmu"] == -1.0
    assert m["auc"] == 0.0


def test_rapport_inconnu_ne_compte_pas_zero():
    """Un rang 1 gagnant sans rapport officiel sort de la mesure PMU (None)."""
    m = metriques_course([0.6, 0.4], 0, [1.8, 2.5], rapport_sg=None)
    assert m["roi_pmu"] is None and m["roi_fige"] == pytest.approx(0.8)


def test_proba_non_normalisee_est_normalisee():
    m = metriques_course([2.0, 1.0, 1.0], 1, [2.0, 3.0, 5.0], None)
    assert m["logloss"] == pytest.approx(-np.log(0.25))


def test_ex_aequo_departages_par_la_plus_petite_cote():
    assert rang1(np.array([0.4, 0.4, 0.2]), np.array([5.0, 3.0, 2.0])) == 1


def test_ecart_apparie_et_ic():
    a = {i: 1.0 + 0.01 * (i % 3) for i in range(100)}
    b = {i: 1.0 for i in range(100)}
    r = ecart_apparie(a, b)
    assert r["n"] == 100 and r["ecart"] == pytest.approx(0.01, abs=1e-3)
    assert r["conclut"] is True and r["ic95"][0] > 0
    assert ecart_apparie({1: 1.0}, {1: 0.0})["ecart"] is None


@pytest.mark.parametrize("total,m1,m2,attendu", [
    ({"ecart": 0.01, "conclut": True}, {"ecart": 0.02}, {"ecart": 0.005}, "réplique"),
    ({"ecart": 0.01, "conclut": True}, {"ecart": 0.03}, {"ecart": -0.01}, "NE RÉPLIQUE PAS"),
    ({"ecart": 0.01, "conclut": False}, {"ecart": 0.03}, {"ecart": -0.01}, "non concluant"),
    ({"ecart": -0.01, "conclut": True}, {"ecart": -0.02}, {"ecart": None}, "NE RÉPLIQUE PAS"),
])
def test_verdict_replication(total, m1, m2, attendu):
    assert verdict_replication(total, m1, m2) == attendu


def test_discipline_et_bande():
    assert discipline_normalisee("Attelé") == "attele"
    assert discipline_normalisee("OBSTACLE") == "obstacle"
    assert discipline_normalisee("Haies") == "obstacle"
    assert discipline_normalisee(None) == "inconnue"
    assert bande_favori(1.5) == "favori < 2"
    assert bande_favori(7.0) == "favori >= 5"


def test_gagnants_et_rapport():
    cl = [{"position": 1, "numero": 7}, {"position": 2, "numero": 3}]
    rd = {"e_simple_gagnant": [{"combinaison": "7", "rapport": 4.2}]}
    assert gagnants_et_rapport(cl, rd) == ([7], 4.2)
    dh = [{"position": 1, "numero": 7}, {"position": 1, "numero": 3}]
    assert gagnants_et_rapport(dh, rd) == ([7, 3], None)


def test_vecteur_lit_les_features_figees():
    v = vecteur({"a": 1.5, "b": "x", "c": None}, ["a", "b", "c", "d"])
    assert v.dtype == np.float32 and list(v) == [1.5, 0.0, 0.0, 0.0]


def _lignes(cid, cotes, servi, brut, dh):
    return [{"course_id": cid, "numero": i + 1, "servi": s, "brut": b, "cote": c,
             "date_heure": dh, "discipline": "Plat", "frais": True, "features": None}
            for i, (c, s, b) in enumerate(zip(cotes, servi, brut))]


def test_preparer_courses_ecarte_ce_qui_n_est_pas_comparable():
    dh = datetime(2026, 9, 1, tzinfo=timezone.utc)
    lignes = (_lignes("OK", [2.0, 3.0, 6.0], [.5, .3, .2], [.4, .4, .2], dh)
              + _lignes("INCOMPLETE", [2.0, 3.0], [.6, .4], [.5, .5], dh)
              + _lignes("SANSCOTE", [2.0, None, 6.0], [.5, .3, .2], [.4, .4, .2], dh)
              + _lignes("DEADHEAT", [2.0, 3.0], [.6, .4], [.5, .5], dh))
    partants = {"OK": 3, "INCOMPLETE": 3, "SANSCOTE": 3, "DEADHEAT": 2}
    gagnants = {"OK": [2], "INCOMPLETE": [1], "SANSCOTE": [1], "DEADHEAT": [1, 2]}
    courses, excl = preparer_courses(lignes, gagnants, {"OK": 3.1}, partants)
    assert [c["course_id"] for c in courses] == ["OK"]
    assert excl["incomplete"] == 1 and excl["sans_cote"] == 1
    assert excl["dead_heat_ou_absent"] == 1
    c = courses[0]
    assert c["g"] == 1 and c["rapport_sg"] == 3.1
    assert c["probas"]["marche"].sum() == pytest.approx(1.0)


def _jeu(n=200, graine=1):
    rng = np.random.default_rng(graine)
    lignes, gagnants, partants = [], {}, {}
    for i in range(n):
        cid = f"C{i:04d}"
        cotes = np.round(rng.uniform(1.5, 20.0, 6), 1)
        q = (1 / cotes) / (1 / cotes).sum()
        g = int(rng.choice(6, p=q))
        brut = np.clip(q + rng.normal(0, 0.03, 6), 0.01, None)
        dh = datetime(2026, 8, 1, tzinfo=timezone.utc).replace(day=1 + i % 28, hour=10 + i % 10)
        lignes += _lignes(cid, list(cotes), list(brut / brut.sum()), list(brut), dh)
        gagnants[cid], partants[cid] = [g + 1], 6
    return preparer_courses(lignes, gagnants, {}, partants)[0]


def test_analyser_rend_niveaux_ecarts_et_calibration():
    courses = _jeu()
    r = analyser(courses, ["marche", "brut", "servi"])
    assert r["n_courses"] == 200
    assert set(r["niveaux"]) == {"marche", "brut", "servi"}
    noms = {(c["a"], c["b"], c["metrique"]) for c in r["comparaisons"]}
    assert ("brut", "marche", "auc") in noms
    assert all(c["verdict"] in ("réplique", "NE RÉPLIQUE PAS", "non concluant")
               for c in r["comparaisons"])
    total = sum(b["n"] for b in r["calibration"]["marche"])
    assert total == 200 * 6


def test_melange_croise_ne_juge_jamais_sur_les_courses_qui_fixent_beta():
    courses = _jeu(300)
    betas = ajouter_melanges_croises(courses, ["brut"])
    assert len(betas["brut"]) == 2                    # un β par moitié
    assert sum("brut_melange" in c["probas"] for c in courses) == 300


def test_calibration_par_bande():
    p = np.array([0.01, 0.01, 0.4, 0.4])
    y = np.array([0, 0, 1, 0])
    bandes = {b["bande"]: b for b in calibration_par_bande(p, y)}
    assert bandes["0.30-0.50"]["realise"] == 0.5 and bandes["0.30-0.50"]["n"] == 2
