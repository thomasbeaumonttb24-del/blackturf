"""
resettle_place_fix.py — RE-règle les runs déjà 'settled' pour corriger le bug du
Simple/Couplé Placé réglé au rapport du VAINQUEUR au lieu du cheval réellement joué.

Cause (corrigée dans services/bet_settlement.py le 2026-06-15) :
  - `_place_rapport_exact` comparait les combinaisons en CHAÎNES → "08" != "8"
    (numéros zéro-paddés PMU) → match raté → repli sur l'agrégat `rapports[...]`
    qui vaut le rapport du 1er cheval placé (le gagnant). Un Simple Placé sur le
    N°8 (3e, 3.40€) était payé 10.00€ (rapport du N°15 vainqueur).
  - L'agrégat « mauvais cheval » est désormais INTERDIT pour les placés.

Cette passe recharge le PLAN figé + le RÉSULTAT réel de chaque run settled/partial
et relance settle_plan (avec rapports_detail). Si le bilan change, on met à jour
`resultat` + `roi_reel`. 100% déterministe (rejoue le même règlement, code corrigé).
NE régénère PAS le plan : le prono figé reste identique, seul le RÈGLEMENT change.

À lancer sur le VPS (où vit la DB) :
    python scripts/resettle_place_fix.py --dry-run   # compte les runs impactés, n'écrit rien
    python scripts/resettle_place_fix.py             # corrige + recalcule les poids appris
    python scripts/resettle_place_fix.py --no-recompute
"""
import sys
import os
import json
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from sqlalchemy import text
from db.database import AsyncSessionLocal as async_session
from services.bet_settlement import settle_plan
from ml.profil_learning import compute_profil_weights


async def main(dry_run: bool, recompute: bool) -> int:
    # Tous les runs réglés (ou partiels) d'une course terminée avec résultat.
    async with async_session() as session:
        runs = (await session.execute(text("""
            SELECT pl.log_id, pl.course_id, pl.plan, pl.resultat,
                   r.classement, r.rapports, c.nb_partants, r.rapports_detail
            FROM profil_run_log pl
            JOIN courses c   ON c.course_id = pl.course_id
            JOIN resultats r ON r.course_id = pl.course_id
            WHERE pl.statut IN ('settled', 'partial')
              AND r.classement IS NOT NULL
        """))).all()

    print(f"Runs settled/partial à revérifier : {len(runs)}")
    changed = []   # (log_id, old_gain, new_gain)
    updates = []   # (log_id, bilan, roi, statut)

    for log_id, cid, plan, old_res, classement, rapports, nb_partants, rapports_detail in runs:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan or "{}")
        old = old_res if isinstance(old_res, dict) else json.loads(old_res or "{}")
        cl = classement if isinstance(classement, list) else []
        if not plan_d or not cl:
            continue
        bilan = settle_plan(plan_d, cl, rapports or {}, nb_partants or len(cl),
                            rapports_detail or None)
        old_gain = round(float(old.get("total_gain") or 0), 2)
        new_gain = round(float(bilan.get("total_gain") or 0), 2)
        if abs(new_gain - old_gain) > 0.005:
            changed.append((log_id, cid, old_gain, new_gain))
            roi = bilan.get("roi")
            statut = "partial" if bilan.get("en_attente") else "settled"
            updates.append((log_id, json.dumps(bilan),
                            (roi / 100.0) if roi is not None else None, statut))

    print(f"Runs dont le gain change : {len(changed)}")
    for log_id, cid, og, ng in changed[:20]:
        print(f"  {cid}  log {log_id}: gain {og:.2f}€ -> {ng:.2f}€  ({ng - og:+.2f})")
    if len(changed) > 20:
        print(f"  … +{len(changed) - 20} autres")

    if dry_run:
        print("DRY-RUN — aucune écriture.")
        return 0
    if not updates:
        print("Rien à corriger.")
        return 0

    async with async_session() as session:
        for log_id, res_j, roi, statut in updates:
            await session.execute(text("""
                UPDATE profil_run_log
                SET resultat = CAST(:res AS jsonb), roi_reel = :roi,
                    statut = :st, settled_at = now()
                WHERE log_id = :id
            """), {"res": res_j, "roi": roi, "st": statut, "id": log_id})
        await session.commit()
    print(f"Corrigés : {len(updates)} runs.")

    if recompute:
        async with async_session() as session:
            state = await compute_profil_weights(session)
        print(f"Poids recalculés : {state.get('n_total_runs')} runs settled agrégés.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Compte seulement, n'écrit rien")
    p.add_argument("--no-recompute", dest="recompute", action="store_false",
                   help="Ne pas recalculer les poids appris après correction")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.recompute)))
