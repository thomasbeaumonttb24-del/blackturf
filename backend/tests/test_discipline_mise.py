"""Ne pas engager la même somme sur une course qui rend et une qui ne rend pas.

Contrefactuel mesuré sur les 19 996 paris réglés (gains winsorisés) :

    tout jouer, toutes cellules              -16,0 %
    Simple Gagnant ×4-15 + Simple Placé <×4   -6,1 %
    Simple Gagnant ×4-8 seul                  -1,9 %

La concentration est le levier qui reste quand le modèle n'a pas d'avantage
suffisant : le plan est servi sur CHAQUE course — contrainte produit — mais la
somme engagée suit la qualité mesurée de la cellule, et le reliquat part en
réserve.
"""
import pytest

from services.mise_calculator import (
    DISCIPLINE_RATIO_PLANCHER,
    MISE_PLANCHER,
    _appliquer_discipline_mise,
)

PALIER = {"min_stake": 2}
CFG = {"min_stake_factor": 1.0}


def _paris(*couples):
    return [{"mise": m, "_pb_mult": q} for m, q in couples]


def test_une_bonne_cellule_garde_la_mise_pleine():
    paris = _paris((10, 1.05), (6, 1.00))
    _appliquer_discipline_mise(paris, 16, PALIER, CFG)
    assert [p["mise"] for p in paris] == [10, 6]


def test_la_pire_cellule_est_ramenee_au_plancher_du_ratio():
    """Tranche à 0.60 (le pire mesuré, Trio ≥×15 à −52,6 %) → 40 % engagés."""
    paris = _paris((20, 0.60))
    _appliquer_discipline_mise(paris, 20, PALIER, CFG)
    assert paris[0]["mise"] == 8
    assert paris[0]["_discipline_ratio"] == DISCIPLINE_RATIO_PLANCHER


def test_reduction_proportionnelle_entre_les_deux():
    paris = _paris((20, 0.80))
    _appliquer_discipline_mise(paris, 20, PALIER, CFG)
    assert paris[0]["mise"] == 14          # ratio 0.70


def test_chaque_pari_est_juge_sur_sa_propre_cellule():
    """Un ticket sain ne doit pas etre rogne parce qu'un petit ticket annexe tombe
    dans une mauvaise tranche — c'est aussi ce qui deplace le MELANGE de l'argent
    vers les bonnes cellules, et pas seulement le total engage."""
    paris = _paris((18, 1.00), (10, 0.60))
    _appliquer_discipline_mise(paris, 28, PALIER, CFG)
    assert paris[0]["mise"] == 18, "le ticket dans une bonne tranche reste plein"
    assert paris[1]["mise"] == 4, "celui de la pire tranche tombe a 40 %"


def test_le_plan_ne_disparait_jamais():
    """Contrainte produit : une mise de course peut être réduite, jamais annulée."""
    paris = _paris((3, 0.60), (2, 0.60))
    _appliquer_discipline_mise(paris, 5, PALIER, CFG)
    assert all(p["mise"] >= MISE_PLANCHER for p in paris)
    assert all(p["mise"] > 0 for p in paris)


def test_sans_table_apprise_aucune_reduction():
    """Démarrage à froid : sans mesure, on ne réduit rien."""
    paris = [{"mise": 10}, {"mise": 5}]
    _appliquer_discipline_mise(paris, 15, PALIER, CFG)
    assert [p["mise"] for p in paris] == [10, 5]


def test_le_montant_saisi_par_l_utilisateur_est_deploye_en_entier():
    """S'il a saisi 20 €, il veut jouer 20 € : la discipline ne s'applique qu'aux
    plans dimensionnés par le système."""
    import inspect

    from services import mise_calculator

    source = inspect.getsource(mise_calculator.generer_plan)
    i_disc = source.index("_appliquer_discipline_mise(selected")
    avant = source[:i_disc]
    assert avant.rindex("else:") > avant.rindex("if respect_montant:"), (
        "l'appel doit vivre dans la branche SANS respect_montant")
