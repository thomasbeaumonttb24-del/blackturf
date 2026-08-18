"""Écriture compatible du journal immuable des prédictions.

La table ``predictions`` reste volontairement la projection courante. Ce module
effectue le dual-write dans ``prediction_snapshots`` au sein de la transaction du
prono. Pendant une fenêtre de déploiement où le code précède exceptionnellement la
migration, seule l'absence précise de cette table est tolérée via un savepoint.
Toute autre erreur remonte et annule la transaction : un audit incomplet ne doit
pas passer silencieusement.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import PredictionSnapshot


log = structlog.get_logger()
UNDEFINED_TABLE_SQLSTATE = "42P01"


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported snapshot value: {type(value).__name__}")


def _json_safe(value: Any) -> Any:
    """Normalise comme le modèle (valeur manquante -> null, puis fillna au replay)."""
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # Un set n'a pas d'ordre : on le TRIE pour que l'empreinte reste stable
        # d'un appel à l'autre (deux plans identiques doivent donner le même hash,
        # sinon l'idempotence de bet_plan_snapshots tombe). Tri par représentation
        # textuelle : les familles de paris d'un profil sont des chaînes, et cela
        # reste défini même sur un set hétérogène.
        return [_json_safe(item) for item in sorted(value, key=str)]
    return value


def canonical_json(value: Any) -> str:
    """Sérialisation stable utilisée à la fois pour la copie et l'empreinte."""
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_snapshot_values(
    *,
    prediction_run_id: str,
    snapshot_id: str,
    prediction_id: str,
    participation_id: str,
    course_id: str,
    model_version_id: str | None,
    features: dict,
    observed_at: datetime,
    course_start_at: datetime | None,
    proba_top1: float,
    proba_top3: float,
    proba_top1_raw: float | None,
    proba_top3_raw: float | None,
    proba_top1_low: float | None,
    proba_top1_high: float | None,
    rang_predit: int,
    confidence_score: float | None,
    cote_figee: float | None,
    odds_observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Construit une copie JSON autonome, hashée et temporellement qualifiée."""
    encoded = canonical_json(features)
    frozen_features = json.loads(encoded)
    schema = canonical_json(sorted(frozen_features.keys()))
    seen_at = _utc(observed_at)
    start_at = _utc(course_start_at)
    assert seen_at is not None

    return {
        "snapshot_id": snapshot_id,
        "prediction_run_id": prediction_run_id,
        "prediction_id": prediction_id,
        "participation_id": participation_id,
        "course_id": course_id,
        "model_version_id": model_version_id,
        "features": frozen_features,
        "features_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "feature_schema_hash": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
        "proba_top1": proba_top1,
        "proba_top3": proba_top3,
        "proba_top1_raw": proba_top1_raw,
        "proba_top3_raw": proba_top3_raw,
        "proba_top1_low": proba_top1_low,
        "proba_top1_high": proba_top1_high,
        "rang_predit": rang_predit,
        "confidence_score": confidence_score,
        "cote_figee": cote_figee,
        "observed_at": seen_at,
        # Heure à laquelle la SOURCE a publié cette cote, quand elle est connue
        # (PMU dateRapport, cf. migration 0033). À défaut on retombe sur l'heure du
        # calcul — c'est une borne SUPÉRIEURE honnête (la cote existait au plus tard
        # à cet instant), jamais une date inventée. La distinction compte pour le
        # CLV : une cote publiée 20 min avant le calcul n'a pas la même valeur
        # informative qu'une cote publiée à la seconde.
        "odds_observed_at": (
            _utc(odds_observed_at) if odds_observed_at is not None
            else (seen_at if cote_figee is not None else None)
        ),
        "course_start_at": start_at,
        "is_pre_course": bool(start_at is not None and seen_at < start_at),
        "origin": "live",
        "is_replayable": True,
    }


def is_missing_snapshot_table(error: BaseException) -> bool:
    """Vrai uniquement pour PostgreSQL 42P01 visant prediction_snapshots."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code == UNDEFINED_TABLE_SQLSTATE and "prediction_snapshots" in str(error):
            return True
        current = getattr(current, "orig", None) or current.__cause__ or current.__context__
    return False


async def persist_snapshot_compat(session, values: dict[str, Any]) -> bool:
    """Dual-write idempotent; tolère seulement une migration pas encore appliquée."""
    try:
        async with session.begin_nested():
            stmt = (
                pg_insert(PredictionSnapshot)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["prediction_run_id", "participation_id"]
                )
            )
            await session.execute(stmt)
    except Exception as exc:
        if not is_missing_snapshot_table(exc):
            raise
        log.warning(
            "pipeline.prediction_snapshot.table_missing",
            course_id=values.get("course_id"),
            prediction_run_id=values.get("prediction_run_id"),
        )
        return False
    return True
