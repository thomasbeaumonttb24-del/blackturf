"""Module Quinté+ explicite — audit du 2026-09-23 (P0), budget du 2026-09-24.

Constat : sur 10 courses Quinté+ du 13 au 22 septembre, 0/10 plans pré-course
(prudent/modéré/risqué) contenaient un ticket Quinté+, alors que
`combo_bets.enumerate_bet_candidates` sait en construire un — il n'était
autorisé que pour le profil agressif et perdait la compétition des six
meilleurs candidats. `_construire_module_quinte` calcule ce module séparément,
pour les trois profils.

Arbitrage produit du 2026-09-24 : son coût est PRIS SUR le montant du plan, il
ne s'y ajoute plus. Le plan principal se construit sur le reste et
plan principal + Quinté+ = exactement le montant saisi.

Second arbitrage du même jour : le Quinté+ du jour est proposé sur TOUS les
plans, et chaque combinaison est jouée à la mise de base de 2 € (pas de Flexi
réducteur). Sous 4 €, le ticket tendu de 2 € s'ajoute au montant saisi.
"""
import math

import pytest

from services import mise_calculator as mc
from services.bet_settlement import settle_module_quinte, settle_plan

_INFO_QUINTE = {
    "nb_partants": 16, "est_simple_gagnant": True, "est_simple_place": True,
    "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True,
    "est_couple_ordre": True, "est_2sur4": True, "est_tierce": True,
    "est_quarte": True, "est_quinte": True,
}

_INFO_SANS_QUINTE = dict(_INFO_QUINTE, est_quinte=False)
PROFILS = ("conservateur", "equilibre", "agressif")


def _preds(n=16):
    return [
        {"numero": i + 1, "nom_cheval": f"Cheval{i + 1}",
         "cote_pmu": 2.0 + i * 1.5, "proba_top1": max(0.30 - i * 0.018, 0.005),
         "proba_top3": max(0.6 - i * 0.03, 0.02), "non_partant": False}
        for i in range(n)
    ]


def _plan(montant, profil, info=_INFO_QUINTE, preds=None):
    return mc.generer_plan(montant, profil, preds or _preds(), info, respect_montant=True)


def _corps(montant, profil, info=_INFO_QUINTE, preds=None):
    """Le corps de generer_plan SANS le partage Quinté+ : le plan principal seul."""
    return mc.generer_plan.__wrapped__(montant, profil, preds or _preds(), info,
                                       respect_montant=True)


def _mises(plan):
    return sum(p.mise for niv in plan.niveaux for p in niv.paris)


# ── Présence et forme du module ──────────────────────────────────────────────

def test_pas_de_module_hors_course_quinte():
    plan = _plan(10, "agressif", _INFO_SANS_QUINTE)
    assert plan.module_quinte is None
    assert plan.montant_quinte == 0.0


@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [2, 10, 37])
def test_course_non_quinte_strictement_inchangee(profil, montant):
    """Hors Quinté+, le partage ne touche à rien : même plan que le corps seul."""
    avec = mc.plan_to_dict(_plan(montant, profil, _INFO_SANS_QUINTE))
    sans = mc.plan_to_dict(_corps(montant, profil, _INFO_SANS_QUINTE))
    assert avec == sans


def test_module_quinte_present_pour_les_trois_profils():
    for profil in PROFILS:
        mq = _plan(20, profil).module_quinte
        assert mq is not None, f"aucun module Quinté+ pour le profil {profil}"
        assert mq["disponible"] is True and mq["financable"] is True
        assert mq["type_pari"] == "Quinté+ Désordre"
        assert mq["cout_total"] > 0
        assert len(mq["chevaux"]) == mq["nb_chevaux"] >= 5
        assert all(c.get("rang") for c in mq["chevaux"]), "rang IA de chaque cheval"


def test_couverture_s_elargit_avec_le_profil_quand_le_budget_le_permet():
    """Prudent = tendu (le moins cher), risqué = champ 7 (la plus grosse couverture).
    À 2 € la combinaison, un champ 7 (21 combinaisons) coûte 42 € : il faut 200 €."""
    couv = {p: _plan(200, p).module_quinte["couverture"] for p in PROFILS}
    assert couv == {"conservateur": "tendue", "equilibre": "champ 6 chevaux",
                    "agressif": "champ 7 chevaux"}


@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [1, 2, 3, 4, 7, 10, 20, 50, 100, 200])
def test_quinte_toujours_propose_a_deux_euros_la_combinaison(profil, montant):
    """Tous les plans d'une course Quinté+ proposent des combinaisons Quinté+, et
    chaque combinaison est jouée au moins à 2 €."""
    mq = _plan(montant, profil).module_quinte
    assert mq is not None and mq["disponible"] is True, f"{profil}/{montant} €"
    assert mq["mise_unitaire"] >= 2.0
    assert mq["flexi_pct"] == 100
    assert mq["cout_total"] == mq["nb_combinaisons"] * 2.0


def test_honnetete_aucune_ev_affichee():
    """Un Quinté+ systématique est une couverture : aucune EV n'est présentée."""
    for profil in PROFILS:
        mq = _plan(20, profil).module_quinte
        assert mq["ev"] is None and mq["ev_etablie"] is False
        assert "espérance" in mq["note"]


def test_plan_to_dict_expose_le_module_et_son_cout():
    out = mc.plan_to_dict(_plan(20, "equilibre"))
    assert out["module_quinte"]["disponible"] is True
    assert out["montant_quinte"] == out["module_quinte"]["cout_total"]
    out_sans = mc.plan_to_dict(_plan(20, "equilibre", _INFO_SANS_QUINTE))
    assert out_sans["module_quinte"] is None and out_sans["montant_quinte"] == 0.0


# ── Budget : pris SUR le montant ─────────────────────────────────────────────

@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [4, 5, 7, 10, 13, 20, 50, 100])
def test_somme_exacte_egale_au_montant_saisi(profil, montant):
    plan = _plan(montant, profil)
    mq = plan.module_quinte
    assert mq["disponible"] is True
    assert plan.montant_total == montant
    assert _mises(plan) == plan.montant_joue, "montant_joue = tickets du plan principal"
    assert plan.montant_joue + plan.montant_quinte == montant, (
        f"{profil}/{montant} € : {plan.montant_joue} + {plan.montant_quinte} ≠ {montant}")
    assert plan.montant_reserve == 0
    assert plan.montant_quinte == mq["cout_total"] == float(int(mq["cout_total"])), (
        "coût en euros entiers : le plan principal garde un montant entier")


@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [4, 10, 20, 50])
def test_plan_principal_construit_sur_le_montant_moins_le_quinte(profil, montant):
    plan = mc.plan_to_dict(_plan(montant, profil))
    principal = mc.plan_to_dict(_corps(int(montant - plan["montant_quinte"]), profil))
    assert plan["niveaux"] and [
        [(p["type"], p["mise"], [c["numero"] for c in p["chevaux"]]) for p in n["paris"]]
        for n in plan["niveaux"]
    ] == [
        [(p["type"], p["mise"], [c["numero"] for c in p["chevaux"]]) for p in n["paris"]]
        for n in principal["niveaux"]
    ]


@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [4, 5, 10, 20, 50])
def test_tranche_du_plan_principal_respectee(profil, montant):
    """Le plan principal garde au moins un pari, dans la tranche de son profil."""
    plan = _plan(montant, profil)
    paris = [p for n in plan.niveaux for p in n.paris]
    assert paris, f"{profil}/{montant} € : plan principal vide"
    assert not any(p.hors_tranche for p in paris)
    plancher = mc.PROFIL_CONFIG[profil].get("rapport_min") or 0.0
    assert all(p.rapport_estime >= plancher for p in paris), (
        [(p.type, p.rapport_estime) for p in paris])
    assert plan.montant_joue >= mc.QUINTE_PRINCIPAL_MIN


@pytest.mark.parametrize("montant,profil,budget,champ", [
    (4, "conservateur", 2, 5), (4, "equilibre", 2, 5), (4, "agressif", 2, 5),
    (10, "conservateur", 2, 5), (10, "equilibre", 2, 5), (10, "agressif", 2, 5),
    (20, "conservateur", 2, 5), (20, "equilibre", 2, 5), (20, "agressif", 2, 5),
    (50, "equilibre", 2, 5), (50, "agressif", 12, 6),
    (60, "equilibre", 12, 6),
    (100, "conservateur", 2, 5), (100, "equilibre", 12, 6), (100, "agressif", 12, 6),
    (200, "conservateur", 2, 5), (200, "equilibre", 12, 6), (200, "agressif", 42, 7),
])
def test_regle_de_budget(montant, profil, budget, champ):
    """Part 15/20/25 %, plafond = moitié et 2 € gardés au plan principal ; chaque
    combinaison à 2 € : le champ se réduit tant que son prix plein dépasse la part,
    le budget ne gonfle jamais et le reliquat retourne au plan principal."""
    regle = mc._regle_budget_quinte(montant, profil)
    assert regle["financable"] is True and regle["en_supplement"] is False
    assert (regle["budget"], regle["champ"]) == (budget, champ)
    assert regle["budget"] == mc._cout_plein_quinte(champ)
    assert montant - regle["budget"] >= mc.QUINTE_PRINCIPAL_MIN


def test_prix_plein_a_deux_euros_la_combinaison():
    assert mc._cout_plein_quinte(5) == 2.0      # tendu : 1 combinaison
    assert mc._cout_plein_quinte(6) == 12.0     # champ 6 : 6 combinaisons
    assert mc._cout_plein_quinte(7) == 42.0     # champ 7 : 21 combinaisons


def test_constantes_alignees_sur_combo_bets_et_le_catalogue_pmu():
    from ml.combo_bets import _JACKPOT_UNIT
    from services.pmu_paris_reference import mise_base
    assert mc.QUINTE_MISE_BASE == _JACKPOT_UNIT == mise_base("Quinté+")


@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [4, 10, 20, 50, 100, 200])
def test_prix_coherents(profil, montant):
    mq = _plan(montant, profil).module_quinte
    n_comb = math.comb(mq["nb_chevaux"], 5)
    assert mq["nb_combinaisons"] == n_comb
    assert mq["mise_unitaire"] == 2.0 and mq["flexi_pct"] == 100
    assert mq["cout_total"] == n_comb * 2.0


def test_champ_reduit_explique_quand_le_budget_ne_suffit_pas():
    mq = _plan(10, "agressif").module_quinte
    assert mq["couverture"] == "tendue" and mq["couverture_visee"] == "champ 7 chevaux"
    assert mq["couverture_reduite"] is True
    assert "42 €" in mq["motif_couverture"]


# ── Montant trop faible / module indisponible ────────────────────────────────

@pytest.mark.parametrize("profil", PROFILS)
@pytest.mark.parametrize("montant", [1, 2, 3])
def test_montant_trop_faible_quinte_ajoute_en_supplement(profil, montant):
    """Sous 4 € : le Quinté+ reste proposé (ticket tendu de 2 €), ajouté au montant ;
    le plan principal garde tout le montant saisi et son pari, et le plan le dit."""
    plan = _plan(montant, profil)
    mq = plan.module_quinte
    saisi = max(2, montant)
    assert mq["disponible"] is True and mq["en_supplement"] is True
    assert mq["couverture"] == "tendue" and mq["cout_total"] == 2.0
    assert plan.montant_quinte == 2.0
    assert plan.montant_joue == saisi and plan.montant_total == saisi + 2
    assert plan.montant_reserve == 0
    assert "4 €" in mq["motif_supplement"] and "ajouté" in mq["motif_supplement"]
    assert "ajouté" in plan.resume_ia
    assert [p for n in plan.niveaux for p in n.paris]


def test_impossibilite_signalee_quand_pas_assez_de_partants():
    """Moins de 5 chevaux exploitables : le module le dit, le plan garde tout."""
    plan = _plan(10, "agressif", dict(_INFO_QUINTE, nb_partants=4), _preds(n=4))
    mq = plan.module_quinte
    assert mq is not None and mq["disponible"] is False
    assert mq["motif"] and "4" in mq["motif"]
    assert plan.montant_quinte == 0.0
    assert plan.montant_joue + plan.montant_reserve == 10


def test_non_partants_exclus_de_la_selection():
    preds = _preds()
    preds[0]["non_partant"] = True
    mq = _plan(20, "equilibre", preds=preds).module_quinte
    assert 1 not in [c["numero"] for c in mq["chevaux"]]


# ── Incertitude ──────────────────────────────────────────────────────────────

def test_rapport_estime_avec_fourchette_et_bonus():
    mq = _plan(200, "agressif").module_quinte
    f = mq["rapport_fourchette"]
    assert f and f["bas"] <= f["median"] <= f["haut"]
    assert f["haut"] > f["bas"], "un champ couvre des arrivées aux rapports différents"
    assert mq["gain_fourchette"]["bas"] == pytest.approx(f["bas"] * mq["mise_unitaire"], abs=0.02)
    assert 0 < mq["proba_gain"] < 1
    assert 0 <= mq["proba_bonus"] < 1


# ── Règlement : ROI mesurable séparément ─────────────────────────────────────

ARRIVEE = [{"numero": n, "position": i} for i, n in enumerate((1, 4, 3, 10, 8), 1)]
DETAIL = {"e_quinte_plus": [
    {"libelle": "e-Quinté+ Ordre", "combinaison": "1-4-3-10-8", "rapport": 11652.4},
    {"libelle": "e-Quinté+ Désordre", "combinaison": "1-4-3-10-8", "rapport": 138.2},
    {"libelle": "e-Bonus 4sur5", "combinaison": "1-4-3-10", "rapport": 4.8},
    {"libelle": "e-Bonus 3", "combinaison": "1-4-3", "rapport": 4.0},
]}
AGREGAT = {"e_quinte_plus": 11652.4}


def _module(numeros, cout):
    return {"disponible": True, "type_pari": "Quinté+ Désordre", "cout_total": cout,
            "couverture": "tendue" if len(numeros) == 5 else f"champ {len(numeros)} chevaux",
            "chevaux": [{"numero": n} for n in numeros]}


def test_reglement_tendu_au_rapport_desordre_jamais_a_l_ordre():
    res = settle_module_quinte(_module([8, 10, 3, 4, 1], 2.0), ARRIVEE, AGREGAT, 16, DETAIL)
    assert res["total_mise"] == 2.0
    assert res["total_gain"] == pytest.approx(276.4)
    assert res["nb_gagnantes"] == 1


def test_reglement_champ_combinaison_par_combinaison_avec_bonus():
    """Champ 6 à 12 € : 6 combinaisons à 2 €. Deux Bonus 4sur5, un Bonus 3."""
    res = settle_module_quinte(_module([1, 4, 3, 10, 11, 12], 12.0), ARRIVEE, AGREGAT, 16, DETAIL)
    assert res["nb_combinaisons"] == 6
    assert res["total_mise"] == 12.0
    assert res["nb_gagnantes"] == 3
    assert res["total_gain"] == pytest.approx(2 * 4.8 * 2 + 2 * 4.0, abs=0.01)
    assert res["net"] == pytest.approx(res["total_gain"] - 12.0, abs=0.01)


def test_reglement_non_partant_rembourse_ses_seules_combinaisons():
    res = settle_module_quinte(_module([1, 4, 3, 10, 8, 12], 12.0), ARRIVEE, AGREGAT, 16,
                               DETAIL, non_partants={12})
    assert res["nb_rembourse"] == 5
    assert res["total_mise"] == pytest.approx(2.0, abs=0.01)
    assert res["total_gain"] == pytest.approx(2 * 138.2, abs=0.01)


def test_settle_plan_separe_le_quinte_du_plan_principal():
    plan = {"niveaux": [{"niveau": "securite", "paris": [{
                "type": "Simple Gagnant", "mise": 8, "chevaux": [{"numero": 2}]}]}],
            "module_quinte": _module([8, 10, 3, 4, 1], 2.0)}
    bilan = settle_plan(plan, ARRIVEE, AGREGAT, 16, DETAIL)
    # Le plan principal : inchangé, seul dans `paris` et dans total_mise/net/roi.
    assert bilan["nb_paris"] == 1 and bilan["total_mise"] == 8.0
    assert bilan["net"] == -8.0 and bilan["roi"] == -100.0
    # Le Quinté+ : ROI à part, et le total réellement engagé.
    assert bilan["module_quinte"]["net"] == pytest.approx(274.4)
    assert bilan["total_avec_quinte"]["total_mise"] == 10.0
    assert bilan["total_avec_quinte"]["net"] == pytest.approx(266.4)


def test_settle_plan_sans_module_n_ajoute_rien():
    plan = {"niveaux": [{"niveau": "securite", "paris": [{
        "type": "Simple Gagnant", "mise": 10, "chevaux": [{"numero": 1}]}]}],
        "module_quinte": {"disponible": False, "cout_total": 0.0}}
    bilan = settle_plan(plan, ARRIVEE, {"simple_gagnant": 2.0}, 16, None)
    assert "module_quinte" not in bilan and "total_avec_quinte" not in bilan


def test_plan_genere_puis_regle_bout_a_bout():
    """Le plan servi se règle tel quel : mises du plan principal + coût du Quinté+
    = montant saisi, et le Quinté+ a son propre bilan."""
    plan = mc.plan_to_dict(_plan(10, "equilibre"))
    arrivee = [{"numero": n, "position": i} for i, n in enumerate((1, 2, 3, 4, 5), 1)]
    # Le PMU publie l'Ordre ET le Désordre : un tendu arrivé dans l'ordre joué est
    # payé à l'Ordre ; sans ce rapport il resterait en attente (jamais inventé).
    detail = {"e_quinte_plus": [
        {"libelle": "e-Quinté+ Ordre", "combinaison": "1-2-3-4-5", "rapport": 900.0},
        {"libelle": "e-Quinté+ Désordre", "combinaison": "1-2-3-4-5", "rapport": 50.0},
        {"libelle": "e-Bonus 4sur5", "combinaison": "1-2-3-4", "rapport": 3.0},
        {"libelle": "e-Bonus 3", "combinaison": "1-2-3", "rapport": 2.0}]}
    bilan = settle_plan(plan, arrivee, {}, 16, detail)
    assert bilan["total_mise"] + bilan["module_quinte"]["total_mise"] == pytest.approx(10.0)
    assert bilan["module_quinte"]["nb_gagnantes"] >= 1
    assert bilan["module_quinte"]["en_attente"] is False
