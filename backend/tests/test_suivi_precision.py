"""Le suivi de précision doit dire la vérité sur les arrivées : ces tests verrouillent
ses mesures par course, l'exactitude des cumuls (toute fenêtre s'agrège sans perte)
et le figeage des mesures du modèle technique (jamais jugé en échantillon)."""
from __future__ import annotations

import math

import pytest

from ml import suivi_precision as sp

COTES = [2.0, 4.0, 6.0, 10.0, 20.0]


def _course(gagnant=1, servi=(0.40, 0.25, 0.15, 0.12, 0.08), **kw):
    return sp.mesurer_course([1, 2, 3, 4, 5], list(servi), [0.8, 0.7, 0.6, 0.5, 0.4],
                             COTES, gagnant, {1, 2, 3}, **kw)


def test_le_n1_gagnant_et_la_reference_marche():
    m = _course(gagnant=1)
    assert m["hit_servi"] == 1.0 and m["hit_marche"] == 1.0
    assert m["auc_servi"] == 1.0
    m2 = _course(gagnant=3)
    assert m2["hit_servi"] == 0.0 and m2["top3_servi"] == 1.0
    assert m2["ll_servi"] == pytest.approx(-math.log(0.15))


def test_la_cote_juste_est_jugee_contre_la_cote():
    q = [1 / c for c in COTES]
    qn = q[0] / sum(q)
    m = _course(gagnant=1)
    assert m["ll_marche"] == pytest.approx(-math.log(qn))
    assert m["d_ll"] == pytest.approx(m["ll_marche"] - m["ll_servi"])


def test_une_course_sans_cote_complete_n_est_pas_mesuree():
    assert sp.mesurer_course([1, 2, 3, 4], [0.4, 0.3, 0.2, 0.1], [0.8] * 4,
                             [2.0, None, 5.0, 9.0], 1, {1}) is None


def test_le_simple_gagnant_et_les_valeurs_au_rapport_reel():
    m = _course(gagnant=1, sg_rang1={"gagne": True, "rapport": 45.0},
                valeurs=[{"niveau": 4, "gagne": True, "rapport": 3.1},
                         {"niveau": 2, "gagne": False, "rapport": None}])
    assert m["sg1_retour"] == 45.0 and m["sg1_retour_w"] == sp.WINSOR
    assert m["valeurs"]["4"] == [1, 1, 3.1, 3.1]
    assert m["valeurs"]["2"] == [1, 0, 0.0, 0.0]
    # Rapport gagnant pas encore publié : le pari n'est PAS compté (ni gagné, ni perdu).
    m2 = _course(gagnant=1, sg_rang1={"gagne": True, "rapport": None, "rapport_connu": False})
    assert "sg1_n" not in m2


def test_les_cumuls_s_empilent_exactement():
    courses = [_course(gagnant=g) for g in (1, 2, 3, 1, 5)]
    tout = sp.cumuler(courses)
    en_deux = sp.cumuler([sp.cumuler(courses[:2]), sp.cumuler(courses[2:])])
    for k in ("n", "hit_servi", "ll_servi", "sum_d_ll", "sq_d_ll"):
        assert tout[k] == pytest.approx(en_deux[k])
    assert tout["calibration_servi"] == en_deux["calibration_servi"]
    lu = sp.lire_cumul(tout)
    assert lu["n_courses"] == 5
    assert lu["n1_gagne_servi"] == pytest.approx(2 / 5)
    assert lu["cote_juste_vs_marche"]["n"] == 5
    assert lu["cote_juste_vs_marche"]["ic95"] is not None


def test_rien_d_observe_rien_d_affiche():
    lu = sp.lire_cumul(sp.cumuler([]))
    assert lu["n_courses"] == 0
    assert lu["n1_gagne_servi"] is None
    assert lu["technique"]["n1_gagne"] is None
    assert lu["simple_gagnant_n1"] is None


def test_les_mesures_techniques_d_un_jour_restent_figees():
    avant = sp.cumuler([_course(gagnant=1, tech1=[0.5, 0.2, 0.1, 0.1, 0.1])])
    nouveau = sp.cumuler([_course(gagnant=1, tech1=[0.1, 0.5, 0.2, 0.1, 0.1]),
                          _course(gagnant=2)])
    fige = sp.figer_technique(nouveau, avant)
    assert fige["n"] == 2                       # partie servie : recalculée
    assert fige["n_tech"] == avant["n_tech"]    # partie technique : celle d'origine
    assert fige["ll_tech"] == avant["ll_tech"]
    assert sp.figer_technique(nouveau, None) is nouveau


def _regler_arrivee(arrivee, rapports, offerts=("Simple Gagnant", "Simple Placé", "Couplé Gagnant",
                                               "Couplé Placé", "Trio")):
    """Règlement simplifié d'une arrivée 1-2-3 pour les tests."""
    top2, top3 = set(arrivee[:2]), set(arrivee[:3])

    def regler(nom, sel):
        if nom not in offerts:
            return None
        s = set(sel)
        gagne = {"Simple Gagnant": s == {arrivee[0]}, "Simple Placé": s <= top3,
                 "Couplé Gagnant": s == top2, "Couplé Placé": s <= top3,
                 "Trio": s == top3}[nom]
        return rapports.get((nom, tuple(sorted(s)))) if gagne else 0.0
    return regler


def test_chaque_source_joue_sa_meilleure_combinaison():
    sel = sp.selections([1, 2, 3, 4, 5], [0.40, 0.25, 0.15, 0.12, 0.08])
    assert sel["sg"] == (1,)
    assert sel["cg"] == (1, 2)
    assert sel["trio"] == (1, 2, 3)
    # Proba placé fournie : c'est elle qui choisit le placé, pas Harville.
    assert sp.selections([1, 2, 3, 4, 5], [0.40, 0.25, 0.15, 0.12, 0.08],
                         [0.5, 0.9, 0.4, 0.3, 0.2])["sp"] == (2,)
    assert sp.selections([1, 2], [0.5, 0.5]) is None


def test_les_paris_par_type_au_rapport_reel_et_les_ecarts_apparies():
    rapports = {("Simple Gagnant", (1,)): 2.0, ("Trio", (1, 2, 3)): 12.0,
                ("Couplé Gagnant", (1, 2)): 4.0, ("Simple Placé", (1,)): 1.2,
                ("Couplé Placé", (1, 2)): 2.0}
    m = _course(gagnant=1, tech1=[0.10, 0.15, 0.20, 0.25, 0.30],
                regler=_regler_arrivee([1, 2, 3], rapports))
    # Servi (1 > 2 > 3) : tout gagne. Marché (cotes 2 < 4 < 6) : pareil.
    assert m["pt_sg_servi_r"] == 2.0 and m["pt_trio_servi_r"] == 12.0
    assert m["pt_trio_marche_r"] == 12.0 and m["d_pt_trio_servi"] == 0.0
    # Technique (5 > 4 > 3) : Trio perdu → écart apparié −12.
    assert m["pt_trio_tech_r"] == 0.0 and m["d_pt_trio_tech"] == -12.0
    lu = sp.lire_cumul(sp.cumuler([m]))
    trio = next(t for t in lu["paris_par_type"] if t["type"] == "Trio")
    assert trio["servi"]["roi"] == pytest.approx(11.0)
    assert trio["tech"]["roi"] == pytest.approx(-1.0)
    assert trio["technique_vs_servi"]["n"] == 1


def test_un_pari_non_offert_ou_sans_rapport_n_est_pas_compte():
    m = _course(gagnant=1, regler=_regler_arrivee([1, 2, 3], {("Simple Gagnant", (1,)): None},
                                                  offerts=("Simple Gagnant",)))
    assert "pt_trio_servi_n" not in m           # Trio non offert
    assert "pt_sg_servi_n" not in m             # gagné mais rapport pas publié
    lu = sp.lire_cumul(sp.cumuler([m]))
    assert lu["paris_par_type"] == []


def test_les_paris_du_modele_technique_restent_figes():
    reg = _regler_arrivee([1, 2, 3], {("Simple Gagnant", (1,)): 2.0})
    avant = sp.cumuler([_course(gagnant=1, tech1=[0.5, 0.2, 0.1, 0.1, 0.1], regler=reg)])
    nouveau = sp.cumuler([_course(gagnant=1, tech1=[0.1, 0.5, 0.2, 0.1, 0.1], regler=reg)])
    fige = sp.figer_technique(nouveau, avant)
    assert fige["pt_sg_tech_r"] == avant["pt_sg_tech_r"] == 2.0
    assert fige["sum_d_pt_sg_tech"] == avant["sum_d_pt_sg_tech"]
