"""Audit P0 du 2026-09-24 — « le filet sert des tickets à EV négative ».

Le rejeu (1 958 courses réglées) n'a justifié AUCUN changement de règle : le filet se
déclenche sur 1 à 4 % des courses, et ni un plancher d'EV plus haut, ni le choix du
candidat de meilleure EV, ni une énumération élargie n'améliorent le rendement réel
(cf. la note au-dessus de `_SPEC_EV_FLOOR`). Ces tests fixent les invariants que le
rejeu a vérifiés, pour qu'un changement futur les casse bruyamment :

1. le filet reste dans la tranche du profil dès qu'un candidat y existe ;
2. il y préfère un candidat au-dessus du plancher d'EV quand il en a un ;
3. le plancher est bien celui que lit la sélection (constante de module câblée) ;
4. le seul cas réel sans candidat dans la tranche est joué, et marqué hors tranche.
"""
import pytest

from services import mise_calculator as mc


def _cfg(profil):
    cfg = dict(mc._effective_config(profil, 0.0))
    cfg["rang_max"] = mc._rang_max_effectif(cfg.get("rang_max"), 12)
    return cfg


def _cand(type_pari, nums_cotes, p, rap, edge=0.0, rang=1, niveau="coup"):
    return {
        "niveau": niveau, "type_pari": type_pari,
        "chevaux": [{"numero": n, "nom": f"C{n}", "cote": c} for n, c in nums_cotes],
        "proba_gain": p, "rapport_estime": rap, "ev": round(p * rap - 1.0, 4),
        "edge": edge, "_rang_max": rang, "texte_explication": "test",
    }


def _risque_tout_refuse():
    """Deux candidats de la tranche ×10 du risqué, tous deux refusés par les gates
    (poids appris à 0 = gate dur) → le filet décide seul.

    A : Couplé Gagnant EV −0,30 (au-dessus du plancher).
    B : Simple Gagnant EV −0,44 (sous le plancher) mais porté par un edge qui lui
        donne un meilleur score de repli que A.
    """
    a = _cand("Couplé Gagnant", [(1, 5.0), (2, 8.0)], 0.058, 12.0, rang=2)
    b = _cand("Simple Gagnant", [(3, 16.0)], 0.035, 16.0, edge=0.15, rang=3)
    rw = {"Couplé Gagnant": 0.0, "Simple Gagnant": 0.0}
    return [a, b], a, b, rw


def _select(cands, rw, profil="agressif", montant=10):
    return mc._select_conviction(cands, montant, mc._palier(montant), _cfg(profil), rw)


def test_le_filet_prefere_le_candidat_au_dessus_du_plancher():
    cands, a, b, rw = _risque_tout_refuse()
    assert b["ev"] < mc._SPEC_EV_FLOOR <= a["ev"]
    sel = _select(cands, rw)
    assert sel and sel[0] is a
    assert not sel[0].get("_hors_bande"), "le filet est sorti de la tranche"


def test_sans_le_plancher_le_filet_prendrait_le_candidat_sous_le_plancher():
    """Contrôle négatif : prouve que le cas ci-dessus exerce bien le plancher (sans
    lui, le score de repli choisit B)."""
    cands, a, b, rw = _risque_tout_refuse()
    ancien = mc._REPLI_PLANCHER_EV
    mc._REPLI_PLANCHER_EV = False
    try:
        sel = _select(cands, rw)
    finally:
        mc._REPLI_PLANCHER_EV = ancien
    assert sel and sel[0] is b


def test_le_filet_joue_quand_meme_si_rien_ne_tient_le_plancher():
    """Pas d'abstention : sans candidat au-dessus du plancher, la course reste jouée
    DANS la tranche (cas des 22 courses du risqué au rejeu du 2026-09-24)."""
    _, _, b, rw = _risque_tout_refuse()
    sel = _select([b], rw)
    assert sel == [b]
    assert not b.get("_hors_bande")


def test_le_plancher_lu_par_la_selection_est_la_constante_de_module():
    """Un coup spéculatif du risqué (EV<0, sans edge) à −0,30 passe les gates avec le
    plancher de production et les échoue si on le relève à −0,20."""
    c = _cand("Couplé Gagnant", [(1, 5.0), (2, 8.0)], 0.058, 12.0, rang=2)
    assert mc._SPEC_EV_FLOOR == -0.40
    pool = []
    mc._select_conviction([dict(c)], 10, mc._palier(10), _cfg("agressif"), {},
                          pool_out=pool)
    assert len(pool) == 1
    ancien = mc._SPEC_EV_FLOOR
    mc._SPEC_EV_FLOOR = -0.20
    try:
        pool = []
        mc._select_conviction([dict(c)], 10, mc._palier(10), _cfg("agressif"), {},
                              pool_out=pool)
    finally:
        mc._SPEC_EV_FLOOR = ancien
    assert pool == []


# Course RÉELLE 28082026R6C1 (Attelé, 6 partants), prédictions figées avant le départ :
# la seule des 1 958 courses rejouées sans AUCUN candidat dans la tranche prudente.
# Deux favoris à 1,8 et 2,0 (placé ~×1,1, gagnant sous la cote 3 du catalogue), aucun
# Couplé Placé offert. Seules des combinaisons HORS du catalogue prudent (Couplé
# Ordre) atteignent ×1,8-5 : arbitrer entre le type et la tranche est une décision
# produit, laissée à l'exploitant. Le test fixe l'état actuel : un pari est servi,
# et il est MARQUÉ hors tranche.
_R6C1 = [(5, 2.0, 0.478, 0.99), (6, 1.8, 0.478, 0.99), (1, 31.0, 0.017, 0.127),
         (4, 34.0, 0.009, 0.17), (2, 38.0, 0.009, 0.127), (3, 44.0, 0.009, 0.087)]
_R6C1_INFO = {"nb_partants": 6, "discipline": "Attelé",
              "est_simple_gagnant": True, "est_simple_place": True,
              "est_couple_ordre": True, "est_trio_ordre": True}


def test_course_reelle_sans_candidat_dans_la_tranche_prudente():
    preds = [{"numero": n, "nom_cheval": f"C{n}", "cote_pmu": c, "proba_top1": p1,
              "proba_top3": p3, "non_partant": False} for n, c, p1, p3 in _R6C1]
    plan = mc.generer_plan(10, "conservateur", preds, _R6C1_INFO, respect_montant=True)
    paris = [p for niv in plan.niveaux for p in niv.paris]
    assert paris, "pas d'abstention : la course doit rester jouée"
    assert all(p.type in mc.PROFIL_CONFIG["conservateur"]["types"] for p in paris)
    assert any(p.hors_tranche for p in paris), (
        "aucun candidat n'est dans la tranche : le pari servi doit le dire")


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_course_reelle_les_autres_profils_restent_joues(profil):
    preds = [{"numero": n, "nom_cheval": f"C{n}", "cote_pmu": c, "proba_top1": p1,
              "proba_top3": p3, "non_partant": False} for n, c, p1, p3 in _R6C1]
    plan = mc.generer_plan(10, profil, preds, _R6C1_INFO, respect_montant=True)
    assert sum(len(niv.paris) for niv in plan.niveaux) >= 1
