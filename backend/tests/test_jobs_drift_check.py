"""
Tests de job_drift_check (audit 2026-08-16).

Régression protégée : le conteneur `scheduler` (seul process qui exécute les
jobs APScheduler, cf. RUN_SCHEDULER=1 vs RUN_SCHEDULER=0 côté api) n'a AUCUN
hook de démarrage qui appelle `initialize_drift_detector()` — seul
`api/main.py:lifespan` le fait, et le worker RQ le fait par job (cf. commentaire
`pipeline.py` run_post_course). `job_drift_check` appelait la version NUE
`get_drift_detector()`, qui lève `RuntimeError` tant qu'aucun init n'a eu lieu
DANS CE PROCESS → le job échouait TOUTES LES HEURES en silence (`log.error`,
jamais remonté ailleurs), et le retraining incrémental sur dérive critique
n'a donc jamais pu se déclencher par cette voie.

Fix : recharger l'état depuis la DB à CHAQUE exécution du job (comme le fait
déjà `run_post_course` pour le worker RQ, pour la même raison structurelle),
pas un init unique au boot du conteneur qui resterait figé sur un snapshot
pendant que le worker met l'état à jour en continu.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from services import jobs


def _fake_session_local(session=None):
    """Factory bidon pour `db.database.AsyncSessionLocal` : `async with
    AsyncSessionLocal() as s` doit fonctionner sans jamais toucher une vraie DB."""
    @asynccontextmanager
    async def _ctx():
        yield session or SimpleNamespace()
    return _ctx


class _FakeDriftDetector:
    def __init__(self, status: str, brier_mean: float = 0.19):
        self._status = status
        self._brier_mean = brier_mean

    def get_drift_report(self) -> dict:
        return {"status": self._status, "brier_mean": self._brier_mean}


@pytest.mark.asyncio
async def test_ne_leve_plus_meme_si_get_drift_detector_nu_casse(monkeypatch):
    """LE test de la régression : avant le fix, `job_drift_check` dépendait de
    `get_drift_detector()` qui lève RuntimeError hors process API/worker. On
    simule ce vieux comportement cassé pour prouver qu'il n'est plus sur le
    chemin d'exécution."""
    import db.database as dbmod

    def _boom():
        raise RuntimeError(
            "DriftDetector has not been initialised. "
            "Call initialize_drift_detector(session) during application startup."
        )

    monkeypatch.setattr("ml.drift_detector.get_drift_detector", _boom)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session_local())

    async def _fake_init(session):
        return _FakeDriftDetector("healthy")

    monkeypatch.setattr("ml.drift_detector.initialize_drift_detector", _fake_init)

    await jobs.job_drift_check()  # ne doit lever aucune exception


@pytest.mark.asyncio
async def test_recharge_l_etat_a_chaque_appel(monkeypatch):
    """Pas un init one-shot mémorisé : chaque exécution doit repasser par
    `initialize_drift_detector(session)` pour voir l'état DB le plus frais
    (écrit en continu par le worker RQ entre deux runs horaires)."""
    import db.database as dbmod

    calls = []

    async def _fake_init(session):
        calls.append(session)
        return _FakeDriftDetector("healthy")

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session_local())
    monkeypatch.setattr("ml.drift_detector.initialize_drift_detector", _fake_init)

    await jobs.job_drift_check()
    await jobs.job_drift_check()

    assert len(calls) == 2, "chaque run doit ré-initialiser depuis la DB"


@pytest.mark.asyncio
async def test_severite_healthy_n_enqueue_rien(monkeypatch):
    import db.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session_local())

    async def _fake_init(session):
        return _FakeDriftDetector("healthy")

    monkeypatch.setattr("ml.drift_detector.initialize_drift_detector", _fake_init)

    enqueued = []
    monkeypatch.setattr(
        "rq.Queue.enqueue",
        lambda self, *a, **kw: enqueued.append(a) or SimpleNamespace(id="job-1"),
    )

    await jobs.job_drift_check()

    assert enqueued == []


@pytest.mark.asyncio
async def test_severite_critical_enqueue_le_retrain_incremental(monkeypatch):
    import db.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session_local())

    async def _fake_init(session):
        return _FakeDriftDetector("critical")

    monkeypatch.setattr("ml.drift_detector.initialize_drift_detector", _fake_init)

    enqueued = []

    def _fake_enqueue(self, name, **kw):
        enqueued.append(name)
        return SimpleNamespace(id="job-1")

    monkeypatch.setattr("rq.Queue.enqueue", _fake_enqueue)

    await jobs.job_drift_check()

    assert enqueued == ["ml.pipeline.run_incremental_retraining_sync"]


@pytest.mark.asyncio
async def test_erreur_inattendue_ne_remonte_jamais(monkeypatch):
    """Comportement historique à préserver : ce job ne doit jamais faire
    tomber APScheduler, quelle que soit la panne."""
    import db.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session_local())

    async def _fake_init(session):
        raise ConnectionError("db down")

    monkeypatch.setattr("ml.drift_detector.initialize_drift_detector", _fake_init)

    await jobs.job_drift_check()  # ne doit pas lever
