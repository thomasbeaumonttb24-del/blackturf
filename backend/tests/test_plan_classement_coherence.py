"""Le plan de mise doit être lisible EN FACE du classement de l'IA.

Course de référence : Valparaiso (Chili) du 2026-08-31, 13 partants, celle qui a
déclenché la demande. Le n°5 SO HANDSOME était classé 1er par l'IA et a gagné,
payé 12,70 au Simple Gagnant. Le moteur, lui, l'avait vu à 5,80 (prix gelé) et a
joué le n°2 à 11,0 — dont la cote de clôture était retombée à 4,0.

Les invariants ci-dessous ne jugent pas la SÉLECTION (c'est une décision produit
mesurée ailleurs) : ils exigent que le plan puisse EXPLIQUER ce qu'il a fait du
haut du classement, et avec quel prix.
"""
import pytest

from ml import combo_bets
from ml.combo_bets import enumerate_bet_candidates
from services import mise_calculator as mc


# (numero, nom, cote figée au gel, cote de clôture, proba_top1, proba_top3)
VALPARAISO = [
    (5, "SO HANDSOME", 5.8, 12.0, 0.1318, 0.5193),
    (13, "TE LO CEDO", 6.6, 6.2, 0.1065, 0.1564),
    (3, "MISTER CESAR", 11.0, 25.0, 0.0940, 0.4591),
    (9, "BETTER THAN", 10.0, 12.0, 0.0958, 0.1502),
    (2, "ANAHEIM", 11.0, 4.0, 0.0937, 0.1522),
    (8, "BONE LESS", 8.2, 12.0, 0.0940, 0.1663),
    (4, "JARRA DE VINO", 10.0, 5.0, 0.0798, 0.4594),
    (1, "LIUCURA PARK", 12.0, 9.7, 0.0689, 0.1129),
    (6, "RESPECT", 20.0, 42.0, 0.0531, 0.1223),
    (11, "RADIO TEATRO", 13.0, 18.0, 0.0581, 0.1240),
    (7, "TAISEI", 15.0, 34.0, 0.0578, 0.3704),
    (12, "BIG WALLACE", 33.0, 43.0, 0.0370, 0.1196),
    (10, "TUYARAK", 41.0, 57.0, 0.0296, 0.0879),
]

COURSE_INFO = {
    "nb_partants": 13, "est_quinte": False, "est_quarte": False, "est_tierce": False,
    "est_2sur4": False,
    "paris_disponibles": ["E_COUPLE_GAGNANT", "E_COUPLE_PLACE", "E_SIMPLE_GAGNANT",
                          "E_SIMPLE_PLACE", "E_TRIO"],
}


def _preds(colonne_cote: int) -> list[dict]:
    """colonne_cote : 2 = cote figée (production), 3 = cote de clôture."""
    return [{"numero": h[0], "nom_cheval": h[1], "cote_pmu": h[colonne_cote],
             "proba_top1": h[4], "proba_top3": h[5], "non_partant": False}
            for h in VALPARAISO]


def _paris(plan) -> list:
    return [p for niv in plan.niveaux for p in niv.paris]


# ── Le prix utilisé par le moteur doit être visible ─────────────────────────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_chaque_cheval_joue_porte_la_cote_utilisee_et_son_rang(profil):
    """Sans cette information, « Plan de mise » et « Synthèse » peuvent afficher deux
    prix différents pour le même cheval sans que rien ne l'explique."""
    plan = mc.generer_plan(10, profil, _preds(2), COURSE_INFO, respect_montant=True)
    paris = _paris(plan)
    if not paris:
        pytest.skip("plan vide honnête pour ce profil sur cette course")
    for p in paris:
        for h in p.chevaux:
            assert h.get("cote"), f"{profil} — cote manquante sur {h}"
            assert h.get("rang"), f"{profil} — rang manquant sur {h}"
            assert 1 <= h["rang"] <= len(VALPARAISO)


def test_la_cote_portee_est_bien_celle_qui_a_servi_au_calcul():
    """Le prix affiché doit être celui du calcul, pas une valeur ré-affichée
    d'ailleurs : on rejoue la même course aux cotes de clôture et le prix suit."""
    plan_fige = mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO,
                                respect_montant=True)
    plan_clot = mc.generer_plan(10, "agressif", _preds(3), COURSE_INFO,
                                respect_montant=True)
    cotes_figees = {h["numero"]: h["cote"] for p in _paris(plan_fige) for h in p.chevaux}
    cotes_clot = {h["numero"]: h["cote"] for p in _paris(plan_clot) for h in p.chevaux}
    ref_figee = {h[0]: h[2] for h in VALPARAISO}
    ref_clot = {h[0]: h[3] for h in VALPARAISO}
    assert cotes_figees, "aucun pari retenu aux cotes figées"
    for num, cote in cotes_figees.items():
        assert cote == pytest.approx(ref_figee[num], abs=0.05)
    for num, cote in cotes_clot.items():
        assert cote == pytest.approx(ref_clot[num], abs=0.05)


def test_le_rapport_du_ticket_est_expose():
    """Le multiplicateur est la promesse du profil ; il doit être une donnée, pas
    seulement une phrase dans `raisons`."""
    plan = mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO, respect_montant=True)
    for p in _paris(plan):
        assert p.rapport_estime > 0
        # gain_potentiel = mise × rapport, à l'arrondi entier près
        assert abs(p.gain_potentiel - p.mise * p.rapport_estime) <= max(
            1.0, 0.02 * p.mise * p.rapport_estime)


# ── Le plan doit répondre « pourquoi pas le n°1 ? » ─────────────────────────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_le_plan_situe_les_trois_premiers_du_classement(profil):
    plan = mc.generer_plan(10, profil, _preds(2), COURSE_INFO, respect_montant=True)
    assert len(plan.classement) == 3, f"{profil} — {plan.classement}"
    assert [c["rang"] for c in plan.classement] == [1, 2, 3]
    assert plan.classement[0]["numero"] == 5      # SO HANDSOME, favori de l'IA
    for c in plan.classement:
        assert c["joue"] is True or c.get("motif"), c


def test_le_favori_ia_non_joue_recoit_un_motif_precis_pas_une_formule_creuse():
    """Cas exact de la course de référence en profil risqué : le n°5 est 1er au
    classement mais sa cote figée (5,8) ne peut pas payer la tranche ×10 du profil.

    En production ce jour-là, les poids appris supprimaient le Couplé Gagnant — il ne
    restait donc AUCUN ticket portant le n°5, et le plan n'a joué que le n°2. On
    reproduit exactement cette configuration (poids à 0 = type supprimé par
    l'apprentissage) plutôt que de sauter le test : c'est le cas qui a motivé la
    demande, il doit être couvert, et le motif doit citer le chiffre qui bloque.
    """
    poids_prod = {"Couplé Gagnant": 0.0, "Couplé Ordre": 0.0, "Trio": 0.0,
                  "Trio Ordre": 0.0}
    plan = mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO,
                           roi_weights=poids_prod, respect_montant=True)
    joues = {h["numero"] for p in _paris(plan) for h in p.chevaux}
    assert 5 not in joues, "le n°5 est joué : ce n'est plus le cas à expliquer"
    fav = plan.classement[0]
    assert fav["numero"] == 5 and fav["joue"] is False, fav
    motif = fav["motif"]
    assert "Conviction inférieure" not in motif, (
        "motif générique alors que le vrai motif est la tranche de rapport : " + motif)
    assert "×5.8" in motif or "×10.0" in motif, motif
    assert fav.get("meilleur_pari_possible"), fav


def test_le_favori_ia_est_joue_quand_son_prix_le_permet():
    """Aux cotes de clôture, le n°5 vaut 12,0 : il entre dans la tranche ×10 du
    profil risqué. Le raccord classement→plan doit alors le montrer JOUÉ — c'est le
    contrôle négatif du test précédent."""
    plan = mc.generer_plan(10, "agressif", _preds(3), COURSE_INFO, respect_montant=True)
    fav = plan.classement[0]
    assert fav["numero"] == 5
    assert fav["joue"] is True, fav


# ── Les paris écartés doivent parler du haut du classement ──────────────────

def test_les_paris_ecartes_ne_sont_pas_tous_des_simple_place():
    """Avant le 2026-09-01 la liste était triée par probabilité décroissante : elle
    ne contenait donc QUE des Simple Placé, jamais le pari qu'on aurait pu faire sur
    le favori de l'IA."""
    plan = mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO, respect_montant=True)
    ecartes = plan.paris_ecartes
    assert ecartes
    assert len({e["type"] for e in ecartes}) > 1, ecartes
    rangs = [h.get("rang") for e in ecartes for h in e["chevaux"]]
    assert 1 in rangs, "aucun pari écarté ne concerne le n°1 du classement"


def test_chaque_pari_ecarte_porte_rang_et_rapport():
    plan = mc.generer_plan(10, "equilibre", _preds(2), COURSE_INFO, respect_montant=True)
    for e in plan.paris_ecartes:
        assert e.get("motif")
        assert e.get("rapport_estime") is not None
        for h in e["chevaux"]:
            assert h.get("rang")


# ── Le gain affiché ne doit jamais dépasser ce que le ticket peut payer ─────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
@pytest.mark.parametrize("colonne", [2, 3])
def test_le_gain_affiche_ne_depasse_jamais_mise_fois_rapport(profil, colonne):
    """Le plancher de tranche servait à rattraper l'arrondi entier du gain ; appliqué
    sans condition, il remontait aussi le gain d'un pari retenu HORS bande (repli
    « chaque course est jouée ») au plancher du profil — un chiffre que le PMU ne
    paierait jamais. Le gain affiché doit rester ≤ mise × rapport, à l'unité près."""
    plan = mc.generer_plan(10, profil, _preds(colonne), COURSE_INFO,
                           respect_montant=True)
    for p in _paris(plan):
        plafond = p.mise * p.rapport_estime
        assert p.gain_potentiel <= plafond + 1, (
            f"{profil} — {p.type} : {p.gain_potentiel}€ affichés pour "
            f"{p.mise}€ × ×{p.rapport_estime}")


def test_le_gain_dun_pari_hors_bande_nest_pas_remonte_au_plancher():
    """Cas construit : un ticket dont le rapport (×3) est sous la tranche du risqué
    (×10). Son gain doit rester 3 × la mise, pas 10 ×."""
    c = {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 5, "nom": "X"}],
         "mise": 10, "rapport_estime": 3.0, "proba_gain": 0.3, "ev": -0.1,
         "niveau": "surprise", "texte_explication": "test", "_hors_bande": True}
    plan = mc._assemble_plan([c], 10, mc._palier(10), False, "agressif")
    pari = plan.niveaux[0].paris[0]
    assert pari.gain_potentiel == 30, pari.gain_potentiel


# ── Le marché qui bouge après le gel doit se voir ───────────────────────────

def test_reprice_signale_le_ticket_sorti_de_sa_tranche():
    """Le plan figé promettait ×10 sur le n°2 à 11,0 ; à la clôture il ne paie plus
    que ×4. Le repricing doit marquer le ticket, pas seulement rabaisser le gain en
    silence."""
    plan = mc.plan_to_dict(mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO,
                                           respect_montant=True))
    paris_figes = [p for niv in plan["niveaux"] for p in niv["paris"]]
    if not paris_figes:
        pytest.skip("aucun pari figé à re-tarifer")
    live = mc.reprice_plan_live(plan, _preds(3), COURSE_INFO)
    paris = [p for niv in live["niveaux"] for p in niv["paris"]]
    retarifes = [p for p in paris if "rapport_live" in p]
    assert retarifes, "aucun pari re-tarifé : le signal serait toujours muet"
    for p in retarifes:
        assert p["rapport_live"] > 0
    assert "marche_a_bouge" in live
    assert "paris_hors_tranche_live" in live


def test_le_gagnant_sec_est_retarife_meme_hors_catalogue_live():
    """Cas exact du 2026-08-31 : le plan risqué figé annonçait « N°2, gain ~103 € »
    (cote 11,0) alors que le marché était retombé à 4,0. Le n°2 ne figurait plus dans
    le catalogue reconstruit aux cotes de clôture, donc l'ancien repricing gardait le
    gain figé et la page continuait d'afficher 103 €. Un gagnant sec n'a pas besoin du
    catalogue : son rapport EST la cote du cheval."""
    plan = {
        "profil": "agressif", "montant_total": 10,
        "niveaux": [{"niveau": "surprise", "montant": 10, "paris": [{
            "type": "Simple Gagnant",
            "chevaux": [{"numero": 2, "nom": "ANAHEIM", "cote": 11.0, "rang": 5}],
            "mise": 10, "gain_potentiel": 103, "probabilite": 0.0867,
            "ev_estime": -0.107, "rapport_estime": 10.3,
        }]}],
    }
    live = mc.reprice_plan_live(plan, _preds(3), COURSE_INFO)
    pari = live["niveaux"][0]["paris"][0]
    assert pari["rapport_live"] == pytest.approx(4.0, abs=0.05)
    assert pari["gain_potentiel"] == pytest.approx(40, abs=1)
    assert pari["rapport_a_bouge"] is True
    assert pari["hors_tranche_live"] is True     # ×4 sous la tranche ×10 du risqué
    assert pari["chevaux"][0]["cote_live"] == pytest.approx(4.0, abs=0.05)
    assert live["marche_a_bouge"] is True
    assert live["paris_hors_tranche_live"] == 1


def test_reprice_ne_signale_rien_quand_le_marche_na_pas_bouge():
    """Contrôle négatif : re-tarifer sur les MÊMES cotes ne doit alarmer personne."""
    plan = mc.plan_to_dict(mc.generer_plan(10, "agressif", _preds(2), COURSE_INFO,
                                           respect_montant=True))
    live = mc.reprice_plan_live(plan, _preds(2), COURSE_INFO)
    assert live["marche_a_bouge"] is False
    assert live["paris_hors_tranche_live"] == 0


# ── Le catalogue doit toujours contenir le gagnant sec des têtes de classement ──

def _catalogue(colonne_cote: int) -> list[dict]:
    preds = [{"numero": p["numero"], "nom": p["nom_cheval"],
              "proba_top1": p["proba_top1"], "proba_top3": p["proba_top3"],
              "cote_pmu": p["cote_pmu"]} for p in _preds(colonne_cote)]
    return enumerate_bet_candidates(preds, COURSE_INFO)


def test_le_simple_gagnant_des_deux_premiers_est_toujours_au_catalogue():
    """Le n°5 (1er au classement, cote figée 5,8) n'avait AUCUN Simple Gagnant : le
    pool était trié « edge positif d'abord » puis tronqué à 3, et un favori du modèle
    payé à son juste prix par le marché en sortait. Mesuré sur 721 courses le
    2026-09-01 : 18,2 % des courses, et le cheval y gagnait 22,9 % du temps."""
    sg = {h["numero"] for c in _catalogue(2) if c["type_pari"] == "Simple Gagnant"
          for h in c["chevaux"]}
    assert 5 in sg, "le 1er du classement n'a pas de Simple Gagnant"
    assert 13 in sg, "le 2e du classement n'a pas de Simple Gagnant"


def test_sans_la_garantie_le_premier_du_classement_disparaissait():
    """Contrôle : sans la garantie, on retrouve exactement le trou qu'on corrige.
    Si ce test cesse d'échouer à 0, c'est que le pool a changé ailleurs et que la
    garantie ne sert peut-être plus — il faut alors re-mesurer, pas la retirer."""
    ancien = combo_bets.SG_RANGS_GARANTIS
    combo_bets.SG_RANGS_GARANTIS = 0
    try:
        sg = {h["numero"] for c in _catalogue(2)
              if c["type_pari"] == "Simple Gagnant" for h in c["chevaux"]}
    finally:
        combo_bets.SG_RANGS_GARANTIS = ancien
    assert 5 not in sg


def test_la_garantie_ne_force_pas_un_cheval_sous_la_cote_minimale():
    """Garantir n'est pas inventer : sous SG_COTE_MIN, le gagnant sec reste exclu
    (le gain ne vaut pas le risque, règle antérieure conservée)."""
    preds = [{"numero": p["numero"], "nom": p["nom_cheval"],
              "proba_top1": p["proba_top1"], "proba_top3": p["proba_top3"],
              "cote_pmu": (1.4 if p["numero"] == 5 else p["cote_pmu"])}
             for p in _preds(2)]
    sg = {h["numero"] for c in enumerate_bet_candidates(preds, COURSE_INFO)
          if c["type_pari"] == "Simple Gagnant" for h in c["chevaux"]}
    assert 5 not in sg


# ── Le plan cite l'outil « Value bets » au lieu de l'ignorer ────────────────

def test_le_value_bet_detecte_remonte_dans_le_plan():
    """`/mise-plan` chargeait les value bets puis les jetait : la page « Value bets »
    et le plan parlaient des mêmes chevaux sans jamais se citer."""
    preds = _preds(3)
    for p in preds:
        if p["numero"] == 5:
            p["value_bet"] = {"ev_max": 0.42, "niveau": 2}
    plan = mc.generer_plan(10, "agressif", preds, COURSE_INFO, respect_montant=True)
    vus = [h for pari in _paris(plan) for h in pari.chevaux if h["numero"] == 5]
    assert vus, "le n°5 n'est pas joué : cas hors sujet pour ce test"
    assert vus[0].get("value_bet") == {"ev_max": 0.42, "niveau": 2}
    assert plan.classement[0]["value_bet"] == {"ev_max": 0.42, "niveau": 2}


def test_aucun_value_bet_invente_quand_il_ny_en_a_pas():
    plan = mc.generer_plan(10, "agressif", _preds(3), COURSE_INFO, respect_montant=True)
    for pari in _paris(plan):
        for h in pari.chevaux:
            assert h.get("value_bet") is None
    for c in plan.classement:
        assert c.get("value_bet") is None


def test_reprice_expose_la_cote_live_a_cote_de_la_cote_du_plan():
    plan = mc.plan_to_dict(mc.generer_plan(10, "equilibre", _preds(2), COURSE_INFO,
                                           respect_montant=True))
    live = mc.reprice_plan_live(plan, _preds(3), COURSE_INFO)
    ref_clot = {h[0]: h[3] for h in VALPARAISO}
    ref_figee = {h[0]: h[2] for h in VALPARAISO}
    vus = 0
    for niv in live["niveaux"]:
        for p in niv["paris"]:
            for h in p["chevaux"]:
                if "cote_live" not in h:
                    continue
                vus += 1
                assert h["cote_live"] == pytest.approx(ref_clot[h["numero"]], abs=0.05)
                assert h["cote"] == pytest.approx(ref_figee[h["numero"]], abs=0.05)
    assert vus, "aucune cote live posée en face de la cote du plan"
