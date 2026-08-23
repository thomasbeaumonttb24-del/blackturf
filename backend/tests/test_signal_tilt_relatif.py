"""Le tilt par SIGNAL : mesuré contre la population, pas contre zéro.

Constat du 2026-08-23 : le multiplicateur d'un signal valait `1 + roi`, où `roi` est
le rendement d'une mise plate sur les chevaux qui le portent. Or une mise plate sur
N'IMPORTE QUEL cheval rend environ −15 % (le prélèvement PMU du simple gagnant) : tous
les signaux sortaient donc sous 1, et le PRODUIT de 4 à 6 d'entre eux s'écrasait sur la
borne basse. Sur 242 chevaux de 20 courses, 207 (86 %) recevaient exactement 0,50 — un
multiplicateur constant, qui ne trie plus rien, et une explication utilisateur qui
annonçait « mise réduite » sans qu'aucune mise ne change.
"""
import math

import pytest

from ml.signal_performance import (K_SHRINK, SIG_M_MAX, SIG_M_MIN, SIGNALS,
                                   _multiplicateur_relatif, _roi_reference,
                                   signal_multiplier)


def test_un_signal_dans_la_moyenne_est_neutre():
    """−15 % dans un monde à −15 % : le signal n'apprend rien, il ne doit rien changer.
    L'ancienne formule renvoyait 0,85 et pénalisait tout le monde."""
    assert _multiplicateur_relatif(-0.15, -0.15, 100_000) == pytest.approx(1.0, abs=1e-6)


def test_un_signal_meilleur_que_la_population_est_favorise():
    m = _multiplicateur_relatif(0.0, -0.15, 100_000)     # 0 % contre −15 %
    assert m > 1.0
    assert m == pytest.approx(1.0 / 0.85, rel=0.01)


def test_un_signal_pire_que_la_population_est_penalise():
    assert _multiplicateur_relatif(-0.35, -0.15, 100_000) < 1.0


def test_petit_echantillon_ramene_vers_le_neutre():
    fort = _multiplicateur_relatif(0.30, -0.15, 100_000)
    faible = _multiplicateur_relatif(0.30, int(K_SHRINK) // 4, 10)
    assert abs(faible - 1.0) < abs(fort - 1.0)
    assert _multiplicateur_relatif(0.30, -0.15, 0) == pytest.approx(1.0)


def test_multiplicateur_borne():
    assert _multiplicateur_relatif(50.0, -0.15, 100_000) == SIG_M_MAX
    assert _multiplicateur_relatif(-1.0, -0.15, 100_000) == SIG_M_MIN


def test_roi_reference_agrege_toute_la_population():
    agg = {"a": {"stake": 100.0, "payout": 80.0}, "b": {"stake": 100.0, "payout": 90.0}}
    assert _roi_reference(agg) == pytest.approx(-0.15)
    assert _roi_reference({}) == 0.0
    assert _roi_reference({"a": {"stake": 0.0, "payout": 0.0}}) == 0.0


# ── Combinaison des signaux : moyenne géométrique, pas produit ───────────────

def _perf(mult_par_signal):
    return {"signals": {nom: {"multiplier": m} for nom, m in mult_par_signal.items()}}


def _features_portant(noms):
    """Features minimales déclenchant exactement les signaux demandés."""
    f = {}
    for n in noms:
        if n == "forme_basse":
            f["forme_5_courses"] = 0.10
        elif n == "en_regression":
            f["forme_tendance"] = -0.50
        elif n == "elo_inferieur":
            f["elo_vs_moyenne"] = -100
        elif n == "montee_categorie":
            f["class_drop_ratio"] = 2.0
        elif n == "terrain_defavorable":
            f["pref_terrain_actuel"] = 0.10
        elif n == "premier_deferre":
            f["premier_deferre"] = True
        else:
            raise AssertionError(f"signal {n} non couvert par le fixture")
    return f


def test_porter_plus_de_signaux_ne_penalise_plus_mecaniquement():
    """Six facteurs à 0,9 donnaient 0,53 par produit : le cheval payait le NOMBRE de
    signaux qu'il porte. La moyenne géométrique dit 0,9, une fois."""
    noms = ["forme_basse", "en_regression", "elo_inferieur", "montee_categorie",
            "terrain_defavorable", "premier_deferre"]
    perf = _perf({n: 0.9 for n in noms})
    un_seul = signal_multiplier(_features_portant(noms[:1]), perf)
    les_six = signal_multiplier(_features_portant(noms), perf)
    assert un_seul == pytest.approx(0.9, abs=1e-6)
    assert les_six == pytest.approx(0.9, abs=1e-6)
    assert les_six > 0.53, "l'ancien produit écrasait le cheval sur la borne"


def test_la_moyenne_geometrique_garde_le_sens():
    noms = ["forme_basse", "elo_inferieur"]
    perf = _perf({"forme_basse": 0.6, "elo_inferieur": 1.4})
    # 0,6 et 1,4 se compensent presque : √(0,6×1,4) ≈ 0,917
    assert signal_multiplier(_features_portant(noms), perf) == pytest.approx(
        math.sqrt(0.6 * 1.4), abs=1e-6)
    # deux mauvais restent mauvais
    perf2 = _perf({"forme_basse": 0.6, "elo_inferieur": 0.8})
    assert signal_multiplier(_features_portant(noms), perf2) == pytest.approx(
        math.sqrt(0.6 * 0.8), abs=1e-6)


def test_aucun_signal_porte_reste_neutre():
    assert signal_multiplier({}, _perf({"forme_basse": 0.5})) == 1.0
    assert signal_multiplier({"forme_5_courses": 0.10}, None) == 1.0


def test_tous_les_signaux_du_fixture_existent_bien():
    """Garde-fou : si un signal est renommé, le fixture doit crier plutôt que de
    tester silencieusement le vide."""
    for n in ("forme_basse", "en_regression", "elo_inferieur", "montee_categorie",
              "terrain_defavorable", "premier_deferre"):
        assert n in SIGNALS


# ── Bandes d'EV : même correction, et un gate dur qui en dépend ──────────────

def test_les_bandes_d_ev_sont_aussi_jugees_contre_la_population():
    """Le multiplicateur de bande d'EV alimente un GATE DUR dans mise_calculator
    (`if evb(c) <= 0.80 : rejet`). Mesuré en prod le 2026-08-23, TOUTES les bandes
    valaient entre 0,667 et 0,808 — le gate rejetait donc tout candidat spéculatif
    quelle que soit sa bande : une interdiction générale déguisée en apprentissage."""
    from ml.signal_performance import _multiplicateur_relatif

    # Une bande exactement dans la moyenne ne doit PAS déclencher le gate à 0,80.
    moyenne = _multiplicateur_relatif(-0.20, -0.20, 50_000)
    assert moyenne == pytest.approx(1.0, abs=1e-6)
    assert moyenne > 0.80

    # Une bande franchement pire que la population le déclenche, elle.
    toxique = _multiplicateur_relatif(-0.45, -0.20, 50_000)
    assert toxique < 0.80
