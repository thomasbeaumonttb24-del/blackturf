"""La calibration estimé→réel doit apprendre sur les valeurs BRUTES (audit 2026-09-28).

Le plan figé porte la proba et le rapport APRÈS correction. Apprendre dessus
mesure l'écart restant : avec un vrai ratio r et un facteur en service f, on
mesure r / f. Le facteur oscille et, mêlé sur l'historique, se stabilise vers
√r au lieu de r. Mesuré en production le 28/09 : Couplé Placé annoncé 23,9 %
(déjà corrigé), réalisé 19,5 %.

Le plan porte désormais `probabilite_brute` et `rapport_estime_brut`. Un type
bascule sur ces valeurs dès qu'il en a assez ; avant, le calcul historique est
inchangé.
"""
import asyncio
import copy

import pytest

from ml.signal_performance import (
    PC_BRUT_MIN_PARIS,
    PC_K_SHRINK,
    RC_BRUT_MIN_WINS,
    RC_K_SHRINK,
    compute_rapport_calibration,
)
from services.mise_calculator import PROFIL_CONFIG, generer_plan, plan_to_dict
from tests.test_rapport_calibration import COURSE, _field


# ── Le plan porte les valeurs d'avant correction ─────────────────────────────
def _tous_les_types() -> list[str]:
    types = set()
    for cfg in PROFIL_CONFIG.values():
        types.update(cfg.get("types") or ())
    return sorted(types)


def _paris(plan_d: dict) -> list[dict]:
    return [p for niv in plan_d["niveaux"] for p in niv["paris"]]


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_le_plan_porte_proba_et_rapport_bruts(profil):
    fr, fp = 0.8, 0.7
    calib = {"global": {t: {"factor": fr, "proba_factor": fp} for t in _tous_les_types()}}
    brut = plan_to_dict(generer_plan(20, profil, _field(10), COURSE, respect_montant=True))
    corrige = plan_to_dict(generer_plan(20, profil, _field(10), COURSE,
                                        respect_montant=True, rapport_calib=calib))

    # Sans calibration, brut = affiché.
    for p in _paris(brut):
        assert p["probabilite_brute"] == p["probabilite"], p["type"]
        assert p["rapport_estime_brut"] == pytest.approx(p["rapport_estime"], abs=0.01), p["type"]

    paris = _paris(corrige)
    assert paris, "plan vide"
    for p in paris:
        assert p["probabilite_brute"] is not None, p["type"]
        assert p["rapport_estime_brut"] is not None, p["type"]
        # Affiché = brut × facteur (arrondis de generer_plan : 4 décimales / 0,1).
        assert p["probabilite"] == pytest.approx(round(p["probabilite_brute"] * fp, 4), abs=1e-4)
        assert p["rapport_estime"] == pytest.approx(round(p["rapport_estime_brut"] * fr, 1),
                                                    abs=0.051)
        assert p["probabilite_brute"] > p["probabilite"]


def test_la_calibration_ne_change_rien_d_autre_au_plan():
    """Ajouter deux clés ne doit rien changer à ce qui est joué."""
    calib = {"global": {t: {"factor": 0.85, "proba_factor": 0.9} for t in _tous_les_types()}}
    d = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                  respect_montant=True, rapport_calib=calib))
    for p in _paris(d):
        q = dict(p)
        q.pop("probabilite_brute")
        q.pop("rapport_estime_brut")
        assert set(q) == set(p) - {"probabilite_brute", "rapport_estime_brut"}


# ── L'apprentissage lit les valeurs brutes ───────────────────────────────────
class _Res:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, *_a, **_k):
        return _Res(self.rows)


def _run(profil, type_pari, proba_aff, proba_brute, rapport_aff, rapport_brut,
         gagne, rapport_reel, avec_brut=True):
    pari = {"type": type_pari, "chevaux": [{"numero": 1}, {"numero": 2}],
            "mise": 10.0, "gain_potentiel": round(10.0 * rapport_aff),
            "probabilite": proba_aff}
    if avec_brut:
        pari["probabilite_brute"] = proba_brute
        pari["rapport_estime_brut"] = rapport_brut
    plan = {"niveaux": [{"paris": [pari]}]}
    res = {"paris": [{"type": type_pari, "chevaux": [{"numero": 1}, {"numero": 2}],
                      "statut": "gagne" if gagne else "perdu", "mise": 10.0,
                      "gain": 10.0 * rapport_reel if gagne else 0.0,
                      "rapport_reel": rapport_reel if gagne else None}]}
    return (profil, plan, res, "FRA")


def _population(n, n_gagnants, avec_brut=True):
    """Vrai ratio 0,6 sur la proba et le rapport ; facteur 0,8 déjà appliqué."""
    return [_run("equilibre", "Couplé Placé", 0.24, 0.30, 4.0, 5.0,
                 i < n_gagnants, 3.0, avec_brut=avec_brut) for i in range(n)]


def _calibrer(rows):
    return asyncio.run(compute_rapport_calibration(_Session(rows)))


def test_au_dessus_du_seuil_le_facteur_suit_le_vrai_ratio():
    n, g = 1000, 180                       # 18 % réalisés pour 30 % bruts : r = 0,6
    assert n >= PC_BRUT_MIN_PARIS and g >= RC_BRUT_MIN_WINS
    e = _calibrer(_population(n, g))["global"]["Couplé Placé"]
    assert e["source_proba_factor"] == "brut"
    assert e["source_factor"] == "brut"
    w_p = n / (n + PC_K_SHRINK)
    assert e["proba_factor"] == pytest.approx(round(1 + (0.6 - 1) * w_p, 3), abs=1e-3)
    w_r = g / (g + RC_K_SHRINK)
    assert e["factor"] == pytest.approx(round(1 + (0.6 - 1) * w_r, 3), abs=1e-3)
    # L'ancien calcul aurait mesuré 0,18 / 0,24 = 0,75 : correction à moitié faite.
    assert e["proba_factor"] < 0.70


def test_sous_le_seuil_le_calcul_historique_est_inchange():
    """Quelques jours de plans neufs ne doivent pas déplacer un facteur appris sur
    des milliers de paris."""
    anciens = _population(1000, 180, avec_brut=False)
    neufs = _population(PC_BRUT_MIN_PARIS - 1, RC_BRUT_MIN_WINS - 1)
    melange = _calibrer(anciens + neufs)["global"]["Couplé Placé"]
    sans_cles = copy.deepcopy(anciens + neufs)
    for _, plan, _, _ in sans_cles:
        for p in plan["niveaux"][0]["paris"]:
            p.pop("probabilite_brute", None)
            p.pop("rapport_estime_brut", None)
    historique = _calibrer(sans_cles)["global"]["Couplé Placé"]
    assert melange["source_proba_factor"] == "historique"
    assert melange["source_factor"] == "historique"
    assert melange["factor"] == historique["factor"]
    assert melange["proba_factor"] == historique["proba_factor"]


def test_plans_anciens_sans_cles():
    e = _calibrer(_population(800, 150, avec_brut=False))["global"]["Couplé Placé"]
    assert e["source_factor"] == e["source_proba_factor"] == "historique"
    assert e["n_win_brut"] == 0 and e["n_proba_brut"] == 0


@pytest.mark.parametrize("valeur", [None, 0, -1.0, "0.3", True])
def test_valeur_brute_invalide_ignoree(valeur):
    rows = _population(700, 120)
    for _, plan, _, _ in rows:
        plan["niveaux"][0]["paris"][0]["probabilite_brute"] = valeur
        plan["niveaux"][0]["paris"][0]["rapport_estime_brut"] = valeur
    e = _calibrer(rows)["global"]["Couplé Placé"]
    assert e["source_factor"] == e["source_proba_factor"] == "historique"


def test_le_profil_bascule_aussi():
    e = _calibrer(_population(1000, 180))["profils"]["equilibre"]["Couplé Placé"]
    assert e["source_proba_factor"] == "brut"


# ── Formules combinées : rapport du TICKET, pas de la combinaison ────────────
def _run_2sur4(gain_mult, rapport_reel=6.0, rapport_est=1.6):
    pari = {"type": "2sur4", "chevaux": [{"numero": i} for i in (1, 2, 3, 4)],
            "mise": 12.0, "gain_potentiel": round(12.0 * rapport_est),
            "probabilite": 0.5}
    res = {"paris": [{"type": "2sur4", "chevaux": pari["chevaux"], "statut": "gagne",
                      "mise": 12.0, "gain": round(12.0 * rapport_reel * gain_mult, 2),
                      "rapport_reel": rapport_reel}]}
    return ("conservateur", {"niveaux": [{"paris": [pari]}]}, res, "FRA")


def test_2sur4_compare_le_rapport_du_ticket():
    """4 chevaux, 2 dans les 4 premiers : 1/6 de la mise au rapport. Le ticket a
    rendu 6,0 / 6 = 1,0, pas 6,0."""
    e = _calibrer([_run_2sur4(1 / 6) for _ in range(40)])["global"]["2sur4"]
    assert e["real_mean"] == pytest.approx(1.0, abs=0.01)
    assert e["factor"] < 1.0, "un ticket payé 1,0 pour 1,6 estimé doit baisser le rapport"


def test_mise_pleine_inchangee():
    """Sans paiement partiel, le réel reste `rapport_reel` à l'identique."""
    rows = [_run("equilibre", "Simple Gagnant", 0.2, 0.2, 5.0, 5.0, True, 4.37)
            for _ in range(30)]
    for _, _, res, _ in rows:
        res["paris"][0]["gain"] = 43.7       # arrondi au centime, gain_mult = 1
    e = _calibrer(rows)["global"]["Simple Gagnant"]
    assert e["real_mean"] == 4.37


def test_gain_absent_retombe_sur_rapport_reel():
    rows = [_run_2sur4(1 / 6) for _ in range(10)]
    for _, _, res, _ in rows:
        res["paris"][0]["gain"] = None
    e = _calibrer(rows)["global"]["2sur4"]
    assert e["real_mean"] == 6.0
