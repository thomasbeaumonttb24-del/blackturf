"""
Tests de l'anti-gel du daemon de scraping.

Régression protégée : le 2026-08-11 à 22:59 le daemon s'est figé dans
run_bookmakers_cycle (page Playwright bloquée, AUCUNE exception). Le process est
resté « Up », le try/except de run_daemon n'a rien vu, et la base n'a plus reçu
une seule course pendant 4 j 16 h. Un cycle doit désormais être BORNÉ dans le
temps, et le gel doit être VISIBLE (heartbeat).
"""
import asyncio
import os
import time

import pytest

from scraper import orchestrator as orch_mod
from scraper.healthcheck import main as healthcheck_main


# ── Heartbeat ────────────────────────────────────────────────────────────────

def test_heartbeat_ecrit_un_timestamp(tmp_path, monkeypatch):
    hb = tmp_path / "sub" / "hb"
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", str(hb))

    orch_mod._write_heartbeat()

    assert hb.exists(), "le heartbeat doit créer son dossier parent"
    assert abs(float(hb.read_text()) - time.time()) < 5


def test_heartbeat_illisible_ne_leve_pas(monkeypatch):
    # Un heartbeat raté (volume plein, droits) ne doit JAMAIS tuer le scraping.
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", "/proc/nope/interdit")
    orch_mod._write_heartbeat()  # ne doit pas lever


# ── Healthcheck ──────────────────────────────────────────────────────────────

def test_healthcheck_ok_si_heartbeat_frais(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    hb.write_text(str(time.time()))
    monkeypatch.setattr("scraper.healthcheck.HEARTBEAT_PATH", str(hb))
    monkeypatch.setattr("scraper.healthcheck.MAX_AGE_S", 2700)

    assert healthcheck_main() == 0


def test_healthcheck_ko_si_heartbeat_perime(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    # Le scénario du 11/08 : dernier cycle il y a 4 jours.
    hb.write_text(str(time.time() - 4 * 86400))
    monkeypatch.setattr("scraper.healthcheck.HEARTBEAT_PATH", str(hb))
    monkeypatch.setattr("scraper.healthcheck.MAX_AGE_S", 2700)

    assert healthcheck_main() == 1


def test_healthcheck_ko_si_heartbeat_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.healthcheck.HEARTBEAT_PATH",
                        str(tmp_path / "jamais_ecrit"))
    assert healthcheck_main() == 1


def test_healthcheck_ko_si_heartbeat_corrompu(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    hb.write_text("pas-un-float")
    monkeypatch.setattr("scraper.healthcheck.HEARTBEAT_PATH", str(hb))
    assert healthcheck_main() == 1


# ── Bornage du cycle ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cycle_bloque_est_annule_et_la_boucle_continue(tmp_path, monkeypatch):
    """LE test de la régression : un run_once qui ne rend jamais la main ne doit
    plus figer le daemon — il est annulé et le cycle suivant repart."""
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", str(tmp_path / "hb"))
    monkeypatch.setattr(orch_mod, "CYCLE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(orch_mod, "_start_cycle_watchdog", lambda: None)

    orch = orch_mod.BlackTurfOrchestrator()
    cycles = {"n": 0}

    async def _run_once_qui_gele():
        cycles["n"] += 1
        await asyncio.sleep(3600)  # le hang Playwright du 11/08

    monkeypatch.setattr(orch, "run_once", _run_once_qui_gele)

    # 3 sleeps inter-cycles ≈ 3 cycles, puis on sort de la boucle infinie.
    sleeps = {"n": 0}
    real_sleep = asyncio.sleep

    async def _fake_inter_cycle_sleep(_s):
        sleeps["n"] += 1
        if sleeps["n"] >= 3:
            raise KeyboardInterrupt
        await real_sleep(0)

    monkeypatch.setattr(orch_mod.asyncio, "sleep", _fake_inter_cycle_sleep)
    try:
        with pytest.raises(KeyboardInterrupt):
            await orch.run_daemon(interval_minutes=5)
    finally:
        monkeypatch.setattr(orch_mod.asyncio, "sleep", real_sleep)

    assert cycles["n"] >= 2, "la boucle doit relancer un cycle après un gel"


@pytest.mark.asyncio
async def test_cycle_normal_ecrit_le_heartbeat(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", str(hb))
    monkeypatch.setattr(orch_mod, "_start_cycle_watchdog", lambda: None)

    orch = orch_mod.BlackTurfOrchestrator()

    async def _run_once_ok():
        return None

    monkeypatch.setattr(orch, "run_once", _run_once_ok)

    real_sleep = asyncio.sleep

    async def _stop(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr(orch_mod.asyncio, "sleep", _stop)
    try:
        with pytest.raises(KeyboardInterrupt):
            await orch.run_daemon(interval_minutes=5)
    finally:
        monkeypatch.setattr(orch_mod.asyncio, "sleep", real_sleep)

    assert abs(float(hb.read_text()) - time.time()) < 5


@pytest.mark.asyncio
async def test_exception_de_cycle_ne_casse_pas_la_boucle(tmp_path, monkeypatch):
    """Comportement historique à préserver : une source qui lève n'arrête rien."""
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", str(tmp_path / "hb"))
    monkeypatch.setattr(orch_mod, "_start_cycle_watchdog", lambda: None)

    orch = orch_mod.BlackTurfOrchestrator()
    cycles = {"n": 0}

    async def _run_once_qui_leve():
        cycles["n"] += 1
        raise RuntimeError("pmu down")

    monkeypatch.setattr(orch, "run_once", _run_once_qui_leve)

    sleeps = {"n": 0}
    real_sleep = asyncio.sleep

    async def _fake_sleep(_s):
        sleeps["n"] += 1
        if sleeps["n"] >= 3:
            raise KeyboardInterrupt
        await real_sleep(0)

    monkeypatch.setattr(orch_mod.asyncio, "sleep", _fake_sleep)
    try:
        with pytest.raises(KeyboardInterrupt):
            await orch.run_daemon(interval_minutes=5)
    finally:
        monkeypatch.setattr(orch_mod.asyncio, "sleep", real_sleep)

    assert cycles["n"] >= 2


@pytest.mark.asyncio
async def test_cycle_started_at_remis_a_zero(tmp_path, monkeypatch):
    """Si le marqueur restait armé après un cycle sain, le watchdog tuerait un
    process parfaitement vivant au bout de 22 min."""
    monkeypatch.setattr(orch_mod, "HEARTBEAT_PATH", str(tmp_path / "hb"))
    monkeypatch.setattr(orch_mod, "_start_cycle_watchdog", lambda: None)

    orch = orch_mod.BlackTurfOrchestrator()
    monkeypatch.setattr(orch, "run_once", lambda: asyncio.sleep(0))

    real_sleep = asyncio.sleep

    async def _stop(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr(orch_mod.asyncio, "sleep", _stop)
    try:
        with pytest.raises(KeyboardInterrupt):
            await orch.run_daemon(interval_minutes=5)
    finally:
        monkeypatch.setattr(orch_mod.asyncio, "sleep", real_sleep)

    assert orch_mod._cycle_started_at is None


# ── Watchdog thread (dernier rempart) ────────────────────────────────────────

def test_watchdog_tue_le_process_si_le_cycle_depasse(monkeypatch):
    """Le cas où wait_for LUI-MÊME se bloque (annulation impossible, Playwright).
    Seul un thread peut encore agir : la boucle asyncio, elle, est morte."""
    monkeypatch.setattr(orch_mod, "CYCLE_TIMEOUT_S", 0)
    monkeypatch.setattr(orch_mod, "WATCHDOG_GRACE_S", 0)
    tue = {}

    def _fake_exit(code):
        # Le vrai os._exit ne rend jamais la main ; ici on simule sa sortie par
        # une exception, sinon la boucle du watchdog tournerait à l'infini.
        tue["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(orch_mod.os, "_exit", _fake_exit)
    # Le watchdog ne se réveille que toutes les 30 s → on court-circuite l'attente.
    monkeypatch.setattr(orch_mod.time, "sleep", lambda _s: None)
    # Cycle démarré « il y a longtemps » = gelé.
    monkeypatch.setattr(orch_mod, "_cycle_started_at", time.monotonic() - 9999)

    started = []
    monkeypatch.setattr(orch_mod.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    orch_mod._start_cycle_watchdog()
    with pytest.raises(SystemExit):
        started[0]()  # exécute la boucle du watchdog dans CE thread

    assert tue.get("code") == 1


def test_watchdog_ne_tue_pas_hors_cycle(monkeypatch):
    """_cycle_started_at à None = daemon au repos entre deux cycles."""
    monkeypatch.setattr(orch_mod, "_cycle_started_at", None)
    tue = {}
    monkeypatch.setattr(orch_mod.os, "_exit", lambda code: tue.setdefault("code", code))

    tours = {"n": 0}

    def _sleep_borne(_s):
        tours["n"] += 1
        if tours["n"] > 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(orch_mod.time, "sleep", _sleep_borne)

    started = []
    monkeypatch.setattr(orch_mod.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    orch_mod._start_cycle_watchdog()
    with pytest.raises(KeyboardInterrupt):
        started[0]()

    assert "code" not in tue


def test_watchdog_ne_tue_pas_un_cycle_dans_les_temps(monkeypatch):
    monkeypatch.setattr(orch_mod, "CYCLE_TIMEOUT_S", 1200)
    monkeypatch.setattr(orch_mod, "WATCHDOG_GRACE_S", 120)
    monkeypatch.setattr(orch_mod, "_cycle_started_at", time.monotonic() - 300)  # 5 min
    tue = {}
    monkeypatch.setattr(orch_mod.os, "_exit", lambda code: tue.setdefault("code", code))

    tours = {"n": 0}

    def _sleep_borne(_s):
        tours["n"] += 1
        if tours["n"] > 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(orch_mod.time, "sleep", _sleep_borne)

    started = []
    monkeypatch.setattr(orch_mod.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _self: started.append(kw["target"])})())
    orch_mod._start_cycle_watchdog()
    with pytest.raises(KeyboardInterrupt):
        started[0]()

    assert "code" not in tue


# ── Configuration ────────────────────────────────────────────────────────────

def test_timeout_par_defaut_laisse_de_la_marge():
    """Cycle complet mesuré en prod : 2,5 à 6 min. Le défaut doit garder ~3×."""
    assert orch_mod.CYCLE_TIMEOUT_S >= 900
    assert orch_mod.WATCHDOG_GRACE_S > 0


def test_max_age_healthcheck_superieur_au_pire_cas_legitime():
    """Sinon le conteneur clignote unhealthy alors qu'il tourne normalement.
    Pire cas légitime = timeout cycle + grâce watchdog + redémarrage + 1 cycle."""
    import scraper.healthcheck as hc
    pire_cas = orch_mod.CYCLE_TIMEOUT_S + orch_mod.WATCHDOG_GRACE_S + 60 + 360
    assert hc.MAX_AGE_S > pire_cas
