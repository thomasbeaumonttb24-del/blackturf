"""Watchdog synchrone pour les daemons de cotes lancés par systemd.

Ces daemons utilisent des navigateurs synchrones : si le driver se fige, leur
boucle principale ne peut ni lever une exception ni mettre à jour son état.
Le contrôle doit donc vivre dans un vrai thread et forcer la sortie du process ;
les unités systemd ``Restart=always`` se chargent ensuite du redémarrage propre.

DEUX pannes distinctes, deux gardes distinctes :

* le cycle NE REND PLUS LA MAIN (driver figé sur un pipe IPC mort) → la garde de
  durée (`timeout_s` + `grace_s`) le tue ;
* le cycle rend la main VITE, mais en échec, indéfiniment → la garde de
  STÉRILITÉ (`sterile_timeout_s`) le tue. C'est le trou observé le 26/08/2026 sur
  le daemon ZEturf : plus une seule cote écrite de 12:55 à 18:46, alors que
  `systemctl` le donnait actif et que son heartbeat avait moins d'une minute. Un
  cycle qui échoue appelle quand même `finish_cycle()`, donc RAFRAÎCHIT le
  heartbeat : surveiller le heartbeat seul revient à surveiller que le daemon
  tourne, pas qu'il serve à quelque chose.
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
        sterile_timeout_s: int | None = None,
    ) -> None:
        self.name = name
        self.timeout_s = timeout_s
        self.grace_s = grace_s
        self.heartbeat_path = heartbeat_path
        self.log = log
        self.check_interval_s = max(1, check_interval_s)
        self._exit_fn = exit_fn or os._exit
        self._cycle_started_at: float | None = None
        # `None` = garde de stérilité désarmée (le daemon ne sait pas distinguer
        # un cycle utile d'un cycle vide).
        self.sterile_timeout_s = sterile_timeout_s
        self._last_progress_at: float = time.monotonic()

    @property
    def deadline_s(self) -> int:
        return self.timeout_s + self.grace_s

    def begin_cycle(self) -> None:
        self._cycle_started_at = time.monotonic()

    def finish_cycle(self) -> None:
        self._cycle_started_at = None
        self.write_heartbeat()

    def record_progress(self) -> None:
        """Marque un cycle UTILE — à n'appeler que si le daemon a fait son travail.

        « Utile » ne veut pas dire « a écrit une cote » : la nuit, un cycle qui
        parcourt un programme vide est parfaitement sain. C'est l'ABSENCE de
        cycle mené à son terme qui est le symptôme, pas l'absence de données.
        """
        self._last_progress_at = time.monotonic()

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
        """Tue le process si le cycle courant est figé, ou si le daemon est stérile."""
        started = self._cycle_started_at
        if started is not None:
            elapsed = time.monotonic() - started
            if elapsed > self.deadline_s:
                self.log(
                    f"{self.name}.watchdog_kill",
                    elapsed_s=int(elapsed),
                    deadline_s=self.deadline_s,
                )
                self._exit_fn(1)
                return

        if self.sterile_timeout_s is None:
            return
        sterile_s = time.monotonic() - self._last_progress_at
        if sterile_s > self.sterile_timeout_s:
            self.log(
                f"{self.name}.watchdog_sterile",
                sterile_s=int(sterile_s),
                sterile_timeout_s=self.sterile_timeout_s,
            )
            self._exit_fn(1)

    def start(self) -> None:
        """Démarre le thread indépendant de la boucle/browser surveillé."""
        self.write_heartbeat()
        # Le compte à rebours de stérilité part du DÉMARRAGE, pas de l'import :
        # sinon un camoufox lent à ouvrir grignoterait le délai.
        self.record_progress()

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
            sterile_timeout_s=self.sterile_timeout_s,
            heartbeat=self.heartbeat_path,
        )
