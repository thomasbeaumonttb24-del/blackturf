"""
backfill_dynamics.py — Rétro-remplissage des signaux de dynamique (Phase 1).

Les lignes d'historique enregistrées AVANT la Phase 1 n'ont ni réduction km ni
accélération finale. Sans ce backfill, les features dyn_* restent neutres pour
tout l'historique et le modèle ne peut rien en apprendre.

Ce module recalcule, pour les lignes manquantes :
  - reduction_km        : depuis temps_officiel + distance (toujours possible)
  - acceleration_*      : depuis le dernier 400 m (temps_passage), si disponible

RÈGLE D'INTÉGRITÉ : on ne remplit que ce qui est calculable depuis des données
réelles. Pas de donnée → on laisse NULL.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select, text

from db.models import HistoriqueCourse
from ml.race_dynamics import compute_reduction_km, compute_acceleration

log = structlog.get_logger()


async def backfill_historique_dynamics(session, batch_size: int = 500, max_rows: int = 0) -> dict:
    """
    Recalcule reduction_km + acceleration_* pour les lignes historiques manquantes.

    batch_size : nombre de lignes traitées par lot (commit par lot).
    max_rows   : 0 = tout ; sinon plafond (utile pour tests/dry-run).

    Retourne {rows_scannees, reduction_remplie, acceleration_remplie}.
    """
    stats = {"rows_scannees": 0, "reduction_remplie": 0, "acceleration_remplie": 0}
    cursor = ""  # keyset : on avance par historique_id croissant, chaque ligne 1 fois

    while True:
        q = (
            select(HistoriqueCourse)
            .where(
                HistoriqueCourse.historique_id > cursor,
                HistoriqueCourse.reduction_km.is_(None),
            )
            .order_by(HistoriqueCourse.historique_id)
            .limit(batch_size)
        )
        rows = (await session.execute(q)).scalars().all()
        if not rows:
            break
        cursor = rows[-1].historique_id  # avance le curseur même sur lignes non remplies

        for h in rows:
            stats["rows_scannees"] += 1

            # reduction_km depuis temps officiel + distance
            red = compute_reduction_km(h.temps_officiel, h.distance)
            if red is not None:
                h.reduction_km = red
                stats["reduction_remplie"] += 1

            # acceleration depuis le dernier 400m (temps_passage), si course interne
            if h.course_id:
                tp = await session.execute(text("""
                    SELECT tp.passage_dernier_400m
                    FROM temps_passage tp
                    JOIN participations p
                      ON p.course_id = tp.course_id AND p.numero = tp.numero
                    WHERE tp.course_id = :cid AND p.cheval_id = :chid
                    LIMIT 1
                """), {"cid": h.course_id, "chid": h.cheval_id})
                row = tp.fetchone()
                if row and row[0]:
                    accel = compute_acceleration(row[0], h.temps_officiel, h.distance)
                    if accel:
                        h.acceleration_index = accel["acceleration_index"]
                        h.acceleration_label = accel["acceleration_label"]
                        stats["acceleration_remplie"] += 1

            if max_rows and stats["rows_scannees"] >= max_rows:
                break

        await session.commit()
        log.info("backfill.batch", **stats)

        if max_rows and stats["rows_scannees"] >= max_rows:
            break
        if len(rows) < batch_size:
            break  # dernier lot

    return stats
