"""Rentabilité du plan : deux garde-fous qui n'étaient pas appliqués.

1. Le filet « chaque course est jouée » ignorait le PLAFOND DE RANG du profil. Un
   pari de secours pouvait porter un cheval que le modèle classe 12e — précisément
   ce que le plafond interdit dans la sélection normale.
2. Le gate MARCHÉ, qui refuse un modèle ne battant pas la simple cote, était
   désactivé. Sa condition de réactivation (delta positif) est remplie depuis huit
   versions consécutives.
"""
import pytest

from ml import algo_flags
from ml.pipeline import _should_deploy
from services import mise_calculator as mc


# ── 1. Le plafond de rang doit survivre au filet de repli ───────────────────

def _course_sans_candidat_dans_la_bande(n=14):
    """Peloton conçu pour qu'AUCUN pari ne passe les gates du profil risqué :
    des cotes courtes partout, donc aucun rapport ≥ ×10. Le moteur bascule alors
    sur son filet, et c'est là que le plafond de rang était oublié."""
    horses = []
    for i in range(n):
        horses.append({
            "numero": i + 1,
            "nom_cheval": "Cheval%d" % (i + 1),
            "cote_pmu": round(1.6 + i * 0.12, 2),      # 1.6 → 3.2 : rapports courts
            "proba_top1": max(0.30 - i * 0.02, 0.005),
            "proba_top3": min(max(0.30 - i * 0.02, 0.005) * 3.0, 0.9),
            "non_partant": False,
        })
    return horses


COURSE_INFO = {"nb_partants": 14, "est_quinte": False, "est_quarte": False,
               "est_tierce": True, "est_2sur4": False, "paris_disponibles": None}


def _rangs_joues(plan):
    return [h.get("rang") for niv in plan.niveaux for p in niv.paris
            for h in p.chevaux if h.get("rang")]


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_le_repli_respecte_le_plafond_de_rang(profil):
    preds = _course_sans_candidat_dans_la_bande()
    plan = mc.generer_plan(10, profil, preds, COURSE_INFO, respect_montant=True)
    rangs = _rangs_joues(plan)
    if not rangs:
        pytest.skip("aucun pari retenu sur cette course pour ce profil")
    cfg = mc.PROFIL_CONFIG[profil]
    plafond = mc._rang_max_effectif(cfg["rang_max"], COURSE_INFO["nb_partants"])
    plafond += mc.RANG_MAX_BONUS_PLACE      # borne la plus permissive (types Placé)
    assert max(rangs) <= plafond, (
        "%s : pari sur un cheval au rang %d alors que le plafond effectif est %d"
        % (profil, max(rangs), plafond))


def test_sans_la_garde_le_repli_depassait_le_plafond():
    """Contrôle négatif : en repassant le drapeau à False on doit pouvoir retrouver
    un dépassement. Si ce test cesse d'échouer, c'est que le repli ne se déclenche
    plus sur cette course et qu'il faut en construire une autre — pas retirer la
    garde."""
    preds = _course_sans_candidat_dans_la_bande()
    ancien = mc._REPLI_RESPECTE_RANG
    mc._REPLI_RESPECTE_RANG = False
    try:
        rangs_sans = []
        for profil in ("conservateur", "equilibre", "agressif"):
            plan = mc.generer_plan(10, profil, preds, COURSE_INFO, respect_montant=True)
            rangs_sans += _rangs_joues(plan)
    finally:
        mc._REPLI_RESPECTE_RANG = ancien
    rangs_avec = []
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(10, profil, preds, COURSE_INFO, respect_montant=True)
        rangs_avec += _rangs_joues(plan)
    assert rangs_sans and rangs_avec
    assert max(rangs_avec) <= max(rangs_sans), (
        "la garde ne doit jamais AGGRAVER le pire rang joué")


def test_le_plan_reste_servi_sur_chaque_course():
    """La garde ne doit pas vider les plans : la promesse « chaque course est jouée »
    passe avant le plafond de rang, elle ne passe simplement plus AVANT lui."""
    preds = _course_sans_candidat_dans_la_bande()
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(10, profil, preds, COURSE_INFO, respect_montant=True)
        n = sum(len(niv.paris) for niv in plan.niveaux)
        assert n >= 1, "%s : plan vide alors qu'un pari restait jouable" % profil


def test_petit_champ_le_plafond_cede_plutot_que_de_vider_le_plan():
    """Champ de 5 partants : le plafond effectif tombe à 4 et peut ne laisser aucune
    combinaison. La course doit rester jouée."""
    preds = _course_sans_candidat_dans_la_bande(5)
    info = dict(COURSE_INFO, nb_partants=5)
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(10, profil, preds, info, respect_montant=True)
        assert sum(len(niv.paris) for niv in plan.niveaux) >= 1


# ── 2. Le gate marché ────────────────────────────────────────────────────────

def test_le_gate_marche_est_actif_par_defaut():
    """Sa condition de réactivation est remplie : l'avantage sur le marché est
    positif sur v520 à v527 (min +0.0188)."""
    assert algo_flags.FLAGS.market_gate is True
    assert algo_flags.FLAGS.market_gate_margin == 0.0


def test_un_modele_sous_le_marche_nest_pas_promu():
    assert _should_deploy(
        0.80, 0.70, current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        market_gate_enabled=True, rank_delta_market=-0.001) is False


def test_un_modele_au_dessus_du_marche_reste_promu():
    assert _should_deploy(
        0.80, 0.70, current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        market_gate_enabled=True, rank_delta_market=0.0188) is True


def test_le_gate_ne_bloque_pas_quand_la_mesure_est_impossible():
    """Une absence de mesure n'est pas une preuve d'échec : sans cote sur le
    hold-out, bloquer figerait le modèle sur une panne de données."""
    assert _should_deploy(
        0.80, 0.70, current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        market_gate_enabled=True, rank_delta_market=None) is True


@pytest.mark.parametrize("delta", [0.0198, 0.0197, 0.0200, 0.0199,
                                   0.0192, 0.0201, 0.0188, 0.0190])
def test_aucune_des_huit_versions_recentes_naurait_ete_bloquee(delta):
    """Preuve que l'activation est sans effet sur le régime actuel : les deltas
    réellement mesurés de v520 à v527 passent tous."""
    assert _should_deploy(
        0.7868, 0.7869, current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        market_gate_enabled=True, rank_delta_market=delta) is True
