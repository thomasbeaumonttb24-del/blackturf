"""Consensus de presse — la donnée était scrapée puis jetée.

`participations.rang_pronostic_pmu` / `rang_pronostic_geny` sont NULL sur 100 % des
participations, si bien que `pronostic_expert_rang`, `consensus_sources` et
`sagesse_foules_score` n'avaient qu'UNE valeur distincte sur 218 640 lignes de
`features_ml` (mesure du 2026-09-01, fenêtre d'un an). Ces tests vérifient que le
consensus est bien reconstruit depuis `pronostics_presse`, et surtout qu'il ne
fabrique rien quand la presse est absente.
"""
import pytest

from ml.features import _appliquer_consensus_presse, PRESSE_RANG_NON_CITE


def _peloton(n=6):
    return [{"numero": i, "rang_cote": i} for i in range(1, n + 1)]


def test_le_cheval_le_mieux_note_par_la_presse_est_premier_du_consensus():
    feats = _peloton()
    presse = {
        3: {"nb_experts": 3, "nb_premier": 2, "rang_moyen": 1.3, "rang_min": 1},
        1: {"nb_experts": 2, "nb_premier": 0, "rang_moyen": 4.0, "rang_min": 3},
        5: {"nb_experts": 1, "nb_premier": 0, "rang_moyen": 2.0, "rang_min": 2},
    }
    _appliquer_consensus_presse(feats, presse)
    par_num = {f["numero"]: f for f in feats}
    assert par_num[3]["pronostic_expert_rang"] == 1
    assert par_num[3]["presse_score_borda"] == 1.0
    assert par_num[1]["pronostic_expert_rang"] < PRESSE_RANG_NON_CITE
    # Non cités : jamais un rang inventé, tous au même rang « hors sélection ».
    assert par_num[2]["pronostic_expert_rang"] == PRESSE_RANG_NON_CITE
    assert par_num[6]["pronostic_expert_rang"] == PRESSE_RANG_NON_CITE
    assert par_num[2]["presse_score_borda"] == 0.0


def test_le_nombre_de_sources_est_reporte_tel_quel():
    feats = _peloton(4)
    presse = {2: {"nb_experts": 2, "nb_premier": 1, "rang_moyen": 1.5, "rang_min": 1}}
    _appliquer_consensus_presse(feats, presse)
    par_num = {f["numero"]: f for f in feats}
    assert par_num[2]["presse_nb_sources"] == 2
    assert par_num[2]["presse_rang_moyen"] == 1.5
    assert par_num[1]["presse_nb_sources"] == 0
    assert par_num[1]["presse_rang_moyen"] == 0.0


def test_sans_presse_rien_nest_invente():
    """Le cas le plus important : une course non couverte ne doit pas produire un
    faux consensus. Le modèle doit voir « signal absent », pas « signal neutre
    déguisé en information »."""
    feats = _peloton(5)
    _appliquer_consensus_presse(feats, {})
    for f in feats:
        assert f["pronostic_expert_rang"] == PRESSE_RANG_NON_CITE
        assert f["presse_score_borda"] == 0.0
        assert f["presse_nb_sources"] == 0
        assert f["consensus_sources"] == 0.5      # ni accord ni désaccord constatable


def test_consensus_maximal_quand_presse_et_marche_disent_la_meme_chose():
    feats = _peloton(5)
    presse = {
        1: {"nb_experts": 2, "nb_premier": 2, "rang_moyen": 1.0, "rang_min": 1},
        2: {"nb_experts": 2, "nb_premier": 0, "rang_moyen": 2.0, "rang_min": 2},
        3: {"nb_experts": 2, "nb_premier": 0, "rang_moyen": 3.0, "rang_min": 3},
    }
    _appliquer_consensus_presse(feats, presse)
    par_num = {f["numero"]: f for f in feats}
    # rang_cote 1,2,3 == rang de presse 1,2,3 → accord parfait
    for num in (1, 2, 3):
        assert par_num[num]["consensus_sources"] == 1.0


def test_consensus_bas_quand_la_presse_contredit_le_marche():
    feats = _peloton(6)
    # La presse adore le n°6, que le marché place bon dernier.
    presse = {6: {"nb_experts": 3, "nb_premier": 3, "rang_moyen": 1.0, "rang_min": 1}}
    _appliquer_consensus_presse(feats, presse)
    par_num = {f["numero"]: f for f in feats}
    assert par_num[6]["pronostic_expert_rang"] == 1
    assert par_num[6]["consensus_sources"] < 0.3


def test_la_sagesse_des_foules_repart_du_rang_par_cote():
    """Elle valait 1/10 partout : elle dérivait de `rang_pronostic_pmu`, NULL à 100 %."""
    feats = _peloton(4)
    _appliquer_consensus_presse(feats, {})
    par_num = {f["numero"]: f for f in feats}
    assert par_num[1]["sagesse_foules_score"] == 1.0
    assert par_num[4]["sagesse_foules_score"] == 0.25
    assert len({f["sagesse_foules_score"] for f in feats}) == 4   # plus constante


def test_aucune_erreur_sans_rang_cote():
    """Une course dont les cotes manquent ne doit pas casser le calcul."""
    feats = [{"numero": 1}, {"numero": 2}]
    _appliquer_consensus_presse(feats, {1: {"nb_experts": 1, "rang_moyen": 1.0}})
    assert feats[0]["consensus_sources"] == 0.5
    assert "sagesse_foules_score" not in feats[0]
