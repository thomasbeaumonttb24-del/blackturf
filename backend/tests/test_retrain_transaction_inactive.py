"""Aucun long calcul du retrain ne doit garder une transaction ouverte.

Le rôle `bt_app` porte `idle_in_transaction_session_timeout = 10min` depuis le
durcissement du 06/10/2026. Le 07/10, l'entraînement (24 min) suivait la lecture
du dataset dans la même transaction : PostgreSQL a coupé la connexion à 09:07:01,
dix minutes pile après la lecture, et le retrain a échoué après avoir tout calculé.
"""
import inspect

import pytest


def _src(fn):
    return inspect.getsource(fn)


def test_transaction_close_entre_lecture_du_dataset_et_entrainement():
    from ml import pipeline

    src = _src(pipeline._do_retraining)
    lecture = src.index("_build_training_dataset_from_db(")
    cloture = src.index("await _clore_lecture(session)")
    entrainement = src.index("model.train(X, y, y_win)")
    assert lecture < cloture < entrainement


def test_transaction_close_avant_le_refit():
    from ml import pipeline

    src = _src(pipeline._do_retraining)
    debut_refit = src.index("if _refit:\n")
    refit = src.index("_modele_a_servir(model, X, y, y_win, refit=True)")
    assert "await _clore_lecture(session)" in src[debut_refit:refit]


def test_transaction_close_avant_le_scoring_du_duel():
    from ml import pipeline

    src = _src(pipeline._head_to_head_auc)
    requete = src.index("SELECT course_id FROM courses WHERE date_heure > :cutoff")
    cloture = src.index("await _clore_lecture(session)")
    scoring = src.index("isin(oos_courses)")
    assert requete < cloture < scoring


@pytest.mark.asyncio
async def test_clore_lecture_committe():
    from ml.pipeline import _clore_lecture

    appels = []

    class _Session:
        async def commit(self):
            appels.append("commit")

    await _clore_lecture(_Session())
    assert appels == ["commit"]


@pytest.mark.asyncio
async def test_clore_lecture_ne_fait_jamais_echouer_le_retrain():
    """Un commit raté ne doit pas changer une décision de promotion."""
    from ml.pipeline import _clore_lecture

    class _Cassee:
        async def commit(self):
            raise RuntimeError("connexion perdue")

    await _clore_lecture(_Cassee())     # ne doit pas lever
    await _clore_lecture(object())      # session factice sans commit()


def test_les_sessions_ne_perimant_pas_leurs_objets_au_commit():
    """`_clore_lecture` en cours de retrain suppose que `current_mv`, lu avant,
    reste lisible après : sans `expire_on_commit=False`, l'accès suivant
    déclencherait un chargement paresseux interdit en asynchrone."""
    from db.database import AsyncSessionLocal

    assert AsyncSessionLocal.kw.get("expire_on_commit") is False
