"""Le retrain nocturne se relance seul s'il meurt sans conclure.

Nuit du 06→07/10/2026 : un reboot de maintenance programmé à 02:00 UTC a tué le
retrain 4 s après son départ. Le trigger de 02:00 ne tire qu'une fois, et le
scheduler oublie à son redémarrage ce qu'il a manqué : sans rattrapage, le
modèle et ses 28 apprentissages restaient sur la veille jusqu'à la nuit
suivante.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.jobs import (
    RATTRAPAGE_RETRAIN_MAX,
    decision_rattrapage_retrain,
)

MATIN = datetime(2026, 10, 7, 4, 15, tzinfo=timezone.utc)


def _run(statut, quand):
    return {"step": "retrain", "last_status": statut, "last_attempt_at": quand}


def _decide(run, **kw):
    params = {"bail_actif": False, "en_file": False, "deja_relances": 0}
    params.update(kw)
    return decision_rattrapage_retrain(run, MATIN, **params)


def test_retrain_tue_par_un_reboot_est_relance():
    """LE cas du 07/10 : « en_cours » depuis 02:00:02, plus aucun bail vivant."""
    run = _run("en_cours", datetime(2026, 10, 7, 2, 0, 2, tzinfo=timezone.utc))
    assert _decide(run) == "relancer"


def test_retrain_jamais_parti_cette_nuit_est_relance():
    """Scheduler arrêté à 02:00 : dernière tentative = la veille."""
    run = _run("ok", datetime(2026, 10, 6, 2, 0, 1, tzinfo=timezone.utc))
    assert _decide(run) == "relancer"
    assert _decide(None) == "relancer"


def test_retrain_conclu_n_est_jamais_relance():
    quand = datetime(2026, 10, 7, 2, 0, 1, tzinfo=timezone.utc)
    assert _decide(_run("ok", quand)) == "fait"


def test_echec_applicatif_n_est_pas_relance_en_boucle():
    """Une exception se reproduirait à l'identique : le rapport la signale."""
    quand = datetime(2026, 10, 7, 2, 0, 1, tzinfo=timezone.utc)
    assert _decide(_run("echec", quand)) == "fait"


def test_retrain_vivant_n_est_jamais_double():
    """Deux retrains simultanés = 3 Gio : l'OOM qu'on a mis deux mois à chasser."""
    run = _run("en_cours", datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc))
    assert _decide(run, bail_actif=True) == "en_cours"
    assert _decide(run, en_file=True) == "en_cours"


def test_plafond_de_relances_par_nuit():
    run = _run("en_cours", datetime(2026, 10, 7, 2, 0, 2, tzinfo=timezone.utc))
    assert _decide(run, deja_relances=RATTRAPAGE_RETRAIN_MAX) == "plafond"
    assert _decide(run, deja_relances=RATTRAPAGE_RETRAIN_MAX - 1) == "relancer"


def test_tentative_juste_avant_02h_compte_pour_la_nuit():
    """Même tolérance d'une heure que le rapport du matin."""
    quand = datetime(2026, 10, 7, 1, 59, 30, tzinfo=timezone.utc)
    assert _decide(_run("ok", quand)) == "fait"


def test_le_rattrapage_est_planifie_dans_la_fenetre_de_nuit(monkeypatch):
    from unittest.mock import MagicMock

    from services import jobs

    faux = MagicMock()
    monkeypatch.setattr(jobs, "get_scheduler", lambda: faux)
    jobs.start_scheduler()
    appels = {c.kwargs.get("id"): c for c in faux.add_job.call_args_list}
    assert "rattrapage_retrain" in appels
    trigger = appels["rattrapage_retrain"].args[1]
    champs = {f.name: str(f) for f in trigger.fields}
    assert champs["hour"] == "2-6"
    assert champs["minute"] == "15,45"
    assert str(trigger.timezone) == "UTC"


@pytest.mark.asyncio
async def test_le_rattrapage_ne_casse_jamais_le_scheduler(monkeypatch):
    from ml import learning_steps
    from services import jobs

    async def _explose(*_a, **_k):
        raise RuntimeError("base injoignable")

    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    import db.database as dbmod
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _S())
    monkeypatch.setattr(learning_steps, "dernier_run", _explose)
    await jobs.job_rattrapage_retrain()      # ne doit pas lever
