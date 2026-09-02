"""Une calibration s'applique là où elle a été ajustée.

Le drapeau `BT_CALIB_ON_RAW` (actif par défaut) fait ajuster les trois calibrations
de probabilité sur la proba MODÈLE BRUTE (`proba_top1_raw` / `proba_top3_raw`), pour
casser la boucle fermée où la calibration chassait son propre résidu. Il avait réglé
le côté FIT — et laissé le côté INFÉRENCE en décalage :

    isotone top3  ajustée sur `proba_top3_raw`   appliquée après température,
                                                 méta-apprenant, tilt et
                                                 renormalisation Σ=3
    isotone top1  ajustée sur `proba_top1_raw`   appliquée après le blend marché
    longshots     ajustée sur `proba_top1_raw`   appliquée après le blend marché

Une courbe est un tableau « cette valeur-là arrive en réalité tant de fois ». Lui
donner une autre grandeur en entrée ne la rend pas approximative : elle corrige une
chose qu'elle n'a jamais observée.

Ordre correct, et il a un sens simple : on finit de corriger le MODÈLE, puis on le
mélange à un prior EXTÉRIEUR. Le blend marché n'est pas une calibration, c'est un
avis extérieur — il vient donc en dernier.
"""
import inspect

import numpy as np

from ml import pipeline
from ml.isotonic_calibration import apply_calibration as iso_top1
from ml.isotonic_utils import centered_isotonic_curve


def _source():
    return inspect.getsource(pipeline.predict_course)


def _pos(fragment, src=None):
    src = src or _source()
    assert fragment in src, f"fragment introuvable : {fragment}"
    return src.index(fragment)


# ── Ordre de la chaîne top3 ─────────────────────────────────────────────────

def test_isotone_top3_appliquee_sur_le_brut_avant_toute_correction():
    src = _source()
    iso3 = _pos("_t3_apply(_raw_p3_snap", src)
    temperature = _pos("al.apply_calibration(", src)
    meta = _pos("meta.predict_corrections_batch(", src)
    tilt = _pos("al.apply_feature_weight_tilt(", src)
    renorm = _pos("target_sum3 = float(min(3.0, nb_partants))", src)
    assert iso3 < temperature < meta < tilt < renorm, (
        "la courbe top3 est ajustée sur proba_top3_raw : elle doit s'appliquer AVANT "
        "la température, le méta-apprenant, le tilt et la renormalisation")


def test_une_seule_application_de_la_courbe_top3():
    """Empiler deux fois la même correction, c'est la compter deux fois."""
    assert _source().count("_t3_apply(") == 1


# ── Ordre de la chaîne top1 ─────────────────────────────────────────────────

def test_les_calibrations_du_modele_precedent_le_blend_marche():
    src = _source()
    longshot = _pos("apply_calibration(probas_top1, cotes_pmu, _cal_factors)", src)
    iso1 = _pos("_iso_apply(probas_top1, _iso_curve, seg=_seg)", src)
    blend = _pos("blend = np.where(", src)
    assert longshot < blend, (
        "les facteurs longshot sont ajustés sur proba_top1_raw (cf. "
        "scripts.calibration_longshots.fetch_rows) : ils s'appliquent à la proba "
        "MODÈLE, pas au mélange modèle+marché")
    assert iso1 < blend, (
        "la courbe top1 est ajustée sur proba_top1_raw (cf. "
        "ml.isotonic_calibration._fetch_proba_outcomes) : même domaine, même place")


def test_le_snapshot_brut_est_pris_avant_toute_calibration():
    """`proba_top1_raw` est l'abscisse de la courbe de la nuit suivante : s'il était
    pris après une correction, le fit et l'inférence divergeraient à nouveau — dans
    l'autre sens."""
    src = _source()
    snap = _pos("_raw_p1_snap = np.asarray(probas_top1, dtype=float).copy()", src)
    longshot = _pos("apply_calibration(probas_top1, cotes_pmu, _cal_factors)", src)
    iso1 = _pos("_iso_apply(probas_top1, _iso_curve, seg=_seg)", src)
    assert snap < longshot and snap < iso1

    snap3 = _pos("_raw_p3_snap = np.clip(", src)
    iso3 = _pos("_t3_apply(_raw_p3_snap", src)
    assert snap3 < iso3


def test_une_seule_application_de_chaque_calibration_top1():
    src = _source()
    assert src.count("_iso_apply(probas_top1") == 1
    assert src.count("apply_calibration(probas_top1, cotes_pmu") == 1


# ── Ce que coûte réellement le décalage de domaine ──────────────────────────

def _courses_simulees(n_courses=800, n_partants=10, seed=11):
    """Champs réalistes : une vraie proba de victoire par partant (Σ=1 par course),
    un gagnant tiré selon elle, un modèle sur-confiant sur ses favoris, et un
    marché bruité autour de la vérité."""
    rng = np.random.default_rng(seed)
    vraies, modele, marche, gagne = [], [], [], []
    for _ in range(n_courses):
        p = rng.dirichlet(np.full(n_partants, 0.6))
        # Le modèle exagère ses favoris (exposant > 1 = sur-confiance), défaut
        # exactement décrit par la calibration isotone de production.
        m = p ** 1.35
        m /= m.sum()
        # Le marché voit juste, à du bruit près.
        q = p * rng.uniform(0.8, 1.25, size=n_partants)
        q /= q.sum()
        vainqueur = rng.choice(n_partants, p=p)
        vraies.append(p)
        modele.append(m)
        marche.append(q)
        gagne.append(np.eye(n_partants)[vainqueur])
    return (np.array(modele), np.array(marche), np.array(gagne))


def _blend_marche(p_modele, p_marche, alpha=0.42):
    """Même forme que le blend de production, renormalisé par course."""
    b = alpha * p_modele + (1.0 - alpha) * p_marche
    return b / b.sum(axis=1, keepdims=True)


def test_la_courbe_appliquee_hors_de_son_domaine_calibre_moins_bien():
    """Preuve chiffrée, sans DB. Deux ordres, la MÊME courbe, les mêmes données :

        bon ordre     blend( isotone(modèle), marché )   ← ce que fait le code
        mauvais ordre isotone( blend(modèle, marché) )   ← ce qu'il faisait

    La courbe est un tableau « cette valeur-là arrive en réalité tant de fois »,
    construit sur la proba MODÈLE. Lui donner le mélange modèle+marché en entrée ne
    la rend pas approximative : elle corrige une grandeur qu'elle n'a jamais vue.
    """
    modele, marche, gagne = _courses_simulees()

    # La courbe apprend modèle → fréquence réelle, exactement comme en production.
    courbe = centered_isotonic_curve(modele.ravel(), gagne.ravel())
    assert courbe["x"], "le fit doit produire une courbe"

    def par_course(p, fn):
        return np.array([fn(ligne) for ligne in p])

    bon = _blend_marche(par_course(modele, lambda l: iso_top1(l, courbe)), marche)
    mauvais = par_course(_blend_marche(modele, marche),
                         lambda l: iso_top1(l, courbe))

    def brier(p):
        return float(np.mean((p - gagne) ** 2))

    def logloss(p):
        pc = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-np.mean(gagne * np.log(pc) + (1 - gagne) * np.log(1 - pc)))

    assert brier(bon) < brier(mauvais), (
        f"Brier bon ordre {brier(bon):.6f} vs mauvais ordre {brier(mauvais):.6f}")
    assert logloss(bon) < logloss(mauvais), (
        f"logloss bon ordre {logloss(bon):.6f} vs mauvais ordre {logloss(mauvais):.6f}")


def test_la_courbe_sur_son_domaine_corrige_bien_la_sur_confiance():
    """Contrôle du montage : sur SON domaine, la courbe doit faire son travail —
    sinon le test précédent ne prouverait rien sur l'ordre."""
    modele, _marche, gagne = _courses_simulees()
    courbe = centered_isotonic_curve(modele.ravel(), gagne.ravel())
    calibre = np.array([iso_top1(l, courbe) for l in modele])

    def brier(p):
        return float(np.mean((p - gagne) ** 2))

    assert brier(calibre) < brier(modele)
