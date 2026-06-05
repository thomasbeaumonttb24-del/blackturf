"""
Tests mode starter de l'orchestrator (env : désactivation sources + ralentissement).
"""
import pytest

from scraper.orchestrator import BlackTurfOrchestrator


def test_sources_desactivees(monkeypatch):
    monkeypatch.setenv("SCRAPER_DISABLED_SOURCES", "geny, racing_post ,FRANCE_GALOP")
    monkeypatch.delenv("SCRAPER_INTERVAL_MULTIPLIER", raising=False)
    orch = BlackTurfOrchestrator()
    assert orch._disabled == {"geny", "racing_post", "france_galop"}
    assert orch._should_run("geny") is False
    assert orch._should_run("france_galop") is False
    assert orch._should_run("pmu") is True   # non désactivée, jamais scrapée → due


def test_multiplicateur_ralentit(monkeypatch):
    monkeypatch.setenv("SCRAPER_INTERVAL_MULTIPLIER", "2.0")
    monkeypatch.delenv("SCRAPER_DISABLED_SOURCES", raising=False)
    orch = BlackTurfOrchestrator()
    assert orch._intervals["pmu"] == 360      # 180 × 2
    assert orch._intervals["geny"] == 1200    # 600 × 2


def test_multiplicateur_jamais_plus_agressif(monkeypatch):
    monkeypatch.setenv("SCRAPER_INTERVAL_MULTIPLIER", "0.3")  # < 1 → ignoré
    orch = BlackTurfOrchestrator()
    assert orch._intervals["pmu"] == 180      # inchangé (clamp à 1.0)


def test_multiplicateur_invalide_fallback(monkeypatch):
    monkeypatch.setenv("SCRAPER_INTERVAL_MULTIPLIER", "abc")
    orch = BlackTurfOrchestrator()
    assert orch._intervals["pmu"] == 180


def test_defaut_aucune_source_desactivee(monkeypatch):
    monkeypatch.delenv("SCRAPER_DISABLED_SOURCES", raising=False)
    monkeypatch.delenv("SCRAPER_INTERVAL_MULTIPLIER", raising=False)
    orch = BlackTurfOrchestrator()
    assert orch._disabled == set()
    assert orch._should_run("pmu") is True
