"""EV des combinaisons neutralisées (combo_ev_none) face à la calibration (audit 2026-09-28, M1).

Interrupteur `EV_NEUTRALISEE_RESPECTEE` : False = comportement en service (la
calibration recalcule l'EV), True = l'EV neutralisée reste à 0. Défaut inchangé tant
que le banc de rejeu n'a pas tranché.
"""
import copy

import pytest

from ml.combo_bets import enumerate_bet_candidates
from services import mise_calculator as mc
from tests.test_rapport_calibration import COURSE, _field


def _types():
    t = set()
    for cfg in mc.PROFIL_CONFIG.values():
        t.update(cfg.get("types") or ())
    return sorted(t)


def test_defaut_inchange():
    assert mc.EV_NEUTRALISEE_RESPECTEE is False


def test_marqueur_pose_sur_les_combinaisons_seulement():
    cands = enumerate_bet_candidates(_field(10), COURSE)
    assert cands
    for c in cands:
        if c.get("_ev_neutralise"):
            assert "Simple" not in c["type_pari"] and c["ev"] == 0.0
    assert any(c.get("_ev_neutralise") for c in cands)


def test_neutralisee_respectee_garde_ev_nulle(monkeypatch):
    calib = {"global": {t: {"factor": 0.84, "proba_factor": 0.93} for t in _types()}}
    monkeypatch.setattr(mc, "EV_NEUTRALISEE_RESPECTEE", True)
    captures = []
    vrai = mc._select_conviction

    def espion(cands, *a, **k):
        captures.extend(copy.deepcopy(cands))
        return vrai(cands, *a, **k)

    monkeypatch.setattr(mc, "_select_conviction", espion)
    mc.generer_plan(20, "agressif", _field(10), COURSE, respect_montant=True, rapport_calib=calib)
    neut = [c for c in captures if c.get("_ev_neutralise")]
    assert neut and all(c["ev"] == 0.0 for c in neut)
    simples = [c for c in captures if "Simple" in c["type_pari"]]
    assert simples and any(c["ev"] != 0.0 for c in simples)


@pytest.mark.parametrize("respecte", [False, True])
def test_reprice_identique_dans_les_deux_modes(monkeypatch, respecte):
    monkeypatch.setattr(mc, "EV_NEUTRALISEE_RESPECTEE", respecte)
    calib = {"global": {t: {"factor": 0.84, "proba_factor": 0.93} for t in _types()}}
    preds = _field(10)
    fige = mc.plan_to_dict(mc.generer_plan(20, "agressif", preds, COURSE, respect_montant=True,
                                           rapport_calib=calib))
    live = mc.reprice_plan_live(copy.deepcopy(fige), copy.deepcopy(preds), COURSE)
    for a, b in zip([p for n in fige["niveaux"] for p in n["paris"]],
                    [p for n in live["niveaux"] for p in n["paris"]]):
        assert b["ev_estime"] == pytest.approx(a["ev_estime"], abs=1e-9)
        assert b["gain_potentiel"] == a["gain_potentiel"]
