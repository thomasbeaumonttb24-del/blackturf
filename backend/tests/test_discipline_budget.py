"""Discipline de mise : le levier ne doit plus être inatteignable.

Constat qui impose ces tests : `_appliquer_discipline_mise` et tout le moteur de
risque (Kelly, plafond de corrélation, discount d'incertitude) vivaient dans la
branche ``else`` de ``if respect_montant:`` — or les quatre appelants de
``generer_plan``, en production comme dans l'apprentissage, passent
``respect_montant=True``. Le code le plus rentable du moteur (contrefactuel mesuré :
−16,0 % → −6,1 % de ROI selon la concentration) n'a donc jamais tourné une fois.

La correction sépare deux questions qui n'en formaient qu'une :
  - ``respect_montant`` : COMMENT répartir, et faut-il tout déployer ;
  - ``discipline_mise`` : COMBIEN engager au total sur cette course.
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
    multiplicateur réellement observé (0.60). Sert à prouver que la discipline
    mord — pas à décrire la production."""
    from ml.signal_performance import PB_BUCKETS
    buckets = {f"{lo:g}_{hi:g}": {"multiplier": 0.60} for lo, hi in PB_BUCKETS}
    return {"payout_buckets": {t: dict(buckets) for t in types}}


# ── Le drapeau existe et est indépendant de respect_montant ──────────────────

def test_les_deux_drapeaux_sont_bien_deux_parametres_distincts():
    import inspect
    sig = inspect.signature(mc.generer_plan).parameters
    assert "respect_montant" in sig
    assert "discipline_mise" in sig, (
        "la discipline doit être demandable indépendamment du respect du montant")
    assert sig["discipline_mise"].default is None, (
        "None = repli sur le comportement historique, pour ne rien changer aux "
        "appelants qui ne se prononcent pas")


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_la_discipline_reduit_la_somme_engagee_sur_un_plan_systeme(profil):
    """Toutes les tranches au pire multiplicateur mesuré → on n'engage pas tout."""
    plan = mc.generer_plan(20, profil, _field(), COURSE_INFO, respect_montant=True,
                           rapport_calib=_calib_mauvaise(), discipline_mise=True)
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu sur ce profil avec cette table")
    assert plan.montant_joue < 20, "la somme engagée doit suivre la qualité mesurée"
    assert plan.montant_reserve == 20 - plan.montant_joue
    assert plan.montant_joue >= mc.MISE_PLANCHER, "le plan ne disparaît jamais"


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_sans_discipline_le_montant_saisi_reste_integralement_joue(profil):
    """Invariant du calculateur MANUEL : l'utilisateur a saisi, on déploie."""
    plan = mc.generer_plan(20, profil, _field(), COURSE_INFO, respect_montant=True,
                           rapport_calib=_calib_mauvaise(), discipline_mise=False)
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu sur ce profil avec cette table")
    assert plan.montant_joue == 20
    assert plan.montant_reserve == 0


def test_sans_table_apprise_la_discipline_n_engage_rien_de_moins():
    """Démarrage à froid : sans mesure, aucune réduction inventée."""
    plan = mc.generer_plan(20, "equilibre", _field(), COURSE_INFO,
                           respect_montant=True, discipline_mise=True)
    assert plan.montant_joue in (0, 20)


def test_le_budget_ne_descend_jamais_sous_le_prix_du_ticket_le_plus_cher():
    """Un Multi en 4 coûte 3 € au guichet : réduire sous ce prix ne fait pas
    économiser, ça rend le plan injouable."""
    from services.pmu_paris_reference import cout_minimum
    assert cout_minimum("Multi en 4") == 3.0
    # 40 % de 6 € = 2 €, soit moins que le ticket : le plancher guichet l'emporte.
    engage = mc._budget_discipline([{"type_pari": "Multi en 4", "_pb_mult": 0.60}],
                                   6, mc.MISE_PLANCHER)
    assert engage == 3


def test_le_budget_engage_ne_depasse_jamais_le_budget_demande():
    """Un ticket plus cher que le plan entier ne peut pas faire GONFLER la mise :
    la sélection l'a déjà écarté, la discipline ne doit pas le ressusciter."""
    engage = mc._budget_discipline([{"type_pari": "Multi en 5", "_pb_mult": 0.60}],
                                   10, mc.MISE_PLANCHER)
    assert engage == 10


def test_le_ratio_suit_la_qualite_mesuree():
    assert mc._budget_discipline([{"_pb_mult": 1.00}], 20, 2) == 20
    assert mc._budget_discipline([{"_pb_mult": 0.60}], 20, 2) == 8      # 40 %
    assert mc._budget_discipline([{"_pb_mult": 0.80}], 20, 2) == 14     # 70 %


def test_la_qualite_est_moyennee_sur_les_tickets_reellement_retenus():
    """Un ticket sain et un mauvais → réduction intermédiaire, pas le pire des deux."""
    engage = mc._budget_discipline([{"_pb_mult": 1.00}, {"_pb_mult": 0.60}], 20, 2)
    assert 8 < engage < 20


# ── Le plan système est identifié par son montant de référence ───────────────

def test_le_montant_de_reference_est_celui_de_l_apprentissage():
    from ml.profil_learning import MISE_REF
    assert mc.MISE_REF_SYSTEME == MISE_REF, (
        "les deux constantes décrivent le MÊME plan : celui que le système fige "
        "avant course et sur lequel toute la rentabilité est mesurée")


def test_est_plan_systeme():
    assert mc.est_plan_systeme(10) is True
    assert mc.est_plan_systeme(10.0) is True
    assert mc.est_plan_systeme(20) is False
    assert mc.est_plan_systeme(None) is False
    assert mc.est_plan_systeme("bruit") is False


# ── Les appelants se prononcent explicitement ────────────────────────────────

def test_le_plan_fige_du_systeme_demande_la_discipline():
    import inspect
    from ml import profil_learning
    src = inspect.getsource(profil_learning.record_profil_runs)
    assert "discipline_mise=True" in src, (
        "le plan figé est LE plan du système : personne n'a saisi ce montant")


def test_les_routes_ne_disciplinent_que_le_plan_systeme():
    import inspect
    from api.routes import courses
    src = inspect.getsource(courses)
    assert src.count("discipline_mise=") == 3, (
        "les trois générations de plan des routes doivent se prononcer")
    assert "discipline_mise=est_plan_systeme(montant)" in src
    assert "discipline_mise=_eps(montant)" in src


# ── Garde-fous de risque : atteignables sous l'allocation réellement utilisée ─

def test_le_moteur_de_risque_vit_dans_l_allocation_reellement_utilisee():
    """Les trois profils allouent en `spread`. Un garde-fou qui n'existe que dans
    `_allocate_kelly` ne protège donc personne."""
    import inspect
    src = inspect.getsource(mc._allocate_spread)
    assert "_apply_correlation_cap" in src
    assert "_uncertainty_discount" in src


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


def test_sans_reserve_autorisee_le_montant_reste_integralement_joue():
    """Sur un montant SAISI, le plafond cède devant le contrat « tout jouer »."""
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


# ── Le contrat de tranche survit à la réduction du budget ────────────────────

@pytest.mark.parametrize("profil,cible", [("equilibre", 4.0), ("agressif", 10.0)])
def test_le_contrat_de_gain_porte_sur_la_somme_engagee(profil, cible):
    """La promesse « un ticket gagnant rend ≥ ×g » doit tenir sur ce qui est
    RÉELLEMENT misé — c'est pourquoi la discipline agit sur le budget AVANT
    l'allocation, et pas en rognant les mises après coup."""
    plan = mc.generer_plan(20, profil, _field(), COURSE_INFO, respect_montant=True,
                           rapport_calib=_calib_mauvaise(), discipline_mise=True)
    if plan.montant_joue == 0:
        pytest.skip("aucun pari retenu")
    paris = [p for n in plan.niveaux for p in n.paris]
    assert paris
    meilleur = max(p.gain_potentiel for p in paris)
    assert meilleur >= cible * plan.montant_joue * 0.98, (
        f"{profil} : gain max {meilleur} € pour {plan.montant_joue} € engagés")
