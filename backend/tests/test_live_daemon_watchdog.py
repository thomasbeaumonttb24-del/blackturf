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
        # La garde de stérilité ne sert à rien si le daemon ne déclare jamais
        # un cycle utile : les deux appels vont ensemble.
        assert "sterile_timeout_s=" in source
        assert "_watchdog.record_progress()" in source


# ─── Garde de stérilité ──────────────────────────────────────────────────────
# Panne du 26/08/2026 : le daemon ZEturf n'a plus écrit une seule cote de 12:55 à
# 18:46, `systemctl` actif et heartbeat de moins d'une minute. Ses cycles
# échouaient VITE (psql expiré, puis `Page.goto` expiré), donc ni la garde de
# durée ni le heartbeat ne pouvaient le voir.


def _watchdog_sterile(tmp_path, *, exit_fn, sterile_timeout_s=900, logs=None):
    return CycleWatchdog(
        name="test_daemon",
        timeout_s=10,
        grace_s=2,
        heartbeat_path=str(tmp_path / "heartbeat"),
        log=(lambda event, **kv: logs.append((event, kv))) if logs is not None
        else (lambda *_a, **_kv: None),
        exit_fn=exit_fn,
        sterile_timeout_s=sterile_timeout_s,
    )


def test_cycles_en_echec_a_repetition_tuent_le_process(tmp_path, monkeypatch):
    """Le heartbeat se pose à CHAQUE fin de cycle, y compris en échec : c'est la
    stérilité — aucun cycle mené à son terme — qui doit déclencher la sortie."""
    logs = []
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)

    class _ProcessTue(Exception):
        """`os._exit` ne rend jamais la main : la sortie doit arrêter la boucle."""

    def _exit(code):
        raise _ProcessTue(code)

    watchdog = _watchdog_sterile(tmp_path, exit_fn=_exit, logs=logs)
    watchdog.record_progress()

    # Cycles qui échouent vite : chacun FINIT, donc chacun écrit un heartbeat.
    tue_a = None
    for instant in range(60, 1200, 60):
        monkeypatch.setattr(time, "monotonic", lambda t=instant: float(t))
        watchdog.begin_cycle()
        watchdog.finish_cycle()          # pas de record_progress : cycle en échec
        try:
            watchdog.check_once()
        except _ProcessTue:
            tue_a = instant
            break

    assert tue_a is not None, "un daemon qui tourne sans rien produire doit être relancé"
    assert 900 < tue_a <= 960, "ni avant le délai de stérilité, ni un cycle trop tard"
    assert (tmp_path / "heartbeat").exists(), "le heartbeat restait frais pendant la panne"
    assert logs[-1][0] == "test_daemon.watchdog_sterile"


def test_cycle_utile_reporte_la_garde_de_sterilite(tmp_path, monkeypatch):
    """Une nuit sans course est saine : le cycle aboutit, il ne produit rien."""
    exits = []
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    watchdog = _watchdog_sterile(tmp_path, exit_fn=exits.append)

    for instant in range(60, 3600, 60):
        monkeypatch.setattr(time, "monotonic", lambda t=instant: float(t))
        watchdog.begin_cycle()
        watchdog.record_progress()
        watchdog.finish_cycle()
        watchdog.check_once()

    assert exits == []


def test_garde_de_sterilite_desarmee_par_defaut(tmp_path, monkeypatch):
    exits = []
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    watchdog = _watchdog(tmp_path, exit_fn=exits.append)   # sans sterile_timeout_s
    monkeypatch.setattr(time, "monotonic", lambda: 100_000.0)

    watchdog.check_once()

    assert exits == []


def test_cycle_bloque_prime_sur_la_sterilite(tmp_path, monkeypatch):
    """Un cycle figé ET stérile ne doit tuer qu'une fois, avec le bon motif."""
    exits, logs = [], []
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    watchdog = _watchdog_sterile(tmp_path, exit_fn=exits.append, logs=logs)
    watchdog.begin_cycle()
    monkeypatch.setattr(time, "monotonic", lambda: 5_000.0)

    watchdog.check_once()

    assert exits == [1]
    assert logs[-1][0] == "test_daemon.watchdog_kill"
