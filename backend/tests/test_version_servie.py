"""Attribution des prédictions au modèle réellement chargé (current_model.pkl).

Les prédictions portaient `model_versions.est_actif`, qui peut diverger du fichier
servi pendant une promotion ou un retour arrière (v545 attribué à v544).
"""
import pickle
from types import SimpleNamespace

import pytest

from db.models import ModelVersion
from ml import models as ml_models
from ml.pipeline import version_servie


def _mv(num: int, actif: bool) -> ModelVersion:
    return ModelVersion(
        version_id=f"id-{num}", version_num=num, nom_fichier=f"model_v{num:04d}.pkl",
        auc_roc=0.0, brier_score=1.0, precision_top3=0.0, roi_simule=0.0,
        nb_courses_train=0, est_actif=actif,
    )


@pytest.mark.asyncio
async def test_modele_sans_numero_retombe_sur_est_actif(db):
    db.add_all([_mv(544, True), _mv(545, False)])
    await db.commit()
    assert await version_servie(db, SimpleNamespace(version_num=0)) == "id-544"


@pytest.mark.asyncio
async def test_numero_du_pickle_prime_sur_est_actif(db):
    db.add_all([_mv(544, True), _mv(545, False)])
    await db.commit()
    assert await version_servie(db, SimpleNamespace(version_num=545)) == "id-545"


@pytest.mark.asyncio
async def test_numero_concordant(db):
    db.add_all([_mv(548, True)])
    await db.commit()
    assert await version_servie(db, SimpleNamespace(version_num=548)) == "id-548"


@pytest.mark.asyncio
async def test_numero_inconnu_retombe_sur_est_actif(db):
    db.add_all([_mv(548, True)])
    await db.commit()
    assert await version_servie(db, SimpleNamespace(version_num=999)) == "id-548"


@pytest.mark.asyncio
async def test_aucune_version(db):
    assert await version_servie(db, SimpleNamespace(version_num=0)) is None


def test_save_inscrit_le_numero_dans_le_pickle(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_models, "MODELS_DIR", tmp_path)
    m = ml_models.BlackTurfEnsemble.__new__(ml_models.BlackTurfEnsemble)
    m.version_num = 0
    m.feature_names = ["a"]
    chemin = m.save(548)
    with open(chemin, "rb") as f:
        assert pickle.load(f).version_num == 548
