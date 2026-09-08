"""
Tests du RE-GEL du pronostic juste avant le verrou T-10.

Régression protégée — Auteuil 08/09/2026 R1C8 (départ 16:13 UTC) : le dernier
pronostic datait de 15:45, soit T-28, parce que le recalcul est porté par le cycle
de scrape (navigateur compris, ~20 min en pratique). Le plan a donc été figé sur
une cote de 5,1 pour le n°1 du classement, alors qu'elle valait 8,2 à T-10 et 10,0
au départ — à 5,1 le moteur écarte ce cheval (EV −7 %), à 8,2 il le joue (EV +49 %).
Il a gagné.

Invariants vérifiés ici :
  1. la fenêtre de re-gel reste AVANT le verrou (elle ne le repousse jamais) ;
  2. une course n'est re-gelée qu'une fois ;
  3. le jeu de courses déjà traitées se vide au changement de journée ;
  4. un échec de prédiction ne fait pas tomber la boucle.
"""
import asyncio

import pytest

from scraper import orchestrator as orch_mod
from scraper.orchestrator import BlackTurfOrchestrator


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Session asynchrone minimale : renvoie les course_id programmés."""

    def __init__(self, rows, vu):
        self._rows = rows
        self._vu = vu

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        self._vu.append((str(stmt), params))
        return _FakeResult(self._rows)


def _brancher(monkeypatch, rows, predits, *, echoue=False):
    """Branche une fausse base + un faux `predict_course` sur l'orchestrateur."""
    vu: list = []
    monkeypatch.setattr(orch_mod, "AsyncSessionLocal", lambda: _FakeSession(rows, vu))

    async def _predict(cid):
        predits.append(cid)
        if echoue:
            raise RuntimeError("modèle indisponible")
        return True

    import ml.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "predict_course", _predict)
    return vu


def test_fenetre_bornee_avant_le_verrou(monkeypatch):
    """La borne basse vaut le verrou : une course déjà dans les 10 dernières
    minutes n'est jamais re-pronostiquée."""
    vu = _brancher(monkeypatch, rows=[], predits=[])
    orch = BlackTurfOrchestrator()

    asyncio.run(orch.run_regel_pronos())

    assert vu, "la requête de sélection doit être exécutée"
    _sql, params = vu[0]
    assert params["borne_basse"] == orch_mod.PRONO_LOCK_MIN * 60
    assert params["borne_haute"] == orch_mod.PRONO_LOCK_MIN * 60 + orch_mod.REGEL_WINDOW_S
    assert params["borne_haute"] > params["borne_basse"]
    # Une fenêtre plus étroite que la cadence laisserait passer des courses.
    assert orch_mod.REGEL_TICK_S <= orch_mod.REGEL_WINDOW_S


def test_une_seule_fois_par_course(monkeypatch):
    predits: list = []
    _brancher(monkeypatch, rows=[("C1",), ("C2",)], predits=predits)
    orch = BlackTurfOrchestrator()

    asyncio.run(orch.run_regel_pronos())
    asyncio.run(orch.run_regel_pronos())   # la course est encore dans la fenêtre

    assert predits == ["C1", "C2"], "le re-gel ne doit pas se répéter à chaque tick"


def test_reset_au_changement_de_jour(monkeypatch):
    predits: list = []
    _brancher(monkeypatch, rows=[("C1",)], predits=predits)
    orch = BlackTurfOrchestrator()

    monkeypatch.setattr(orch_mod, "jour_courses", lambda: "2026-09-08")
    asyncio.run(orch.run_regel_pronos())
    monkeypatch.setattr(orch_mod, "jour_courses", lambda: "2026-09-09")
    asyncio.run(orch.run_regel_pronos())

    assert predits == ["C1", "C1"], "le lendemain, la mémoire des courses doit repartir à zéro"


def test_echec_de_prediction_ne_propage_pas(monkeypatch):
    """Le prono précédent doit rester en place ; la boucle ne doit pas mourir."""
    predits: list = []
    _brancher(monkeypatch, rows=[("C1",)], predits=predits, echoue=True)
    orch = BlackTurfOrchestrator()

    asyncio.run(orch.run_regel_pronos())   # ne doit pas lever

    assert predits == ["C1"]


def test_cycle_de_predictions_respecte_le_verrou():
    """Le cycle porté par le scrape s'arrêtait à T-5 et pouvait donc changer un
    prono APRÈS l'instant de gel affiché à l'utilisateur."""
    import inspect

    src = inspect.getsource(BlackTurfOrchestrator.run_predictions_cycle)
    assert "interval '5 minutes'" not in src
    assert "make_interval(mins => :lock)" in src
