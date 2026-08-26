"""Accès base du daemon ZEturf : une expiration ne doit pas passer pour un vide.

Panne du 26/08/2026 : le daemon a cessé d'écrire des cotes de 12:55 à 18:46. Son
premier appel de cycle, `load_blackturf()`, passe par `docker exec … psql` — un
appel qui coûte 0,1 s au repos, mais qui dépassait les 30 s d'origine sous la
charge des camoufox (load 5-6 sur 4 cœurs, 2,4 Go de swap). Chaque cycle lent
mourait donc sur sa première ligne.

Deux invariants sont verrouillés ici :

* une expiration est REPRISE une fois (un pic de charge n'est pas une panne) ;
* si la reprise échoue à son tour, l'appel LÈVE. Rendre une liste vide ferait
  passer une base injoignable pour un programme sans course — et un daemon
  aveugle pour un daemon au repos.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRAPER = Path(__file__).parents[1] / "scraper"


@pytest.fixture
def daemon(monkeypatch):
    """Importe le daemon avec camoufox neutralisé (absent hors du VPS)."""
    faux = types.ModuleType("camoufox")
    sync_api = types.ModuleType("camoufox.sync_api")
    sync_api.Camoufox = object
    faux.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "camoufox", faux)
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", sync_api)
    monkeypatch.syspath_prepend(str(SCRAPER))

    module = importlib.import_module("zeturf_live_daemon")
    monkeypatch.setattr(module, "log", lambda *_a, **_kv: None)
    return module


def _expiration(*_args, **_kwargs):
    raise subprocess.TimeoutExpired(cmd="psql", timeout=60)


def test_une_expiration_isolee_est_reprise(daemon, monkeypatch):
    essais = []

    def _run(cmd, **kwargs):
        essais.append(cmd)
        if len(essais) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)
        return subprocess.CompletedProcess(cmd, 0, stdout="a\x1fb\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    assert daemon.db_query("SELECT 1") == [["a", "b"]]
    assert len(essais) == 2, "un pic de charge doit coûter une reprise, pas le cycle"


def test_base_injoignable_leve_au_lieu_de_rendre_un_vide(daemon, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _expiration)

    with pytest.raises(RuntimeError):
        daemon.db_query("SELECT 1")

    with pytest.raises(RuntimeError):
        daemon.db_exec("UPDATE participations SET cote_unibet = 2.0")


def test_erreur_sql_reste_non_fatale(daemon, monkeypatch):
    """Une requête refusée par PostgreSQL n'est pas une base injoignable : le
    daemon la journalise et continue, comme avant."""
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )

    assert daemon.db_query("SELECT bogus") == []
    assert daemon.db_exec("UPDATE bogus") is False


def test_le_delai_couvre_la_charge_observee(daemon):
    assert daemon.DB_TIMEOUT_S >= 60, (
        "30 s ne suffisaient pas : `docker exec` doit d'abord être ordonnancé, "
        "et la charge des camoufox à elle seule dépassait ce délai le 26/08/2026")
