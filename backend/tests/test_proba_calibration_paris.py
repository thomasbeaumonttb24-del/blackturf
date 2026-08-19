"""La probabilité annoncée doit tenir devant les résultats — sinon l'EV ment.

Mesuré le 2026-08-19 sur les 19 968 paris réellement réglés :

| type            | annoncé | réel  | sur-confiance |
|-----------------|---------|-------|---------------|
| Simple Gagnant  | 10,9 %  | 8,9 % | ×1,22         |
| Simple Placé    | 45,3 %  | 36,9 %| ×1,23         |
| Couplé Gagnant  |  4,9 %  | 3,7 % | ×1,34         |
| Couplé Placé    | 26,9 %  | 18,4 %| ×1,46         |
| Trio            |  5,3 %  | 2,4 % | ×2,26         |

Comme EV = proba × rapport − 1, une probabilité gonflée de 22 % affiche +10 %
d'espérance là où le réel est −10 %. C'est la cause première du ROI négatif : les
bandes d'EV ne triaient RIEN (toutes entre −8 % et −9 % de ROI réel).
"""
import pytest

from ml.signal_performance import (
    PC_F_MAX,
    PC_F_MIN,
    PC_MIN_PARIS,
    proba_realization_factor,
)


def _calib(type_pari: str, **champs) -> dict:
    return {"global": {type_pari: champs}}


def test_sans_table_aucune_correction():
    """Démarrage à froid : on ne corrige jamais à l'aveugle."""
    assert proba_realization_factor("Simple Gagnant", None) == 1.0
    assert proba_realization_factor("Simple Gagnant", {}) == 1.0
    assert proba_realization_factor(None, _calib("Simple Gagnant", proba_factor=0.8)) == 1.0


def test_type_inconnu_reste_neutre():
    assert proba_realization_factor("Quinté+", _calib("Trio", proba_factor=0.44)) == 1.0


def test_le_facteur_appris_est_applique():
    assert proba_realization_factor("Trio", _calib("Trio", proba_factor=0.44)) == 0.44


def test_le_facteur_est_lu_sur_le_pool_global():
    """La fréquence à laquelle un Couplé tombe ne dépend pas du profil qui le
    joue : découper par profil diviserait l'échantillon sans rien apprendre."""
    calib = {
        "global": {"Couplé Gagnant": {"proba_factor": 0.75}},
        "profils": {"agressif": {"Couplé Gagnant": {"proba_factor": 0.10}}},
    }
    assert proba_realization_factor("Couplé Gagnant", calib) == 0.75


# ── Bornes du facteur ────────────────────────────────────────────────────────
def test_on_ne_gonfle_jamais_une_probabilite():
    """Corriger vers le HAUT fabriquerait de faux value bets : le plafond est
    juste au-dessus de 1, le plancher laisse de la marge pour les combinés."""
    assert PC_F_MAX <= 1.05
    assert PC_F_MIN >= 0.40


def test_l_echantillon_minimal_protege_du_bruit():
    """Sur 30 paris, un facteur de 0,5 refléterait la variance, pas un biais."""
    assert PC_MIN_PARIS >= 100


# ── Intégration dans le plan de mise ─────────────────────────────────────────
def test_le_plan_recalcule_l_ev_apres_correction():
    """Sans recalcul, la proba serait corrigée mais l'EV garderait l'ancienne
    valeur — donc la sélection continuerait de se tromper."""
    import inspect

    from services import mise_calculator

    source = inspect.getsource(mise_calculator.generer_plan)
    assert "proba_realization_factor" in source
    i_proba = source.index("proba_realization_factor")
    extrait = source[i_proba:i_proba + 700]
    assert 'c["proba_gain"] = round(float(c["proba_gain"]) * fp' in extrait
    assert 'c["ev"] = round(float(c["proba_gain"]) * float(c["rapport_estime"]) - 1.0' in extrait, (
        "l'EV doit être recalculée sur la probabilité CORRIGÉE")


def test_la_correction_precede_la_selection():
    """La proba sert aussi aux gates (min_proba, tranche de rapport) : corriger
    après la sélection laisserait choisir sur des chiffres faux."""
    import inspect

    from services import mise_calculator

    source = inspect.getsource(mise_calculator.generer_plan)
    assert source.index("proba_realization_factor") < source.index("_select_conviction"), (
        "la calibration doit s'appliquer avant la sélection des paris")


# ── Tilt par tranche de rapport ──────────────────────────────────────────────
def test_le_tilt_de_tranche_lit_la_table_fusionnee():
    """La table voyage dans `rapport_calibration`, déjà chargée et transmise
    partout où un plan se construit : un paramètre séparé aurait demandé de
    modifier cinq appelants, dont un oubli aurait désactivé le tilt en silence."""
    from ml.signal_performance import payout_bucket_multiplier

    fusionnee = {"payout_buckets": {"Simple Gagnant": {"4_8": {"multiplier": 1.12}}}}
    assert payout_bucket_multiplier("Simple Gagnant", 6.0, fusionnee) == 1.12

    autonome = {"types": {"Simple Gagnant": {"4_8": {"multiplier": 1.12}}}}
    assert payout_bucket_multiplier("Simple Gagnant", 6.0, autonome) == 1.12


def test_tilt_neutre_sans_donnee():
    from ml.signal_performance import payout_bucket_multiplier

    assert payout_bucket_multiplier("Simple Gagnant", 6.0, None) == 1.0
    assert payout_bucket_multiplier("Simple Gagnant", None, {"payout_buckets": {}}) == 1.0
    assert payout_bucket_multiplier("Trio", 6.0, {"payout_buckets": {"Simple Gagnant": {}}}) == 1.0


def test_les_tranches_couvrent_toute_l_echelle():
    """Un rapport ne doit jamais tomber hors des tranches, sinon le tilt
    disparaîtrait silencieusement pour toute une catégorie de paris."""
    from ml.signal_performance import PB_BUCKETS, _pb_key

    for rapport in (1.0, 1.9, 2.0, 3.9, 4.0, 7.9, 8.0, 14.9, 15.0, 500.0):
        assert _pb_key(rapport), f"rapport {rapport} sans tranche"
    assert PB_BUCKETS[0][0] == 0.0, "la première tranche doit partir de 0"


def test_le_tilt_reste_borne():
    """C'est une préférence entre candidats, pas une barrière : le contrat produit
    (tranche de rapport par profil, un plan sur CHAQUE course) doit survivre."""
    from ml.signal_performance import PB_M_MAX, PB_M_MIN

    assert 0.5 <= PB_M_MIN < 1.0 < PB_M_MAX <= 1.5


def test_le_tilt_est_applique_dans_les_deux_chemins_de_selection():
    """Le chemin de secours sert quand toutes les gates ont échoué — c'est
    précisément là qu'il ne faut pas retomber sur la pire tranche."""
    import inspect

    from services import mise_calculator

    source = inspect.getsource(mise_calculator)
    assert source.count('_pb_mult') >= 3, (
        "le tilt doit être posé sur les candidats ET lu par les deux scoreurs")
