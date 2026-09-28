"""
patch_features_commentaires.py — Réécrit les SEULES clés `commentaire_*` des
vecteurs `features_ml` stockés, après le rattrapage des commentaires post-course
(scripts/rattraper_commentaires_pmu.py).

Même calcul que le direct (`_compute_features_from_batch`, § GG-bis) : les six
dernières sorties du cheval STRICTEMENT antérieures au jour de la course (même
borne `date_course < jour` que `_load_course_batch_data`), leurs commentaires non
vides, passés à `ml.features.compute_commentaire_signal`. `computed_at` n'est
jamais modifié ; les anciennes valeurs vont dans `--journal`.

    python scripts/patch_features_commentaires.py --dry-run --limite 20
    python scripts/patch_features_commentaires.py --depuis 2026-08-27 --journal /tmp/patch_com.csv
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

from ml.features import compute_commentaire_signal  # noqa: E402

CLES = ("commentaire_signal", "commentaire_malchance_recente", "commentaire_gagne_facile",
        "nb_commentaires_lus")
SORTIES_LUES = 6


def traits_commentaires(textes) -> dict:
    signal, malchance, facile, nb = compute_commentaire_signal(list(textes))
    return {"commentaire_signal": float(signal), "commentaire_malchance_recente": float(malchance),
            "commentaire_gagne_facile": float(facile), "nb_commentaires_lus": int(nb)}


async def vecteurs_course(session, course_id: str, jour) -> dict[str, dict]:
    parts = (await session.execute(text("""
        SELECT participation_id, cheval_id FROM participations
        WHERE course_id = :cid AND non_partant = false
    """), {"cid": course_id})).all()
    if not parts:
        return {}
    rows = (await session.execute(text("""
        SELECT cheval_id, commentaire_course FROM (
            SELECT cheval_id, commentaire_course,
                   ROW_NUMBER() OVER (PARTITION BY cheval_id ORDER BY date_course DESC) AS rang
            FROM historique_courses
            WHERE cheval_id = ANY(:cids) AND date_course < :jour
        ) h WHERE h.rang <= :n
        ORDER BY cheval_id, rang
    """), {"cids": [p[1] for p in parts], "jour": jour, "n": SORTIES_LUES})).all()
    textes: dict = {}
    for cheval_id, com in rows:
        if com:
            textes.setdefault(cheval_id, []).append(com)
    return {pid: traits_commentaires(textes.get(cheval_id, [])) for pid, cheval_id in parts}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depuis", default="2026-08-27")
    ap.add_argument("--limite", type=int, default=100_000)
    ap.add_argument("--journal", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db.database import AsyncSessionLocal

    plancher = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    async with AsyncSessionLocal() as s:
        courses = (await s.execute(text("""
            SELECT c.course_id, c.date_heure FROM courses c
            WHERE c.date_heure >= :depuis
              AND EXISTS (SELECT 1 FROM participations p
                          JOIN features_ml f ON f.participation_id = p.participation_id
                          WHERE p.course_id = c.course_id)
            ORDER BY c.date_heure LIMIT :limite
        """), {"depuis": plancher, "limite": args.limite})).all()
    print(f"[patch-commentaires] {len(courses)} courses depuis {args.depuis} "
          f"(dry_run={args.dry_run})", flush=True)

    fj = open(args.journal, "a", encoding="utf-8") if args.journal else None
    t0 = time.monotonic()
    n_lignes = n_changees = n_non_nuls = 0
    try:
        for cid, date_heure in courses:
            async with AsyncSessionLocal() as s:
                vec = await vecteurs_course(s, cid, date_heure.date())
                if not vec:
                    continue
                anciens = {r[0]: r[1] for r in (await s.execute(text("""
                    SELECT participation_id,
                           jsonb_build_object('commentaire_signal', features->'commentaire_signal',
                                              'commentaire_malchance_recente', features->'commentaire_malchance_recente',
                                              'commentaire_gagne_facile', features->'commentaire_gagne_facile',
                                              'nb_commentaires_lus', features->'nb_commentaires_lus')
                    FROM features_ml WHERE participation_id = ANY(:pids)
                """), {"pids": list(vec)})).all()}
                for pid, traits in vec.items():
                    if pid not in anciens:
                        continue
                    avant = anciens[pid] or {}
                    change = any(abs(float(avant.get(k) or 0.0) - float(traits[k])) > 1e-9 for k in CLES)
                    if change and not args.dry_run:
                        await s.execute(text("""
                            UPDATE features_ml SET features = features || CAST(:patch AS jsonb)
                             WHERE participation_id = :pid
                        """), {"patch": json.dumps(traits), "pid": pid})
                    n_lignes += 1
                    n_changees += int(change)
                    n_non_nuls += int(traits["nb_commentaires_lus"] > 0)
                    if fj and change:
                        fj.write(f"{pid};{cid};{json.dumps(avant)};{json.dumps(traits)}\n")
                if not args.dry_run:
                    await s.commit()
    finally:
        if fj:
            fj.close()
    print(f"[patch-commentaires] TERMINÉ en {time.monotonic() - t0:.0f}s — {n_lignes} vecteurs, "
          f"{n_changees} changés, {n_non_nuls} avec au moins un commentaire lu", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
