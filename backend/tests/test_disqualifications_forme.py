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


# ── ELO : calcul d'une course ───────────────────────────────────────────────
from ml.elo import (  # noqa: E402
    ELO_INITIAL, amorcer_inedits, calculer_deltas_course, champ_elo,
    multiplicateur_provisoire,
)


def test_elo_somme_nulle_et_vainqueur_gagne():
    valides = [{"cheval_id": c, "position": p} for c, p in (("a", 1), ("b", 2), ("c", 3))]
    r = {"a": 1500.0, "b": 1500.0, "c": 1500.0}
    d = calculer_deltas_course(valides, r, {"a": 20, "b": 20, "c": 20}, 32)
    assert d["a"] > 0 > d["c"]
    assert abs(sum(d.values())) < 1e-9


def test_elo_disqualifie_recule():
    cl = classement_elo([
        {"cheval_id": "a", "position": 1}, {"cheval_id": "b", "position": 2},
        {"cheval_id": "dq", "position": None, "incident": "DISQUALIFIE"},
    ])
    r = {"a": 1400.0, "b": 1400.0, "dq": 1600.0}
    d = calculer_deltas_course(cl, r, {c: 20 for c in r}, 32)
    assert d["dq"] < 0


def test_elo_k_provisoire_decroit_jusqu_a_un():
    assert multiplicateur_provisoire(0) == 2.5
    assert 1.0 < multiplicateur_provisoire(4) < 2.5
    assert multiplicateur_provisoire(8) == multiplicateur_provisoire(50) == 1.0


def test_elo_inedit_amorce_a_la_moyenne_du_champ():
    r = {"a": 1700.0, "b": 1650.0, "c": 1600.0, "new": ELO_INITIAL}
    seed = amorcer_inedits(r, {"a": 5, "b": 5, "c": 5})
    assert seed["new"] == 1650.0 and seed["a"] == 1700.0
    # Trop peu de chevaux notés : pas d'amorçage.
    assert amorcer_inedits({"a": 1700.0, "new": ELO_INITIAL}, {"a": 5})["new"] == ELO_INITIAL


def test_champ_elo_toutes_graphies():
    assert champ_elo("Attelé") == champ_elo("TROT_ATTELE") == champ_elo("Monté") == "elo_score_trot"
    assert champ_elo("Steeple") == champ_elo("HAIES") == "elo_score_obstacle"
    assert champ_elo("plat") == champ_elo(None) == "elo_score_plat"
