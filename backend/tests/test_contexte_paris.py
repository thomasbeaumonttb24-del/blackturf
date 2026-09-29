"""Carte type de pari × contexte (ml.contexte_paris) — fonctions pures."""
from ml import contexte_paris as cp

RD = {
    "e_simple_gagnant": [{"combinaison": "1", "rapport": 15.3}],
    "e_simple_place": [{"combinaison": "1", "rapport": 5.6},
                       {"combinaison": "14", "rapport": 7.8},
                       {"combinaison": "10", "rapport": 4.1}],
    "e_couple_gagnant": [{"combinaison": "1-14", "rapport": 270.4}],
    "e_couple_place": [{"combinaison": "1-14", "rapport": 82.9},
                       {"combinaison": "1-10", "rapport": 47.5},
                       {"combinaison": "14-10", "rapport": 90.0}],
    "e_trio": [{"combinaison": "1-14-10", "rapport": 1646.7}],
    "e_multi": [{"combinaison": "1-14-10-2", "libelle": "e-Multi en 6", "rapport": 56.7}],
}
ARRIVEE = [1, 14, 10, 2, 8]


def test_chemin_contexte():
    ci = {"discipline": "Plat", "nb_partants": 16, "categorie_particularite": "HANDICAP_DIVISE",
          "terrain_officiel": "PSF STANDARD"}
    assert cp.chemin_contexte(ci) == ["*", "plat", "plat|c15+", "plat|c15+|h",
                                      "plat|c15+|h|psf"]
    assert cp.chemin_contexte(None)[1] == "autre"


def test_paris_canoniques_regles_aux_vrais_rapports():
    rangs = {1: 2, 2: 13, 3: 1, 4: 4, 5: 3, 6: 10}
    paris = cp.paris_canoniques(rangs, ARRIVEE, RD)
    d = {}
    for t, r in paris:
        d.setdefault(t, []).append(r)
    assert sorted(d["Simple Gagnant"]) == [-1.0, -1.0, 15.3 - 1]
    assert 5.6 - 1 in d["Simple Placé"]
    assert d["Trio"] == [-1.0]
    assert d["Couplé Placé"] == [-1.0, -1.0, -1.0]      # 2-13, 2-1, 13-1 : aucun dans le top 3
    assert "2sur4" not in d                              # non offert → jamais réglé
    assert d["Multi en 6"] == [-1.0]                     # 14 hors du top 6 IA


def test_type_gagnant_sans_rapport_publie_ignore():
    rangs = {1: 1, 2: 14, 3: 10, 4: 2}
    rd = dict(RD)
    rd["e_trio"] = [{"combinaison": "5-6-7", "rapport": 10.0}]
    assert not [t for t, _ in cp.paris_canoniques(rangs, ARRIVEE, rd) if t == "Trio"]


def _courses(n, ci, rd, arrivee, rangs):
    return [{"course_info": ci, "rangs": rangs, "arrivee": arrivee, "rd": rd}] * n


def test_shrink_vers_la_case_parente():
    ci_a = {"discipline": "Plat", "nb_partants": 16}
    ci_b = {"discipline": "Attelé", "nb_partants": 10}
    gagne = {1: 1, 2: 14, 3: 10}
    perd = {1: 5, 2: 6, 3: 7}
    carte = cp.apprendre_carte(_courses(20, ci_a, RD, ARRIVEE, gagne)
                               + _courses(2000, ci_b, RD, ARRIVEE, perd))
    sg = carte["cases"]["plat|c15+|nh|t?"]["Simple Gagnant"]
    # 20 courses seulement : fortement ramené vers la parente, jamais au brut.
    assert sg["roi"] > sg["roi_s"]


def test_facteurs_neutres_sans_carte_ou_petite_carte():
    assert cp.facteurs_contexte(None, {}) == {}
    assert cp.facteurs_contexte({"n_courses": 10, "cases": {}}, {}) == {}


def test_facteurs_bornes_et_coupe():
    carte = {"n_courses": 5000, "cases": {
        "*": {"Trio": {"n": 5000, "roi": -0.4, "roi_s": -0.4},
              "Simple Gagnant": {"n": 9000, "roi": -0.15, "roi_s": -0.15}},
        "plat": {"Trio": {"n": 900, "roi": -0.7, "roi_s": -0.65},
                 "Simple Gagnant": {"n": 3000, "roi": 0.5, "roi_s": 0.45}},
    }}
    f = cp.facteurs_contexte(carte, {"discipline": "Plat"})
    assert f["Trio"] == 0.0 and f["Tiercé Désordre"] == 0.0
    assert f["Simple Gagnant"] == cp.FACTEUR_MAX


def test_appliquer_facteurs_respecte_les_gates():
    out = cp.appliquer_facteurs({"Trio": 0.0, "Simple Gagnant": 0.8}, {"Trio": 1.4, "Simple Gagnant": 1.25})
    assert out["Trio"] == 0.0 and out["Simple Gagnant"] == 1.0


def test_carte_eteinte_ne_change_pas_le_plan(monkeypatch):
    from services import mise_calculator as mc
    from tests.test_plan_handicap import _field, _info
    assert mc.CONTEXTE_PARIS_ACTIF is False
    cp._CACHE.clear()
    cp._CACHE.update({"n_courses": 5000, "cases": {
        "*": {"Simple Gagnant": {"n": 9000, "roi": -0.15, "roi_s": -0.15}},
        "plat": {"Simple Gagnant": {"n": 3000, "roi": -0.9, "roi_s": -0.9}}}})
    try:
        info = dict(_info("COURSE_A_CONDITIONS"), discipline="Plat")
        a = mc.plan_to_dict(mc.generer_plan(10, "agressif", _field(), info, respect_montant=True))
        cp._CACHE.clear()
        b = mc.plan_to_dict(mc.generer_plan(10, "agressif", _field(), info, respect_montant=True))
        assert a["niveaux"] == b["niveaux"]
    finally:
        cp._CACHE.clear()
