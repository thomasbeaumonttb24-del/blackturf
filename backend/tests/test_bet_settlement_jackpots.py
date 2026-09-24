"""Règlement des rapports PMU détaillés pour les formules désordre."""

from services.bet_settlement import settle_pari, settle_plan


ARRIVEE = [{"numero": n, "position": i} for i, n in enumerate((1, 4, 3, 10, 8), 1)]
DETAIL = {
    "e_tierce": [
        {"libelle": "e-Tiercé Ordre", "combinaison": "1-4-3", "rapport": 1479.9},
        {"libelle": "e-Tiercé Désordre", "combinaison": "1-4-3", "rapport": 175.8},
    ],
    "e_quarte_plus": [
        {"libelle": "e-Quarté+ Ordre", "combinaison": "1-4-3-10", "rapport": 2115.4},
        {"libelle": "e-Quarté+ Désordre", "combinaison": "1-4-3-10", "rapport": 168.5},
        {"libelle": "e-Bonus", "combinaison": "1-4-3", "rapport": 21.4},
    ],
    "e_quinte_plus": [
        {"libelle": "e-Quinté+ Ordre", "combinaison": "1-4-3-10-8", "rapport": 11652.4},
        {"libelle": "e-Quinté+ Désordre", "combinaison": "1-4-3-10-8", "rapport": 138.2},
        {"libelle": "e-Bonus 4sur5", "combinaison": "1-4-3-10", "rapport": 4.8},
        {"libelle": "e-Bonus 3", "combinaison": "1-4-3", "rapport": 4.0},
    ],
}
AGGREGATE = {key: entries[0]["rapport"] for key, entries in DETAIL.items()}


def test_jackpot_desordre_uses_desordre_report_not_aggregate_order():
    for bet_type, numbers, expected in (
        ("Tiercé Désordre", [4, 1, 3], 175.8),
        ("Quarté+ Désordre", [4, 1, 10, 3], 168.5),
        ("Quinté+ Désordre", [4, 1, 10, 3, 8], 138.2),
    ):
        result = settle_pari(bet_type, numbers, ARRIVEE, AGGREGATE, 16, DETAIL)
        assert result["gagne"] is True
        assert result["rapport_reel"] == expected


def test_quinte_bonus_and_quarte_bonus():
    for bet_type, numbers, expected in (
        ("Quinté+ Désordre", [1, 4, 3, 10, 12], 4.8),
        ("Quinté+ Désordre", [1, 4, 3, 11, 12], 4.0),
        ("Quarté+ Désordre", [1, 4, 3, 12], 21.4),
    ):
        result = settle_pari(bet_type, numbers, ARRIVEE, AGGREGATE, 16, DETAIL)
        assert result["gagne"] is True
        assert result["rapport_reel"] == expected


def test_missing_specific_report_stays_pending_without_order_fallback():
    result = settle_pari("Quinté+ Désordre", [1, 4, 3, 10, 8], ARRIVEE,
                         AGGREGATE, 16, None)
    assert result["gagne"] is True
    assert result["rapport_reel"] is None


def test_incomplete_result_does_not_create_bonus():
    result = settle_pari("Quinté+ Désordre", [2, 3, 4, 5, 6],
                         [{"numero": 1, "position": 1}], AGGREGATE, 16, DETAIL)
    assert result["gagne"] is False


def test_plan_bonus_return_uses_actual_bonus_report():
    plan = {"niveaux": [{"niveau": "coup", "paris": [{
        "type": "Quinté+ Désordre", "mise": 2,
        "chevaux": [{"numero": n} for n in (1, 4, 3, 10, 12)],
    }]}]}
    result = settle_plan(plan, ARRIVEE, AGGREGATE, 16, DETAIL)
    assert result["total_gain"] == 9.6
    assert result["net"] == 7.6
    assert result["nb_gagnes"] == 1


# ── Quinté+ : les rangs de gain, rapports RÉELS de 22092026R1C4 ──────────────
# Arrivée 1-4-3-10-8. Le PMU publie UNE entrée « e-Bonus 4sur5 » PAR 4-uplet de
# l'arrivée (cinq entrées, même rapport 4,8 — relevé en base, lecture seule, le
# 2026-09-24) ; `DETAIL` ci-dessus n'en garde qu'une, comme une collecte tronquée.
DETAIL_COMPLET = {"e_quinte_plus": [
    {"libelle": "e-Quinté+ Ordre", "combinaison": "1-4-3-10-8", "rapport": 11652.4},
    {"libelle": "e-Quinté+ Désordre", "combinaison": "1-4-3-10-8", "rapport": 138.2},
    {"libelle": "e-Bonus 4sur5", "combinaison": "1-4-10-8", "rapport": 4.8},
    {"libelle": "e-Bonus 4sur5", "combinaison": "1-4-3-10", "rapport": 4.8},
    {"libelle": "e-Bonus 4sur5", "combinaison": "1-4-3-8", "rapport": 4.8},
    {"libelle": "e-Bonus 4sur5", "combinaison": "1-3-10-8", "rapport": 4.8},
    {"libelle": "e-Bonus 4sur5", "combinaison": "4-3-10-8", "rapport": 4.8},
    {"libelle": "e-Bonus 3", "combinaison": "1-4-3", "rapport": 4.0},
]}


def _quinte(numbers, detail=DETAIL, **kw):
    return settle_pari("Quinté+ Désordre", numbers, ARRIVEE, AGGREGATE, 16, detail, **kw)


def test_quinte_cinq_sur_cinq_dans_l_ordre_paie_l_ordre():
    for detail in (DETAIL, DETAIL_COMPLET):
        res = _quinte([1, 4, 3, 10, 8], detail)
        assert res["gagne"] is True and res["rapport_reel"] == 11652.4


def test_quinte_cinq_sur_cinq_dans_un_autre_ordre_paie_le_desordre():
    res = _quinte([4, 1, 3, 10, 8], DETAIL_COMPLET)
    assert res["gagne"] is True and res["rapport_reel"] == 138.2


def test_quinte_ordre_exact_d_un_champ_regle_au_desordre():
    """Combinaison issue d'un champ : l'ordre n'est pas supposé couvert."""
    res = _quinte([1, 4, 3, 10, 8], DETAIL_COMPLET, ordre_joue=False)
    assert res["rapport_reel"] == 138.2


def test_quinte_ordre_sans_rapport_ordre_publie_reste_en_attente():
    """« ordre » est une sous-chaîne de « désordre » : sans entrée Ordre, on ne
    paie JAMAIS l'Ordre au rapport Désordre."""
    sans_ordre = {"e_quinte_plus": [e for e in DETAIL_COMPLET["e_quinte_plus"]
                                    if e["libelle"] != "e-Quinté+ Ordre"]}
    res = _quinte([1, 4, 3, 10, 8], sans_ordre)
    assert res["gagne"] is True and res["rapport_reel"] is None


def test_quinte_ordre_avec_tirelire():
    avec_tirelire = {"e_quinte_plus": [
        {"libelle": "e-Quinté+ Désordre", "combinaison": "1-4-3-10-8", "rapport": 138.2},
        {"libelle": "e-Quinté+ Ordre + e-Tirelire", "combinaison": "1-4-3-10-8",
         "rapport": 25000.0}]}
    assert _quinte([1, 4, 3, 10, 8], avec_tirelire)["rapport_reel"] == 25000.0


def test_quinte_bonus_4sur5_avec_un_autre_4_uplet_que_celui_publie():
    """4 des 5 premiers, pas forcément les 4 premiers (ex. 1-4-3-8 sans le 4ᵉ
    arrivé) : le détail tronqué ne publie que 1-4-3-10, le Bonus 4sur5 est dû."""
    for numbers in ([1, 4, 3, 8, 12], [4, 3, 10, 8, 2], [1, 3, 10, 8, 14]):
        for detail in (DETAIL, DETAIL_COMPLET):
            res = _quinte(numbers, detail)
            assert res["gagne"] is True and res["rapport_reel"] == 4.8, (numbers, res)
            assert "Bonus 4sur5" in res["note"]


def test_quinte_bonus_4sur5_ne_prend_pas_un_4_uplet_etranger_a_l_arrivee():
    faux = {"e_quinte_plus": [{"libelle": "e-Bonus 4sur5", "combinaison": "1-4-3-12",
                               "rapport": 99.0}]}
    res = _quinte([1, 4, 3, 8, 12], faux)
    assert res["gagne"] is True and res["rapport_reel"] is None


def test_quinte_trois_sur_cinq():
    # Les 3 premiers (podium) : Bonus 3.
    res = _quinte([1, 4, 3, 11, 12], DETAIL_COMPLET)
    assert res["gagne"] is True and res["rapport_reel"] == 4.0
    # 3 des 5 premiers mais pas le podium : rien (Bonus 3 = les 3 PREMIERS).
    assert _quinte([1, 10, 8, 11, 12], DETAIL_COMPLET)["gagne"] is False


def test_quinte_zero_sur_cinq():
    res = _quinte([2, 5, 6, 7, 9], DETAIL_COMPLET)
    assert res["gagne"] is False and res["rapport_reel"] is None
