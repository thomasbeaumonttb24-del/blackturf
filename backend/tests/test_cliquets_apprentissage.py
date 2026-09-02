"""Deux mécanismes d'apprentissage qui ne pouvaient bouger que dans un sens.

POIDS DE FEATURES
    Les nudges causaux montaient à CHAQUE course ; la décroissance vers les poids
    par défaut vivait après le `return` du cas « pas de surprise », donc ne
    s'appliquait QUE les jours de surprise. Les poids ne pouvaient que grimper vers
    leur plafond de 2,0 et y rester — et `apply_feature_weight_tilt` applique ce
    plafond à chaque prédiction.

TEMPÉRATURE
    Drapeau `BT_TEMP_FIT` à 0 (le défaut, donc la production) : un cliquet montait T
    sur les surprises, fréquentes, et ne la baissait que sur `brier < 0,14 ET pas de
    surprise` — dérive vers le haut (1,2567 mesurée), qui aplatit le champ et remonte
    les outsiders. Drapeau à 1 : `_update_temperature` renvoyait 0.0 et RIEN ne
    prenait le relais, `fit_temperature_holdout` n'existant que dans un commentaire.
    L'activer GELAIT donc la température sur la valeur déjà dérivée.
"""
import numpy as np
import pytest

from ml.adaptive_learning import (
    DEFAULT_FEATURE_WEIGHTS, T_MAX, T_MIN, AdaptiveLearning,
    _nll_temperature, fit_temperature,
)


# ── Poids de features ──────────────────────────────────────────────────────

def _autopsie_causale():
    return {"causal_tags": [{"tag": "gagnant_finit_fort"}]}


def test_les_poids_redescendent_meme_sans_surprise():
    """La décroissance ne dépend plus de la surprise du jour."""
    al = AdaptiveLearning()
    al.feature_weights["dynamique"] = 2.0          # déjà au plafond
    al._update_feature_weights({}, was_surprise=False)
    assert al.feature_weights["dynamique"] < 2.0


def test_un_groupe_nudge_a_chaque_course_ne_finit_plus_au_plafond():
    """Cent courses sans surprise, chacune portant le même tag causal : avant, le
    poids saturait à 2,0 et y restait pour toujours."""
    al = AdaptiveLearning()
    for _ in range(100):
        al._update_feature_weights(_autopsie_causale(), was_surprise=False)
    sature = al.feature_weights["dynamique"]
    assert sature < 2.0, f"le poids colle encore au plafond ({sature})"

    # Et surtout : il REDESCEND dès que la cause disparaît. Avant, il ne pouvait
    # revenir vers son défaut qu'au gré des surprises — donc quasiment jamais.
    for _ in range(100):
        al._update_feature_weights({}, was_surprise=False)
    apres = al.feature_weights["dynamique"]
    assert apres < sature - 0.5, (
        f"le poids doit revenir vers son défaut : {sature} → {apres}")
    assert apres > DEFAULT_FEATURE_WEIGHTS["dynamique"], (
        "la décroissance est lente (2 % par course), pas une remise à zéro")


def test_le_renforcement_sur_surprise_fonctionne_toujours():
    al = AdaptiveLearning()
    avant = al.feature_weights["elo"]
    al._update_feature_weights({"elo_sous_estime": {"valeur": 1.0}}, was_surprise=True)
    assert al.feature_weights["elo"] > avant


def test_un_poids_deja_au_defaut_ne_bouge_pas_sans_signal():
    al = AdaptiveLearning()
    avant = dict(al.feature_weights)
    al._update_feature_weights({}, was_surprise=False)
    assert al.feature_weights == avant


# ── Température ────────────────────────────────────────────────────────────

def _champs(n_courses=400, n_partants=10, exposant=1.0, seed=4):
    """Champs simulés. `exposant` > 1 = modèle SUR-confiant sur ses favoris, le
    défaut que la température doit corriger (T > 1 resserre vers la moyenne)."""
    rng = np.random.default_rng(seed)
    logits, labels = [], []
    for _ in range(n_courses):
        p = rng.dirichlet(np.full(n_partants, 0.7))
        p3 = np.clip(p * 3.0, 1e-4, 0.99)               # P(top3) ≈ 3 × P(gagne)
        arrivee = rng.choice(n_partants, size=3, replace=False, p=p)
        y = np.zeros(n_partants)
        y[arrivee] = 1.0
        biaise = np.clip(p3 ** exposant, 1e-6, 0.999)
        biaise = biaise / biaise.sum() * p3.sum()       # même masse, forme déformée
        biaise = np.clip(biaise, 1e-7, 1 - 1e-7)
        logits.append(np.log(biaise / (1 - biaise)))
        labels.append(y)
    return logits, labels


def test_la_temperature_ajustee_est_bornee():
    logits, labels = _champs()
    T = fit_temperature(logits, labels)
    assert T is not None
    assert T_MIN <= T <= T_MAX


def test_la_temperature_ajustee_ne_degrade_jamais_la_nll():
    """Le fit minimise la NLL : par construction il ne peut pas faire pire que
    T = 1, contrairement au cliquet qui bougeait sans jamais mesurer."""
    logits, labels = _champs()
    T = fit_temperature(logits, labels)
    assert _nll_temperature(logits, labels, T) <= _nll_temperature(logits, labels, 1.0)


def test_un_modele_sur_confiant_appelle_une_temperature_superieure_a_un():
    logits, labels = _champs(exposant=1.6)
    assert fit_temperature(logits, labels) > 1.0


def test_un_modele_sous_confiant_appelle_une_temperature_inferieure_a_un():
    logits, labels = _champs(exposant=0.55)
    assert fit_temperature(logits, labels) < 1.0


def test_sans_donnee_exploitable_aucune_temperature_n_est_inventee():
    """Une valeur par défaut écraserait une calibration existante."""
    assert fit_temperature([], []) is None
    zeros = [np.zeros(5)]
    assert fit_temperature(zeros, [np.zeros(5)]) is None      # aucun positif
    assert fit_temperature(zeros, [np.ones(5)]) is None       # que des positifs


def test_le_scaling_est_centre_sur_le_champ():
    """T > 1 doit RÉDUIRE l'écart favori↔champ sans propulser les outsiders vers
    0,5 : c'est le centrage sur la moyenne des logits de la course qui l'assure."""
    al = AdaptiveLearning()
    al.temperature = 1.6
    probas = np.array([0.60, 0.30, 0.06, 0.04])
    out = al.apply_calibration(probas)
    assert out[0] < probas[0]
    assert out[-1] > probas[-1]
    assert out[-1] < 0.20
    assert np.all(np.diff(out) < 0)


def test_le_drapeau_a_desormais_un_remplacant():
    """Le drapeau ne peut être actif par défaut que parce que la fonction qu'il
    suppose existe réellement — c'est ce qui manquait."""
    from ml import adaptive_learning
    from ml.algo_flags import FLAGS

    assert FLAGS.temp_fit is True
    assert callable(getattr(adaptive_learning, "fit_temperature_holdout", None))


def test_la_nuit_ajuste_la_temperature():
    import inspect
    from ml import pipeline
    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    assert "fit_temperature_holdout" in src, (
        "sans recalcul nocturne, le drapeau gèle la température au lieu de la corriger")
    i_iso = src.index("isotonic_calibration_top3")
    i_temp = src.index("fit_temperature_holdout")
    assert i_iso < i_temp, (
        "la température corrige ce que l'isotone a laissé : même ordre qu'à l'inférence")
