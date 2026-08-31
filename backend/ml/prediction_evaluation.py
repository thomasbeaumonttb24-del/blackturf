"""Qualité et couverture de la cohorte causale de prédictions."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# Seuils de remplacement d'un état de production existant. Ils protègent le cold
# start après activation des snapshots : sous ces volumes, on observe mais on ne
# remplace jamais une calibration déjà validée par une identité/structure vide.
MIN_LONGSHOT_REPLAYABLE_OBS = 200
MIN_COTE_REPLAYABLE_OBS = 200
MIN_COTE_BUCKET_OBS = 30
MIN_EV_BAND_REPLAYABLE_OBS = 200
MIN_EV_BAND_OBS = 30
# Multiplicateurs de signaux (duo J/E, ELO, pedigree…) appris sur des features_ml
# FIGÉES avant le départ. Sous ce volume, chaque signal retombe à multiplier=1.0 :
# une structure neutre complète qui écraserait des multiplicateurs déjà validés.
MIN_SIGNAL_PERF_OBS = 200
# Apprentissages assis sur les plans réellement émis (profil_run_log réglé).
# 30 runs ≈ 10 par profil = MIN_RUNS_FOR_WEIGHTS : sous ce seuil l'agrégat ne peut
# produire que des poids neutres et perdrait les suppressions déjà prouvées.
MIN_PROFIL_WEIGHTS_RUNS = 30
MIN_RAPPORT_CALIB_RUNS = 30


async def missing_snapshot_causes(session: AsyncSession) -> dict:
    """Pourquoi une évaluation retombe-t-elle sur la ligne legacy mutable ?

    Trois causes exclusives, mesurées sur les lignes ``is_replayable = false`` :

    - ``no_snapshot_row`` : aucun snapshot pour cette participation (prédiction
      antérieure au dual-write, ou écriture du snapshot en échec) ;
    - ``post_course_only`` : des snapshots existent mais tous post-départ
      (``is_pre_course = false``) — rien de rejouable causalement ;
    - ``not_replayable`` : des snapshots pré-course existent mais sont marqués
      non rejouables (features/cotes non figées de façon fiable).

    Comptage en ``SUM(CASE …)`` plutôt qu'en ``FILTER`` : identique sous
    PostgreSQL et sous le SQLite des tests.
    """
    row = (await session.execute(text("""
        SELECT
            count(*) AS n_legacy,
            COALESCE(SUM(CASE WHEN s.participation_id IS NULL
                              THEN 1 ELSE 0 END), 0) AS no_snapshot_row,
            COALESCE(SUM(CASE WHEN s.participation_id IS NOT NULL
                               AND s.n_pre_course = 0
                              THEN 1 ELSE 0 END), 0) AS post_course_only,
            COALESCE(SUM(CASE WHEN s.n_pre_course > 0
                              THEN 1 ELSE 0 END), 0) AS not_replayable,
            count(DISTINCT pe.course_id) AS courses_legacy
        FROM prediction_evaluation pe
        LEFT JOIN (
            SELECT participation_id,
                   SUM(CASE WHEN is_pre_course THEN 1 ELSE 0 END) AS n_pre_course
            FROM prediction_snapshots
            GROUP BY participation_id
        ) s ON s.participation_id = pe.participation_id
        WHERE pe.is_replayable = false
    """))).first()
    if not row:
        return {"n_legacy": 0, "no_snapshot_row": 0, "post_course_only": 0,
                "not_replayable": 0, "courses_legacy": 0}
    return {
        "n_legacy": int(row[0] or 0),
        "no_snapshot_row": int(row[1] or 0),
        "post_course_only": int(row[2] or 0),
        "not_replayable": int(row[3] or 0),
        "courses_legacy": int(row[4] or 0),
    }


async def evaluation_coverage(session: AsyncSession) -> dict:
    """Couverture globale du read-model, sans mélanger legacy et rejouable.

    ``courses_replayable`` compte les courses ayant AU MOINS une évaluation
    rejouable ; ``courses_fully_replayable`` celles dont TOUS les partants sont
    couverts — seule cette seconde cohorte peut servir de base à un backtest de
    course entière. Les causes d'absence sont jointes quand elles sont
    calculables (table ``prediction_snapshots`` présente).
    """
    row = (await session.execute(text("""
        SELECT
            count(*) AS n_total,
            count(*) FILTER (WHERE is_replayable = true) AS n_replayable,
            count(*) FILTER (WHERE is_replayable = false) AS n_legacy,
            count(DISTINCT course_id) AS courses_total,
            count(DISTINCT course_id) FILTER (WHERE is_replayable = true) AS courses_replayable,
            min(created_at) FILTER (WHERE is_replayable = true) AS first_replayable_at,
            max(created_at) FILTER (WHERE is_replayable = true) AS last_replayable_at,
            count(DISTINCT course_id) FILTER (WHERE is_replayable = false) AS courses_with_legacy
        FROM prediction_evaluation
    """))).first()
    total = int(row[0] or 0) if row else 0
    replayable = int(row[1] or 0) if row else 0
    courses_total = int(row[3] or 0) if row else 0
    courses_replayable = int(row[4] or 0) if row else 0
    courses_with_legacy = int(row[7] or 0) if row and len(row) > 7 else 0
    out = {
        "n_total": total,
        "n_replayable": replayable,
        "n_legacy": int(row[2] or 0) if row else 0,
        "coverage_pct": round(100.0 * replayable / total, 2) if total else 0.0,
        "courses_total": courses_total,
        "courses_replayable": courses_replayable,
        # Course entièrement couverte = aucune de ses lignes n'est legacy.
        "courses_fully_replayable": max(0, courses_total - courses_with_legacy),
        "courses_partially_replayable": max(
            0, courses_replayable - (courses_total - courses_with_legacy)
        ),
        "first_replayable_at": row[5] if row else None,
        "last_replayable_at": row[6] if row else None,
    }
    try:
        out["missing_causes"] = await missing_snapshot_causes(session)
    except Exception:
        # Snapshots pas encore migrés (< 0029) : la couverture reste publiable,
        # on ne fabrique aucune cause qu'on ne sait pas mesurer. Rollback pour
        # désempoisonner la transaction (asyncpg la marque avortée) et laisser
        # les requêtes suivantes de l'appelant fonctionner.
        try:
            await session.rollback()
        except Exception:
            pass
        out["missing_causes"] = None
    return out
