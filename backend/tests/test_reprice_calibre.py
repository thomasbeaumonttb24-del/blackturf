"""Re-pricing après le gel : mêmes facteurs de calibration que le pari figé (audit 2026-09-28, M4).

Avant : `reprice_plan_live` re-tarifait au prix BRUT du marché et comparait ce prix au
rapport figé CALIBRÉ. Le seul facteur (Couplé Gagnant 0,84, Couplé Ordre 0,79)
suffisait à afficher « le marché a bougé » et un gain gonflé de 19 à 27 %, marché
parfaitement immobile.
"""
import copy

import pytest

from services.mise_calculator import PROFIL_CONFIG, generer_plan, plan_to_dict, reprice_plan_live
from tests.test_rapport_calibration import COURSE, _field


def _types():
    t = set()
    for cfg in PROFIL_CONFIG.values():
        t.update(cfg.get("types") or ())
    return sorted(t)


def _paris(plan):
    return [p for niv in plan["niveaux"] for p in niv["paris"]]


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
@pytest.mark.parametrize("fr,fp", [(0.839, 0.933), (0.788, 1.0), (1.15, 0.827), (1.0, 1.0)])
def test_marche_immobile_plan_identique(profil, fr, fp):
    calib = {"global": {t: {"factor": fr, "proba_factor": fp} for t in _types()}}
    preds = _field(10)
    fige = plan_to_dict(generer_plan(20, profil, preds, COURSE, respect_montant=True,
                                     rapport_calib=calib))
    live = reprice_plan_live(copy.deepcopy(fige), copy.deepcopy(preds), COURSE)
    assert _paris(fige), "plan vide"
    for a, b in zip(_paris(fige), _paris(live)):
        assert a["type"] == b["type"]
        assert b["gain_potentiel"] == a["gain_potentiel"], (a["type"], a, b)
        assert b["probabilite"] == pytest.approx(a["probabilite"], abs=1e-9)
        assert b["ev_estime"] == pytest.approx(a["ev_estime"], abs=1e-9)
        assert not b.get("rapport_a_bouge"), f"{a['type']} : « le marché a bougé » à tort"
        assert b.get("rapport_live") == pytest.approx(a["rapport_estime"], abs=0.01)
        if not a.get("hors_tranche"):
            assert not b.get("hors_tranche_live")
    assert not live.get("marche_a_bouge")


def test_facteurs_enregistres_dans_le_plan():
    calib = {"global": {t: {"factor": 0.8, "proba_factor": 0.9} for t in _types()}}
    d = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE, respect_montant=True,
                                  rapport_calib=calib))
    for p in _paris(d):
        assert p["facteur_rapport"] == 0.8 and p["facteur_proba"] == 0.9
    d0 = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE, respect_montant=True))
    for p in _paris(d0):
        assert p["facteur_rapport"] == 1.0 and p["facteur_proba"] == 1.0


def test_plan_ancien_sans_facteurs_comportement_d_avant():
    """Un plan figé avant le correctif n'a pas les clés : prix brut, comme avant."""
    calib = {"global": {t: {"factor": 0.8, "proba_factor": 1.0} for t in _types()}}
    preds = _field(10)
    fige = plan_to_dict(generer_plan(20, "agressif", preds, COURSE, respect_montant=True,
                                     rapport_calib=calib))
    for p in _paris(fige):
        p.pop("facteur_rapport")
        p.pop("facteur_proba")
    live = reprice_plan_live(copy.deepcopy(fige), preds, COURSE)
    for a, b in zip(_paris(fige), _paris(live)):
        if b.get("rapport_live") and a["rapport_estime"]:
            # Prix brut = figé / 0,8 (aux arrondis près).
            assert b["rapport_live"] == pytest.approx(a["rapport_estime"] / 0.8, rel=0.06)


def test_le_marche_qui_bouge_est_toujours_signale():
    """La correction ne doit pas masquer une vraie dérive : cotes ×2 → signalé."""
    calib = {"global": {t: {"factor": 0.839, "proba_factor": 1.0} for t in _types()}}
    preds = _field(10)
    fige = plan_to_dict(generer_plan(20, "agressif", preds, COURSE, respect_montant=True,
                                     rapport_calib=calib))
    # Tripler TOUTES les cotes ne change rien (probas de marché renormalisées) : on
    # fait dériver les seuls chevaux des tickets, comme un vrai mouvement de marché.
    nums = {h["numero"] for p in _paris(fige) for h in p["chevaux"]}
    bouge = [dict(p, cote_pmu=p["cote_pmu"] * 3.0) if p["numero"] in nums else dict(p)
             for p in preds]
    live = reprice_plan_live(copy.deepcopy(fige), bouge, COURSE)
    assert live.get("marche_a_bouge")
    assert any(p.get("rapport_a_bouge") for p in _paris(live))
