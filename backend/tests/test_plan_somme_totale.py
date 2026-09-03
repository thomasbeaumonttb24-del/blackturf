"""Le montant affiché est le montant joué — sur TOUS les plans servis.

Constat qui impose ces tests (2026-09-03) : l'écran du plan de mise annonçait
« Budget 10 € » puis « Total joué 9,00 € », et le bilan d'après course « MISÉ 9 € ».
Deux mécanismes retenaient l'argent sur le plan SYSTÈME (le montant de référence,
celui que personne n'a saisi) :

  - une « discipline de mise » qui n'engageait que 40 à 100 % du budget selon la
    qualité mesurée des tranches de rapport retenues ;
  - le plafond d'exposition par cheval qui, faute de pari décorrélé pour absorber
    l'excédent, laissait cet excédent non engagé.

Aucun des deux ne se voyait dans l'interface : `montant_reserve` existait côté API,
était typé côté front, et n'était affiché nulle part. Arbitrage de l'utilisateur :
tout jouer, toujours. Le levier de rentabilité qui reste est le CHOIX des paris.
"""
import pytest

from services import mise_calculator as mc


def _horse(numero, cote, p1, p3):
    return {"numero": numero, "nom_cheval": f"Cheval{numero}", "cote_pmu": cote,
            "proba_top1": p1, "proba_top3": p3, "non_partant": False}


def _field(n=12):
    out = []
    for i in range(n):
        p1 = max(0.35 - i * 0.028, 0.006)
        out.append(_horse(i + 1, round(1.8 + i * 2.3, 1), p1, min(p1 * 3.2, 0.92)))
    return out


COURSE_INFO = {"nb_partants": 12, "est_quinte": False, "est_quarte": False,
               "est_tierce": True, "est_2sur4": False, "paris_disponibles": None}

_TYPES = ["Simple Gagnant", "Simple Placé", "Couplé Gagnant", "Couplé Placé",
          "Couplé Ordre", "Trio", "Trio Ordre", "2sur4", "Tiercé Désordre",
          "Tiercé Ordre", "Multi en 4", "Multi en 5", "Multi en 6", "Multi en 7",
          "Mini Multi en 4", "Mini Multi en 5", "Mini Multi en 6", "Mini Multi en 7",
          "Quarté+ Désordre", "Quinté+ Désordre", "Super 4", "Pick5"]


def _calib_mauvaise(types=_TYPES):
    """Table apprise fictive : toutes les tranches de tous les types au PIRE
    multiplicateur réellement observé (0.60). C'est exactement la situation qui
    faisait fondre la somme engagée — elle ne doit plus rien retenir."""
    from ml.signal_performance import PB_BUCKETS
    buckets = {f"{lo:g}_{hi:g}": {"multiplier": 0.60} for lo, hi in PB_BUCKETS}
    return {"payout_buckets": {t: dict(buckets) for t in types}}


# ── L'invariant produit ──────────────────────────────────────────────────────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
@pytest.mark.parametrize("montant", [10, 20])
def test_le_montant_affiche_est_le_montant_joue(profil, montant):
    """Cas qui produisait la réserve : la pire table apprise possible."""
    plan = mc.generer_plan(montant, profil, _field(), COURSE_INFO,
                           respect_montant=True, rapport_calib=_calib_mauvaise())
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu sur ce profil avec cette table")
    assert plan.montant_joue == montant, (
        f"{profil} : {plan.montant_joue} € joués pour un plan annoncé à {montant} €")
    assert plan.montant_reserve == 0, "aucune réserve silencieuse"


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_le_montant_de_reference_du_systeme_est_joue_en_entier(profil):
    """10 € = le montant du plan SYSTÈME, celui que personne n'a saisi et sur lequel
    toute la rentabilité est mesurée. C'est LUI qui sous-misait."""
    from ml.profil_learning import MISE_REF
    plan = mc.generer_plan(MISE_REF, profil, _field(), COURSE_INFO,
                           respect_montant=True, rapport_calib=_calib_mauvaise())
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu")
    assert plan.montant_joue == MISE_REF
    assert plan.montant_reserve == 0


def test_la_somme_des_mises_egale_le_montant():
    """Le total affiché est la somme des tickets, pas une valeur recalculée à part."""
    plan = mc.generer_plan(10, "agressif", _field(), COURSE_INFO,
                           respect_montant=True, rapport_calib=_calib_mauvaise())
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu")
    assert sum(p.mise for n in plan.niveaux for p in n.paris) == 10


def test_plus_aucun_drapeau_de_discipline_de_budget():
    """La réserve ne doit pas pouvoir revenir par un paramètre oublié."""
    import inspect
    sig = inspect.signature(mc.generer_plan).parameters
    assert "discipline_mise" not in sig
    assert not hasattr(mc, "_budget_discipline")
    assert not hasattr(mc, "est_plan_systeme")


def test_les_routes_ne_disciplinent_plus_le_budget():
    import inspect
    from api.routes import courses
    src = inspect.getsource(courses)
    assert "discipline_mise" not in src
    assert "est_plan_systeme" not in src


def test_le_plan_fige_du_systeme_joue_tout():
    import inspect
    from ml import profil_learning
    src = inspect.getsource(profil_learning.record_profil_runs)
    assert "discipline_mise" not in src


# ── Le contrat de tranche tient sur la somme entière ─────────────────────────

@pytest.mark.parametrize("profil,cible", [("equilibre", 4.0), ("agressif", 10.0)])
def test_le_contrat_de_gain_porte_sur_le_montant_entier(profil, cible):
    """La promesse « un ticket gagnant rend ≥ ×g de la mise TOTALE » se mesure
    maintenant sur le montant entier, puisqu'il est intégralement joué."""
    plan = mc.generer_plan(20, profil, _field(), COURSE_INFO, respect_montant=True,
                           rapport_calib=_calib_mauvaise())
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu")
    paris = [p for n in plan.niveaux for p in n.paris]
    assert paris
    meilleur = max(p.gain_potentiel for p in paris)
    assert meilleur >= cible * plan.montant_joue * 0.98, (
        f"{profil} : gain max {meilleur} € pour {plan.montant_joue} € joués")


# ── Garde-fous de risque : atteignables sous l'allocation réellement utilisée ─

def test_le_moteur_de_risque_vit_dans_l_allocation_reellement_utilisee():
    """Les trois profils allouent en `spread`. Un garde-fou qui n'existe que dans
    `_allocate_kelly` ne protège donc personne."""
    import inspect
    src = inspect.getsource(mc._allocate_spread)
    assert "_apply_correlation_cap" in src
    assert "_uncertainty_discount" in src


def test_le_plafond_de_correlation_ne_retient_plus_d_argent():
    """Aucun pari décorrélé pour absorber l'excédent = le cas NORMAL (tous les
    tickets sont ancrés sur les deux premiers du classement). Le plafond cède, le
    montant reste joué."""
    import inspect
    src = inspect.getsource(mc._allocate_spread)
    assert "respect_montant=True, cap_fn=_cap" in src
    assert "autoriser_reserve" not in src


def test_le_plafond_de_correlation_respecte_le_plafond_de_bande():
    """Déplacer de l'argent pour casser une corrélation ne doit pas faire sortir un
    ticket par le HAUT de la tranche de son profil."""
    paris = [
        {"type_pari": "Couplé Gagnant", "chevaux": [{"numero": 1}, {"numero": 2}],
         "mise": 9, "proba_gain": 0.10, "rapport_estime": 8.0},
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 3}],
         "mise": 9, "proba_gain": 0.30, "rapport_estime": 3.0},
        {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 5}],
         "mise": 2, "proba_gain": 0.10, "rapport_estime": 9.0},
    ]
    total = sum(p["mise"] for p in paris)
    mc._apply_correlation_cap(paris, total, 2, respect_montant=True,
                              cap_fn=lambda b: 3)
    assert sum(p["mise"] for p in paris) == total, "le montant reste conservé"
    assert paris[2]["mise"] <= 3


def test_le_plafond_regarde_tous_les_paris_exposes_pas_seulement_le_plus_faible():
    """Dès que le pari le moins convaincant touchait son plancher contractuel, la
    boucle rendait la main — alors que rogner le SUIVANT suffisait à rentrer sous le
    plafond. Avec l'ancrage sur les 2 premiers du classement, tous les tickets
    partagent leurs chevaux : c'était le cas NORMAL, pas une exception."""
    paris = [
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 2}],
         "mise": 15, "_besoin": 15, "proba_gain": 0.30, "rapport_estime": 5.0},
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 3}],
         "mise": 18, "_besoin": 12, "proba_gain": 0.25, "rapport_estime": 6.0},
    ]
    # Le premier est DÉJÀ à son plancher (_besoin) ; seul le second a de la marge.
    mc._apply_correlation_cap(paris, 40, 2, respect_montant=False)
    expo = sum(p["mise"] for p in paris)          # les deux portent le cheval n°1
    assert expo <= int(40 * mc.MAX_HORSE_EXPOSURE_FRAC) + 1, expo
    assert paris[0]["mise"] == 15, "le pari au plancher contractuel n'est pas touché"
    assert paris[1]["mise"] >= 12, "on ne descend jamais sous le contrat de gain"


def test_le_montant_reste_integralement_joue_sous_le_plafond():
    paris = [
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 2}],
         "mise": 22, "_besoin": 15, "proba_gain": 0.30, "rapport_estime": 5.0},
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 3}],
         "mise": 18, "_besoin": 12, "proba_gain": 0.25, "rapport_estime": 6.0},
    ]
    mc._apply_correlation_cap(paris, 40, 2, respect_montant=True)
    assert sum(p["mise"] for p in paris) == 40


def test_le_plafond_de_correlation_termine_quand_tout_est_au_plafond():
    """Tous les paris déjà au plafond : la boucle de redistribution doit sortir."""
    paris = [
        {"type_pari": "Couplé Gagnant", "chevaux": [{"numero": 1}, {"numero": 2}],
         "mise": 20, "proba_gain": 0.10, "rapport_estime": 8.0},
        {"type_pari": "Couplé Placé", "chevaux": [{"numero": 1}, {"numero": 3}],
         "mise": 20, "proba_gain": 0.30, "rapport_estime": 3.0},
        {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 5}],
         "mise": 2, "proba_gain": 0.10, "rapport_estime": 9.0},
    ]
    mc._apply_correlation_cap(paris, 42, 2, respect_montant=True, cap_fn=lambda b: 2)
    assert sum(p["mise"] for p in paris) == 42
