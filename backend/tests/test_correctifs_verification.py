"""Non-régression des défauts trouvés à la vérification du 2026-10-07."""
from ml.portfolio import _rapport_place, dutching_calculator
from ml.recommendations import _kelly_mise, generer_recommandations_course


def _pred(numero, p3, cote, ev=0.0, p1=0.2):
    return {"numero": numero, "nom": f"C{numero}", "proba_top3": p3, "proba_top1": p1,
            "cote_pmu": cote, "ev_max": ev}


def test_recommandations_favori_sans_cote_ne_plantent_pas():
    """Un favori sans cote PMU (cote_pmu = None, plus de 5,0 fabriqué) faisait lever
    un TypeError au formatage — et annulait toutes les prédictions de la course."""
    preds = [_pred(1, 0.7, None, ev=0.3), _pred(2, 0.5, 4.0), _pred(3, 0.4, 6.0)]
    recos = generer_recommandations_course(preds, {"nb_partants": 3}, bankroll=100.0)
    assert all(1 not in [h["numero"] for h in r["chevaux"]] or r["type_pari"] != "Simple Placé"
               for r in recos)


def test_kelly_sans_cote_vaut_zero():
    assert _kelly_mise(0.2, None, 100.0) == 0.0
    assert _kelly_mise(None, 3.0, 100.0) == 0.0


def test_rapport_place_realiste_pour_un_favori():
    """La règle linéaire saturait dès la cote 3 (rapport 1,05) et rayait le placé."""
    assert 1.2 < _rapport_place({"cote_pmu": 3.0}) < 1.5
    assert _rapport_place({"cote_pmu": 10.0}) > _rapport_place({"cote_pmu": 3.0})
    assert _rapport_place({"cote_pmu": None}) is None


def test_dutching_jamais_rentable_au_bruit_flottant():
    """Avec proba = 1/cote, l'espérance vaut 0 : jamais « positive »."""
    for cotes in ([2.0, 4.0], [3.0, 7.0, 11.0], [1.7, 9.5]):
        sel = [{"numero": i + 1, "nom": f"C{i}", "cote": c, "proba": 1.0 / c} for i, c in enumerate(cotes)]
        try:
            res = dutching_calculator(sel, 10.0)
        except TypeError:
            res = dutching_calculator(sel, budget=10.0)
        assert res["is_profitable"] is False
