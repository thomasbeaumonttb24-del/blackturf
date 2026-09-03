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


# ── 2. Les types qui ne paient jamais sont hors du profil risqué ────────────

TYPES_SANS_AUCUN_GAGNANT = ["Super 4", "Pick5", "Multi en 4", "Multi en 5"]


@pytest.mark.parametrize("type_mort", TYPES_SANS_AUCUN_GAGNANT + ["Trio", "Trio Ordre"])
def test_le_profil_risque_ne_propose_plus_les_types_perdants(type_mort):
    """Mesuré sur les règlements réels : Super 4, Pick5 et Multi en 4 comptent
    ZÉRO gagnant sur 134, 86 et 145 paris — donc −100 % par construction, pas par
    malchance. Le Trio rend −58,7 % winsorisé sur 13 682 paris."""
    assert type_mort not in mc.PROFIL_CONFIG["agressif"]["types"]


def test_le_profil_risque_garde_de_quoi_jouer():
    """Retirer six types ne doit pas vider le catalogue : le risqué garde ses duos
    et ses jackpots à l'ordre, qui portent sa tranche ≥ ×10."""
    restants = mc.PROFIL_CONFIG["agressif"]["types"]
    assert "Couplé Gagnant" in restants
    assert "Simple Gagnant" in restants
    assert len(restants) >= 5


def test_les_mini_multi_sont_couverts_par_la_normalisation():
    """`_fam` ramène « Mini Multi en N » à « Multi en N » : retirer Multi en 4/5
    retire aussi leurs variantes Mini, sans avoir à les lister."""
    for t in ("Mini Multi en 4", "Mini Multi en 5"):
        assert mc._fam(t) not in mc.PROFIL_CONFIG["agressif"]["types"]


def test_les_autres_profils_ne_sont_pas_touches():
    """La mesure portait sur le seul profil risqué ; le Trio reste au modéré, où il
    n'a pas été mesuré séparément."""
    assert "Trio" in mc.PROFIL_CONFIG["equilibre"]["types"]


# ── 2 bis. Retirer un type du profil doit le retirer des PLANS ──────────────
# Les tests ci-dessus vérifient la CONFIG. Ils étaient verts pendant que la
# production émettait quand même ces types : le 2026-09-02, 18 des 57 paris du
# profil risqué portaient un type retiré la veille (Trio, Trio Ordre, Super 4,
# Mini Multi en 4) ou jamais présent (Couplé Placé). Tous venaient du FILET, dont
# la première étape de relâchement lâchait le TYPE en gardant la bande de rapport
# — c'est-à-dire exactement la porte par laquelle les types à gros rapport
# rentraient. Un test sur la config ne peut pas voir ça ; il faut regarder le plan.

# Course RÉELLE 02092026R7C5 (Plat, 8 partants), prédictions figées avant le départ.
# Choisie parce qu'elle reproduit exactement le cas de production : aucun cheval
# au-dessus de la cote 5,7, donc aucun Simple Gagnant à ×10 et aucune combinaison
# ancrée sur les deux favoris (1,9 et 3,8) qui atteigne la tranche du profil. Seules
# des combinaisons HORS catalogue y arrivent — et c'est un Trio à EV −0,498 que la
# production a effectivement servi ce jour-là.
_COURSE_REELLE_02092026R7C5 = [
    # numero, cote figée, proba_top1, proba_top3   (dans l'ordre du rang prédit)
    (6, 1.9, 0.254281, 0.393272),
    (5, 3.8, 0.132223, 0.513108),
    (4, 5.7, 0.098921, 0.336218),
    (1, 5.0, 0.098772, 0.310585),
    (2, 5.0, 0.101687, 0.559948),
    (7, 5.0, 0.112382, 0.358819),
    (3, 5.7, 0.102391, 0.312622),
    (8, 5.0, 0.099342, 0.215428),
]


def _course_ou_seuls_les_types_hors_profil_paient(n=8):
    """Peloton où AUCUN pari du catalogue risqué n'atteint ×10, alors que des
    combinaisons hors catalogue (Trio, Couplé Placé) y arrivent — c'est là que le
    filet lâchait le type."""
    return [{"numero": num, "nom_cheval": "Cheval%d" % num, "cote_pmu": cote,
             "proba_top1": p1, "proba_top3": p3, "non_partant": False}
            for num, cote, p1, p3 in _COURSE_REELLE_02092026R7C5[:n]]


# La course R7C5 n'offrait ni Tiercé ni Quarté ni Quinté : sans ces jackpots, le
# catalogue du risqué se réduit aux duos et au Simple Gagnant, aucun n'atteignant ×10.
COURSE_INFO_R7C5 = dict(COURSE_INFO, nb_partants=8, est_tierce=False)


def _types_joues(plan):
    return [p.type for niv in plan.niveaux for p in niv.paris]


def _plans_du_risque(preds, info):
    return [mc.generer_plan(m, "agressif", preds, info, respect_montant=True)
            for m in (5, 10, 20, 50)]


class _RisqueAncrageStrict:
    """Reproduit l'état EXACT de la production du 2026-09-02 : le risqué en ancrage
    strict. C'est cet état qui vidait la sélection et faisait tomber toutes les
    courses sur le filet — la démonstration du défaut a donc besoin de lui, même si
    le réglage a depuis été retiré du profil (cf. `ancrage_strict`)."""

    def __enter__(self):
        self._ancien = mc.PROFIL_CONFIG["agressif"].get("ancrage_strict", False)
        mc.PROFIL_CONFIG["agressif"]["ancrage_strict"] = True

    def __exit__(self, *exc):
        mc.PROFIL_CONFIG["agressif"]["ancrage_strict"] = self._ancien
        return False


def _types_hors_catalogue(preds, info):
    autorises = mc.PROFIL_CONFIG["agressif"]["types"]
    return [t for plan in _plans_du_risque(preds, info)
            for t in _types_joues(plan) if mc._fam(t) not in autorises]


@pytest.mark.parametrize("fabrique,info", [
    (_course_ou_seuls_les_types_hors_profil_paient, COURSE_INFO_R7C5),
    (_course_sans_candidat_dans_la_bande, dict(COURSE_INFO, nb_partants=14)),
])
def test_le_filet_ne_sert_jamais_un_type_hors_du_profil(fabrique, info):
    """Invariant : un type absent du catalogue d'un profil ne doit sortir d'AUCUN
    chemin du moteur — sélection, complément manuel ou filet de secours."""
    preds = fabrique(info["nb_partants"])
    with _RisqueAncrageStrict():
        hors = _types_hors_catalogue(preds, info)
    assert not hors, ("le plan risqué sert %s, hors de son catalogue %s"
                      % (sorted(set(hors)),
                         sorted(mc.PROFIL_CONFIG["agressif"]["types"])))


def test_sans_la_garde_le_filet_sortait_du_catalogue():
    """Contrôle négatif : en repassant le drapeau à False, le type hors catalogue
    doit réapparaître. C'est le Trio — le type le plus lourdement retiré du profil
    (−58,7 % winsorisé sur 13 682 paris) — qui revient, parce que la première étape
    de relâchement gardait la bande de rapport et lâchait le type, et que les types à
    gros rapport sont précisément ceux qui tiennent la tranche ×10.

    Si ce test cesse d'échouer, c'est que la course de démonstration ne déclenche plus
    le filet et qu'il faut en construire une autre — surtout pas retirer la garde."""
    preds = _course_ou_seuls_les_types_hors_profil_paient(8)
    ancien = mc._REPLI_RESPECTE_TYPE
    mc._REPLI_RESPECTE_TYPE = False
    try:
        with _RisqueAncrageStrict():
            hors = _types_hors_catalogue(preds, COURSE_INFO_R7C5)
    finally:
        mc._REPLI_RESPECTE_TYPE = ancien
    assert hors, ("la course de démonstration ne fait plus sortir de type hors "
                  "catalogue même sans la garde : le test ne prouve plus rien")


def test_la_garde_ne_vide_aucun_plan():
    """La garde de type ne doit pas coûter la promesse « chaque course est jouée » :
    le catalogue du risqué contient le Simple Gagnant, disponible sur toute course.
    """
    for fabrique, info in ((_course_ou_seuls_les_types_hors_profil_paient,
                            COURSE_INFO_R7C5),
                           (_course_sans_candidat_dans_la_bande,
                            dict(COURSE_INFO, nb_partants=14)),
                           (_course_sans_candidat_dans_la_bande,
                            dict(COURSE_INFO, nb_partants=5))):
        preds = fabrique(info["nb_partants"])
        for profil in ("conservateur", "equilibre", "agressif"):
            plan = mc.generer_plan(10, profil, preds, info, respect_montant=True)
            assert sum(len(niv.paris) for niv in plan.niveaux) >= 1, (
                "%s : plan vide sur un champ de %d"
                % (profil, info["nb_partants"]))


def _champ_ou_le_filet_choisissait_la_loterie():
    """Tête de champ SUR-JOUÉE et queue longue : le filet y a le choix entre un
    Simple Gagnant à EV −0,417 et un Couplé Gagnant à EV nulle, et prenait le
    premier sans la garde.

    Reconstruit le 2026-09-03 avec le passage du plafond de rang du risqué à 4.
    L'ancien champ (cotes ×1,35 par rang à partir de 1,5) plaçait son pari sous le
    plancher au rang 5 et au-delà : hors du plafond, il ne sortait plus du tout, et
    le test devenait vert sans rien prouver — ce que son assertion annonçait
    elle-même. Les quatre premiers sont désormais courts (2,20 / 2,53 / 2,91 /
    3,35) pour que l'EV négative soit ACCESSIBLE au profil, et la queue reste
    longue pour que le Couplé Gagnant des deux premiers reste finançable comme
    alternative à EV nulle. Marge conservée sur le seuil : −0,417 contre −0,40.
    """
    rows = [(0.19, 2.20), (0.18, 2.53), (0.17, 2.91), (0.16, 3.35),
            (0.09, 13.0), (0.07, 20.0), (0.05, 30.0), (0.04, 45.0),
            (0.03, 60.0), (0.03, 75.0), (0.02, 90.0), (0.02, 110.0)]
    return [{"numero": i + 1, "nom_cheval": "Cheval%d" % (i + 1),
             "cote_pmu": c, "proba_top1": p, "proba_top3": min(p * 2.6, 0.95),
             "non_partant": False}
            for i, (p, c) in enumerate(rows)]


def _pire_ev_du_risque(preds, info):
    evs = [p.ev_estime for plan in _plans_du_risque(preds, info)
           for niv in plan.niveaux for p in niv.paris if p.ev_estime is not None]
    return min(evs) if evs else None


def test_le_filet_refuse_la_loterie_pure_quand_il_a_le_choix():
    """Le filet est le seul chemin du moteur sans borne d'EV : la sélection normale
    refuse sous `SPEC_EV_FLOOR` (−0,40), pas lui. En production le 2026-09-02 il a
    servi des Trios à −0,498 et −0,483 d'EV.

    ⚠ HONNÊTETÉ DE LA MESURE : au rejeu A/B sur 1 200 courses, ce plancher seul vaut
    +0,3 point de ROI winsorisé — c'est-à-dire RIEN de mesurable. Il est conservé
    parce qu'il ferme le seul chemin du moteur sans borne d'EV, pas parce qu'il
    rapporte. Le gain mesuré du lot vient de la garde de TYPE, pas d'ici."""
    preds = _champ_ou_le_filet_choisissait_la_loterie()
    info = dict(COURSE_INFO, nb_partants=len(preds))
    avec = _pire_ev_du_risque(preds, info)

    ancien = mc._REPLI_PLANCHER_EV
    mc._REPLI_PLANCHER_EV = False
    try:
        sans = _pire_ev_du_risque(preds, info)
    finally:
        mc._REPLI_PLANCHER_EV = ancien

    assert sans is not None and sans < -0.40, (
        "ce champ ne fait plus sortir de pari sous le plancher même sans la garde : "
        "le test ne prouve plus rien, il faut en construire un autre")
    assert avec is not None and avec >= -0.40, (
        "pari de filet à EV %.3f, sous le plancher de loterie pure" % avec)


def test_le_plancher_dev_ne_vide_pas_le_plan():
    """Le plancher est une PRÉFÉRENCE : si aucun candidat ne le tient, la course reste
    jouée. Champ de cotes courtes où rien n'atteint la tranche du risqué."""
    preds = _course_sans_candidat_dans_la_bande(6)
    info = dict(COURSE_INFO, nb_partants=6)
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(10, profil, preds, info, respect_montant=True)
        assert sum(len(niv.paris) for niv in plan.niveaux) >= 1


# ── 3. Le gate marché ────────────────────────────────────────────────────────

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
