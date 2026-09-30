"""Règlement des plans sur le détail officiel PMU (combinaisons payées publiées).

Cas tirés des arrivées réelles rejouées le 2026-09-30 (resultats.rapports_detail) :
chaque ticket est cherché dans la liste des combinaisons payées, comme le fait le PMU.
"""
from services.bet_settlement import settle_pari, settle_plan


def _cl(*places):
    """Classement : (numéro, place) ; place None = non classé."""
    return [{"numero": n, "position": p} for n, p in places]


def _d(cle, *entrees):
    return {cle: [{"libelle": lib, "combinaison": comb, "rapport": rap} for lib, comb, rap in entrees]}


def _paye(res):
    assert res["gagne"] and not res.get("rembourse") and res["rapport_reel"] is not None, res
    return round(res["rapport_reel"] * res["gain_mult"], 4)


# 16082026R6C4 — 10 partants, n°10 non-partant.
CL_R6C4 = _cl((8, 1), (9, 2), (2, 3), (7, 4), (5, 5), (4, 6))
DET_R6C4 = {
    **_d("e_couple_place", ("e-Couplé Placé", "8-9", 7.3), ("e-Couplé Placé", "8-2", 8.2),
         ("e-Couplé Placé", "9-2", 13.9), ("e-Couplé Placé 1 NP", "9-NP", 3.0),
         ("e-Couplé Placé 1 NP", "2-NP", 3.3)),
    **_d("e_simple_place", ("e-Simple Placé", "8", 1.9), ("e-Simple Placé", "9", 3.4),
         ("e-Simple Placé", "2", 2.8)),
}


def test_couple_place_1_np_paye_au_rapport_np():
    res = settle_pari("Couplé Placé", [9, 10], CL_R6C4, {}, 10, DET_R6C4, {10})
    assert _paye(res) == 3.0


def test_couple_place_1_np_perdu_si_l_autre_n_est_pas_place():
    # Avant : remboursé. Le PMU ne paie « 1 NP » que si l'autre cheval est placé.
    res = settle_pari("Couplé Placé", [7, 10], CL_R6C4, {}, 10, DET_R6C4, {10})
    assert not res["gagne"] and not res.get("rembourse")


def test_couple_place_1_np_non_publie_pour_le_gagnant_reste_rembourse():
    # 11092026R3C8 : « 1-NP » absent du détail alors que 11-NP et 9-NP sont publiés.
    cl = _cl((1, 1), (11, 2), (9, 3), (5, 4), (2, 5))
    det = {**_d("e_couple_place", ("e-Couplé Placé", "1-11", 4.2), ("e-Couplé Placé", "1-9", 6.7),
                ("e-Couplé Placé", "11-9", 3.9), ("e-Couplé Placé 1 NP", "11-NP", 1.6),
                ("e-Couplé Placé 1 NP", "9-NP", 1.9)),
           **_d("e_simple_place", ("e-Simple Placé", "1", 2.3), ("e-Simple Placé", "11", 1.3),
                ("e-Simple Placé", "9", 2.0))}
    res = settle_pari("Couplé Placé", [4, 1], cl, {}, 12, det, {4, 6, 10})
    assert res.get("rembourse")


def test_trio_1_np_paye_si_les_deux_autres_sont_1er_et_2e():
    # 28072026R4C4
    cl = _cl((5, 1), (1, 2), (4, 3), (3, 4), (7, 5))
    det = _d("e_trio", ("e-Trio", "5-1-4", 29.9), ("e-Trio 1 NP", "5-1-NP", 14.5))
    assert _paye(settle_pari("Trio", [1, 8, 5], cl, {}, 9, det, {8, 9})) == 14.5
    perdu = settle_pari("Trio", [5, 4, 8], cl, {}, 9, det, {8, 9})
    assert not perdu["gagne"] and not perdu.get("rembourse")


def test_places_payees_lues_dans_la_liste_publiee():
    # nb_partants = 8 exclut déjà le retiré : l'ancien recompte (8 − 1 = 7 → 2 places)
    # réglait perdant le 3ᵉ, que le PMU paie.
    cl = _cl((4, 1), (3, 2), (6, 3), (1, 4))
    det = _d("simple_place", ("Simple Placé", "4", 1.4), ("Simple Placé", "3", 2.1),
             ("Simple Placé", "6", 1.6))
    assert _paye(settle_pari("Simple Placé", [6], cl, {}, 8, det, {2})) == 1.6


def test_multi_ex_aequo_a_la_4e_place():
    # 20082026R1C4 : 5 et 8 ex æquo 4ᵉ, deux combinaisons publiées.
    cl = _cl((1, 1), (7, 2), (3, 3), (5, 4), (8, 4), (10, 6))
    det = _d("e_multi", ("e-Multi en 4", "1-7-3-5", 115.5), ("e-Multi en 4", "1-7-3-8", 115.5),
             ("e-Multi en 5", "1-7-3-5", 23.1), ("e-Multi en 5", "1-7-3-8", 23.1))
    assert _paye(settle_pari("Multi en 4", [1, 7, 3, 8], cl, {}, 16, det)) == 115.5
    assert _paye(settle_pari("Multi en 5", [1, 7, 3, 5, 12], cl, {}, 16, det)) == 23.1


def test_couple_gagnant_ex_aequo_paye_son_propre_rapport():
    # 01082026R9C6 : 5 et 6 ex æquo 2ᵉ. L'agrégat (9,6 = 7-5) payait aussi 7-6.
    cl = _cl((7, 1), (5, 2), (6, 2), (10, 4))
    det = _d("e_couple_gagnant", ("e-Couplé Gagnant", "7-5", 9.6), ("e-Couplé Gagnant", "7-6", 5.2))
    assert _paye(settle_pari("Couplé Gagnant", [7, 6], cl, {"e_couple_gagnant": 9.6}, 10, det)) == 5.2


def test_simple_gagnant_dead_heat():
    cl = _cl((4, 1), (11, 1), (8, 3))
    det = _d("e_simple_gagnant", ("e-Simple Gagnant", "4", 2.1), ("e-Simple Gagnant", "11", 5.1))
    assert _paye(settle_pari("Simple Gagnant", [11], cl, {"e_simple_gagnant": 2.1}, 16, det)) == 5.1


def test_quinte_ordre_sans_la_tirelire():
    # 19082026R1C8 : l'Ordre payait 47 818,2 (avec la Tirelire) au lieu de 22 818,2.
    cl = _cl((4, 1), (10, 2), (12, 3), (11, 4), (7, 5))
    det = _d("e_quinte_plus", ("e-Quinté+ Ordre + e-Tirelire", "4-10-12-11-7", 47818.2),
             ("e-Quinté+ Ordre", "4-10-12-11-7", 22818.2),
             ("e-Quinté+ Désordre", "4-10-12-11-7", 291.5))
    res = settle_pari("Quinté+ Désordre", [4, 10, 12, 11, 7], cl, {}, 16, det)
    assert _paye(res) == 22818.2 and res["note"] == "Rang de gain : Ordre."


def test_2sur4_formule_avec_un_non_partant():
    # 17082026R2C3, n°1 non-partant. Ticket 5-1-7 = 3 combinaisons : 5-7 (1,2),
    # 5-NP (1,1), 7-NP (1,1). Avant : tout remboursé.
    cl = _cl((5, 1), (7, 2), (3, 3), (2, 4), (10, 5))
    det = _d("e_deux_sur_quatre", ("e-2sur4", "5-7", 1.2), ("e-2sur4", "5-3", 1.2),
             ("e-2sur4 1 NP", "5-NP", 1.1), ("e-2sur4 1 NP", "7-NP", 1.1))
    assert _paye(settle_pari("2sur4", [5, 1, 7], cl, {}, 11, det, {1})) == round((1.2 + 1.1 + 1.1) / 3, 4)
    # 10-1 : le 10 est 5ᵉ → combinaison NP perdue, pas remboursée.
    perdu = settle_pari("2sur4", [10, 1], cl, {}, 11, det, {1})
    assert not perdu["gagne"] and not perdu.get("rembourse")


def test_pick5_1_np():
    # 17082026R3C8, n°15 non-partant : payé si les quatre autres sont les 4 premiers.
    cl = _cl((12, 1), (1, 2), (9, 3), (10, 4), (5, 5), (11, 6))
    det = _d("e_pick5", ("e-Pick5", "12-1-9-10-5", 305.8), ("e-Pick5 1 NP", "12-1-9-10-NP", 136.4))
    assert _paye(settle_pari("Pick5", [12, 1, 9, 10, 15], cl, {}, 8, det, {15})) == 136.4
    # Champ de 6 : 12-1-9-10-5 (305,8) + 12-1-9-10-15 (136,4) sur 6 combinaisons.
    assert _paye(settle_pari("Pick5", [12, 1, 9, 10, 5, 15], cl, {}, 8, det, {15})) == \
        round((305.8 + 136.4) / 6, 4)


def test_remboursement_general_publie():
    # 26082026R5C8 : trois chevaux à l'arrivée, Super 4 remboursé par le PMU.
    cl = _cl((2, 1), (8, 2), (5, 3), (1, None), (3, None))
    det = _d("e_super_quatre", ("Remboursement e-Super4", "Autres Chevaux", 1.0))
    res = settle_pari("Super 4", [2, 8, 5, 1], cl, {"e_super_quatre": 1.0}, 8, det)
    assert res.get("rembourse") and res["rapport_reel"] == 1.0


def test_non_partant_en_base_mais_classe_a_couru():
    # 06082026R6C4 : le n°8, marqué non-partant en base, a gagné (payé au Simple).
    cl = _cl((8, 1), (3, 2), (5, 3), (7, 4))
    det = _d("e_simple_gagnant", ("e-Simple Gagnant", "8", 14.5))
    assert _paye(settle_pari("Simple Gagnant", [8], cl, {}, 12, det, {8})) == 14.5


def test_combinaison_publiee_tronquee_completee_par_l_arrivee():
    # 27092026R14C2 : Trio publié « 5-6 » au rapport de 5-6-8.
    cl = _cl((5, 1), (6, 2), (8, 3), (2, 4))
    det = _d("e_trio", ("e-Trio", "5-6", 30.1))
    assert _paye(settle_pari("Trio", [8, 5, 6], cl, {"e_trio": 30.1}, 14, det)) == 30.1
    perdu = settle_pari("Trio", [5, 6, 2], cl, {"e_trio": 30.1}, 14, det)
    assert not perdu["gagne"]


def test_detail_incomplet_ticket_gagnant_reste_en_attente():
    # L'arrivée dit gagné, le détail ne publie pas la combinaison : attente, pas perdu.
    cl = _cl((1, 1), (2, 2), (3, 3))
    det = _d("e_couple_gagnant", ("e-Couplé Gagnant", "1-3", 9.0))
    res = settle_pari("Couplé Gagnant", [1, 2], cl, {}, 8, det)
    assert res["gagne"] and res["rapport_reel"] is None


def test_sans_detail_repli_sur_le_classement():
    cl = _cl((1, 1), (2, 2), (3, 3))
    res = settle_pari("Couplé Gagnant", [2, 1], cl, {"couple_gagnant": 7.5}, 8)
    assert _paye(res) == 7.5


def test_settle_plan_conventions_inchangees():
    cl = CL_R6C4
    plan = {"niveaux": [{"niveau": 1, "paris": [
        {"type": "Couplé Placé", "mise": 2.0, "chevaux": [{"numero": 9}, {"numero": 10}]},
        {"type": "Couplé Placé", "mise": 2.0, "chevaux": [{"numero": 7}, {"numero": 10}]},
        {"type": "Simple Placé", "mise": 2.0, "chevaux": [{"numero": 10}]},
    ]}]}
    bilan = settle_plan(plan, cl, {}, 10, DET_R6C4, {10})
    statuts = [p["statut"] for p in bilan["paris"]]
    assert statuts == ["gagne", "perdu", "rembourse"]
    assert bilan["total_mise"] == 4.0 and bilan["total_gain"] == 6.0
    assert bilan["nb_rembourse"] == 1 and not bilan["en_attente"]
