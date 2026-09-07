"""L'avantage du produit servi ne se déclare que s'il est PROUVÉ.

Ces tests portent sur la logique pure de décision — pas sur la requête. Ils
verrouillent les trois règles qui empêchent ce module de raconter n'importe quoi :

  1. un écart dont l'intervalle contient zéro n'est PAS un avantage ;
  2. un échantillon trop court ne rend aucun chiffre, seulement une raison ;
  3. la comparaison est APPARIÉE — une course absente d'un des deux bras ne doit
     jamais contribuer à l'écart.

La troisième est la plus facile à casser sans s'en rendre compte : il suffit de
moyenner deux dictionnaires séparément.
"""
import numpy as np
import pytest

from ml.avantage_marche import MIN_COURSES, _ecart_apparie, _moyenne


def test_un_ecart_dont_l_intervalle_contient_zero_ne_conclut_pas():
    # Différences centrées sur +0,003 mais très dispersées : c'est exactement le
    # cas mesuré en production le 07/09/2026 (+0,0030, IC [−0,0023 ; +0,0083]).
    rng = np.random.default_rng(0)
    a = {f"c{i}": 0.75 for i in range(400)}
    b = {f"c{i}": 0.75 - 0.003 + float(rng.normal(0, 0.3)) for i in range(400)}
    r = _ecart_apparie(a, b, set(a))
    assert r["ic95"][0] < 0 < r["ic95"][1], "l'intervalle devrait contenir zéro"
    assert r["conclut"] is False


def test_un_ecart_net_et_serre_conclut():
    # Écart franc, dispersion faible : là, un verdict est légitime.
    a = {f"c{i}": 0.80 for i in range(400)}
    b = {f"c{i}": 0.75 for i in range(400)}
    r = _ecart_apparie(a, b, set(a))
    assert r["conclut"] is True
    assert r["ecart"] == pytest.approx(0.05, abs=1e-6)
    assert r["ic95"][0] > 0


def test_l_appariement_ignore_les_courses_absentes_d_un_bras():
    """Une course présente d'un seul côté ne doit RIEN peser.

    Sans cette garde, l'écart mesuré mélangerait une différence de qualité et une
    différence de composition — deux populations, deux moyennes, une conclusion
    fausse.
    """
    a = {"c1": 0.9, "c2": 0.9, "orpheline": 0.0}
    b = {"c1": 0.8, "c2": 0.8}
    r = _ecart_apparie(a, b, set(a) & set(b))
    assert r["n"] == 2
    assert r["ecart"] == pytest.approx(0.1, abs=1e-9)


def test_un_echantillon_de_moins_de_deux_courses_ne_rend_aucun_chiffre():
    r = _ecart_apparie({"c1": 0.9}, {"c1": 0.8}, {"c1"})
    assert r["ecart"] is None
    assert r["conclut"] is False


def test_la_moyenne_est_restreinte_a_l_ensemble_commun():
    par_course = {"c1": 1.0, "c2": 0.0}
    assert _moyenne(par_course, {"c1"}) == pytest.approx(1.0)
    assert _moyenne(par_course, set()) is None


def test_le_seuil_d_echantillon_reste_explicite():
    """Le seuil est une décision, pas un détail d'implémentation.

    S'il baisse un jour, que ce soit en connaissance de cause : l'écart à mesurer
    se joue à quelques millièmes d'AUC.
    """
    assert MIN_COURSES >= 300
