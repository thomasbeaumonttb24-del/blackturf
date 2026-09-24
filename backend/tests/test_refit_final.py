"""Refit final du modèle servi (drapeau `refit_full`, P0 audit 2026-09-23).

Le modèle servi était celui entraîné sur les 80 % de courses les plus anciennes :
v544, promu le 24/09, porte `train_fin = 2026-07-08`. Le drapeau garde la
DÉCISION intacte (même hold-out, même arbitre) et sert, une fois la promotion
décidée, la même procédure rejouée sur tout le jeu.

Ce que ces tests verrouillent :
  - le refit voit bien les courses du hold-out (il apprend un régime qui n'existe
    QUE dans le hold-out) ;
  - les métriques stockées restent celles du hold-out, en base comme dans le
    pickle servi ;
  - drapeau éteint = comportement actuel, au même objet près ;
  - `train_fin` est celle du modèle servi ; la borne du duel de la nuit suivante
    reste celle du modèle d'évaluation ;
  - l'arbitre confronte le challenger au modèle d'ÉVALUATION du champion refit.
"""
import dataclasses
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from ml import algo_flags


# ── Jeux synthétiques ────────────────────────────────────────────────────────

def _jeu_changement_de_regime(n_courses=200, n_partants=10, graine=11):
    """Courses chronologiques. Sur les 80 % anciennes, le gagnant suit `g` ; sur
    les 20 % récentes (le hold-out), il suit `f`. Un modèle qui n'a pas appris le
    hold-out ne peut pas savoir que `f` compte."""
    rng = np.random.RandomState(graine)
    coupe = int(n_courses * 0.8)
    lignes = []
    for c in range(n_courses):
        f, g = rng.randn(n_partants), rng.randn(n_partants)
        signal = g if c < coupe else f
        ordre = np.argsort(-(signal * 2.0 + rng.randn(n_partants) * 0.3))
        for i in range(n_partants):
            pos = int(np.where(ordre == i)[0][0]) + 1
            lignes.append({"course_id": f"c{c:04d}", "f": float(f[i]), "g": float(g[i]),
                           "bruit": float(rng.randn()), "_pos": pos})
    df = pd.DataFrame(lignes)
    pos = df.pop("_pos")
    return df, (pos <= 3).astype(int), (pos == 1).astype(int)


def _courses_regime_recent(n_courses=150, n_partants=10, graine=99):
    """Courses NEUVES du régime récent (gagnant = argmax f), jamais vues."""
    rng = np.random.RandomState(graine)
    lignes = []
    for c in range(n_courses):
        f, g = rng.randn(n_partants), rng.randn(n_partants)
        gagnant = int(np.argmax(f * 2.0 + rng.randn(n_partants) * 0.3))
        for i in range(n_partants):
            lignes.append({"course_id": f"n{c:04d}", "f": float(f[i]), "g": float(g[i]),
                           "bruit": float(rng.randn()), "_win": int(i == gagnant)})
    df = pd.DataFrame(lignes)
    return df, df.pop("_win")


def _jeu_simple(n_courses=60, n_partants=8, graine=5):
    rng = np.random.RandomState(graine)
    lignes = []
    for c in range(n_courses):
        force = rng.randn(n_partants)
        ordre = np.argsort(-(force + rng.randn(n_partants) * 0.6))
        for i in range(n_partants):
            pos = int(np.where(ordre == i)[0][0]) + 1
            lignes.append({"course_id": f"c{c:04d}",
                           "cote_pmu": float(np.clip(12.0 - 3.0 * force[i], 1.2, 60.0)),
                           "forme": float(force[i]), "bruit": float(rng.randn()),
                           "_pos": pos})
    df = pd.DataFrame(lignes)
    pos = df.pop("_pos")
    return df, (pos <= 3).astype(int), (pos == 1).astype(int)


def _rang_auc_victoire(modele, X, y_win):
    from ml.ranking_metrics import within_race_auc
    return float(within_race_auc(y_win.to_numpy(), modele.predict_win_proba(X),
                                 X["course_id"].to_numpy()))


# ── Le modèle ────────────────────────────────────────────────────────────────

def test_le_refit_apprend_les_courses_du_hold_out(tmp_path, monkeypatch):
    """Le cœur du P0 : le régime qui n'existe QUE dans le hold-out doit être
    appris par le refit, et ignoré par le modèle d'évaluation."""
    monkeypatch.chdir(tmp_path)          # catboost_info/ écrit dans le cwd
    from ml.models import BlackTurfEnsemble
    from ml.pipeline import _modele_a_servir

    X, y3, yw = _jeu_changement_de_regime()
    evaluation = BlackTurfEnsemble()
    evaluation.train(X, y3, y_win=yw)
    servi = _modele_a_servir(evaluation, X, y3, yw, refit=True)

    X_neuf, yw_neuf = _courses_regime_recent()
    rang_eval = _rang_auc_victoire(evaluation, X_neuf, yw_neuf)
    rang_servi = _rang_auc_victoire(servi, X_neuf, yw_neuf)
    assert rang_servi > rang_eval + 0.10, (rang_eval, rang_servi)
    # Et l'importance de `f` le dit aussi.
    assert servi.feature_importance["f"] > evaluation.feature_importance["f"]


def test_le_refit_voit_toutes_les_lignes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble

    X, y3, yw = _jeu_simple()
    vus = {}
    from sklearn.calibration import CalibratedClassifierCV
    fit_origine = CalibratedClassifierCV.fit

    def _espion(self, Xf, yf, *a, **k):
        vus.setdefault("n", []).append(len(Xf))
        return fit_origine(self, Xf, yf, *a, **k)

    monkeypatch.setattr(CalibratedClassifierCV, "fit", _espion)
    sortie = BlackTurfEnsemble().train(X, y3, y_win=yw, refit=True,
                                       feature_names=["cote_pmu", "forme", "bruit"])
    assert sortie == {"refit": True, "n_lignes": len(X)}
    # XGB, LGBM, CatBoost et le modèle de victoire : tous sur TOUT le jeu.
    assert vus["n"] and all(n == len(X) for n in vus["n"]), vus


def test_le_refit_ne_produit_aucune_mesure_propre(tmp_path, monkeypatch):
    """Aucune mesure du refit sur ses propres données : ni walk-forward, ni
    `_evaluate` (il n'y a plus d'échantillon non vu)."""
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble

    def _interdit(*a, **k):
        raise AssertionError("le refit ne doit rien mesurer")

    monkeypatch.setattr(BlackTurfEnsemble, "_walk_forward_validation", _interdit)
    monkeypatch.setattr(BlackTurfEnsemble, "_evaluate", _interdit)
    X, y3, yw = _jeu_simple()
    m = BlackTurfEnsemble()
    m.train(X, y3, y_win=yw, refit=True, feature_names=["cote_pmu", "forme", "bruit"])
    assert m.est_refit is True
    assert m.auc_roc == 0.0 and m.rank_auc is None    # rien d'inventé


def test_les_mesures_servies_sont_celles_du_hold_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble
    from ml.pipeline import _modele_a_servir

    X, y3, yw = _jeu_simple()
    evaluation = BlackTurfEnsemble()
    metrics = evaluation.train(X, y3, y_win=yw)
    servi = _modele_a_servir(evaluation, X, y3, yw, refit=True)

    for nom in BlackTurfEnsemble.MESURES_HORS_ECHANTILLON:
        assert getattr(servi, nom) == getattr(evaluation, nom), nom
    assert servi.auc_roc == metrics["auc_roc"]
    assert servi.rank_auc == metrics["rank_auc"]
    assert servi.market_rank_auc == metrics["market_rank_auc"]
    assert servi.win_auc == metrics["win_auc"]
    assert servi is not evaluation and servi.est_refit and not evaluation.est_refit


def test_drapeau_eteint_sert_le_modele_d_evaluation_lui_meme():
    from ml.pipeline import _modele_a_servir

    sentinelle = object()
    assert _modele_a_servir(sentinelle, None, None, None, refit=False) is sentinelle


def test_le_drapeau_est_eteint_par_defaut(monkeypatch):
    monkeypatch.delenv("BT_REFIT_FULL", raising=False)
    assert algo_flags.AlgoFlags().refit_full is False
    assert "refit_full" in algo_flags.AlgoFlags().as_dict()
    monkeypatch.setenv("BT_REFIT_FULL", "1")
    assert algo_flags.AlgoFlags().refit_full is True


def test_le_vecteur_de_features_est_fige_sur_l_evaluation(tmp_path, monkeypatch):
    """Une colonne constante sur les 80 % anciens mais vivante dans le hold-out
    n'a jamais été validée hors échantillon : elle n'entre pas au refit."""
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble
    from ml.pipeline import _modele_a_servir

    X, y3, yw = _jeu_simple()
    X = X.copy()
    X["source_revenue"] = 0.0
    recentes = X["course_id"].isin(sorted(X["course_id"].unique())[-10:])
    X.loc[recentes, "source_revenue"] = np.random.RandomState(1).randn(int(recentes.sum()))
    evaluation = BlackTurfEnsemble()
    evaluation.train(X, y3, y_win=yw)
    assert "source_revenue" in evaluation.constant_features
    servi = _modele_a_servir(evaluation, X, y3, yw, refit=True)
    assert servi.feature_names == evaluation.feature_names
    assert "source_revenue" not in servi.feature_names


def test_une_colonne_attendue_absente_fait_echouer_le_refit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble

    X, y3, yw = _jeu_simple()
    with pytest.raises(ValueError):
        BlackTurfEnsemble().train(X, y3, y_win=yw, refit=True,
                                  feature_names=["forme", "inexistante"])


# ── Retard d'apprentissage ───────────────────────────────────────────────────

def test_retard_apprentissage_sans_refit_v544():
    """v544 : train_fin 08/07 19:46, lu le 24/09 → ~77,5 jours, attendu sans
    refit (largeur du hold-out) : exposé, pas d'alerte."""
    from ml.pipeline import retard_apprentissage

    r = retard_apprentissage(datetime(2026, 7, 8, 19, 46, tzinfo=timezone.utc),
                             datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc),
                             refit_actif=False)
    assert r["jours"] == pytest.approx(77.4, abs=0.1)
    assert r["alerte"] is False and r["seuil_jours"] == 100.0


def test_retard_apprentissage_avec_refit_alerte_au_dela_d_une_semaine():
    from ml.pipeline import retard_apprentissage

    maintenant = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)
    frais = retard_apprentissage(maintenant - timedelta(days=1), maintenant, refit_actif=True)
    gele = retard_apprentissage(maintenant - timedelta(days=8), maintenant, refit_actif=True)
    assert frais["alerte"] is False and gele["alerte"] is True
    # Naïf (SQLite) et chaîne ISO : lus comme de l'UTC, jamais une exception.
    assert retard_apprentissage("2026-09-23 06:00:00", maintenant, refit_actif=True)["jours"] == 1.0


def test_retard_absent_n_est_pas_une_alerte():
    from ml.pipeline import retard_apprentissage

    r = retard_apprentissage(None, refit_actif=True)
    assert r["jours"] is None and r["alerte"] is False


@pytest.mark.asyncio
async def test_la_supervision_expose_le_retard_du_modele_actif(db, monkeypatch):
    from db.models import ModelVersion
    from ml.supervision_apprentissage import etat_outils_apprentissage

    monkeypatch.setattr(algo_flags, "FLAGS",
                        dataclasses.replace(algo_flags.FLAGS, refit_full=True))
    db.add(ModelVersion(version_num=544, nom_fichier="model_v0544.pkl", auc_roc=0.73,
                        brier_score=0.19, precision_top3=0.5, roi_simule=0.0,
                        nb_courses_train=175000, est_actif=True,
                        train_fin=datetime.now(timezone.utc) - timedelta(days=77)))
    await db.commit()
    etat = await etat_outils_apprentissage(db)
    assert etat["retrain"]["retard_apprentissage_jours"] == pytest.approx(77, abs=0.2)
    assert etat["retrain"]["retard_apprentissage_alerte"] is True
    assert etat["alerte"] is True


# ── L'arbitre champion/challenger ────────────────────────────────────────────

class _Modele:
    """Classe au niveau du module : picklable. Prédit d'autant mieux que `skill`."""

    def __init__(self, skill, fin=None):
        self.skill = skill
        self.fin_apprentissage = fin

    def predict_proba(self, X):
        y = X["truth"].to_numpy().astype(float)
        bruit = ((np.arange(len(X)) * 7919) % 1000) / 1000.0
        return self.skill * y + (1 - self.skill) * bruit

    def predict_win_proba(self, X):
        return None


class _Session:
    def __init__(self, course_ids):
        self._rows = [(c,) for c in course_ids]
        self.dernier_cutoff = None

    async def execute(self, _stmt, params=None):
        if params:
            self.dernier_cutoff = params.get("cutoff")
        return self._rows


class _MV:
    def __init__(self, version_num, created_at, train_fin):
        self.version_num = version_num
        self.created_at = created_at
        self.train_fin = train_fin


def _holdout(n_courses=400):
    cid, truth = [], []
    for i in range(n_courses):
        for j in range(6):
            cid.append(f"C{i}")
            truth.append(1 if j == 0 else 0)
    return pd.DataFrame({"course_id": cid, "truth": truth}), pd.Series(truth)


@pytest.mark.asyncio
async def test_l_arbitre_confronte_le_modele_d_evaluation_du_champion_refit(tmp_path, monkeypatch):
    """Le champion SERVI a appris le hold-out (skill 0.99) ; son modèle
    d'ÉVALUATION non (skill 0.30). L'arbitre doit juger ce dernier, avec SA
    borne — sinon le challenger perdrait mécaniquement."""
    from ml import models as ml_models
    from ml import pipeline as pl

    monkeypatch.setattr(ml_models, "MODELS_DIR", tmp_path)
    borne_eval = pd.Timestamp("2026-07-08", tz="UTC")
    with open(tmp_path / "model_v0544_eval.pkl", "wb") as fh:
        pickle.dump(_Modele(0.30, fin=borne_eval), fh)
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _Modele(0.99)))
    X, y = _holdout()
    session = _Session(X["course_id"].unique())
    champion = _MV(544, pd.Timestamp("2026-09-24", tz="UTC"),
                   train_fin=pd.Timestamp("2026-09-23", tz="UTC"))

    res = await pl._head_to_head_auc(session, _Modele(0.95), X, y, champion)
    assert res is not None
    assert res["delta"] > 0, "jugé contre le modèle d'évaluation, pas le refit"
    assert res["borne_source"] == "evaluation"
    assert session.dernier_cutoff == borne_eval, "borne du modèle d'évaluation, pas train_fin"


@pytest.mark.asyncio
async def test_sans_fichier_d_evaluation_le_chemin_historique_est_inchange(tmp_path, monkeypatch):
    from ml import models as ml_models
    from ml import pipeline as pl

    monkeypatch.setattr(ml_models, "MODELS_DIR", tmp_path)       # répertoire vide
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _Modele(0.30)))
    X, y = _holdout()
    session = _Session(X["course_id"].unique())
    fin = pd.Timestamp("2026-07-07", tz="UTC")
    res = await pl._head_to_head_auc(session, _Modele(0.95), X, y,
                                     _MV(543, pd.Timestamp("2026-09-23", tz="UTC"), fin))
    assert res is not None and res["delta"] > 0
    assert res["borne_source"] == "train_fin" and session.dernier_cutoff == fin


@pytest.mark.asyncio
async def test_une_evaluation_sans_borne_renonce_au_duel(tmp_path, monkeypatch):
    """Une borne inventée serait pire que pas de test : repli walk-forward."""
    from ml import models as ml_models
    from ml import pipeline as pl

    monkeypatch.setattr(ml_models, "MODELS_DIR", tmp_path)
    with open(tmp_path / "model_v0544_eval.pkl", "wb") as fh:
        pickle.dump(_Modele(0.30, fin=None), fh)
    X, y = _holdout()
    res = await pl._head_to_head_auc(_Session(X["course_id"].unique()), _Modele(0.95), X, y,
                                     _MV(544, pd.Timestamp("2026-09-24", tz="UTC"), None))
    assert res is None


# ── Le pipeline de bout en bout ──────────────────────────────────────────────

async def _nuit(engine, tmp_path, monkeypatch, *, refit: bool):
    """Joue `_do_retraining` sur un jeu synthétique, base SQLite, sans champion."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import select

    from db.models import ModelVersion
    from ml import models as ml_models
    from ml import pipeline as pl

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ml_models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(algo_flags, "FLAGS", dataclasses.replace(
        algo_flags.FLAGS, refit_full=refit, roi_deploy_gate=False,
        market_gate=False))   # BT_MARKET_GATE=0 en production (chantier C)
    fabrique = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(pl, "AsyncSessionLocal", fabrique)
    # Table du cliquet (migration 0045, hors métadonnées ORM) : sans elle,
    # `_persister_dette` fait un rollback qui emporte la ligne de version.
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE retrain_ratchet (id INTEGER PRIMARY KEY, dette FLOAT, "
            "depuis_version INTEGER, maj TIMESTAMP)")

    X, y3, yw = _jeu_simple(n_courses=80)
    ordre = list(dict.fromkeys(X["course_id"]))
    t0 = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    dates = {cid: t0 + timedelta(days=i) for i, cid in enumerate(ordre)}

    async def _faux_dataset(session, mois, max_rows=None, date_fin=None):
        return X.copy(), y3.copy(), yw.copy()

    async def _fausse_date(session, course_id):
        return dates.get(course_id)

    appels = []
    train_origine = pl.BlackTurfEnsemble.train

    def _espion(self, Xa, ya, y_win=None, frac_train=0.8, **k):
        appels.append({"n": len(Xa), "refit": k.get("refit", False)})
        return train_origine(self, Xa, ya, y_win, frac_train, **k)

    monkeypatch.setattr(pl, "_build_training_dataset_from_db", _faux_dataset)
    monkeypatch.setattr(pl, "_date_course", _fausse_date)
    monkeypatch.setattr(pl.BlackTurfEnsemble, "train", _espion)

    issue = await pl._do_retraining(mois=12, label="test")
    async with fabrique() as s:
        mv = (await s.execute(select(ModelVersion))).scalars().one()

    from ml.models import temporal_holdout_mask
    hm = temporal_holdout_mask(X)
    return {"issue": issue, "mv": mv, "appels": appels, "X": X, "dates": dates,
            "fin_eval": dates[X.loc[~hm, "course_id"].iloc[-1]],
            "fin_complet": dates[X["course_id"].iloc[-1]]}


def _naif(d):
    return d.replace(tzinfo=None) if d is not None and d.tzinfo else d


@pytest.mark.asyncio
async def test_nuit_drapeau_eteint_comportement_actuel(engine, tmp_path, monkeypatch):
    from ml.models import BlackTurfEnsemble

    r = await _nuit(engine, tmp_path, monkeypatch, refit=False)
    assert r["issue"]["issue"] == "promu"
    assert r["appels"] == [{"n": len(r["X"]), "refit": False}], "un seul entraînement"
    assert _naif(r["mv"].train_fin) == _naif(r["fin_eval"])
    assert not list(tmp_path.glob("*_eval.pkl")), "aucun modèle d'évaluation archivé"
    servi = BlackTurfEnsemble.load(tmp_path / "current_model.pkl")
    assert getattr(servi, "est_refit", False) is False
    assert "refit" not in r["issue"]
    assert r["issue"]["retard_apprentissage"]["refit_actif"] is False


@pytest.mark.asyncio
async def test_nuit_drapeau_allume_sert_le_refit(engine, tmp_path, monkeypatch):
    from ml.models import BlackTurfEnsemble

    r = await _nuit(engine, tmp_path, monkeypatch, refit=True)
    mv, X = r["mv"], r["X"]
    assert r["issue"]["issue"] == "promu" and r["issue"]["refit"]["ok"] is True
    # Une évaluation (80/20), PUIS un refit sur tout le jeu.
    assert r["appels"] == [{"n": len(X), "refit": False}, {"n": len(X), "refit": True}]

    # train_fin = dernière course du JEU ENTIER, postérieure à celle de l'évaluation.
    assert _naif(mv.train_fin) == _naif(r["fin_complet"])
    assert r["fin_complet"] > r["fin_eval"]

    servi = BlackTurfEnsemble.load(tmp_path / "current_model.pkl")
    evaluation = BlackTurfEnsemble.load(tmp_path / f"model_v{mv.version_num:04d}_eval.pkl")
    assert servi.est_refit is True and evaluation.est_refit is False
    assert servi.fin_apprentissage == r["fin_complet"]
    # La borne du duel de demain : celle du modèle d'ÉVALUATION.
    assert evaluation.fin_apprentissage == r["fin_eval"]

    # Métriques stockées = hold-out honnête, et le pickle servi dit la même chose.
    assert mv.auc_roc == evaluation.auc_roc == servi.auc_roc
    assert mv.rank_auc == evaluation.rank_auc == servi.rank_auc
    assert mv.market_rank_auc == evaluation.market_rank_auc
    assert mv.rank_source == "hold_out"
    assert mv.nb_courses_train == len(X)


@pytest.mark.asyncio
async def test_un_refit_qui_echoue_ne_coute_pas_la_promotion(engine, tmp_path, monkeypatch):
    from ml import pipeline as pl
    from ml.models import BlackTurfEnsemble

    def _boom(*a, **k):
        raise MemoryError("simulée")

    monkeypatch.setattr(pl, "_modele_a_servir", _boom)
    r = await _nuit(engine, tmp_path, monkeypatch, refit=True)
    assert r["issue"]["issue"] == "promu"
    assert r["issue"]["refit"]["ok"] is False
    # Repli : le modèle d'évaluation est servi, avec SA fin d'apprentissage.
    assert _naif(r["mv"].train_fin) == _naif(r["fin_eval"])
    servi = BlackTurfEnsemble.load(tmp_path / "current_model.pkl")
    assert getattr(servi, "est_refit", False) is False
    assert r["issue"]["retard_apprentissage"]["alerte"] is True   # 7 j dépassés
