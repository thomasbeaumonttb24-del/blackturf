"""Un cheval déclaré non-partant sort du pronostic — sans casser la sauvegarde.

Constaté en production le 2026-08-19 : ``db_writer`` supprimait la prédiction du
cheval forfait, la clé étrangère de ``prediction_snapshots`` (journal append-only,
migration 0029) refusait la suppression, et c'est la transaction de la COURSE
ENTIÈRE qui était annulée — cotes, statut non-partant et résultats compris.

Deux invariants en découlent, tenus ici :
1. le writer ne supprime plus de ligne ``predictions`` ;
2. la ligne survivante ne doit pas être évaluée, sinon les calibrateurs comptent
   en perdant un cheval qui n'a jamais couru.
"""
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Cheval,
    Course,
    Participation,
    Prediction,
    PredictionSnapshot,
)

NOW = datetime.now(timezone.utc)
DB_WRITER = pathlib.Path(__file__).resolve().parents[1] / "scraper" / "db_writer.py"


async def _seed(
    db: AsyncSession,
    course_id: str,
    *,
    non_partant: bool,
    avec_snapshot: bool,
) -> str:
    """Une course, un cheval, sa prédiction, et au choix son snapshot pré-course."""
    db.add(Course(
        course_id=course_id, reunion_id=f"R-{course_id}", numero=1, nom="Prix Test",
        date_heure=NOW + timedelta(hours=2), hippodrome_nom="Test", discipline="Plat",
        distance=2000, nb_partants=6, statut="a_venir",
    ))
    db.add(Cheval(cheval_id=f"cheval-{course_id}", nom=f"Cheval {course_id}", age=5, sexe="H"))
    part_id = f"part-{course_id}"
    db.add(Participation(
        participation_id=part_id, course_id=course_id, cheval_id=f"cheval-{course_id}",
        numero=1, cote_pmu=4.0, non_partant=non_partant,
    ))
    pred_id = f"pred-{course_id}"
    db.add(Prediction(
        prediction_id=pred_id, participation_id=part_id, course_id=course_id,
        proba_top1=0.25, proba_top3=0.55, rang_predit=1, cote_figee=4.0,
    ))
    if avec_snapshot:
        db.add(PredictionSnapshot(
            snapshot_id=f"snap-{course_id}", prediction_run_id=f"run-{course_id}",
            prediction_id=pred_id, participation_id=part_id, course_id=course_id,
            features={}, features_hash="h", feature_schema_hash="s",
            proba_top1=0.25, proba_top3=0.55, rang_predit=1, cote_figee=4.0,
            observed_at=NOW, course_start_at=NOW + timedelta(hours=2),
            is_pre_course=True, origin="live", is_replayable=True,
        ))
    await db.commit()
    return part_id


async def _participations_evaluees(db: AsyncSession) -> set[str]:
    rows = await db.execute(text("SELECT participation_id FROM prediction_evaluation"))
    return {r[0] for r in rows.fetchall()}


# ── 1. Le writer ne supprime plus de prédiction ──────────────────────────────
def test_le_writer_ne_supprime_jamais_de_prediction():
    """La suppression annulait la sauvegarde entière de la course (FK NO ACTION
    depuis `prediction_snapshots` ET depuis `value_bets`). Le retrait du pronostic
    passe désormais par `participations.non_partant`, posé dans la même
    transaction."""
    source = DB_WRITER.read_text(encoding="utf-8")
    assert not re.search(r"DELETE\s+FROM\s+predictions", source, re.I), (
        "db_writer supprime à nouveau des lignes `predictions` : la clé étrangère "
        "du journal append-only fera échouer la sauvegarde de la course entière.")
    assert "UPDATE value_bets SET actif = false" in source, (
        "le value bet d'un cheval non-partant doit toujours être désactivé")


# ── 2. Un non-partant n'est jamais évalué ────────────────────────────────────
async def test_un_partant_normal_reste_evaluable(db: AsyncSession):
    part_id = await _seed(db, "NP-OK", non_partant=False, avec_snapshot=True)
    assert part_id in await _participations_evaluees(db)


async def test_le_snapshot_d_un_non_partant_sort_de_l_evaluation(db: AsyncSession):
    """Le snapshot SURVIT (journal append-only, on ne le supprime pas) mais il ne
    doit plus être servi comme pronostic évaluable : sinon les calibrateurs le
    comptent en perdant alors que le cheval n'a jamais couru."""
    part_id = await _seed(db, "NP-SNAP", non_partant=True, avec_snapshot=True)

    reste = (await db.execute(text(
        "SELECT count(*) FROM prediction_snapshots WHERE participation_id = :p"),
        {"p": part_id})).scalar()
    assert reste == 1, "le journal ne doit pas être amputé"
    assert part_id not in await _participations_evaluees(db)


async def test_la_prediction_legacy_d_un_non_partant_sort_de_l_evaluation(db: AsyncSession):
    """Même exclusion sur la branche legacy de la vue (aucun snapshot)."""
    part_id = await _seed(db, "NP-LEGACY", non_partant=True, avec_snapshot=False)

    encore_la = (await db.execute(text(
        "SELECT count(*) FROM predictions WHERE participation_id = :p"),
        {"p": part_id})).scalar()
    assert encore_la == 1, "la prédiction reste en base : c'est la lecture qui filtre"
    assert part_id not in await _participations_evaluees(db)


# ── 3. L'endpoint pronostic écarte les non-partants ──────────────────────────
def test_l_endpoint_pronostic_filtre_les_non_partants():
    """Sans ce filtre, la page course afficherait une probabilité et un rang
    périmés sur un cheval qui ne court pas."""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "api" / "routes" / "predictions.py").read_text(encoding="utf-8")
    normalise = " ".join(source.split())
    assert "Participation.non_partant == False" in normalise, (
        "la liste des pronostics doit exclure les non-partants")
