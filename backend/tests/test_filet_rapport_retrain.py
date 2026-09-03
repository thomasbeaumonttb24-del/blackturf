"""Le garde-fou du retrain a lui-même besoin d'un garde-fou.

Le rapport du matin (`scripts/check_retrain_nightly.py`) est ce qui empêche un
modèle de rester gelé sans que personne ne le sache — 48 jours en juin-août 2026.
Mais il est lancé par un cron SYSTÈME, hors Docker, et le 2026-08-19 ce cron n'a
jamais tourné : le script n'était pas exécutable. Des semaines sans un seul
e-mail — et l'absence d'e-mail ne fait aucun bruit.

Deux invariants ici :

  - l'issue de la nuit (promu / rejeté) est PERSISTÉE par le retrain lui-même,
    pas seulement journalisée dans un `docker logs` qui disparaît au premier
    déploiement ;
  - un filet dans le scheduler renvoie le rapport si le cron s'est tu, et
    seulement dans ce cas.
"""
import inspect
from datetime import datetime, timedelta, timezone

import pytest


class _SessionFactice:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


@pytest.fixture
def filet(monkeypatch):
    """Le job du scheduler, avec sa session de base neutralisée."""
    import db.database as dbmod
    from services import jobs

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _SessionFactice())
    return jobs.job_filet_rapport_retrain


def _pose_dernier_rapport(monkeypatch, quand):
    from ml import learning_steps

    async def _faux(_session, step):
        assert step == "rapport_retrain"
        return None if quand is None else {"step": step, "last_success_at": quand}

    monkeypatch.setattr(learning_steps, "dernier_run", _faux)


def _capture_envois(monkeypatch):
    envois = []
    import scripts.check_retrain_nightly as rapport

    async def _faux_main(dry_run: bool = False):
        envois.append(dry_run)

    monkeypatch.setattr(rapport, "main", _faux_main)
    return envois


@pytest.mark.asyncio
async def test_le_filet_se_tait_quand_le_cron_a_fait_son_travail(filet, monkeypatch):
    """Deux e-mails chaque matin, c'est un e-mail qu'on cesse de lire."""
    _pose_dernier_rapport(monkeypatch,
                          datetime.now(timezone.utc) - timedelta(hours=2))
    envois = _capture_envois(monkeypatch)
    await filet()
    assert envois == []


@pytest.mark.asyncio
async def test_le_filet_envoie_quand_le_cron_sest_taise(filet, monkeypatch):
    """Panne du 2026-08-19 : plus aucun rapport, et rien pour le signaler."""
    _pose_dernier_rapport(monkeypatch,
                          datetime.now(timezone.utc) - timedelta(hours=30))
    envois = _capture_envois(monkeypatch)
    await filet()
    assert envois == [False], "le filet doit ENVOYER, pas tourner à vide"


@pytest.mark.asyncio
async def test_le_filet_envoie_quand_aucun_rapport_na_jamais_ete_envoye(filet, monkeypatch):
    _pose_dernier_rapport(monkeypatch, None)
    envois = _capture_envois(monkeypatch)
    await filet()
    assert envois == [False]


@pytest.mark.asyncio
async def test_le_filet_marque_son_canal(filet, monkeypatch):
    """Un rapport « filet » deux matins de suite dit que le cron de l'hôte est
    mort — information que le rapport lui-même ne peut pas porter."""
    import os

    monkeypatch.delenv("BT_RAPPORT_CANAL", raising=False)
    _pose_dernier_rapport(monkeypatch, None)
    canaux = []
    import scripts.check_retrain_nightly as rapport

    async def _faux_main(dry_run: bool = False):
        canaux.append(os.getenv("BT_RAPPORT_CANAL"))

    monkeypatch.setattr(rapport, "main", _faux_main)
    await filet()
    assert canaux == ["filet"]


@pytest.mark.asyncio
async def test_le_filet_ne_casse_jamais_le_scheduler(filet, monkeypatch):
    """Le scheduler porte 18 autres jobs : une panne ici ne doit rien emporter."""
    from ml import learning_steps

    async def _explose(*_a, **_k):
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(learning_steps, "dernier_run", _explose)
    await filet()          # ne doit pas lever


def test_le_filet_est_bien_planifie(monkeypatch):
    """Un job non enregistré ne tourne jamais, et rien ne le dit."""
    from unittest.mock import MagicMock

    from services import jobs

    faux = MagicMock()
    monkeypatch.setattr(jobs, "get_scheduler", lambda: faux)
    jobs.start_scheduler()
    ids = [c.kwargs.get("id") for c in faux.add_job.call_args_list]
    assert "filet_rapport_retrain" in ids


def test_le_filet_laisse_une_nuit_de_marge_au_cron():
    """26 h : jamais deux matins de suite sans rapport, jamais de doublon non plus."""
    from services.jobs import FILET_RAPPORT_APRES_H

    assert 24 < FILET_RAPPORT_APRES_H <= 30


# ── L'issue de la nuit est persistée, pas seulement journalisée ─────────────

def test_le_retrain_renvoie_son_issue():
    """`_do_retraining` doit RENVOYER promu / rejeté / insuffisant.

    Tant que cette issue n'existait que dans `log.info(...)`, le rapport du matin
    devait la relire dans `docker logs` — qui ne remonte pas au-delà de
    l'instance courante du conteneur et disparaît au premier déploiement.
    """
    from ml import pipeline

    src = inspect.getsource(pipeline._do_retraining)
    assert '"issue": "promu"' in src
    assert '"issue": "rejete"' in src
    assert '"issue": "insuffisant"' in src
    assert "return _issue" in src


def test_le_motif_du_rejet_nest_calcule_quune_fois():
    """Le log et l'état persistant doivent nommer le MÊME motif.

    Deux expressions séparées finissent toujours par diverger, et le rapport
    afficherait alors un motif que les logs contredisent."""
    from ml import pipeline

    src = inspect.getsource(pipeline._do_retraining)
    assert src.count("below_min_auc") == 1, "motif dupliqué : log et détail vont diverger"
    assert "reason=_raison_rejet" in src


def test_l_issue_est_bien_branchee_sur_l_etape_persistee():
    """Câblage : renvoyer l'issue ne sert à rien si personne ne l'écrit."""
    from ml import pipeline

    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    assert "_e_retrain.detail = await _do_retraining(" in src
