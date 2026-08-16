"""Preuves ciblées du watchdog des daemons ZEturf/GenyBet."""
from __future__ import annotations

import time
from pathlib import Path

from scraper.live_daemon_watchdog import CycleWatchdog


def _watchdog(tmp_path: Path, *, exit_fn=lambda _code: None) -> CycleWatchdog:
    return CycleWatchdog(
        name="test_daemon",
        timeout_s=10,
        grace_s=2,
        heartbeat_path=str(tmp_path / "heartbeat"),
        log=lambda *_args, **_kwargs: None,
        exit_fn=exit_fn,
    )


def test_fin_cycle_ecrit_un_heartbeat(tmp_path):
    watchdog = _watchdog(tmp_path)
    watchdog.begin_cycle()
    watchdog.finish_cycle()

    heartbeat = tmp_path / "heartbeat"
    assert heartbeat.exists()
    assert abs(float(heartbeat.read_text()) - time.time()) < 2


def test_cycle_termine_ne_declenche_pas_le_kill(tmp_path, monkeypatch):
    exits = []
    watchdog = _watchdog(tmp_path, exit_fn=exits.append)
    watchdog.begin_cycle()
    watchdog.finish_cycle()
    monkeypatch.setattr(time, "monotonic", lambda: 10_000)

    watchdog.check_once()

    assert exits == []


def test_cycle_bloque_declenche_le_kill_apres_timeout_et_grace(tmp_path, monkeypatch):
    exits = []
    watchdog = _watchdog(tmp_path, exit_fn=exits.append)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    watchdog.begin_cycle()
    monkeypatch.setattr(time, "monotonic", lambda: 112.1)

    watchdog.check_once()

    assert exits == [1]


def test_heartbeat_non_ecrivable_reste_non_fatal(tmp_path):
    impossible = tmp_path / "fichier" / "heartbeat"
    (tmp_path / "fichier").write_text("pas un dossier")
    logs = []
    watchdog = CycleWatchdog(
        name="test_daemon",
        timeout_s=10,
        grace_s=2,
        heartbeat_path=str(impossible),
        log=lambda event, **kv: logs.append((event, kv)),
    )

    watchdog.write_heartbeat()

    assert logs[0][0] == "test_daemon.heartbeat_failed"


def test_les_deux_daemons_branchent_le_watchdog():
    scraper_dir = Path(__file__).parents[1] / "scraper"
    for filename in ("zeturf_live_daemon.py", "genybet_live_daemon.py"):
        source = (scraper_dir / filename).read_text(encoding="utf-8")
        assert "_watchdog.start()" in source
        assert "_watchdog.begin_cycle()" in source
        assert "_watchdog.finish_cycle()" in source
