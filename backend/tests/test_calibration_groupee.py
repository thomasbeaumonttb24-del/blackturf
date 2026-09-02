"""La calibration interne ne doit pas voir les frères de course de ce qu'elle calibre.

`CalibratedClassifierCV(..., cv=3)` construit un `StratifiedKFold` qui découpe par
LIGNE. Les partants d'une même course tombent donc des deux côtés du pli : le
calibrateur est ajusté sur des probabilités produites par un modèle qui a vu leurs
frères de course. Via les features de champ (`nb_partants`, `field_hhi`,
`elo_vs_moyenne`…), une course se reconnaît.

Le drapeau `BT_GROUP_SPLIT` protégeait le hold-out temporel, les plis out-of-fold du
stacking et le walk-forward. Il ne protégeait PAS cette calibration-là — pourtant la
dernière chose que traverse chaque probabilité servie.

CE QUE LA MESURE DIT, honnêtement : sur cinq jeux simulés avec un effet de course
fort, le groupement améliore 3 fois sur 5 en Brier comme en log-loss, pour un gain
moyen de +0,0008 en Brier et −0,010 en log-loss. C'est un match nul dans le bruit.
On garde le groupement pour la RAISON, pas pour un gain : fermer trois fuites sur
quatre et laisser la dernière ouverte n'a pas de sens, et la mesure montre que ça ne
coûte rien.
"""
import numpy as np
import pandas as pd
import pytest

from ml.models import plis_calibration


def _jeu(n_courses=40, n_partants=8, seed=3):
    rng = np.random.RandomState(seed)
    lignes, y, groupes = [], [], []
    for c in range(n_courses):
        force = rng.randn(n_partants)
        places = set(np.argsort(-force)[:3])
        for i in range(n_partants):
            lignes.append({"force": float(force[i]), "bruit": float(rng.randn())})
            y.append(int(i in places))
            groupes.append(f"c{c:03d}")
    return pd.DataFrame(lignes), pd.Series(y), np.array(groupes)


def test_aucun_partant_ne_se_retrouve_des_deux_cotes_d_un_pli():
    X, y, g = _jeu()
    plis = plis_calibration(X, y, g)
    assert not isinstance(plis, int), "le groupement doit avoir eu lieu"
    for i_train, i_val in plis:
        courses_train = set(g[i_train])
        courses_val = set(g[i_val])
        assert not (courses_train & courses_val), (
            "une course est à cheval sur les deux côtés du pli de calibration")


def test_chaque_pli_de_validation_porte_les_deux_classes():
    """Un pli sans les deux classes rend la calibration isotone dégénérée."""
    X, y, g = _jeu()
    plis = plis_calibration(X, y, g)
    for _, i_val in plis:
        assert len(np.unique(y.to_numpy()[i_val])) == 2


def test_tous_les_partants_sont_calibres_une_fois_et_une_seule():
    X, y, g = _jeu()
    plis = plis_calibration(X, y, g)
    vus = np.concatenate([i_val for _, i_val in plis])
    assert sorted(vus) == list(range(len(X)))


def test_sans_groupes_le_comportement_historique_est_rendu():
    """Rollback : `BT_GROUP_SPLIT=0` fait passer `groupes=None` et on retombe sur
    l'entier que `CalibratedClassifierCV` interprétait déjà."""
    X, y, _ = _jeu()
    assert plis_calibration(X, y, None) == 3
    assert plis_calibration(X, y, None, n_splits=5) == 5


def test_un_jeu_trop_pauvre_retombe_sur_l_entier_sans_lever():
    """Aucune exception ne doit remonter jusqu'à l'entraînement : au pire on rend
    le découpage d'avant."""
    X = pd.DataFrame({"a": [0.1, 0.2, 0.3, 0.4]})
    y = pd.Series([1, 0, 0, 0])
    g = np.array(["c1", "c1", "c2", "c2"])
    assert plis_calibration(X, y, g) == 3


def test_les_quatre_modeles_calibres_utilisent_les_plis_groupes():
    import inspect

    from ml.models import BlackTurfEnsemble

    src = inspect.getsource(BlackTurfEnsemble.train)
    assert 'cv=3' not in src, "plus aucun découpage par ligne"
    assert src.count("cv=_cv_calib") == 4, (
        "XGBoost, LightGBM, CatBoost et son repli logistique")
    assert "cv=_cv_win" in src, (
        "le modèle de victoire a son propre label, bien plus déséquilibré : ses "
        "plis doivent être stratifiés dessus")


def test_le_desalignement_du_stacking_reste_documente_et_non_corrige():
    """Constat MESURÉ puis ÉCARTÉ : servir le L2 avec les L0 non calibrées dégrade
    de 10,2 % en Brier et 8,6 % en log-loss. Le commentaire doit rester, pour que
    personne ne « corrige » à nouveau sans remesurer."""
    import inspect

    from ml.models import BlackTurfEnsemble

    src = inspect.getsource(BlackTurfEnsemble.predict_proba)
    assert "ÉCART FIT/SERVICE CONNU" in src
    assert "0.17051" in src, "les chiffres de la mesure doivent rester lisibles"
    assert not hasattr(BlackTurfEnsemble, "_predictions_l0_brutes"), (
        "le correctif a été mesuré défavorable : il ne doit pas rester en place")
