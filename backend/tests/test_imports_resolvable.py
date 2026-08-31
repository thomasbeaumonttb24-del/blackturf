"""Tout import interne doit exister réellement.

Pourquoi ce test (incident du 2026-08-18) : deux appels enveloppés dans un
``try/except Exception`` référençaient des noms absents du module cible —
``services.alerts.notify_resultats_course`` et ``api.config.settings`` (le
projet expose ``get_settings()``, pas d'instance ``settings``). L'exception
était avalée et seulement journalisée en warning : la fonctionnalité était
silencieusement morte en production (aucun plan de mise figé, aucun plafond
d'exposition appliqué) alors que la suite passait au vert, parce qu'aucun test
n'exerçait ces branches.

Un contrôle statique attrape ce cas sans avoir à exécuter chaque chemin : on
vérifie que chaque ``from <module_interne> import <nom>`` désigne un nom
réellement défini par le module importé.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import pathlib

import pytest


BACKEND = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                       or pathlib.Path(__file__).resolve().parents[1])
PAQUETS_INTERNES = {"services", "ml", "api", "db", "scraper", "scripts"}
IGNORES = ("__pycache__", ".venv", "site-packages")


def _noms_exportes(chemin: pathlib.Path) -> set[str]:
    """Noms qu'un module définit au niveau supérieur (def/class/assign/import)."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    noms: set[str] = set()

    def _cibles(cible: ast.expr) -> None:
        """Enregistre une cible d'affectation, y compris le dépaquetage de tuple
        (``T_MIN, T_MAX = 0.6, 2.0`` définit bien DEUX noms exportés)."""
        if isinstance(cible, ast.Name):
            noms.add(cible.id)
        elif isinstance(cible, (ast.Tuple, ast.List)):
            for element in cible.elts:
                _cibles(element)

    for node in ast.walk(arbre):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms.add(node.name)
        elif isinstance(node, ast.Assign):
            for cible in node.targets:
                _cibles(cible)
        elif isinstance(node, ast.AnnAssign):
            _cibles(node.target)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            noms.update(a.asname or a.name.split(".")[0] for a in node.names)
    return noms


def _fichiers_source() -> list[pathlib.Path]:
    return [p for p in sorted(BACKEND.rglob("*.py"))
            if not any(x in str(p) for x in IGNORES)]


def test_tous_les_imports_internes_designent_un_nom_existant():
    manquants: list[str] = []
    for fichier in _fichiers_source():
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(arbre):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.split(".")[0] not in PAQUETS_INTERNES:
                continue
            try:
                spec = importlib.util.find_spec(node.module)
            except (ImportError, ValueError, ModuleNotFoundError):
                continue
            if spec is None:
                manquants.append(
                    f"{fichier.relative_to(BACKEND)}:{node.lineno} → module "
                    f"'{node.module}' introuvable")
                continue
            # Un paquet peut exposer ses sous-modules sans les définir : on ne
            # contrôle que les modules simples, où l'absence est sans ambiguïté.
            if spec.submodule_search_locations or not spec.origin:
                continue
            exportes = _noms_exportes(pathlib.Path(spec.origin))
            for alias in node.names:
                if alias.name != "*" and alias.name not in exportes:
                    manquants.append(
                        f"{fichier.relative_to(BACKEND)}:{node.lineno} → "
                        f"'{node.module}.{alias.name}' n'existe pas")
    assert not manquants, (
        "Imports internes cassés (silencieux si enveloppés dans try/except) :\n  "
        + "\n  ".join(manquants))


@pytest.mark.parametrize("module,nom", [
    # Chemins du plan de mise figé et du plafond d'exposition : entièrement
    # sous try/except, donc invisibles à l'exécution s'ils cassent.
    ("api.config", "get_settings"),
    ("services.bet_plan_snapshots", "record_plan_snapshot"),
    ("services.bet_plan_snapshots", "daily_exposure_total"),
    ("services.bet_plan_snapshots", "subject_hash"),
    ("services.bet_plan_snapshots", "latest_prediction_run_id"),
    ("services.bet_plan_snapshots", "settle_course_plans"),
    ("services.bet_plan_snapshots", "settle_catchup_plans"),
    ("ml.bet_plan_performance", "compute_forward_performance"),
    ("ml.bet_plan_performance", "evaluate_segment_gates"),
    ("ml.bet_plan_performance", "persist_segment_gates"),
    ("ml.bet_plan_performance", "apply_type_gates"),
    ("ml.prediction_snapshots", "build_snapshot_values"),
    ("ml.prediction_snapshots", "persist_snapshot_compat"),
    ("ml.prediction_evaluation", "evaluation_coverage"),
    ("services.mise_calculator", "_apply_correlation_cap"),
    ("services.mise_calculator", "_uncertainty_discount"),
])
def test_symboles_critiques_importables(module, nom):
    """Import RÉEL (pas statique) des symboles dont l'échec serait silencieux."""
    mod = __import__(module, fromlist=[nom])
    assert hasattr(mod, nom), f"{module}.{nom} est introuvable à l'import"
