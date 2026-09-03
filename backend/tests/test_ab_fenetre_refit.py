"""L'outillage de rejeu ne doit RIEN changer à la nuit de production.

`date_fin` (borne haute du dataset) et `frac_train` (taille du hold-out)
n'existent que pour mesurer ce que coûte l'angle mort du hold-out temporel : le
modèle déployé n'apprend rien des 20 % de courses les plus récentes — 78 jours
depuis que la fenêtre vaut douze mois, soit 4 209 courses réglées que v527 n'a
jamais vues.

Deux ajouts inertes, donc deux invariants : les défauts sont ceux d'hier, et
l'anti-fuite tient dans le rejeu comme dans la nuit.
"""
import inspect

import numpy as np
import pandas as pd
import pytest


def test_le_decoupage_de_production_reste_a_80_pour_cent():
    """Déplacer ce défaut changerait la MESURE en même temps que le modèle : le
    hold-out est ce sur quoi l'arbitrage champion/challenger se joue."""
    from ml.models import BlackTurfEnsemble, temporal_holdout_mask

    assert inspect.signature(BlackTurfEnsemble.train).parameters["frac_train"].default == 0.8
    assert inspect.signature(temporal_holdout_mask).parameters["frac_train"].default == 0.8


def test_la_borne_haute_du_dataset_est_absente_par_defaut():
    """La production doit continuer d'apprendre jusqu'à maintenant."""
    from ml.pipeline import _build_training_dataset_from_db

    assert inspect.signature(_build_training_dataset_from_db).parameters["date_fin"].default is None


def test_un_holdout_plus_petit_laisse_apprendre_plus_de_courses():
    """C'est tout le sujet : à 0,98 le modèle voit presque toute la fenêtre."""
    from ml.models import temporal_holdout_mask

    X = pd.DataFrame({"course_id": [f"c{i // 5:03d}" for i in range(500)]})
    prod = temporal_holdout_mask(X, frac_train=0.8)
    frais = temporal_holdout_mask(X, frac_train=0.98)
    assert frais.sum() < prod.sum()
    assert (~frais).sum() > (~prod).sum()
    # Et le hold-out reste la QUEUE chronologique dans les deux cas : un
    # découpage qui piocherait au milieu ferait fuiter l'avenir dans le passé.
    assert np.all(np.diff(np.where(frais)[0]) >= 1)
    assert np.where(frais)[0][-1] == len(X) - 1


def test_la_borne_haute_borne_aussi_la_borne_basse():
    """Un rejeu au 01/07 demandant douze mois doit remonter au 01/07 moins douze
    mois — et non à « aujourd'hui moins douze mois », qui ne trouverait presque
    rien de son côté du temps."""
    from ml import pipeline

    src = inspect.getsource(pipeline._build_training_dataset_from_db)
    assert "date_limite = date_fin - timedelta(days=mois * 30)" in src


def test_le_rejeu_garde_la_clause_anti_fuite():
    """Les deux bras doivent voir les mêmes features FIGÉES AVANT le départ, sinon
    le bras « frais » gagnerait en lisant l'avenir."""
    from scripts import ab_fenetre_refit

    src = inspect.getsource(ab_fenetre_refit._dataset_evaluation)
    assert "fm.computed_at < c.date_heure" in src
    assert "c.statut = 'termine'" in src


def test_le_rejeu_exige_deux_moities_pour_conclure():
    """Une seule moitié positive est indiscernable du hasard."""
    from scripts import ab_fenetre_refit

    assert ab_fenetre_refit.MIN_COURSES_MOITIE >= 200
    src = inspect.getsource(ab_fenetre_refit.main)
    assert "all(gains)" in src
    assert "ne réplique pas" in src


def test_les_moities_sont_decoupees_par_course():
    """Découper par LIGNE couperait une course en deux et mélangerait les bras."""
    from scripts.ab_fenetre_refit import _moities

    X = pd.DataFrame({"course_id": ["a", "a", "a", "b", "b", "c", "c", "d"],
                      "_win": [1, 0, 0, 1, 0, 1, 0, 1]})
    p, s = _moities(X)
    assert set(p["course_id"]) & set(s["course_id"]) == set()
    assert len(p) + len(s) == len(X)
    assert set(p["course_id"]) == {"a", "b"}


def test_le_rejeu_nest_pas_un_deploiement():
    """Il ne doit ni écrire un modèle, ni toucher model_versions."""
    from scripts import ab_fenetre_refit

    src = inspect.getsource(ab_fenetre_refit)
    for interdit in ("deploy(", "ModelVersion", "session.commit", "est_actif"):
        assert interdit not in src, f"le rejeu ne doit pas contenir « {interdit} »"


@pytest.mark.parametrize("champ", ["rank_auc", "market_rank_auc", "delta_market"])
def test_la_mesure_rend_lecart_au_marche(champ):
    """L'AUC nue ne dit pas si le modèle mérite d'exister ; l'écart au marché si."""
    from scripts.ab_fenetre_refit import _mesurer

    class _Faux:
        def predict_proba(self, X):
            return np.linspace(0.9, 0.1, len(X))

    X = pd.DataFrame({
        "course_id": ["a"] * 4 + ["b"] * 4,
        "_win": [1, 0, 0, 0, 0, 1, 0, 0],
        "cote_pmu": [2.0, 4.0, 8.0, 16.0, 3.0, 5.0, 9.0, 20.0],
    })
    assert champ in _mesurer(_Faux(), X)


def test_la_mesure_ne_ment_pas_sur_un_echantillon_vide():
    from scripts.ab_fenetre_refit import _mesurer

    assert _mesurer(None, pd.DataFrame()) == {"n_lignes": 0, "n_courses": 0}
