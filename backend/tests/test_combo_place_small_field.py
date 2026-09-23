"""Un Simple Placé sur 4 à 7 partants paie seulement les deux premiers."""

from ml.combo_bets import enumerate_bet_candidates


def test_place_anchor_uses_top_two_probability_not_top_three():
    predictions = [
        {"numero": i, "nom": f"Cheval {i}", "cote_pmu": 6.0,
         "proba_top1": 1 / 6, "proba_top3": 0.99}
        for i in range(1, 7)
    ]
    candidates = enumerate_bet_candidates(predictions, {"nb_partants": 6})
    anchors = [c for c in candidates if c["type_pari"] == "Simple Placé"
               and c.get("_anchor")]
    assert len(anchors) == 1
    assert 0.32 < anchors[0]["proba_gain"] < 0.35
    assert "dans les 2" in anchors[0]["texte_explication"]
