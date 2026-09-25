"""
patch_features_elo.py — Réécrit les SEULES clés tirées des deltas ELO dans les
vecteurs `features_ml` déjà stockés : delta_elo_5courses, velocity_elo,
elo_trend_30j, bounce_score, career_momentum.

POURQUOI : jusqu'au 25/09/2026 le chargeur comparait `elo_historique.date_course`
(une DATE) à l'heure de départ ; la ligne ELO de la course calculée passait le
filtre (minuit < 13 h 50). Sans effet en direct (l'ELO se met à jour après
l'arrivée), mais le recalcul complet du 24/09 (recompute_features_prerace
--depuis-jours 400) a réécrit tout l'historique avec le delta du RÉSULTAT : le
cheval au plus fort `velocity_elo` gagnait 44 % des courses, et le modèle v545
promu dans la nuit a appris l'arrivée.

Ici les deltas sont relus avec la borne corrigée (jours STRICTEMENT antérieurs,
jamais la course elle-même, même plafond par cheval que le direct) et passés à
`ml.features.traits_historique_elo`, le calcul même du direct. `computed_at` n'est
jamais modifié. Chaque ancienne valeur est consignée dans `--journal`.

    python scripts/patch_features_elo.py --dry-run --limite 20
    python scripts/patch_features_elo.py --depuis 2025-06-01 --journal /tmp/patch_elo.csv
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

from ml.features import ELO_DELTAS_PAR_CHEVAL, traits_historique_elo  # noqa: E402

CLES = ("delta_elo_5courses", "velocity_elo", "elo_trend_30j", "bounce_score",
        "career_momentum")


async def vecteurs_elo_course(session, course_id: str, jour) -> dict[str, dict]:
    """{participation_id: {5 traits ELO}} pour une course, bornés comme le direct."""
    parts = (await session.execute(text("""
        SELECT participation_id, cheval_id FROM participations
        WHERE course_id = :cid AND non_partant = false
    """), {"cid": course_id})).all()
    if not parts:
        return {}
    rows = (await session.execute(text("""
        SELECT cheval_id, delta_elo FROM (
            SELECT cheval_id, delta_elo, date_course,
                   ROW_NUMBER() OVER (PARTITION BY cheval_id
                                      ORDER BY date_course DESC) AS rang
            FROM elo_historique
            WHERE cheval_id = ANY(:cids)
              AND date_course < :today
              AND course_id IS DISTINCT FROM :cid
        ) h
        WHERE h.rang <= :n
        ORDER BY cheval_id, date_course DESC
    """), {"cids": [p[1] for p in parts], "cid": course_id, "today": jour,
           "n": ELO_DELTAS_PAR_CHEVAL})).all()
    deltas: dict = {}
    for cheval_id, delta in rows:
        deltas.setdefault(cheval_id, []).append(delta)
    return {pid: traits_historique_elo(deltas.get(cheval_id, [])) for pid, cheval_id in parts}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depuis", default="2025-06-01")
    ap.add_argument("--limite", type=int, default=200_000)
    ap.add_argument("--journal", default=None, help="CSV pid;course;anciens;nouveaux")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db.database import AsyncSessionLocal

    plancher = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    async with AsyncSessionLocal() as s:
        # Toute course déjà partie : c'est là que l'ELO de la course peut exister.
        courses = (await s.execute(text("""
            SELECT c.course_id, c.date_heure FROM courses c
            WHERE c.date_heure >= :depuis AND c.date_heure < now()
              AND EXISTS (SELECT 1 FROM participations p
                          JOIN features_ml f ON f.participation_id = p.participation_id
                          WHERE p.course_id = c.course_id)
            ORDER BY c.date_heure
            LIMIT :limite
        """), {"depuis": plancher, "limite": args.limite})).all()
    print(f"[patch-elo] {len(courses)} courses depuis {args.depuis} "
          f"(dry_run={args.dry_run})", flush=True)

    fj = open(args.journal, "a", encoding="utf-8") if args.journal else None
    t0 = time.monotonic()
    n_lignes = n_changees = n_sans_vecteur = 0
    try:
        for i, (cid, date_heure) in enumerate(courses, 1):
            async with AsyncSessionLocal() as s:
                vec = await vecteurs_elo_course(s, cid, date_heure.date())
                if not vec:
                    continue
                anciens = {r[0]: r[1] for r in (await s.execute(text("""
                    SELECT participation_id,
                           jsonb_build_object('delta_elo_5courses', features->'delta_elo_5courses',
                                              'velocity_elo', features->'velocity_elo',
                                              'elo_trend_30j', features->'elo_trend_30j',
                                              'bounce_score', features->'bounce_score',
                                              'career_momentum', features->'career_momentum')
                    FROM features_ml WHERE participation_id = ANY(:pids)
                """), {"pids": list(vec)})).all()}
                for pid, traits in vec.items():
                    if pid not in anciens:
                        n_sans_vecteur += 1
                        continue
                    avant = anciens[pid] or {}
                    change = any(abs(float(avant.get(k) or 0.0) - traits[k]) > 1e-9 for k in CLES)
                    if change and not args.dry_run:
                        # `||` remplace ces cinq clés et laisse les autres intactes ;
                        # `computed_at` n'est pas dans le SET.
                        await s.execute(text("""
                            UPDATE features_ml
                               SET features = features || CAST(:patch AS jsonb)
                             WHERE participation_id = :pid
                        """), {"patch": json.dumps(traits), "pid": pid})
                    n_lignes += 1
                    n_changees += int(change)
                    if fj and change:
                        fj.write(f"{pid};{cid};{json.dumps(avant)};{json.dumps(traits)}\n")
                if not args.dry_run:
                    await s.commit()
            if i % 500 == 0:
                if fj:
                    fj.flush()
                print(f"  … {i}/{len(courses)} courses · {n_lignes} vecteurs · "
                      f"{n_changees} changés · {time.monotonic() - t0:.0f}s", flush=True)
    finally:
        if fj:
            fj.close()
    print(f"[patch-elo] TERMINÉ en {time.monotonic() - t0:.0f}s — {n_lignes} vecteurs lus, "
          f"{n_changees} changés, {n_sans_vecteur} partants sans vecteur", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
