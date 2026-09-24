"""Un cheval disqualifié ou non placé doit être noté comme tel.

Cas réel (LIVRE BLANC, musique « DaDa0aDa0a ») : classé 2ᵉ du prono avec une
forme lue comme correcte et un ELO « au-dessus du lot ». Trois défauts :
  - le « 0 » de musique (non placé) valait PLUS qu'une victoire ;
  - les disqualifications ne coûtaient aucun point d'ELO ;
  - une sortie sur incident disparaissait de l'historique distance/terrain.
"""
from ml.elo import classement_elo
from ml.features import (
    POSITION_NON_PLACE, compute_allure_regularite, parse_musique, score_position,
)
from scraper.sources.pmu import _place_ou_incident


def test_un_non_place_ne_vaut_jamais_plus_qu_une_victoire():
    pos = parse_musique("0a1a")
    assert pos == [POSITION_NON_PLACE, 1]
    assert score_position(pos[0], 10) < score_position(pos[1], 10)
    assert score_position(pos[0], 10) <= 0.0 + 1e-9


def test_musique_entierement_fautive_donne_une_forme_nulle():
    scores = [score_position(p, 12) for p in parse_musique("DaDa0aDa0a")]
    assert len(scores) == 5
    assert max(scores) <= 0.2


def test_les_annees_entre_parentheses_ne_sont_pas_des_places():
    assert parse_musique("1a2a(25)3aDa") == [1, 2, 3, 20]
    taux, derniere, n = compute_allure_regularite("1a(25)Da0a")
    assert n == 3 and derniere == 0.0 and abs(taux - 1 / 3) < 1e-9


def test_taux_disqualification_de_la_musique():
    taux, derniere, n = compute_allure_regularite("DaDa0aDa0a")
    assert n == 5 and derniere == 1.0 and abs(taux - 0.6) < 1e-9


def test_elo_un_disqualifie_est_battu_par_tous_les_classes():
    cl = classement_elo([
        {"cheval_id": "a", "position": 1, "incident": None},
        {"cheval_id": "b", "position": 2, "incident": None},
        {"cheval_id": "dq", "position": None, "incident": "DISQUALIFIE_POUR_ALLURE_IRREGULIERE"},
        {"cheval_id": "dq2", "position": None, "incident": "TOMBE"},
        {"cheval_id": "np", "position": None, "incident": "NON_PARTANT"},
    ])
    par_id = {r["cheval_id"]: r["position"] for r in cl}
    assert "np" not in par_id
    assert par_id["dq"] == par_id["dq2"] == 3
    assert par_id["a"] == 1 and par_id["b"] == 2


def test_place_pmu_non_numerique_devient_un_incident():
    assert _place_ou_incident({"place": 4}) == (4, None)
    assert _place_ou_incident({"place": "DAI"}) == (None, "DAI")
    assert _place_ou_incident({"statusArrivee": "DISQUALIFIE"}) == (None, "DISQUALIFIE")
    assert _place_ou_incident({"statusArrivee": "NON_PARTANT"}) == (None, None)
    assert _place_ou_incident(None) == (None, None)
