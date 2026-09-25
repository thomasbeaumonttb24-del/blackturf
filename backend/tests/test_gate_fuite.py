"""Garde-fou de FUITE : un challenger qui bat la cote d'une marge qu'aucun modèle
honnête n'atteint a appris l'arrivée. Nuit du 24→25/09/2026 : v545 classait à
0,9632 contre 0,7486 pour la cote (record historique : +0,020) après un recalcul
des features qui y avait glissé l'ELO du résultat — et elle a été promue."""
from ml import pipeline as pl

BASE = dict(current_is_synth=False, no_current=False, current_unreliable=False, data_jump=False)


def test_v545_est_reconnue_comme_fuite():
    assert pl._fuite_suspectee({"rank_challenger": 0.9632, "rank_marche": 0.7486})


def test_le_record_honnete_ne_declenche_pas():
    assert not pl._fuite_suspectee({"rank_challenger": 0.7686, "rank_marche": 0.7486})
    assert not pl._fuite_suspectee({"rank_challenger": 0.7017, "rank_marche": 0.7486})


def test_mesure_absente_ne_bloque_pas():
    assert not pl._fuite_suspectee(None)
    assert not pl._fuite_suspectee({"rank_challenger": 0.95, "rank_marche": None})


def test_la_fuite_bloque_meme_un_meilleur_classement():
    assert pl._should_deploy(0.80, 0.78, h2h_delta=0.18, **BASE)
    assert not pl._should_deploy(0.80, 0.78, h2h_delta=0.18, fuite_suspectee=True, **BASE)


def test_la_fuite_bloque_meme_un_remplacement_structurel():
    for cle in ("current_is_synth", "no_current", "current_unreliable", "data_jump"):
        cas = {**BASE, cle: True}
        assert pl._should_deploy(0.80, 0.78, h2h_delta=0.18, **cas)
        assert not pl._should_deploy(0.80, 0.78, h2h_delta=0.18, fuite_suspectee=True, **cas)
