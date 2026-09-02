"""Le chiffre qui condamne le modèle doit décrire le modèle qu'on déploie.

`model_versions.rank_auc` / `market_rank_auc` / `rank_delta_market` recevaient les
valeurs du WALK-FORWARD, c'est-à-dire d'un XGBoost jetable de 100 arbres ré-entraîné
fold par fold — jamais de l'ensemble complet qu'on met en production. Ce sont
pourtant ces valeurs-là qui :

  - alimentent le premier repli du gate marché (`BT_MARKET_GATE`) ;
  - ont justifié de laisser ce gate FERMÉ (« modèle 0,7340 contre 0,7351 pour la
    cote qu'il voit », donc aucun modèle ne le passerait).

Une décision de cette portée doit porter sur l'ensemble réellement déployé.
"""
import numpy as np
import pandas as pd

from ml.pipeline import _source_rang_marche


def _metrics(**kw):
    base = {"rank_auc": None, "market_rank_auc": None, "rank_delta_market": None,
            "wf_rank_auc": None, "wf_market_rank_auc": None,
            "wf_rank_delta_market": None}
    base.update(kw)
    return base


def test_le_hold_out_de_l_ensemble_complet_passe_avant_tout():
    """C'est le plus gros échantillon hors-échantillon mesuré sur le VRAI modèle."""
    out = _source_rang_marche(
        _metrics(rank_auc=0.74, market_rank_auc=0.73, rank_delta_market=0.01,
                 wf_rank_auc=0.80, wf_market_rank_auc=0.70,
                 wf_rank_delta_market=0.10),
        {"rank_challenger": 0.72, "rank_marche": 0.71, "delta_marche": 0.01},
    )
    assert out["source"] == "hold_out"
    assert out["rank_auc"] == 0.74
    assert out["market_rank_auc"] == 0.73
    assert out["delta_market"] == 0.01


def test_repli_sur_le_head_to_head_quand_le_hold_out_n_a_pas_de_cotes():
    """Toujours l'ensemble complet, simplement sur un échantillon plus étroit."""
    out = _source_rang_marche(
        _metrics(rank_auc=0.74, wf_rank_auc=0.80, wf_market_rank_auc=0.70,
                 wf_rank_delta_market=0.10),
        {"rank_challenger": 0.72, "rank_marche": 0.715, "delta_marche": 0.005},
    )
    assert out["source"] == "h2h"
    assert out["rank_auc"] == 0.72
    assert out["market_rank_auc"] == 0.715
    assert out["delta_market"] == 0.005


def test_le_walk_forward_n_est_plus_qu_un_dernier_recours():
    """Il mesure le DATASET, pas le modèle : il ne passe plus devant personne."""
    out = _source_rang_marche(
        _metrics(wf_rank_auc=0.80, wf_market_rank_auc=0.70,
                 wf_rank_delta_market=0.10),
        None,
    )
    assert out["source"] == "walk_forward"
    assert out["delta_market"] == 0.10


def test_aucune_mesure_ne_fabrique_jamais_un_ecart():
    """Une absence de mesure ne doit pas se lire comme un succès — ni comme un
    échec : le gate marché doit recevoir None et s'abstenir."""
    out = _source_rang_marche(_metrics(), None)
    assert out["source"] is None
    assert out["delta_market"] is None
    assert out["market_rank_auc"] is None


def test_un_ecart_negatif_reste_une_mesure_valide():
    """Zéro et négatif sont des valeurs, pas des absences : `is not None` et non
    la véracité booléenne, sinon un modèle exactement à égalité avec la cote
    retomberait silencieusement sur le walk-forward."""
    out = _source_rang_marche(
        _metrics(rank_auc=0.73, market_rank_auc=0.73, rank_delta_market=0.0,
                 wf_rank_delta_market=0.10),
        None,
    )
    assert out["source"] == "hold_out"
    assert out["delta_market"] == 0.0


def test_ce_qui_est_persiste_vient_de_la_source_retenue():
    """Garde-fou de câblage : `_do_retraining` doit écrire les valeurs du helper,
    et non re-piocher les `wf_*` comme il le faisait."""
    import inspect

    from ml import pipeline

    src = inspect.getsource(pipeline._do_retraining)
    assert "rank_auc=_rank_auc," in src
    assert "market_rank_auc=_market_rank_auc," in src
    assert 'rank_auc=metrics.get("wf_rank_auc")' not in src
    assert 'market_rank_auc=metrics.get("wf_market_rank_auc")' not in src


def test_l_entrainement_produit_bien_les_mesures_du_hold_out(tmp_path, monkeypatch):
    """La source préférée doit exister en pratique, pas seulement en théorie :
    `_evaluate` renvoie le classement de l'ensemble complet ET celui de la cote sur
    le même hold-out. Sans ces clés, `_source_rang_marche` retomberait en silence
    sur le walk-forward — soit exactement le défaut qu'on corrige."""
    monkeypatch.chdir(tmp_path)   # catboost_info/ écrit dans le cwd
    from ml.models import BlackTurfEnsemble

    rng = np.random.RandomState(7)
    n_courses, n_partants = 60, 10
    lignes = []
    for c in range(n_courses):
        force = rng.randn(n_partants)
        gagnant = int(np.argmax(force + rng.randn(n_partants) * 0.6))
        for i in range(n_partants):
            lignes.append({
                "course_id": f"c{c:03d}",
                "cote_pmu": float(np.clip(12.0 - 3.0 * force[i], 1.2, 60.0)),
                "forme": float(force[i]),
                "bruit": float(rng.randn()),
                "_place": int(i == gagnant),
            })
    df = pd.DataFrame(lignes)
    y = df.pop("_place")
    metrics = BlackTurfEnsemble().train(df, y, y_win=y)

    for cle in ("rank_auc", "market_rank_auc", "rank_delta_market"):
        assert cle in metrics, cle
        assert metrics[cle] is not None, f"{cle} mesuré sur le hold-out, pas None"
    assert _source_rang_marche(metrics, None)["source"] == "hold_out"
