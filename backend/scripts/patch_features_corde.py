"""
patch_features_corde.py — Réécrit les SEULES clés de corde des vecteurs
`features_ml` déjà stockés, après le rattrapage des stalles
(scripts/backfill_numero_corde.py).

POURQUOI PAS recompute_features_prerace.py / force_recompute_features.py :
  • force_recompute stampe `computed_at = now()` : toute la cohorte passe du
    mauvais côté du garde anti-fuite `computed_at < date_heure` et sort de
    l'entraînement, sans erreur ;
  • recompute_prerace recalcule TOUT le vecteur. Or l'ELO y est lu en
    `COALESCE(p.elo_avant_*, ch.elo_score_*)` et l'instantané `elo_avant_*` manque
    de juin à début septembre 2026 : le recalcul y injecterait l'ELO d'AUJOURD'HUI,
    qui connaît les arrivées postérieures (fuite, ~57 000 lignes).
Ici on ne touche que `draw_bias_score` et `draw_bias_relatif`, calculés par le
MÊME chemin que le live (`ml.features.charger_biais_corde` + `traits_corde`), sur
les seules courses terminées STRICTEMENT antérieures à chaque course. `computed_at`
n'est jamais modifié. Chaque ancienne valeur est consignée dans `--journal` (retour
arrière : réappliquer la colonne « ancien » du journal).

    python scripts/patch_features_corde.py --dry-run --limite 20
    python scripts/patch_features_corde.py --depuis 2025-09-01 --journal /tmp/patch_corde.csv
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf"
)

from sqlalchemy import text  # noqa: E402

from ml.features import charger_biais_corde, traits_corde  # noqa: E402

CLES = ("draw_bias_score", "draw_bias_relatif")


async def vecteurs_corde_course(session, course_id: str) -> dict[str, dict]:
    """{participation_id: {draw_bias_score, draw_bias_relatif}} pour une course,
    exactement comme `_load_course_batch_data` + `_compute_features_from_batch`."""
    meta = (await session.execute(text("""
        SELECT hippodrome_nom, discipline, distance, date_heure
        FROM courses WHERE course_id = :cid
    """), {"cid": course_id})).first()
    if not meta:
        return {}
    parts = (await session.execute(text("""
        SELECT participation_id, numero, numero_corde FROM participations
        WHERE course_id = :cid AND non_partant = false
    """), {"cid": course_id})).all()
    if not parts:
        return {}
    zones, pente = await charger_biais_corde(session, meta[0], meta[1], meta[2], meta[3])
    stalles = sorted(int(p[2]) for p in parts if p[2] is not None)
    return {p[0]: traits_corde(p[2], stalles, zones, pente) for p in parts}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depuis", default="2025-09-01")
    ap.add_argument("--disciplines", default="Plat")
    ap.add_argument("--limite", type=int, default=100_000)
    ap.add_argument("--journal", default=None, help="CSV pid;course;ancien;nouveau")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db.database import AsyncSessionLocal

    plancher = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    discs = [d.strip() for d in args.disciplines.split(",") if d.strip()]
    async with AsyncSessionLocal() as s:
        cids = [r[0] for r in (await s.execute(text("""
            SELECT c.course_id FROM courses c
            WHERE c.statut = 'termine' AND c.date_heure >= :depuis
              AND c.discipline = ANY(:discs)
              AND EXISTS (SELECT 1 FROM participations p
                          WHERE p.course_id = c.course_id AND p.numero_corde IS NOT NULL)
            ORDER BY c.date_heure
            LIMIT :limite
        """), {"depuis": plancher, "discs": discs, "limite": args.limite})).all()]
    print(f"[patch-corde] {len(cids)} courses {discs} depuis {args.depuis} "
          f"(dry_run={args.dry_run})", flush=True)

    fj = open(args.journal, "a", encoding="utf-8") if args.journal else None
    t0 = time.monotonic()
    n_lignes = n_non_nul = n_sans_vecteur = 0
    try:
        for i, cid in enumerate(cids, 1):
            async with AsyncSessionLocal() as s:
                vec = await vecteurs_corde_course(s, cid)
                if not vec:
                    continue
                anciens = dict((await s.execute(text("""
                    SELECT participation_id, features->'draw_bias_score'
                    FROM features_ml WHERE participation_id = ANY(:pids)
                """), {"pids": list(vec)})).all())
                for pid, traits in vec.items():
                    if pid not in anciens:
                        n_sans_vecteur += 1
                        continue
                    if not args.dry_run:
                        # `||` remplace ces deux clés et laisse les ~200 autres
                        # intactes ; `computed_at` n'est pas dans le SET.
                        await s.execute(text("""
                            UPDATE features_ml
                               SET features = features || CAST(:patch AS jsonb)
                             WHERE participation_id = :pid
                        """), {"patch": json.dumps(traits), "pid": pid})
                    n_lignes += 1
                    if traits["draw_bias_score"] or traits["draw_bias_relatif"]:
                        n_non_nul += 1
                    if fj:
                        fj.write(f"{pid};{cid};{anciens[pid]};{traits['draw_bias_score']};"
                                 f"{traits['draw_bias_relatif']}\n")
                if not args.dry_run:
                    await s.commit()
            if i % 200 == 0:
                if fj:
                    fj.flush()
                print(f"  … {i}/{len(cids)} courses · {n_lignes} vecteurs · {n_non_nul} non nuls "
                      f"· {time.monotonic() - t0:.0f}s", flush=True)
    finally:
        if fj:
            fj.close()
    print(f"[patch-corde] TERMINÉ en {time.monotonic() - t0:.0f}s — {n_lignes} vecteurs "
          f"patchés, {n_non_nul} non nuls, {n_sans_vecteur} partants sans vecteur", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
