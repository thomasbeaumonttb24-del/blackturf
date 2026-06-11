"""
retrain_and_verify.py — Réentraîne le modèle puis VÉRIFIE qu'un modèle sain est actif.

À lancer sur le VPS (là où vivent les données). Enchaîne :
  1. (sauf --skip-train) retrain complet `run_nightly_retraining` (ou incrémental).
  2. Lecture du ModelVersion actif + métriques FIABLES (mêmes garde-fous que le site :
     AUC bornée [0.5,1], ROI masqué si aberrant, précision réelle race_learning_log).
  3. Verdict + CODE DE SORTIE : 0 si modèle sain (AUC ≥ plancher), sinon 1.

Le gate de promotion (`MIN_DEPLOYABLE_AUC`) empêche déjà un modèle sous-aléatoire de
passer actif ; ce script le CONSTATE et échoue bruyamment sinon (utile en CI / cron).

Usage :
    python scripts/retrain_and_verify.py                 # retrain nightly + vérif
    python scripts/retrain_and_verify.py --mode incremental
    python scripts/retrain_and_verify.py --skip-train    # vérifie seulement l'actif
"""
import sys
import os
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from sqlalchemy import select
from db.database import AsyncSessionLocal as async_session
from db.models import ModelVersion
from api.model_metrics import real_model_metrics
from ml.pipeline import (
    MIN_DEPLOYABLE_AUC,
    run_nightly_retraining,
    run_incremental_retraining,
)


def _fmt(x, suffix="", nd=4):
    return "—" if x is None else f"{round(float(x), nd)}{suffix}"


async def _active_model(session) -> ModelVersion | None:
    return (await session.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)  # noqa: E712
        .order_by(ModelVersion.version_num.desc())
    )).scalars().first()


async def _snapshot(session) -> dict:
    """Métriques FIABLES de l'actif (ce que le site afficherait)."""
    mv = await _active_model(session)
    if mv is None:
        return {"mv": None}
    m = await real_model_metrics(session, mv)
    return {
        "mv": mv,
        "version": mv.version_num,
        "synthetique": bool(mv.est_synthetique),
        "nb_courses_train": mv.nb_courses_train,
        "auc_raw": mv.auc_roc,                 # brut en base (peut être aberrant)
        "auc_fiable": m["auc_roc"],            # borné [0.5,1] ou None
        "walk_forward_auc": mv.walk_forward_auc,
        "precision_top3": m["precision_top3"],
        "roi_simule": m["roi_simule"],
        "nb_courses_evaluees": m["nb_courses_evaluees"],
    }


def _print_snapshot(title: str, s: dict) -> None:
    print(f"\n── {title} ──")
    if s.get("mv") is None:
        print("   (aucun modèle actif)")
        return
    print(f"   version            : v{s['version']}{'  [SYNTHÉTIQUE]' if s['synthetique'] else ''}")
    print(f"   courses (train)    : {s['nb_courses_train']}")
    print(f"   AUC brut (base)    : {_fmt(s['auc_raw'])}")
    print(f"   AUC fiable (site)  : {_fmt(s['auc_fiable'])}   (borné [0.5,1], plancher {MIN_DEPLOYABLE_AUC})")
    print(f"   walk-forward AUC   : {_fmt(s['walk_forward_auc'])}")
    print(f"   précision Top-3    : {_fmt(s['precision_top3'])}   (sur {s['nb_courses_evaluees']} courses évaluées)")
    print(f"   ROI simulé         : {_fmt(s['roi_simule'])}")


async def main(skip_train: bool, mode: str) -> int:
    async with async_session() as session:
        before = await _snapshot(session)
    _print_snapshot("AVANT", before)

    if not skip_train:
        print(f"\n>> Retrain ({mode})… (peut être long)")
        try:
            if mode == "incremental":
                await run_incremental_retraining()
            else:
                await run_nightly_retraining()
        except Exception as e:  # noqa: BLE001
            print(f"\nERREUR pendant le retrain : {e}")
            return 3
        print(">> Retrain terminé.")

    async with async_session() as session:
        after = await _snapshot(session)
    _print_snapshot("APRÈS", after)

    print("\n" + "=" * 56)
    if after.get("mv") is None:
        print("ÉCHEC : aucun modèle actif après retrain.")
        return 2

    auc = after["auc_fiable"]
    moved = (not skip_train) and before.get("version") != after.get("version")
    if auc is not None and auc >= MIN_DEPLOYABLE_AUC:
        print(f"OK : modèle actif SAIN (AUC fiable {round(auc, 4)} ≥ {MIN_DEPLOYABLE_AUC}).")
        if not skip_train and not moved:
            print("    Note : aucune nouvelle version promue — l'actif existant est déjà le meilleur.")
        print("=" * 56)
        return 0

    print(f"ATTENTION : modèle actif NON fiable (AUC fiable = {_fmt(auc)} < {MIN_DEPLOYABLE_AUC}).")
    print("   Le site affiche « — » (honnête). Le gate a refusé de promouvoir un modèle cassé.")
    print("   → Probablement pas assez de courses réglées/propres. Backfill des données puis relancer.")
    print("=" * 56)
    return 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--skip-train", action="store_true", help="Vérifie seulement l'actif, sans retrain")
    p.add_argument("--mode", choices=["nightly", "incremental"], default="nightly",
                   help="Type de retrain (défaut : nightly = 18 mois)")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.skip_train, args.mode)))
