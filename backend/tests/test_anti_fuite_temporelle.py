"""Aucune requête d'APPRENTISSAGE ne lit un pronostic postérieur au départ.

Mesure qui motive ce garde-fou (production, 2026-08-31) :

    predictions  : 1 000 lignes / 90 courses écrites APRÈS `courses.date_heure`
    features_ml  : 5 070 lignes (2,3 %) calculées APRÈS le départ

Ces lignes sont légitimes — un recalcul, un backfill, un scraper qui finit après
l'ouverture des portes — mais elles portent de la connaissance du résultat. Une
requête qui les lit pour MESURER ou APPRENDRE produit un chiffre flatteur qui
s'évapore en direct. Le filtre `computed_at < date_heure` / `created_at <
date_heure` est appliqué partout aujourd'hui ; rien ne garantissait qu'il le
reste, et son absence est parfaitement muette : la requête tourne, le chiffre
sort, il est simplement faux.

Ce test relit donc le SQL du dépôt. Une requête qui joint `features_ml` ou
`predictions` à `courses` doit soit porter le filtre, soit se déclarer
explicitement hors périmètre par un commentaire `-- affichage : <raison>` —
l'exception devient alors une décision écrite, pas un oubli.
"""
from __future__ import annotations

import ast
import pathlib
import re

RACINE = pathlib.Path(__file__).resolve().parents[1]
MODULES = ("ml", "api", "services")

GARDE = re.compile(r"(computed_at|created_at)\s*<\s*\w+\.date_heure")
DEROGATION = re.compile(r"--\s*affichage\s*:", re.I)
LIT_UNE_TABLE_SENSIBLE = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:features_ml|predictions)\b", re.I)
JOINT_LES_COURSES = re.compile(r"\b(?:FROM|JOIN)\s+courses\b", re.I)


def _sql_du_depot() -> list[tuple[pathlib.Path, int, str]]:
    """Chaînes littérales ressemblant à du SQL, docstrings exclues.

    Les docstrings décrivent souvent la requête sans la porter (`meta_learner`
    en cite une dans son texte d'aide) : les inclure produisait deux faux
    positifs qui auraient fini par faire ignorer le test.
    """
    trouve: list[tuple[pathlib.Path, int, str]] = []
    for dossier in MODULES:
        for chemin in sorted((RACINE / dossier).rglob("*.py")):
            if "__pycache__" in chemin.parts:
                continue
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            docstrings = {
                id(n.body[0].value)
                for n in ast.walk(arbre)
                if isinstance(n, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)
            }
            for n in ast.walk(arbre):
                if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and id(n) not in docstrings and len(n.value) > 60):
                    trouve.append((chemin, n.lineno, n.value))
    return trouve


def test_toute_lecture_de_pronostic_est_bornee_au_pre_depart():
    manquants: list[str] = []
    for chemin, ligne, sql in _sql_du_depot():
        if not (LIT_UNE_TABLE_SENSIBLE.search(sql) and JOINT_LES_COURSES.search(sql)):
            continue
        if GARDE.search(sql) or DEROGATION.search(sql):
            continue
        manquants.append(f"{chemin.relative_to(RACINE).as_posix()}:{ligne}")

    assert not manquants, (
        "Requêtes joignant `features_ml`/`predictions` à `courses` sans borne "
        "pré-départ :\n  - " + "\n  - ".join(manquants) + "\n\n"
        "Ajouter `AND <alias>.created_at < c.date_heure` (ou `computed_at`), ou — "
        "si la requête ne sert QUE l'affichage et n'alimente aucune mesure — un "
        "commentaire `-- affichage : <raison>` dans le SQL.")


def test_l_entrainement_est_borne_au_pre_depart_par_defaut():
    """`BT_TRAIN_PRERACE_ONLY` gouverne la borne du dataset d'entraînement.

    La requête d'entraînement porte sa borne dans un fragment séparé, activé par
    ce drapeau : le test de lecture du SQL ci-dessus ne peut pas la voir. On
    verrouille donc le DÉFAUT ici. Sans lui, les features recalculées après la
    course (cotes de clôture, stats jockey/entraîneur incluant cette course,
    ELO backfillé) entrent dans l'apprentissage et produisent un gain in-sample
    qui s'évapore en direct.
    """
    import importlib
    import os

    from ml import algo_flags

    ancien = os.environ.pop("BT_TRAIN_PRERACE_ONLY", None)
    try:
        recharge = importlib.reload(algo_flags)
        assert recharge.AlgoFlags().train_prerace_only is True, (
            "BT_TRAIN_PRERACE_ONLY ne vaut plus True par défaut : l'entraînement "
            "lirait les features recalculées après la course.")
    finally:
        if ancien is not None:
            os.environ["BT_TRAIN_PRERACE_ONLY"] = ancien
        importlib.reload(algo_flags)
