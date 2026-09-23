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
