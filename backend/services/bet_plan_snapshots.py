"""Journalisation immuable des plans de mise émis, et règlement PMU.

``prediction_snapshots`` fige la probabilité ; ce module fige le CONSEIL rendu :
sélection exacte, mises, cotes retenues, EV, configuration de l'algorithme. Sans
lui, tout ROI est une reconstruction faite APRÈS le résultat — donc contaminée.

Deux garanties portées ici :

- **Idempotence** : rejouer la même requête n'ajoute pas de ligne (unicité sur
  course × destinataire × empreinte du plan).
- **Aucune régénération post-résultat** : un plan émis après le départ est
  enregistré avec ``is_pre_course = false`` et exclu du read-model de ROI ; le
  règlement est un événement séparé qui ne réécrit jamais le conseil.

Comme pour les snapshots de prédiction, seule l'absence précise de la table
(migration pas encore appliquée) est tolérée — toute autre erreur remonte.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import BetPlanSettlement, BetPlanSnapshot
from ml.prediction_snapshots import canonical_json

log = structlog.get_logger(module="bet_plan_snapshots")

UNDEFINED_TABLE_SQLSTATE = "42P01"
SYSTEM_SUBJECT = "system"

# Clés ajoutées par les routes autour du plan : elles décrivent le contexte de la
# réponse HTTP, pas le conseil. Exclues du payload figé ET de son empreinte.
_ROUTE_META_KEYS = frozenset({
    "quota_restant", "quota_limite", "roi_observe", "prono_fige", "prono_fige_a",
    "cotes_live_utilisees", "message", "detail",
})


def subject_hash(user_id: Optional[str], secret: str) -> str:
    """Pseudonymise le destinataire. HMAC : non réversible sans le secret, et
    stable pour un même utilisateur (donc l'idempotence tient d'une requête à
    l'autre). ``system`` pour les plans émis par les jobs internes."""
    if not user_id:
        return SYSTEM_SUBJECT
    return hmac.new(secret.encode("utf-8"), str(user_id).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _decision_view(plan: dict) -> list[dict]:
    """Réduit le plan à ce qui ENGAGE de l'argent.

    Le libellé, l'emoji ou la formulation d'une raison peuvent changer sans que
    le conseil change : les inclure dans l'empreinte casserait l'idempotence
    pour rien. Un numéro, une mise ou un type qui bouge, en revanche, est un
    conseil différent.
    """
    decisions: list[dict] = []
    for niveau in plan.get("niveaux") or []:
        for pari in niveau.get("paris") or []:
            decisions.append({
                "niveau": niveau.get("niveau"),
                "type": pari.get("type"),
                "chevaux": sorted(int(c["numero"]) for c in (pari.get("chevaux") or [])
                                  if c.get("numero") is not None),
                "mise": round(float(pari.get("mise") or 0.0), 2),
                "gain_potentiel": round(float(pari.get("gain_potentiel") or 0.0), 2),
                "ev_estime": round(float(pari.get("ev_estime") or 0.0), 4),
            })
    decisions.sort(key=lambda d: (str(d["niveau"]), str(d["type"]), d["chevaux"], d["mise"]))
    return decisions


def plan_hash(plan: dict, *, profil: str, montant: float, cotes: dict) -> str:
    """Empreinte canonique du conseil : mêmes paris, mêmes mises, mêmes cotes."""
    payload = {
        "profil": profil,
        "montant": round(float(montant or 0.0), 2),
        "decisions": _decision_view(plan),
        "cotes": {str(k): round(float(v), 3) for k, v in sorted((cotes or {}).items())
                  if v is not None},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def strip_route_metadata(payload: dict) -> dict:
    """Retire du plan les clés propres à la réponse HTTP."""
    return {k: v for k, v in (payload or {}).items() if k not in _ROUTE_META_KEYS}


def _count_paris(plan: dict) -> int:
    return sum(len(n.get("paris") or []) for n in (plan.get("niveaux") or []))


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_plan_snapshot_values(
    *,
    course_id: str,
    plan: dict,
    profil: str,
    montant_demande: float,
    cotes_utilisees: dict,
    algo_config: dict,
    emitted_at: datetime,
    course_start_at: datetime | None,
    subject: str = SYSTEM_SUBJECT,
    bankroll: float | None = None,
    prediction_run_id: str | None = None,
    model_version_id: str | None = None,
    origin: str = "mise_plan",
) -> dict[str, Any]:
    """Construit la ligne figée : copie JSON autonome, hashée et datée."""
    # Aller-retour par la sérialisation canonique : ce qui est STOCKÉ est
    # exactement ce qui est HASHÉ, et le résultat est du JSON pur (sets convertis
    # en listes triées, non-finis en null). Sans cela, la config réelle du moteur
    # — qui contient un set de familles de paris — passait le hash mais faisait
    # échouer l'insertion JSONB côté SQLAlchemy ("Object of type set is not JSON
    # serializable"), erreur avalée par record_plan_snapshot : plus aucun plan
    # journalisé, sans le moindre signal.
    frozen_plan = json.loads(canonical_json(strip_route_metadata(plan)))
    cotes = {str(k): float(v) for k, v in (cotes_utilisees or {}).items() if v is not None}
    config = json.loads(canonical_json(dict(algo_config or {})))
    seen_at = _utc(emitted_at)
    start_at = _utc(course_start_at)
    assert seen_at is not None

    return {
        "plan_snapshot_id": str(uuid.uuid4()),
        "course_id": course_id,
        "prediction_run_id": prediction_run_id,
        "model_version_id": model_version_id,
        "subject_hash": subject or SYSTEM_SUBJECT,
        "profil": profil,
        "montant_demande": float(montant_demande),
        "bankroll": float(bankroll) if bankroll is not None else None,
        "plan": frozen_plan,
        "plan_hash": plan_hash(frozen_plan, profil=profil,
                               montant=montant_demande, cotes=cotes),
        "cotes_utilisees": cotes,
        "algo_config": config,
        # Version DÉRIVÉE de la configuration réellement appliquée : elle change
        # d'elle-même dès qu'un paramètre du moteur change, sans dépendre d'un
        # numéro de version qu'on oublierait de bumper.
        "algo_version": "mp-" + hashlib.sha256(
            canonical_json(config).encode("utf-8")).hexdigest()[:12],
        "nb_paris": _count_paris(frozen_plan),
        "montant_joue": float(frozen_plan.get("montant_joue") or 0.0),
        "ev_estimee": frozen_plan.get("ev_global"),
        "esperance_gain": frozen_plan.get("esperance_gain"),
        "emitted_at": seen_at,
        "course_start_at": start_at,
        # Seul un plan émis STRICTEMENT avant le départ est mesurable. On
        # l'enregistre quand même après le départ, mais marqué comme tel.
        "is_pre_course": bool(start_at is not None and seen_at < start_at),
        "origin": origin,
    }


def is_missing_bet_plan_table(error: BaseException) -> bool:
    """Vrai uniquement pour PostgreSQL 42P01 visant une table de plans."""
    current: BaseException | None = error
    seen: set[int] = set()
    message = str(error)
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code == UNDEFINED_TABLE_SQLSTATE and (
            "bet_plan_snapshots" in message or "bet_plan_settlements" in message
        ):
            return True
        current = getattr(current, "orig", None) or current.__cause__ or current.__context__
    return False


async def persist_plan_snapshot(session, values: dict[str, Any]) -> bool:
    """Écriture idempotente ; tolère seulement une migration pas encore appliquée.

    ``ON CONFLICT DO NOTHING`` sur (course, destinataire, empreinte) : rejouer la
    même demande ne crée pas un second conseil.
    """
    try:
        async with session.begin_nested():
            stmt = (
                pg_insert(BetPlanSnapshot)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["course_id", "subject_hash", "plan_hash"]
                )
            )
            await session.execute(stmt)
    except Exception as exc:
        if not is_missing_bet_plan_table(exc):
            raise
        log.warning("bet_plan_snapshot.table_missing", course_id=values.get("course_id"))
        return False
    return True


async def record_plan_snapshot(session, **kwargs) -> Optional[str]:
    """Fige un plan émis. Retourne son plan_snapshot_id, ou None si non écrit.

    Ne lève jamais vers l'appelant : figer l'audit ne doit pas casser la réponse
    rendue à l'utilisateur. L'échec est journalisé et resté visible en métrique.
    """
    try:
        values = build_plan_snapshot_values(**kwargs)
        written = await persist_plan_snapshot(session, values)
        if not written:
            return None
        # Relit l'identifiant réellement en base : en cas de conflit, c'est celui
        # de la PREMIÈRE émission qui fait foi, pas celui qu'on vient de générer.
        row = (await session.execute(text("""
            SELECT plan_snapshot_id FROM bet_plan_snapshots
            WHERE course_id = :cid AND subject_hash = :sub AND plan_hash = :ph
        """), {"cid": values["course_id"], "sub": values["subject_hash"],
               "ph": values["plan_hash"]})).scalar()
        return row
    except Exception as exc:
        log.warning("bet_plan_snapshot.record_failed",
                    course_id=kwargs.get("course_id"), err=str(exc)[:160])
        try:
            await session.rollback()
        except Exception:
            pass
        return None


async def settle_course_plans(session, course_id: str) -> dict:
    """Règle sur les VRAIS rapports PMU tous les plans figés d'une course.

    Un règlement est un ÉVÉNEMENT ajouté, jamais une réécriture : un rapport
    publié tardivement produit une nouvelle ligne et le dernier ``settled_at``
    fait foi. On ne réémet jamais le plan, on ne le recalcule jamais sur le
    résultat connu.

    Retourne {"n_settled": …, "n_partial": …, "n_skipped": …}.
    """
    from services.bet_settlement import settle_plan

    res = (await session.execute(text("""
        SELECT r.classement, r.rapports, c.nb_partants, r.rapports_detail
        FROM resultats r JOIN courses c ON c.course_id = r.course_id
        WHERE r.course_id = :cid
    """), {"cid": course_id})).first()
    if not res or not res[0]:
        return {"n_settled": 0, "n_partial": 0, "n_skipped": 0}
    # asyncpg (prod) décode déjà json/jsonb en objets Python au niveau de la
    # connexion (codec posé par le dialecte SQLAlchemy) ; aiosqlite (tests) ne le
    # fait pas pour une requête texte brute et renvoie la colonne JSON en chaîne.
    classement_raw = res[0] if isinstance(res[0], list) else (
        json.loads(res[0]) if isinstance(res[0], str) else [])
    classement = classement_raw if isinstance(classement_raw, list) else []
    rapports = res[1] if isinstance(res[1], dict) else (
        json.loads(res[1]) if isinstance(res[1], str) else {}) or {}
    nb_partants = res[2] or len(classement)
    rapports_detail = res[3] if isinstance(res[3], dict) else (
        json.loads(res[3]) if isinstance(res[3], str) else None)

    np_rows = (await session.execute(text("""
        SELECT numero FROM participations
        WHERE course_id = :cid AND non_partant = true
    """), {"cid": course_id})).all()
    non_partants = {int(r[0]) for r in np_rows if r[0] is not None}

    # Ne régler que les plans PRÉ-COURSE dont le dernier règlement connu n'est
    # pas déjà définitif : un plan 'settled' ne doit jamais être recalculé.
    plans = (await session.execute(text("""
        SELECT s.plan_snapshot_id, s.plan
        FROM bet_plan_snapshots s
        WHERE s.course_id = :cid
          AND s.is_pre_course = true
          AND NOT EXISTS (
              SELECT 1 FROM bet_plan_settlements t
              WHERE t.plan_snapshot_id = s.plan_snapshot_id
                AND t.statut = 'settled'
          )
    """), {"cid": course_id})).all()

    n_settled = n_partial = 0
    now = datetime.now(timezone.utc)
    for plan_snapshot_id, plan in plans:
        # asyncpg/aiosqlite renvoient parfois du JSON en chaîne pour une requête
        # texte brute (pas de décodage typé hors ORM).
        plan_d = plan if isinstance(plan, dict) else (json.loads(plan) if plan else {})
        bilan = settle_plan(plan_d, classement, rapports, nb_partants,
                            rapports_detail, non_partants)
        statut = "partial" if bilan.get("en_attente") else "settled"
        await session.execute(
            BetPlanSettlement.__table__.insert().values(
                settlement_id=str(uuid.uuid4()),
                plan_snapshot_id=plan_snapshot_id,
                course_id=course_id,
                bilan=bilan,
                montant_mise=float(bilan.get("total_mise") or 0.0),
                montant_retour=float(bilan.get("total_gain") or 0.0),
                net=float(bilan.get("net") or 0.0),
                roi=(float(bilan["roi"]) / 100.0) if bilan.get("roi") is not None else None,
                nb_paris=int(bilan.get("nb_paris") or 0),
                nb_gagnes=int(bilan.get("nb_gagnes") or 0),
                statut=statut,
                settled_at=now,
            )
        )
        if statut == "settled":
            n_settled += 1
        else:
            n_partial += 1
    await session.commit()
    if n_settled or n_partial:
        log.info("bet_plan_settlement.done", course_id=course_id,
                 n_settled=n_settled, n_partial=n_partial)
    return {"n_settled": n_settled, "n_partial": n_partial, "n_skipped": 0}


async def settle_catchup_plans(session, days: int = 14) -> dict:
    """Rattrapage : re-tente les plans jamais réglés ou encore 'partial'.

    Le règlement inline peut être manqué (worker indisponible, résultat scrapé en
    retard) et un rapport PMU absent au premier passage peut être publié ensuite.
    Sans ce rattrapage, ces plans resteraient hors de toute mesure de ROI — donc
    un ROI calculé uniquement sur les plans faciles à régler, biaisé vers le haut.
    """
    try:
        course_ids = [r[0] for r in (await session.execute(text("""
            SELECT DISTINCT s.course_id
            FROM bet_plan_snapshots s
            JOIN courses c ON c.course_id = s.course_id
            JOIN resultats r ON r.course_id = s.course_id
            WHERE s.is_pre_course = true
              AND c.date_heure > now() - make_interval(days => :days)
              AND NOT EXISTS (
                  SELECT 1 FROM bet_plan_settlements t
                  WHERE t.plan_snapshot_id = s.plan_snapshot_id
                    AND t.statut = 'settled'
              )
        """), {"days": int(days)})).all()]
    except Exception as exc:
        if not is_missing_bet_plan_table(exc):
            raise
        try:
            await session.rollback()
        except Exception:
            pass
        return {"courses": 0, "n_settled": 0, "n_partial": 0}

    totals = {"courses": 0, "n_settled": 0, "n_partial": 0}
    for course_id in course_ids:
        out = await settle_course_plans(session, course_id)
        totals["courses"] += 1
        totals["n_settled"] += out["n_settled"]
        totals["n_partial"] += out["n_partial"]
    if totals["courses"]:
        log.info("bet_plan_settlement.catchup", **totals)
    return totals


async def daily_exposure_total(session, subject: str) -> float:
    """Somme des montants JOUÉS (``montant_joue``) des plans PRÉ-COURSE émis
    aujourd'hui (UTC) par ce destinataire — utilisée pour l'exposition maximale
    par jour (Point 12). Un même plan idempotent (même course/profil/montant)
    n'est compté qu'une fois grâce à l'unicité de ``bet_plan_snapshots``.

    0.0 si la table n'existe pas encore (migration 0031 pas appliquée) — n'échoue
    jamais, le plafond devient alors un no-op plutôt qu'une erreur 500.
    """
    if not subject or subject == SYSTEM_SUBJECT:
        return 0.0
    try:
        total = (await session.execute(text("""
            SELECT COALESCE(SUM(montant_joue), 0) FROM bet_plan_snapshots
            WHERE subject_hash = :sub AND is_pre_course = true
              AND emitted_at >= :day_start
        """), {"sub": subject,
               "day_start": datetime.now(timezone.utc).replace(
                   hour=0, minute=0, second=0, microsecond=0)})).scalar()
        return float(total or 0.0)
    except Exception as exc:
        if not is_missing_bet_plan_table(exc):
            raise
        try:
            await session.rollback()
        except Exception:
            pass
        return 0.0


async def latest_prediction_run_id(session, course_id: str) -> Optional[str]:
    """Cohorte de prédiction la plus récente figée avant le départ, si elle existe."""
    try:
        return (await session.execute(text("""
            SELECT prediction_run_id FROM prediction_snapshots
            WHERE course_id = :cid AND is_pre_course = true
            ORDER BY observed_at DESC
            LIMIT 1
        """), {"cid": course_id})).scalar()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        return None
