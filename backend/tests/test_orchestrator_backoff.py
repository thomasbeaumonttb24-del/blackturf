"""
Tests du backoff adaptatif par source de l'orchestrator.

Une source qui échoue de façon répétée doit voir son intervalle effectif
croître exponentiellement (plafonné), pour éviter de la marteler — et donc
de provoquer/aggraver un ban — quand elle est down.
"""
import time

import pytest

from scraper.orchestrator import BlackTurfOrchestrator


@pytest.fixture
def orch(monkeypatch):
    monkeypatch.delenv("SCRAPER_DISABLED_SOURCES", raising=False)
    monkeypatch.delenv("SCRAPER_INTERVAL_MULTIPLIER", raising=False)
    return BlackTurfOrchestrator()


def test_aucun_backoff_par_defaut(orch):
    assert orch._backoff_mult("geny") == 1


def test_echec_incremente_la_serie_et_le_multiplicateur(orch):
    # Simule un cycle où geny a échoué (alimenté normalement par _log_error).
    orch._failed_this_cycle = {"geny"}
    orch._mark_done("geny")
    assert orch._consecutive_errors["geny"] == 1
    assert orch._backoff_mult("geny") == 2  # BACKOFF_BASE ** 1

    # Deuxième échec consécutif → multiplicateur ×4.
    orch._mark_done("geny")
    assert orch._consecutive_errors["geny"] == 2
    assert orch._backoff_mult("geny") == 4


def test_backoff_plafonne(orch):
    orch._consecutive_errors["pmu"] = 50  # série énorme
    assert orch._backoff_mult("pmu") == orch.BACKOFF_MAX_MULT


def test_succes_reinitialise_la_serie(orch):
    orch._consecutive_errors["geny"] = 3
    # Cycle réussi : geny n'est PAS dans le set d'échecs.
    orch._failed_this_cycle = set()
    orch._mark_done("geny")
    assert orch._consecutive_errors["geny"] == 0
    assert orch._backoff_mult("geny") == 1


def test_should_run_respecte_le_backoff(orch):
    base = orch._intervals["pmu"]  # 180 s par défaut
    # Scrapé il y a (base + 20) s : sans backoff, c'est dû.
    orch._last_scrape["pmu"] = time.time() - (base + 20)
    assert orch._should_run("pmu") is True

    # Avec 2 échecs consécutifs → intervalle ×4 : plus dû.
    orch._consecutive_errors["pmu"] = 2
    assert orch._should_run("pmu") is False

    # Après l'intervalle élargi écoulé → de nouveau dû.
    orch._last_scrape["pmu"] = time.time() - (base * orch._backoff_mult("pmu") + 1)
    assert orch._should_run("pmu") is True


def test_source_desactivee_jamais_due_meme_sans_backoff(monkeypatch):
    monkeypatch.setenv("SCRAPER_DISABLED_SOURCES", "geny")
    orch = BlackTurfOrchestrator()
    assert orch._should_run("geny") is False
