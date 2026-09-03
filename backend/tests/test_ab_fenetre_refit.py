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


def test_le_rejeu_montre_toujours_deux_moities_chronologiques():
    """Elles disent si l'effet TIENT dans le temps — un effet de régime se voit là.

    Elles ne décident plus, en revanche : la décision est appariée (cf. plus bas).
    Le signe d'une moitié reste une information, jamais une preuve.
    """
    from scripts import ab_fenetre_refit

    assert ab_fenetre_refit.MIN_COURSES_MOITIE >= 200
    src = inspect.getsource(ab_fenetre_refit.main)
    assert "moitie_1" in src and "moitie_2" in src
    assert "Première moitié" in src and "Seconde moitié" in src


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


# ── Le verdict est APPARIÉ, pas « même signe deux fois » (2026-09-04) ───────
# Chiffré sur le profil risqué : l'écart-type du rendement par pari atteint
# 359 %, soit ~371 jours de production pour distinguer deux points de ROI en
# échantillons indépendants. Aucune décision produit n'attend ça. Le bruit
# dominant — quel cheval a gagné — étant COMMUN aux deux bras puisque ce sont
# les mêmes courses, il doit s'annuler : c'est tout l'objet du test apparié.

def test_le_verdict_ne_repose_plus_sur_le_signe_des_moities():
    """« Même signe deux fois » est un pile ou face gagné deux fois."""
    from scripts import ab_fenetre_refit

    src = inspect.getsource(ab_fenetre_refit.main)
    assert "_test_apparie(" in src
    assert "apparie[\"conclut\"]" in src


def test_un_intervalle_contenant_zero_ne_conclut_pas():
    from scripts.ab_fenetre_refit import _test_apparie

    rng = np.random.default_rng(7)
    courses = [f"c{i:04d}" for i in range(600)]
    a = {c: float(v) for c, v in zip(courses, rng.uniform(0.3, 0.9, 600))}
    b = dict(a)  # bras identiques : la différence est exactement nulle
    res = _test_apparie(a, b)
    assert res["conclut"] is False
    assert res["ic_bas"] <= 0 <= res["ic_haut"]


def test_un_effet_franc_est_detecte():
    """Un décalage constant de +0,02 sur 600 courses doit sortir de zéro."""
    from scripts.ab_fenetre_refit import _test_apparie

    rng = np.random.default_rng(7)
    courses = [f"c{i:04d}" for i in range(600)]
    a = {c: float(v) for c, v in zip(courses, rng.uniform(0.3, 0.9, 600))}
    b = {c: v + 0.02 for c, v in a.items()}
    res = _test_apparie(a, b)
    assert res["conclut"] is True
    assert res["ecart"] == pytest.approx(0.02, abs=1e-6)
    assert res["ic_bas"] > 0


def test_un_effet_noye_dans_le_bruit_ne_conclut_pas():
    """La garde qui compte : un effet minuscule sous un bruit large reste
    indécidable, et le banc doit le DIRE au lieu de trancher au signe."""
    from scripts.ab_fenetre_refit import _test_apparie

    rng = np.random.default_rng(11)
    courses = [f"c{i:04d}" for i in range(600)]
    a = {c: 0.6 for c in courses}
    b = {c: 0.6 + 0.0005 + float(x) for c, x in zip(courses, rng.normal(0, 0.25, 600))}
    res = _test_apparie(a, b)
    assert res["conclut"] is False


def test_le_test_apparie_ignore_les_courses_non_communes():
    """Comparer sur des courses différentes réintroduirait le bruit qu'on annule."""
    from scripts.ab_fenetre_refit import _test_apparie

    a = {f"c{i}": 0.5 for i in range(100)}
    b = {f"c{i}": 0.6 for i in range(50, 200)}
    res = _test_apparie(a, b)
    assert res["n_courses"] == 50


def test_un_echantillon_minuscule_refuse_de_conclure():
    from scripts.ab_fenetre_refit import _test_apparie

    a = {f"c{i}": 0.5 for i in range(10)}
    b = {f"c{i}": 0.9 for i in range(10)}
    res = _test_apparie(a, b)
    assert res["conclut"] is False
    assert res["ecart"] is None


def test_le_test_apparie_est_reproductible():
    """Un banc dont le verdict change d'un lancement à l'autre n'arbitre rien."""
    from scripts.ab_fenetre_refit import _test_apparie

    rng = np.random.default_rng(3)
    a = {f"c{i:04d}": float(v) for i, v in enumerate(rng.uniform(0.3, 0.9, 400))}
    b = {c: v + 0.01 for c, v in a.items()}
    assert _test_apparie(a, b) == _test_apparie(a, b)


# ── Une seule définition du classement intra-course ─────────────────────────

def test_la_moyenne_par_course_reste_celle_affichee():
    """`within_race_auc` doit moyenner EXACTEMENT les termes que le test apparié
    utilise, sans quoi le chiffre du rapport et le verdict divergeraient."""
    from ml.ranking_metrics import within_race_auc, within_race_auc_par_course

    rng = np.random.default_rng(5)
    n = 900
    groupes = np.array([f"c{i // 9:03d}" for i in range(n)])
    scores = rng.uniform(0, 1, n)
    labels = (rng.uniform(0, 1, n) < 0.11).astype(float)

    par_course = within_race_auc_par_course(labels, scores, groupes)
    assert par_course, "aucune course exploitable : le test ne prouverait rien"
    assert within_race_auc(labels, scores, groupes) == pytest.approx(
        float(np.mean(list(par_course.values()))))


def test_une_course_indiscriminante_est_absente_et_non_neutre():
    """La remplacer par 0,5 diluerait tout écart mesuré vers zéro."""
    from ml.ranking_metrics import within_race_auc_par_course

    labels = [1, 1, 0, 1]          # course « a » : que des gagnants → inexploitable
    scores = [0.9, 0.8, 0.2, 0.7]
    groupes = ["a", "a", "b", "b"]
    par_course = within_race_auc_par_course(labels, scores, groupes)
    assert "a" not in par_course
    assert "b" in par_course
