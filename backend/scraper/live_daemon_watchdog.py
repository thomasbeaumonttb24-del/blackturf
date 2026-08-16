"""Watchdog synchrone pour les daemons de cotes lancés par systemd.

Ces daemons utilisent des navigateurs synchrones : si le driver se fige, leur
boucle principale ne peut ni lever une exception ni mettre à jour son état.
Le contrôle doit donc vivre dans un vrai thread et forcer la sortie du process ;
les unités systemd ``Restart=always`` se chargent ensuite du redémarrage propre.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable


class CycleWatchdog:
    """Surveille la durée d'un cycle et publie un heartbeat à chaque fin."""

    def __init__(
        self,
        *,
        name: str,
        timeout_s: int,
        grace_s: int,
        heartbeat_path: str,
        log: Callable[..., None],
        check_interval_s: int = 30,
        exit_fn: Callable[[int], object] | None = None,
    ) -> None:
        self.name = name
        self.timeout_s = timeout_s
        self.grace_s = grace_s
        self.heartbeat_path = heartbeat_path
        self.log = log
        self.check_interval_s = max(1, check_interval_s)
        self._exit_fn = exit_fn or os._exit
        self._cycle_started_at: float | None = None

    @property
    def deadline_s(self) -> int:
        return self.timeout_s + self.grace_s

    def begin_cycle(self) -> None:
        self._cycle_started_at = time.monotonic()

    def finish_cycle(self) -> None:
        self._cycle_started_at = None
        self.write_heartbeat()

    def write_heartbeat(self) -> None:
        """Écrit un timestamp Unix ; une erreur de heartbeat reste non fatale."""
        try:
            parent = os.path.dirname(self.heartbeat_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.heartbeat_path, "w") as fh:
                fh.write(str(time.time()))
        except Exception as exc:  # le scraping reste prioritaire
            self.log(f"{self.name}.heartbeat_failed", err=str(exc)[:160])

    def check_once(self) -> None:
        """Tue le process si le cycle courant a dépassé sa deadline."""
        started = self._cycle_started_at
        if started is None:
            return
        elapsed = time.monotonic() - started
        if elapsed > self.deadline_s:
            self.log(
                f"{self.name}.watchdog_kill",
                elapsed_s=int(elapsed),
                deadline_s=self.deadline_s,
            )
            self._exit_fn(1)

    def start(self) -> None:
        """Démarre le thread indépendant de la boucle/browser surveillé."""
        self.write_heartbeat()

        def _loop() -> None:
            while True:
                time.sleep(self.check_interval_s)
                self.check_once()

        threading.Thread(
            target=_loop,
            name=f"{self.name}-cycle-watchdog",
            daemon=True,
        ).start()
        self.log(
            f"{self.name}.watchdog_started",
            timeout_s=self.timeout_s,
            deadline_s=self.deadline_s,
            heartbeat=self.heartbeat_path,
        )
