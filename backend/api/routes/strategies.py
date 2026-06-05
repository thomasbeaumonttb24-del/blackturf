"""
Stratégies — BlackTurf.
Créateur de filtres multi-critères + backtest simulé.
Plan Expert.
"""
import uuid
import structlog
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from api.routes.auth import get_current_user
from db.database import get_db
from db.models import User, Strategie, Course, Prediction, Participation, Cheval, Resultat

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class FiltresStrategie(BaseModel):
    discipline: Optional[str] = None          # Plat/Attelé/Haies/Steeple
    distance_min: Optional[int] = None
    distance_max: Optional[int] = None
    hippodrome: Optional[str] = None
    niveau_course: Optional[str] = None       # Group1/Listed/Conditions
    nb_partants_min: Optional[int] = None
    nb_partants_max: Optional[int] = None
    est_quinte: Optional[bool] = None
    terrain: Optional[str] = None

class IndicateursStrategie(BaseModel):
    proba_top3_min: float = 0.50
    ev_min: float = 0.05
    niveau_vb_min: int = 1
    elo_min: Optional[float] = None
    confidence_min: Optional[float] = None

class StrategieCreate(BaseModel):
    nom: str
    filtres: FiltresStrategie
    indicateurs: IndicateursStrategie
    alerte_email: bool = False
    partage_communaute: bool = False

class StrategieOut(BaseModel):
    strategie_id: str
    nom: str
    filtres: dict
    indicateurs: dict
    alerte_email: bool
    partage_communaute: bool
    created_at: datetime


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────
@router.get("/strategies", response_model=list[StrategieOut])
async def list_strategies(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.plan not in ("pro", "expert"):
        raise HTTPException(status_code=403, detail="Plan Expert requis")
    rows = (await db.execute(
        select(Strategie).where(Strategie.user_id == user.user_id).order_by(desc(Strategie.created_at))
    )).scalars().all()
    return [StrategieOut(
        strategie_id=s.strategie_id,
        nom=s.nom,
        filtres=s.filtres,
        indicateurs=s.indicateurs,
        alerte_email=s.alerte_email,
        partage_communaute=s.partage_communaute,
        created_at=s.created_at,
    ) for s in rows]


@router.post("/strategies", response_model=StrategieOut, status_code=201)
async def create_strategy(
    body: StrategieCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.plan not in ("pro", "expert"):
        raise HTTPException(status_code=403, detail="Plan Expert requis")

    s = Strategie(
        strategie_id=str(uuid.uuid4()),
        user_id=user.user_id,
        nom=body.nom,
        filtres=body.filtres.model_dump(exclude_none=True),
        indicateurs=body.indicateurs.model_dump(exclude_none=True),
        alerte_email=body.alerte_email,
        partage_communaute=body.partage_communaute,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    log.info("strategies.created", strategie_id=s.strategie_id, user_id=user.user_id)
    return StrategieOut(
        strategie_id=s.strategie_id,
        nom=s.nom,
        filtres=s.filtres,
        indicateurs=s.indicateurs,
        alerte_email=s.alerte_email,
        partage_communaute=s.partage_communaute,
        created_at=s.created_at,
    )


@router.patch("/strategies/{strategie_id}", response_model=StrategieOut)
async def update_strategy(
    strategie_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Strategie).where(
            and_(Strategie.strategie_id == strategie_id, Strategie.user_id == user.user_id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Stratégie introuvable")

    for k, v in body.items():
        if k in ("nom", "alerte_email", "partage_communaute"):
            setattr(s, k, v)
    await db.commit()
    return StrategieOut(
        strategie_id=s.strategie_id,
        nom=s.nom,
        filtres=s.filtres,
        indicateurs=s.indicateurs,
        alerte_email=s.alerte_email,
        partage_communaute=s.partage_communaute,
        created_at=s.created_at,
    )


@router.delete("/strategies/{strategie_id}", status_code=204)
async def delete_strategy(
    strategie_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Strategie).where(
            and_(Strategie.strategie_id == strategie_id, Strategie.user_id == user.user_id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Stratégie introuvable")
    await db.delete(s)
    await db.commit()


# ─────────────────────────────────────────────
# Backtest
# ─────────────────────────────────────────────
@router.post("/strategies/{strategie_id}/backtest")
async def backtest_strategy(
    strategie_id: str,
    jours: int = Query(default=90, ge=7, le=365),
    mise_fixe: float = Query(default=10.0, ge=1.0, le=1000.0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Simule l'application de la stratégie sur les N derniers jours."""
    if user.plan not in ("standard", "pro", "expert"):
        raise HTTPException(status_code=403, detail="Abonnement Standard ou Expert requis")

    max_jours = 365 if user.plan in ("pro", "expert") else 7
    jours = min(jours, max_jours)

    result = await db.execute(
        select(Strategie).where(
            and_(Strategie.strategie_id == strategie_id, Strategie.user_id == user.user_id)
        )
    )
    strat = result.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="Stratégie introuvable")

    filtres = strat.filtres
    indicateurs = strat.indicateurs
    since = datetime.now().replace(tzinfo=None) - timedelta(days=jours)

    # Requête des prédictions sur les courses terminées matchant les filtres
    q = (
        select(Prediction, Participation, Cheval, Course, Resultat)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == Prediction.course_id)
        .outerjoin(Resultat, Resultat.course_id == Course.course_id)
        .where(
            Course.statut == "termine",
            Course.date_heure >= since,
        )
    )

    # Appliquer filtres cours
    if filtres.get("discipline"):
        q = q.where(Course.discipline == filtres["discipline"])
    if filtres.get("distance_min"):
        q = q.where(Course.distance >= filtres["distance_min"])
    if filtres.get("distance_max"):
        q = q.where(Course.distance <= filtres["distance_max"])
    if filtres.get("est_quinte"):
        q = q.where(Course.est_quinte == True)

    rows = (await db.execute(q.limit(2000))).all()

    # Simuler les paris selon les indicateurs
    proba_min = indicateurs.get("proba_top3_min", 0.5)
    ev_min = indicateurs.get("ev_min", 0.05)
    elo_min = indicateurs.get("elo_min")

    mise_totale = 0.0
    gains_totaux = 0.0
    nb_paris = 0
    nb_gagnants = 0
    serie_perdante = 0
    serie_max_perdante = 0
    courbe: list[dict] = []
    bankroll = 0.0

    for pred, part, cheval, course, resultat in rows:
        if pred.proba_top3 < proba_min:
            continue
        if not part.cote_pmu or part.cote_pmu <= 1:
            continue

        ev = (part.cote_pmu * pred.proba_top3) - 1
        if ev < ev_min:
            continue

        if elo_min and cheval.elo_score_global < elo_min:
            continue

        # Ce cheval satisfait la stratégie → on parie
        mise = mise_fixe
        nb_paris += 1
        mise_totale += mise

        # Vérifier si gagné (position 1 dans le résultat)
        gagne = False
        if resultat and resultat.classement:
            classement = resultat.classement
            if isinstance(classement, list) and classement:
                premier = classement[0]
                if isinstance(premier, dict) and premier.get("numero") == part.numero:
                    gagne = True

        if gagne:
            gain = mise * part.cote_pmu
            gains_totaux += gain
            bankroll += gain - mise
            nb_gagnants += 1
            serie_perdante = 0
        else:
            bankroll -= mise
            serie_perdante += 1
            serie_max_perdante = max(serie_max_perdante, serie_perdante)

        courbe.append({
            "date": course.date_heure.strftime("%Y-%m-%d"),
            "bankroll": round(bankroll, 2),
        })

    roi = (gains_totaux - mise_totale) / mise_totale * 100 if mise_totale > 0 else 0

    return {
        "strategie_id": strategie_id,
        "periode_jours": jours,
        "nb_paris": nb_paris,
        "mise_totale": round(mise_totale, 2),
        "gains_totaux": round(gains_totaux, 2),
        "gain_net": round(gains_totaux - mise_totale, 2),
        "roi_pct": round(roi, 2),
        "taux_reussite": round(nb_gagnants / nb_paris * 100, 1) if nb_paris else 0,
        "serie_max_perdante": serie_max_perdante,
        "courbe": courbe[-100:],  # dernier 100 points pour le graphique
        "avertissement": "Simulation basée sur données historiques. Les résultats passés ne garantissent pas les performances futures.",
    }


@router.get("/strategies/communaute")
async def communaute_strategies(
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stratégies partagées par la communauté."""
    rows = (await db.execute(
        select(Strategie).where(Strategie.partage_communaute == True).order_by(desc(Strategie.created_at)).limit(limit)
    )).scalars().all()
    return [
        {
            "strategie_id": s.strategie_id,
            "nom": s.nom,
            "filtres": s.filtres,
            "indicateurs": s.indicateurs,
        }
        for s in rows
    ]
