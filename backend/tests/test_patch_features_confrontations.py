"""
Patch des vecteurs stockés : seules les clés conf_* reproduites par l'ancienne clé
(date, hippodrome) sont remplacées par le calcul « même course ».
"""
from datetime import date

from scripts.patch_features_confrontations import vecteurs_course
from scripts.patch_features_historique import corrections_course


def _row(position, distance, nb_partants, d=date(2026, 7, 25)):
    return (position, distance, "Bon", "Vincennes", d, nb_partants, 5.0, "Attelé", None)


def test_faux_duel_de_reunion_corrige_si_reproduit():
    # A gagne la C3 (2100 m), B finit 3e de la C6 (2850 m) : l'ancien calcul en
    # faisait un duel gagné par A.
    hist = {"A": [_row(1, 2100, 14)], "B": [_row(3, 2850, 16)]}
    avant, apres = vecteurs_course(hist, {"A": "pA", "B": "pB"})
    assert avant["pA"]["conf_nb_rencontres"] == 1.0
    assert apres["pA"]["conf_nb_rencontres"] == 0.0

    stocke = {"pA": dict(avant["pA"], autre=1.0), "pB": dict(avant["pB"])}
    patch, _ = corrections_course(avant, apres, stocke)
    assert patch["pA"]["patch"]["conf_nb_rencontres"] == 0.0
    assert patch["pA"]["ancien"]["conf_nb_rencontres"] == 1.0
    assert "autre" not in patch["pA"]["patch"]


def test_valeur_stockee_non_reproduite_laissee_intacte():
    hist = {"A": [_row(1, 2100, 14)], "B": [_row(3, 2850, 16)]}
    avant, apres = vecteurs_course(hist, {"A": "pA", "B": "pB"})
    stocke = {"pA": dict(avant["pA"], conf_nb_rencontres=7.0), "pB": dict(avant["pB"])}
    patch, stats = corrections_course(avant, apres, stocke)
    assert "conf_nb_rencontres" not in patch.get("pA", {}).get("patch", {})
    assert stats["conf_nb_rencontres"]["non_reproduit"] == 1


def test_vrai_duel_inchange():
    hist = {"A": [_row(1, 2100, 14)], "B": [_row(3, 2100, 14)]}
    avant, apres = vecteurs_course(hist, {"A": "pA", "B": "pB"})
    assert avant == apres
