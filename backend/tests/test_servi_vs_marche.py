"""Mesure « pronostic servi contre le marché » (ml.servi_vs_marche).

Ce que ces tests verrouillent :
  - Harville rend la proba top 3 EXACTE (comparée à l'énumération des arrivées) ;
  - une course au marché incomplet est ignorée, jamais complétée par une cote inventée ;
  - le gagnant hors des partants scorés invalide la course ;
  - le verdict exige un intervalle de confiance entièrement d'un côté de zéro.
"""
import itertools
import math

import numpy as np

from ml.servi_vs_marche import (
    MIN_COURSES_VERDICT, _devig, _mesure_course, _resume, _verdict, proba_top3_harville,
)


def _brute_top3(p):
    out = np.zeros(p.size)
    for ordre in itertools.permutations(range(p.size), 3):
        pr, reste = 1.0, 1.0
        for i in ordre:
            pr *= p[i] / reste
            reste -= p[i]
        for i in ordre:
            out[i] += pr
    return out


def test_harville_exact_et_somme_trois():
    p = np.array([0.35, 0.2, 0.15, 0.12, 0.08, 0.06, 0.04])
    h = proba_top3_harville(p)
    assert np.allclose(h, _brute_top3(p), atol=1e-12)
    assert math.isclose(h.sum(), 3.0, abs_tol=1e-9)


def test_harville_trois_partants_ou_moins():
    assert np.allclose(proba_top3_harville(np.array([0.5, 0.3, 0.2])), 1.0)


def test_devig_refuse_un_marche_incomplet():
    assert _devig(np.array([2.0, np.nan, 5.0])) is None
    assert _devig(np.array([2.0, 1.0, 5.0])) is None  # cote 1 = absente
    p = _devig(np.array([2.0, 4.0, 4.0]))
    assert np.isclose(p.sum(), 1.0) and p[0] > p[1]


def _ligne(num, p1, rang, cote_fige, cote_fin, gagnant):
    # (course_id, date_heure, discipline, numero, proba_top1, rang, cote_figee, cote_pmu, gagnant)
    return ("C1", None, "plat", num, p1, rang, cote_fige, cote_fin, gagnant)


def test_mesure_course_valeurs():
    lignes = [
        _ligne(1, 0.5, 1, 2.0, 2.5, 1),
        _ligne(2, 0.3, 2, 3.0, 3.0, 1),
        _ligne(3, 0.2, 3, 6.0, 4.0, 1),
    ]
    m = _mesure_course(lignes)
    assert m is not None
    assert math.isclose(m["ll_servi"], -math.log(0.5))
    inv = np.array([1 / 2, 1 / 3, 1 / 6])
    assert math.isclose(m["ll_fige"], -math.log(inv[0] / inv.sum()))
    assert m["top1_servi"] == 1 and m["top1_favori"] == 1
    assert math.isclose(m["net_servi"], 1.5)  # gagne à 2,5 → +1,5 €


def test_mesure_course_ignore_marche_incomplet_et_gagnant_inconnu():
    assert _mesure_course([_ligne(1, 0.6, 1, 2.0, 2.0, 1), _ligne(2, 0.4, 2, None, 3.0, 1)]) is None
    assert _mesure_course([_ligne(1, 0.6, 1, 2.0, 2.0, 9), _ligne(2, 0.4, 2, 3.0, 3.0, 9)]) is None


def test_verdict_exige_un_ic_d_un_seul_cote():
    n = MIN_COURSES_VERDICT
    assert _verdict(n, -0.02, -0.001) == "meilleur"
    assert _verdict(n, 0.001, 0.02) == "moins_bon"
    assert _verdict(n, -0.01, 0.01) == "egal"
    assert _verdict(n - 1, -0.02, -0.01) == "insuffisant"


def test_resume_compte_et_pourcentages():
    mesures = [
        {"ll_servi": 1.0, "ll_fige": 1.2, "ll_final": 0.9, "top1_servi": 1, "top1_favori": 0,
         "net_servi": 2.0, "net_favori": -1.0, "partants": 10},
        {"ll_servi": 2.0, "ll_fige": 2.0, "ll_final": None, "top1_servi": 0, "top1_favori": 1,
         "net_servi": -1.0, "net_favori": None, "partants": 12},
    ]
    r = _resume(mesures)
    assert r["n_courses"] == 2 and r["n_courses_cote_finale"] == 1
    assert r["top1_servi_pct"] == 50.0 and r["top1_favori_pct"] == 50.0
    assert r["roi_servi_pct"] == 50.0 and r["roi_favori_pct"] == -100.0
    assert r["ecart_fige"]["verdict"] == "insuffisant"
