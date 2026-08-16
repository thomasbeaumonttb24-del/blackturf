"""
Tests de l'anti-gel du daemon Oddschecker (audit 2026-08-16).

Régression protégée : le daemon s'est figé le 02/08 à 11:01 UTC (driver
Playwright mort — "Connection closed while reading from the driver") et le
process Python est resté vivant, spinnant à 92% CPU EN CONTINU pendant 15 jours
(`systemctl status` : même PID depuis le 01/08). `Restart=always` était déjà
configuré côté systemd mais ne servait à rien : le process ne mourait jamais de
lui-même, il fallait le tuer explicitement.

Le daemon utilise l'API SYNCHRONE de Camoufox (pas d'event loop asyncio à
annuler comme pour l'orchestrator) → seul un watchdog THREAD indépendant peut
détecter le gel et forcer la sortie via os._exit.

`camoufox` ne vit que dans le venv de scraping du VPS (/opt/scrapling_venv), pas
dans le venv de test du backend → on le stub avant l'import du module.
"""
import sys
import time
import types

import pytest


@pytest.fixture
def daemon(monkeypatch):
    """Importe oddschecker_odds_daemon avec `camoufox` stubbé."""
    if "camoufox" not in sys.modules:
        fake_camoufox = types.ModuleType("camoufox")
        fake_sync_api = types.ModuleType("camoufox.sync_api")
        fake_sync_api.Camoufox = object  # jamais instancié dans ces tests
        fake_camoufox.sync_api = fake_sync_api
        monkeypatch.setitem(sys.modules, "camoufox", fake_camoufox)
        monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync_api)

    import scraper.oddschecker_odds_daemon as mod
    return mod


def test_import_ne_leve_pas(daemon):
    """Le simple fait que ce test tourne prouve que le module s'importe
    (aucune erreur de syntaxe/référence introduite par le patch)."""
    assert daemon.CYCLE_TIMEOUT_S > 0


def test_timeout_par_defaut_laisse_de_la_marge(daemon):
    """3x l'intervalle d'énumération normal (300s) — assez pour couvrir une
    fenêtre chargée sans jamais tuer un cycle légitime."""
    assert daemon.CYCLE_TIMEOUT_S == daemon.ENUM_INTERVAL * 3


def test_watchdog_tue_le_process_si_le_cycle_depasse(daemon, monkeypatch):
    monkeypatch.setattr(daemon, "CYCLE_TIMEOUT_S", 0)
    tue = {}

    def _fake_exit(code):
        tue["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(daemon.os, "_exit", _fake_exit)
    monkeypatch.setattr(daemon.time, "sleep", lambda _s: None)
    monkeypatch.setattr(daemon, "_cycle_started_at", time.time() - 9999)

    started = []
    monkeypatch.setattr(daemon.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    daemon._start_watchdog()
    with pytest.raises(SystemExit):
        started[0]()

    assert tue.get("code") == 1


def test_watchdog_ne_tue_pas_avant_le_premier_cycle(daemon, monkeypatch):
    """`_cycle_started_at` à None = daemon pas encore armé (import du module,
    avant `main()`)."""
    monkeypatch.setattr(daemon, "_cycle_started_at", None)
    tue = {}
    monkeypatch.setattr(daemon.os, "_exit", lambda code: tue.setdefault("code", code))

    tours = {"n": 0}
    def _sleep_borne(_s):
        tours["n"] += 1
        if tours["n"] > 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(daemon.time, "sleep", _sleep_borne)

    started = []
    monkeypatch.setattr(daemon.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    daemon._start_watchdog()
    with pytest.raises(KeyboardInterrupt):
        started[0]()

    assert "code" not in tue


def test_watchdog_ne_tue_pas_un_cycle_dans_les_temps(daemon, monkeypatch):
    monkeypatch.setattr(daemon, "CYCLE_TIMEOUT_S", 900)
    monkeypatch.setattr(daemon, "_cycle_started_at", time.time() - 60)  # 1 min

    tue = {}
    monkeypatch.setattr(daemon.os, "_exit", lambda code: tue.setdefault("code", code))

    tours = {"n": 0}
    def _sleep_borne(_s):
        tours["n"] += 1
        if tours["n"] > 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(daemon.time, "sleep", _sleep_borne)

    started = []
    monkeypatch.setattr(daemon.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    daemon._start_watchdog()
    with pytest.raises(KeyboardInterrupt):
        started[0]()

    assert "code" not in tue


def test_main_arme_le_watchdog_avant_douvrir_le_navigateur(daemon, monkeypatch):
    """Le scénario réel du 02/08 : le driver Playwright meurt PENDANT une visite
    de course, mais un hang dans l'ouverture même de Camoufox() doit aussi être
    couvert — le watchdog doit être armé (`_cycle_started_at` posé) AVANT le
    `with Camoufox(...)`, pas seulement dans la boucle `while _run`."""
    calls = []

    class _HangingCamoufox:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            calls.append("enter")
            # Simule le hang : à cet instant _cycle_started_at doit déjà être posé.
            assert daemon._cycle_started_at is not None
            raise KeyboardInterrupt  # coupe le test proprement ici

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(daemon, "Camoufox", _HangingCamoufox)
    monkeypatch.setattr(daemon, "_start_watchdog", lambda: calls.append("watchdog_started"))

    with pytest.raises(KeyboardInterrupt):
        daemon.main()

    assert calls == ["watchdog_started", "enter"]
