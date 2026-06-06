"""
Predictions & Value Bets routes — BlackTurf.
"""
import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

from api.routes.auth import get_current_user, require_pro
from db.database import get_db
from db.models import (
    Prediction, ValueBet, Recommandation, Participation,
    Cheval, Course, User
)

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class PredictionOut(BaseModel):
    prediction_id: str
    participation_id: str
    numero: int
    nom_cheval: str
    proba_top1: float
    proba_top3: float
    rang_predit: int
    confidence_score: Optional[float]
    cote_pmu: Optional[float]
    value_bet: Optional[dict]


class CoursePredictionsOut(BaseModel):
    course_id: str
    statut: str
    predictions: list[PredictionOut]
    recommandations: list[dict]


class ValueBetOut(BaseModel):
    vb_id: str
    course_id: str
    participation_id: str
    nom_cheval: str
    hippodrome_nom: str
    date_heure: datetime
    ev_max: float
    meilleure_source: Optional[str]
    niveau: int
    cote_pmu: Optional[float]
    spi_detected: bool = False
    spi_score: Optional[float] = None
    actif: bool
    detecte_a: datetime


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@router.get("/courses/{course_id}/predictions", response_model=CoursePredictionsOut)
async def get_predictions(
    course_id: str,
    bankroll: float = Query(default=100.0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Prédictions IA pour une course. Abonnés seulement."""
    if user.plan in ("free", "decouverte"):
        raise HTTPException(status_code=403, detail="Abonnement requis pour les prédictions IA")

    course_res = await db.execute(select(Course).where(Course.course_id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Charger prédictions + partants
    q = (
        select(Prediction, Participation, Cheval)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(Prediction.course_id == course_id)
        .order_by(Prediction.rang_predit)
    )
    rows = (await db.execute(q)).all()

    if not rows:
        # Lancer la prédiction en background si pas encore faite
        raise HTTPException(status_code=404, detail="Prédictions non disponibles pour cette course")

    # Charger les value bets associés
    vb_res = await db.execute(
        select(ValueBet)
        .where(and_(ValueBet.course_id == course_id, ValueBet.actif == True))
    )
    vbs_by_pid = {vb.participation_id: vb for vb in vb_res.scalars().all()}

    predictions = []
    for pred, part, cheval in rows:
        vb = vbs_by_pid.get(part.participation_id)
        predictions.append(PredictionOut(
            prediction_id=pred.prediction_id,
            participation_id=part.participation_id,
            numero=part.numero,
            nom_cheval=cheval.nom,
            proba_top1=round(pred.proba_top1, 4),
            proba_top3=round(pred.proba_top3, 4),
            rang_predit=pred.rang_predit,
            confidence_score=pred.confidence_score,
            cote_pmu=part.cote_pmu,
            value_bet={
                "ev_max": round(vb.ev_max, 4),
                "niveau": vb.niveau,
                "meilleure_source": vb.meilleure_source,
                "spi_detected": vb.spi_detected,
                "spi_score": round(vb.spi_score, 3) if vb.spi_score else None,
            } if vb else None,
        ))

    # Recommandations
    reco_res = await db.execute(
        select(Recommandation)
        .where(Recommandation.course_id == course_id)
        .order_by(Recommandation.created_at.desc())
        .limit(10)
    )
    recos = [
        {
            "reco_id": r.reco_id,
            "niveau": r.niveau,
            "type_pari": r.type_pari,
            "chevaux": r.chevaux_selectionnes,
            "mise_suggeree": r.mise_suggeree,
            "ev_calcule": r.ev_calcule,
            "confidence": r.confidence,
            "explication": r.texte_explication,
            "cout_total": r.cout_total,
        }
        for r in reco_res.scalars().all()
    ]

    return CoursePredictionsOut(
        course_id=course_id,
        statut=course.statut,
        predictions=predictions,
        recommandations=recos,
    )


@router.post("/courses/{course_id}/predict")
async def trigger_prediction(
    course_id: str,
    background_tasks: BackgroundTasks,
    bankroll: float = Query(default=100.0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_pro),
):
    """Déclenche le calcul de prédiction pour une course (async)."""
    course_res = await db.execute(select(Course).where(Course.course_id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")
    if course.statut == "termine":
        raise HTTPException(status_code=400, detail="Course déjà terminée")

    # Lancer le pipeline en background
    async def _run():
        from ml.pipeline import predict_course
        try:
            await predict_course(course_id, bankroll)
        except Exception as e:
            log.error("predictions.trigger_failed", course_id=course_id, error=str(e))

    background_tasks.add_task(_run)
    return {"ok": True, "message": "Prédiction en cours de calcul"}


@router.get("/value-bets", response_model=list[ValueBetOut])
async def get_value_bets_live(
    niveau_min: int = Query(default=1, ge=1, le=4),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_pro),
):
    """Value bets actifs (en direct). Abonnés seulement."""
    filters = [
        ValueBet.actif == True,
        ValueBet.niveau >= niveau_min,
        Course.statut.in_(["a_venir", "en_cours"]),
    ]
    # Standard plan: 15min delay on value bets (briefing §4.2)
    if user.plan == "standard":
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        filters.append(ValueBet.detecte_a <= cutoff)

    q = (
        select(ValueBet, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(and_(*filters))
        .order_by(desc(ValueBet.ev_max))
        .limit(limit)
    )
    rows = (await db.execute(q)).all()

    return [
        ValueBetOut(
            vb_id=vb.vb_id,
            course_id=vb.course_id,
            participation_id=vb.participation_id,
            nom_cheval=cheval.nom,
            hippodrome_nom=course.hippodrome_nom,
            date_heure=course.date_heure,
            ev_max=round(vb.ev_max, 4),
            meilleure_source=vb.meilleure_source,
            niveau=vb.niveau,
            cote_pmu=part.cote_pmu,
            spi_detected=vb.spi_detected,
            spi_score=round(vb.spi_score, 3) if vb.spi_score else None,
            actif=vb.actif,
            detecte_a=vb.detecte_a,
        )
        for vb, part, cheval, course in rows
    ]


@router.get("/value-bets/historique")
async def get_value_bets_history(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_pro),
):
    """Historique des value bets (cours terminées)."""
    q = (
        select(ValueBet, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(Course.statut == "termine")
        .order_by(desc(ValueBet.detecte_a))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "vb_id": vb.vb_id,
            "course_id": vb.course_id,
            "nom_cheval": cheval.nom,
            "hippodrome_nom": course.hippodrome_nom,
            "date_course": course.date_heure,
            "ev_max": round(vb.ev_max, 4),
            "niveau": vb.niveau,
            "cote_pmu": part.cote_pmu,
            "detecte_a": vb.detecte_a,
        }
        for vb, part, cheval, course in rows
    ]


@router.get("/courses/{course_id}/analyse")
async def get_course_analysis(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Analyse narrative complète d'une course :
    - Explication par partant (facteurs positifs/négatifs)
    - Narrative IA (Claude ou rule-based fallback)
    - Signaux marché résumés
    - Dutch bet si profitable
    Requiert plan Standard+.
    """
    if user.plan in ("free", "decouverte"):
        raise HTTPException(status_code=403, detail="Plan Standard ou Expert requis")

    # Charger features depuis DB
    from db.models import FeatureML, Prediction as PredictionModel, ValueBet as VBModel, Course
    from db.models import Participation, Cheval

    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Features par participation
    q = (
        select(FeatureML.participation_id, FeatureML.features,
               PredictionModel.proba_top3, PredictionModel.proba_top1, PredictionModel.rang_predit,
               Participation.numero, Cheval.nom,
               Participation.cote_pmu,
               func.least(
                   Participation.cote_pmu, Participation.cote_geny, Participation.cote_bzh,
                   Participation.cote_winamax, Participation.cote_betclic, Participation.cote_unibet,
               ).label("cote_min"),)
        .join(PredictionModel, PredictionModel.participation_id == FeatureML.participation_id, isouter=True)
        .join(Participation, Participation.participation_id == FeatureML.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(Participation.course_id == course_id)
    )
    rows = (await db.execute(q)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Prédictions non disponibles pour cette course")

    # VBs actifs
    vbs_r = await db.execute(
        select(VBModel.participation_id, VBModel.ev_max, VBModel.niveau, VBModel.spi_detected, VBModel.spi_score)
        .where(VBModel.course_id == course_id, VBModel.actif.is_(True))
    )
    vb_map = {r[0]: {"ev_max": r[1], "niveau": r[2], "spi_detected": r[3], "spi_score": r[4]}
              for r in vbs_r.fetchall()}

    predictions = []
    features_by_pid = {}
    for pid, feat, p3, p1, rang, num, nom, cote_pmu, cote_min in rows:
        features_by_pid[pid] = feat or {}
        predictions.append({
            "participation_id": pid,
            "numero": num,
            "nom": nom,
            "proba_top3": float(p3 or 0),
            "proba_top1": float(p1 or 0),
            "rang_predit": rang or 99,
            "cote_pmu": cote_pmu,
            "cote_min": cote_min,
            "vb": vb_map.get(pid),
        })

    # Cache Redis 2 min
    try:
        from db.redis_client import get_redis
        import json
        redis = await get_redis()
        cache_key = f"analyse:{course_id}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    from ml.narrative import generate_full_course_analysis
    from ml.portfolio import dutching_calculator

    course_info = {
        "hippodrome_nom": course.hippodrome_nom,
        "discipline": course.discipline,
        "distance": course.distance,
        "terrain_officiel": course.terrain_officiel,
        "nb_partants": course.nb_partants,
        "penetrometre_coef": course.penetrometre_coef,
        "est_quinte": course.est_quinte,
        "est_quarte": course.est_quarte,
        "est_tierce": course.est_tierce,
    }

    result = await generate_full_course_analysis(
        session=db,
        course_id=course_id,
        course_info=course_info,
        predictions=predictions,
        features_by_pid=features_by_pid,
    )

    # Dutch bet si ≥ 2 VBs
    vb_preds = [p for p in predictions if p.get("vb") and (p["vb"].get("ev_max") or 0) > 0.05]
    if len(vb_preds) >= 2:
        dutch = dutching_calculator(
            selections=[{"numero": p["numero"], "nom": p["nom"],
                         "cote": p.get("cote_pmu") or 5.0, "proba": p.get("proba_top1") or 0.1}
                        for p in vb_preds[:4]],
            budget=20.0,
        )
        if dutch.get("is_profitable"):
            result["dutch_bet"] = dutch

    # ── Paris multiples (probabilités simulées Plackett-Luce) ──
    try:
        from ml.combo_bets import build_combo_proposals
        result["paris_multiples"] = build_combo_proposals(predictions, course_info, bankroll=100.0)
    except Exception as e:
        log.warning("analyse.combo_bets_failed", course_id=course_id, err=str(e)[:160])

    # Cache 2 min
    try:
        await redis.setex(cache_key, 120, json.dumps(result, default=str))
    except Exception:
        pass

    return result


@router.get("/courses/{course_id}/dutch")
async def get_dutch_bet(
    course_id: str,
    budget: float = Query(default=20.0, ge=2.0, le=500.0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Calcule un Dutch bet pour les value bets de cette course.
    Garantit un gain fixe quel que soit le vainqueur parmi les sélections.
    """
    from db.models import ValueBet as VBModel, Participation, Cheval
    from ml.portfolio import dutching_calculator

    vbs_r = await db.execute(
        select(VBModel.participation_id, VBModel.ev_max, VBModel.niveau,
               Participation.numero, Participation.cote_pmu, Cheval.nom)
        .join(Participation, Participation.participation_id == VBModel.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(VBModel.course_id == course_id, VBModel.actif.is_(True), VBModel.niveau >= 2)
        .order_by(VBModel.ev_max.desc())
    )
    vbs = vbs_r.fetchall()
    if len(vbs) < 2:
        raise HTTPException(status_code=404, detail="Pas assez de value bets pour un Dutch (min 2)")

    selections = [{"numero": r[3], "nom": r[5], "cote": r[4] or 5.0, "proba": 1/(r[4] or 5.0)}
                  for r in vbs[:5]]
    return dutching_calculator(selections, budget)


@router.get("/courses/{course_id}/feature-importance")
async def get_feature_importance(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Retourne les groupes de features les plus impactants selon l'adaptive learning.
    Montre QUELS signaux ont le plus de poids pour les prédictions du modèle.
    """
    from ml.adaptive_learning import get_adaptive_learning
    al = get_adaptive_learning()
    ranking = al.get_feature_importance_ranking()
    return {
        "course_id": course_id,
        "feature_groups": ranking[:15],
        "temperature": round(al.temperature, 3),
        "brier_ema": round(al.brier_ema, 4),
        "n_races_appris": al.n_races_processed,
    }


@router.get("/model/version")
async def get_model_version(db: AsyncSession = Depends(get_db)):
    """Version du modèle actif + métriques. Public."""
    from db.models import ModelVersion
    result = await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )
    mv = result.scalar_one_or_none()
    if not mv:
        return {"version": None}
    return {
        "version_num": mv.version_num,
        "auc_roc": round(mv.auc_roc, 4),
        "brier_score": round(mv.brier_score, 4),
        "precision_top3": round(mv.precision_top3, 4),
        "roi_simule": round(mv.roi_simule, 4),
        "nb_courses_train": mv.nb_courses_train,
        "created_at": mv.created_at,
    }
