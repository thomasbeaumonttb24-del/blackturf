"""Module Quinté+ explicite — audit du 2026-09-23 (P0).

Constat : sur 10 courses Quinté+ du 13 au 22 septembre, 0/10 plans pré-course
(prudent/modéré/risqué) contenaient un ticket Quinté+, alors que
`combo_bets.enumerate_bet_candidates` sait en construire un — il n'était
autorisé que pour le profil agressif et perdait la compétition des six
meilleurs candidats. `_construire_module_quinte` calcule désormais ce module
séparément, pour les trois profils, sans toucher à la sélection du plan
principal.
"""
from services import mise_calculator as mc

_INFO_QUINTE = {
    "nb_partants": 16, "est_simple_gagnant": True, "est_simple_place": True,
    "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True,
    "est_couple_ordre": True, "est_2sur4": True, "est_tierce": True,
    "est_quarte": True, "est_quinte": True,
}

_INFO_SANS_QUINTE = dict(_INFO_QUINTE, est_quinte=False)


def _preds(n=16):
    return [
        {"numero": i + 1, "nom_cheval": f"Cheval{i + 1}",
         "cote_pmu": 2.0 + i * 1.5, "proba_top1": max(0.30 - i * 0.018, 0.005),
         "proba_top3": max(0.6 - i * 0.03, 0.02), "non_partant": False}
        for i in range(n)
    ]


def test_pas_de_module_hors_course_quinte():
    plan = mc.generer_plan(10, "agressif", _preds(), _INFO_SANS_QUINTE, respect_montant=True)
    assert plan.module_quinte is None


def test_module_quinte_present_pour_les_trois_profils():
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(20, profil, _preds(), _INFO_QUINTE, respect_montant=True)
        mq = plan.module_quinte
        assert mq is not None, f"aucun module Quinté+ pour le profil {profil}"
        assert mq["disponible"] is True
        assert mq["type_pari"] == "Quinté+ Désordre"
        assert mq["cout_total"] > 0
        assert mq["chevaux"], "module Quinté+ sans sélection de chevaux"


def test_couverture_s_elargit_avec_le_profil():
    """Prudent = tendu (le moins cher), risqué = champ 7 (la plus grosse couverture) —
    même logique que le reste du profil (quels paris / où va l'argent)."""
    couvertures = {}
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(20, profil, _preds(), _INFO_QUINTE, respect_montant=True)
        couvertures[profil] = plan.module_quinte["couverture"]
    assert couvertures["conservateur"] == "tendue"
    assert couvertures["equilibre"] == "champ 6 chevaux"
    assert couvertures["agressif"] == "champ 7 chevaux"


def test_budget_module_borne_par_le_montant_du_plan():
    plan = mc.generer_plan(10, "conservateur", _preds(), _INFO_QUINTE, respect_montant=True)
    mq = plan.module_quinte
    assert mq["budget_alloue"] == max(mc.QUINTE_BUDGET_MIN, round(10 * mc.QUINTE_BUDGET_FRAC, 2))
    # Le module ne doit pas grignoter le budget du plan principal.
    montant_niveaux = sum(p.mise for niv in plan.niveaux for p in niv.paris)
    assert montant_niveaux == plan.montant_joue


def test_impossibilite_signalee_quand_pas_assez_de_partants():
    """Moins de 5 chevaux exploitables : aucune combinaison Quinté+ calculable —
    le module le dit explicitement plutôt que de rester silencieusement absent."""
    plan = mc.generer_plan(10, "agressif", _preds(n=4),
                           dict(_INFO_QUINTE, nb_partants=4), respect_montant=True)
    mq = plan.module_quinte
    assert mq is not None
    assert mq["disponible"] is False
    assert "motif" in mq and mq["motif"]


def test_plan_to_dict_expose_le_module_quinte():
    plan = mc.generer_plan(20, "equilibre", _preds(), _INFO_QUINTE, respect_montant=True)
    out = mc.plan_to_dict(plan)
    assert out["module_quinte"]["disponible"] is True
    plan_sans = mc.generer_plan(20, "equilibre", _preds(), _INFO_SANS_QUINTE, respect_montant=True)
    assert mc.plan_to_dict(plan_sans)["module_quinte"] is None
