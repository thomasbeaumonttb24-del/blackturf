"""
Courses routes — BlackTurf.
Programme du jour, détail course, partants.
"""
import structlog
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text

from api.routes.auth import get_current_user, require_pro
from api.middleware.rate_limit import rate_limit_public
from db.database import get_db
from db.redis_client import get_redis
from db.models import (
    Course, Reunion, Hippodrome, Participation, Cheval,
    Jockey, Entraineur, Equipement, MeteoCourse, Resultat,
    Prediction as PredictionModel,
    SuspensionProfessionnel, PronosticPresse, TempsPassage,
    AssociationJockeyEntraineur, PenetrometreLog,
)
from db.models import User
from ml.portfolio import BetPortfolioEngine
from ml.adaptive_learning import get_adaptive_learning
from ml.monte_carlo import MonteCarloSimulator

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class PartantOut(BaseModel):
    participation_id: str
    numero: int
    nom_cheval: str
    age: Optional[int]
    sexe: Optional[str]
    jockey: Optional[str]
    entraineur: Optional[str]
    # Cotes multi-sources
    cote_pmu: Optional[float]
    cote_geny: Optional[float]
    cote_winamax: Optional[float]
    cote_betclic: Optional[float]
    cote_betclic_ouverture: Optional[float]   # cote J-1 → steam move si écart > 20%
    cote_unibet: Optional[float]
    cote_betfair_exchange: Optional[float]    # plus efficient du marché
    cote_min: Optional[float]                 # meilleure cote disponible
    cote_max: Optional[float]                 # cote la plus haute
    nb_sources: int = 0                       # nb de sources ayant coté ce partant
    # Mouvement de cote
    mouvement_cote_pct: Optional[float]       # % de variation cote ouverture → actuelle (betclic)
    # Données partant
    musique: Optional[str]
    non_partant: bool
    elo_global: Optional[float]
    # Équipement
    deferre: Optional[str]
    oeilleres: Optional[str]
    premier_deferre: bool
    premieres_oeilleres: bool
    # Nouvelles données
    running_style: Optional[str]              # mene/suit_tete/placier/ferme
    changement_jockey: bool = False           # jockey différent de la dernière course
    jours_depuis_derniere: Optional[int]      # freshness
    poids_reel_pesee: Optional[float]         # post-pesée officielle
    # Généalogie
    pere: Optional[str]
    mere: Optional[str]
    pere_de_mere: Optional[str]
    prix_vente_yearling: Optional[int]
    # Association jockey×entraîneur
    asso_jockey_entraineur_taux: Optional[float]   # win rate de la paire cette saison
    asso_jockey_entraineur_nb: Optional[int]
    # Suspension active
    jockey_suspendu: bool = False
    entraineur_suspendu: bool = False


class MeteoOut(BaseModel):
    terrain_officiel: Optional[str]
    temperature: Optional[float]
    vent_vitesse: Optional[float]
    pluie_24h: Optional[float]
    humidite: Optional[float]


class PronosticPresseOut(BaseModel):
    source: str
    journaliste: Optional[str]
    selection: list   # [{"rang": 1, "numero": 3, "nom": "CHEVAL X"}]
    commentaire: Optional[str]


class CourseDetailOut(BaseModel):
    course_id: str
    nom: Optional[str]
    reunion_id: str
    numero: int
    date_heure: datetime
    hippodrome_nom: str
    discipline: str
    distance: int
    terrain_officiel: Optional[str]
    nb_partants: int
    allocation: Optional[int]
    niveau_course: Optional[str]
    est_quinte: bool
    est_quarte: bool
    est_tierce: bool
    statut: str
    # Nouvelles données course
    penetrometre_coef: Optional[float]        # coefficient 0-9 France Galop
    penetrometre_desc: Optional[str]          # Bon / Souple / Lourd
    pool_total_eur: Optional[int]             # pool total en euros
    pool_gagnant_eur: Optional[int]
    pool_gagnant_evolution: Optional[float] = None  # taux croissance pool (smart money)
    avantage_couloir: Optional[str]           # interieur / exterieur / neutre
    # Enrichissements PMU course
    conditions_texte: Optional[str] = None
    categorie_particularite: Optional[str] = None
    montant_offert_1er: Optional[int] = None        # dotation gagnant (euros)
    nombre_declares_partants: Optional[int] = None
    meteo: Optional[MeteoOut]
    pronostics_presse: list[PronosticPresseOut] = []
    partants: list[PartantOut]


class CourseSummary(BaseModel):
    course_id: str
    nom: Optional[str]
    reunion_id: str
    numero: int
    date_heure: datetime
    hippodrome_nom: str
    discipline: str
    distance: int
    nb_partants: int
    statut: str
    est_quinte: bool
    est_quarte: bool
    est_tierce: bool
    # Données synthèse pour la liste
    penetrometre_coef: Optional[float] = None
    penetrometre_desc: Optional[str] = None
    pool_total_eur: Optional[int] = None


class ProgrammeOut(BaseModel):
    date: date
    nb_courses: int
    reunions: list[dict]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
async def _load_partants(course_id: str, db: AsyncSession) -> list[PartantOut]:
    from datetime import date as date_type
    today = date_type.today()

    # Suspensions actives aujourd'hui (jockeys + entraîneurs)
    susp_res = await db.execute(
        select(SuspensionProfessionnel.nom, SuspensionProfessionnel.type_pro)
        .where(
            SuspensionProfessionnel.est_active.is_(True),
            SuspensionProfessionnel.date_debut <= today,
        )
    )
    suspendus: dict[str, str] = {r.nom.lower(): r.type_pro for r in susp_res.fetchall()}

    q = (
        select(Participation, Cheval, Jockey, Entraineur, Equipement)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .outerjoin(Jockey, Jockey.jockey_id == Participation.jockey_id)
        .outerjoin(Entraineur, Entraineur.entraineur_id == Participation.entraineur_id)
        .outerjoin(Equipement, Equipement.participation_id == Participation.participation_id)
        .where(Participation.course_id == course_id)
        .order_by(Participation.numero)
    )
    rows = (await db.execute(q)).all()

    # Associations jockey × entraîneur pour les paires de cette course
    asso_map: dict[tuple, dict] = {}
    try:
        from datetime import datetime as dt
        saison = dt.now().year
        asso_res = await db.execute(
            select(
                AssociationJockeyEntraineur.jockey_id,
                AssociationJockeyEntraineur.entraineur_id,
                AssociationJockeyEntraineur.taux_victoire,
                AssociationJockeyEntraineur.nb_courses,
            ).where(AssociationJockeyEntraineur.saison == saison)
        )
        for r in asso_res.fetchall():
            asso_map[(r.jockey_id, r.entraineur_id)] = {
                "taux": r.taux_victoire,
                "nb": r.nb_courses,
            }
    except Exception:
        pass

    partants = []
    for p, ch, j, en, eq in rows:
        # Cotes disponibles
        cotes = [c for c in [p.cote_pmu, p.cote_geny, p.cote_winamax,
                              p.cote_betclic, p.cote_unibet, p.cote_betfair_exchange]
                 if c and c > 1.0]
        cote_min = min(cotes) if cotes else None
        cote_max = max(cotes) if cotes else None
        nb_sources = len(cotes)

        # Mouvement cote Betclic : ouverture → actuelle
        mouvement = None
        if p.cote_betclic_ouverture and p.cote_betclic and p.cote_betclic_ouverture > 1.0:
            mouvement = round(
                (p.cote_betclic_ouverture - p.cote_betclic) / p.cote_betclic_ouverture * 100, 1
            )  # positif = cote a baissé (argent dessus)

        # Association jockey × entraîneur
        asso = asso_map.get((p.jockey_id, p.entraineur_id)) if p.jockey_id and p.entraineur_id else None

        # Suspensions
        jockey_nom = (j.nom if j else "").lower()
        entraineur_nom = (en.nom if en else "").lower()
        jockey_suspendu = jockey_nom in suspendus and suspendus[jockey_nom] == "jockey"
        entraineur_suspendu = entraineur_nom in suspendus and suspendus[entraineur_nom] == "entraineur"

        partants.append(PartantOut(
            participation_id=p.participation_id,
            numero=p.numero,
            nom_cheval=ch.nom,
            age=ch.age,
            sexe=ch.sexe,
            jockey=j.nom if j else None,
            entraineur=en.nom if en else None,
            # Cotes
            cote_pmu=p.cote_pmu,
            cote_geny=p.cote_geny,
            cote_winamax=p.cote_winamax,
            cote_betclic=p.cote_betclic,
            cote_betclic_ouverture=p.cote_betclic_ouverture,
            cote_unibet=p.cote_unibet,
            cote_betfair_exchange=p.cote_betfair_exchange,
            cote_min=cote_min,
            cote_max=cote_max,
            nb_sources=nb_sources,
            mouvement_cote_pct=mouvement,
            # Musique / status
            musique=p.musique,
            non_partant=p.non_partant,
            elo_global=ch.elo_score_global,
            # Équipement
            deferre=eq.deferre if eq else None,
            oeilleres=eq.oeilleres if eq else None,
            premier_deferre=eq.premier_deferre if eq else False,
            premieres_oeilleres=eq.premieres_oeilleres if eq else False,
            # Nouvelles données
            running_style=ch.running_style,
            changement_jockey=p.changement_jockey or False,
            jours_depuis_derniere=p.jours_depuis_derniere,
            poids_reel_pesee=p.poids_reel_pesee,
            # Généalogie
            pere=ch.pere,
            mere=ch.mere,
            pere_de_mere=ch.pere_de_mere,
            prix_vente_yearling=ch.prix_vente_yearling,
            # Association J×E
            asso_jockey_entraineur_taux=asso["taux"] if asso else None,
            asso_jockey_entraineur_nb=asso["nb"] if asso else None,
            # Suspensions
            jockey_suspendu=jockey_suspendu,
            entraineur_suspendu=entraineur_suspendu,
        ))
    return partants


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@router.get("/programme", response_model=ProgrammeOut)
async def get_programme(
    jour: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit_public),
):
    """Programme du jour (ou date fournie). Public. Cache Redis 120s."""
    import json
    target = jour or date.today()

    try:
        redis = await get_redis()
        cache_key = f"programme:{target.isoformat()}"
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return ProgrammeOut(**data)
    except Exception:
        pass  # Redis indisponible → continuer sans cache

    q = (
        select(Course, Reunion)
        .join(Reunion, Reunion.reunion_id == Course.reunion_id)
        .where(func.date(Course.date_heure) == target)
        .where(Course.statut != "annule")   # masque les courses annulées / obsolètes
        .order_by(Course.date_heure)
    )
    rows = (await db.execute(q)).all()

    # Regrouper par réunion
    reunions_dict: dict = {}
    for course, reunion in rows:
        rid = reunion.reunion_id
        if rid not in reunions_dict:
            reunions_dict[rid] = {
                "reunion_id": rid,
                "hippodrome": reunion.hippodrome_nom,
                "numero": reunion.numero,
                "courses": [],
            }
        reunions_dict[rid]["courses"].append(CourseSummary(
            course_id=course.course_id,
            nom=course.nom,
            reunion_id=course.reunion_id,
            numero=course.numero,
            date_heure=course.date_heure,
            hippodrome_nom=course.hippodrome_nom,
            discipline=course.discipline,
            distance=course.distance,
            nb_partants=course.nb_partants,
            statut=course.statut,
            est_quinte=course.est_quinte,
            est_quarte=course.est_quarte,
            est_tierce=course.est_tierce,
            penetrometre_coef=course.penetrometre_coef,
            penetrometre_desc=course.penetrometre_desc,
            pool_total_eur=int(course.pool_total_centimes / 100) if course.pool_total_centimes else None,
        ).model_dump())

    result = ProgrammeOut(
        date=target,
        nb_courses=len(rows),
        reunions=list(reunions_dict.values()),
    )

    # Stocker en cache — TTL plus court si c'est aujourd'hui (données live)
    try:
        redis = await get_redis()
        ttl = 60 if target == date.today() else 3600   # 1 min live, 1h passé
        await redis.setex(cache_key, ttl, json.dumps(result.model_dump(), default=str))
    except Exception:
        pass

    return result


@router.get("/courses/{course_id}", response_model=CourseDetailOut)
async def get_course(course_id: str, db: AsyncSession = Depends(get_db)):
    """Détail d'une course + partants. Public. Cache Redis TTL variable."""
    import json

    try:
        redis = await get_redis()
        cache_key = f"course_detail:{course_id}"
        cached = await redis.get(cache_key)
        if cached:
            return CourseDetailOut(**json.loads(cached))
    except Exception:
        pass

    result = await db.execute(select(Course).where(Course.course_id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Météo
    meteo_res = await db.execute(select(MeteoCourse).where(MeteoCourse.course_id == course_id))
    meteo = meteo_res.scalar_one_or_none()
    meteo_out = MeteoOut(
        terrain_officiel=meteo.terrain_officiel if meteo else None,
        temperature=meteo.temperature if meteo else None,
        vent_vitesse=meteo.vent_vitesse if meteo else None,
        pluie_24h=meteo.pluie_24h if meteo else None,
        humidite=meteo.humidite if meteo else None,
    ) if meteo else None

    partants = await _load_partants(course_id, db)

    # Pronostics presse
    pp_res = await db.execute(
        select(PronosticPresse)
        .where(PronosticPresse.course_id == course_id)
        .order_by(PronosticPresse.source)
    )
    pronostics_presse = [
        PronosticPresseOut(
            source=pp.source,
            journaliste=pp.journaliste,
            selection=pp.selection or [],
            commentaire=pp.commentaire,
        )
        for pp in pp_res.scalars().all()
    ]

    response = CourseDetailOut(
        course_id=course.course_id,
        nom=course.nom,
        reunion_id=course.reunion_id,
        numero=course.numero,
        date_heure=course.date_heure,
        hippodrome_nom=course.hippodrome_nom,
        discipline=course.discipline,
        distance=course.distance,
        terrain_officiel=course.terrain_officiel,
        nb_partants=course.nb_partants,
        allocation=course.allocation,
        niveau_course=course.niveau_course,
        est_quinte=course.est_quinte,
        est_quarte=course.est_quarte,
        est_tierce=course.est_tierce,
        statut=course.statut,
        penetrometre_coef=course.penetrometre_coef,
        penetrometre_desc=course.penetrometre_desc,
        pool_total_eur=int(course.pool_total_centimes / 100) if course.pool_total_centimes else None,
        pool_gagnant_eur=int(course.pool_gagnant_centimes / 100) if course.pool_gagnant_centimes else None,
        pool_gagnant_evolution=course.pool_gagnant_evolution,
        avantage_couloir=course.avantage_couloir,
        conditions_texte=course.conditions_texte,
        categorie_particularite=course.categorie_particularite,
        montant_offert_1er=course.montant_offert_1er,
        nombre_declares_partants=course.nombre_declares_partants,
        meteo=meteo_out,
        pronostics_presse=pronostics_presse,
        partants=partants,
    )

    # Cache TTL selon statut
    try:
        redis = await get_redis()
        ttl = {
            "a_venir":  30,    # 30s — cotes live changent fréquemment
            "en_cours": 15,    # 15s — pool + cotes live
            "termine":  3600,  # 1h  — données figées
            "annule":   86400, # 24h — figé définitivement
        }.get(course.statut, 30)
        await redis.setex(
            f"course_detail:{course_id}", ttl,
            json.dumps(response.model_dump(), default=str)
        )
    except Exception:
        pass

    return response


@router.get("/courses/{course_id}/resultats")
async def get_resultats(course_id: str, db: AsyncSession = Depends(get_db)):
    """Résultats officiels d'une course terminée."""
    result = await db.execute(select(Resultat).where(Resultat.course_id == course_id))
    res = result.scalar_one_or_none()
    if not res:
        raise HTTPException(status_code=404, detail="Résultats non disponibles")
    return {
        "course_id": course_id,
        "classement": res.classement,
        "rapports": res.rapports,
        "temps_gagnant": res.temps_gagnant,
        "incidents": res.incidents,
        "commentaire": res.commentaire,              # narratif post-course PMU/GENY
        "duree_course": res.duree_course,            # ms
    }


@router.get("/courses/{course_id}/cotes-historique")
async def get_cotes_historique(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_pro),
):
    """Historique des cotes (réservé abonnés). Données TimescaleDB."""
    from db.models import CoteHistorique, Participation
    q = (
        select(CoteHistorique)
        .join(Participation, Participation.participation_id == CoteHistorique.participation_id)
        .where(Participation.course_id == course_id)
        .order_by(CoteHistorique.time)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "time": r.time,
            "participation_id": r.participation_id,
            "source": r.source,
            "cote": r.cote,
        }
        for r in rows
    ]


@router.post("/courses/{course_id}/mise-plan")
async def get_mise_plan(
    course_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Génère un plan de mise personnalisé selon montant + profil.
    Requiert plan Standard ou Expert.
    """
    from services.mise_calculator import generer_plan, plan_to_dict
    from db.models import Prediction as PredModel, ValueBet

    if user.plan in ("free", "decouverte"):
        from fastapi import HTTPException as _H
        raise _H(status_code=403, detail="Plan Standard ou Expert requis")

    montant = float(body.get("montant", 0))
    if montant <= 0 or montant > 10000:
        from fastapi import HTTPException as _H
        raise _H(status_code=422, detail="Montant invalide (0.01–10000€)")

    profil = body.get("profil_risque") or (user.profil_risque or "equilibre")
    bankroll = body.get("bankroll") or user.bankroll_initiale

    # Charger la course
    course_res = await db.execute(select(Course).where(Course.course_id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Charger prédictions + value bets
    from sqlalchemy import select as _s
    from db.models import Prediction as Pred
    q = (
        _s(Pred, Participation, Cheval)
        .join(Participation, Participation.participation_id == Pred.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(Participation.course_id == course_id)
        .order_by(Pred.rang_predit)
    )
    rows = (await db.execute(q)).all()

    # Value bets
    vb_q = (
        _s(ValueBet)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .where(Participation.course_id == course_id)
        .where(ValueBet.actif.is_(True))
    )
    vbs = {v.participation_id: v for v in (await db.execute(vb_q)).scalars()}

    preds = []
    for pred, part, cheval in rows:
        vb = vbs.get(pred.participation_id)
        preds.append({
            "numero": part.numero,
            "nom_cheval": cheval.nom,
            "proba_top3": pred.proba_top3,
            "proba_top1": pred.proba_top1,
            "cote_pmu": part.cote_pmu,
            "non_partant": part.non_partant,
            "value_bet": {"ev_max": vb.ev_max, "niveau": vb.niveau} if vb else None,
        })

    course_info = {
        "est_quinte": course.est_quinte,
        "est_quarte": course.est_quarte,
        "nb_partants": course.nb_partants,
    }

    plan = generer_plan(montant, profil, preds, course_info, bankroll)
    return plan_to_dict(plan)


@router.get("/courses/{course_id}/comparaison-cotes")
async def get_comparaison_cotes(
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Comparaison multi-bookmakers des cotes pour une course.
    Retourne pour chaque partant : PMU, Geny, Winamax, Betclic, Unibet, Betfair.
    Public — les cotes sont des données publiques.
    """
    result = await db.execute(text("""
        SELECT
            p.numero,
            ch.nom,
            p.cote_pmu,
            p.cote_geny,
            p.cote_winamax,
            p.cote_betclic,
            p.cote_betclic_ouverture,
            p.cote_unibet,
            p.cote_betfair_exchange,
            p.mouvement_cote_pct
        FROM participations p
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        WHERE p.course_id = :cid AND p.non_partant = false
        ORDER BY p.numero
    """), {"cid": course_id})
    rows = result.fetchall()

    return [
        {
            "numero": r[0],
            "nom": r[1],
            "cotes": {
                "pmu":           r[2],
                "geny":          r[3],
                "winamax":       r[4],
                "betclic":       r[5],
                "betclic_ouv":   r[6],   # cote d'ouverture J-1
                "unibet":        r[7],
                "betfair":       r[8],   # exchange
            },
            "cote_min": min(
                c for c in [r[2], r[3], r[4], r[5], r[7], r[8]] if c and c > 1.0
            ) if any(c for c in [r[2], r[3], r[4], r[5], r[7], r[8]] if c and c > 1.0) else None,
            "mouvement_pct": r[9],  # positif = cote baissée = argent dessus
            "is_value": (
                r[2] is not None and r[8] is not None
                and r[2] > r[8] * 1.10  # PMU > Betfair × 1.10 = value bet potentiel
            ),
        }
        for r in rows
    ]


@router.get("/courses/{course_id}/pool-evolution")
async def get_pool_evolution(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_pro),
):
    """
    Évolution du pool PMU dans le temps (smart money indicator).
    Réservé abonnés Standard+.
    """
    from db.models import PoolPMUHistorique
    result = await db.execute(
        select(PoolPMUHistorique)
        .where(PoolPMUHistorique.course_id == course_id)
        .order_by(PoolPMUHistorique.scraped_at)
    )
    rows = result.scalars().all()

    data = [
        {
            "time": r.scraped_at.isoformat(),
            "pool_total_eur": int(r.pool_total_centimes / 100) if r.pool_total_centimes else 0,
            "pool_gagnant_eur": int(r.pool_gagnant_centimes / 100) if r.pool_gagnant_centimes else 0,
            "nb_parieurs": r.nb_parieurs,
        }
        for r in rows
    ]

    # Détecter les mouvements forts (variation > 20% sur 15 min)
    smart_money_alerts = []
    for i in range(1, len(data)):
        prev = data[i - 1]["pool_total_eur"] or 0
        curr = data[i]["pool_total_eur"] or 0
        if prev > 0 and curr > 0:
            variation = (curr - prev) / prev
            if variation > 0.20:
                smart_money_alerts.append({
                    "time": data[i]["time"],
                    "variation_pct": round(variation * 100, 1),
                    "pool_eur": curr,
                })

    return {
        "course_id": course_id,
        "evolution": data,
        "smart_money_alerts": smart_money_alerts,
        "dernier_pool_eur": data[-1]["pool_total_eur"] if data else 0,
    }


@router.get("/courses/{course_id}/temps-passage")
async def get_temps_passage(
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Temps de passage (splits) post-course. Disponible après résultat."""
    result = await db.execute(
        select(TempsPassage)
        .where(TempsPassage.course_id == course_id)
        .order_by(TempsPassage.numero)
    )
    rows = result.scalars().all()
    if not rows:
        return []
    return [
        {
            "numero": r.numero,
            "nom": r.nom_cheval,
            "passage_400m": r.passage_400m,
            "passage_800m": r.passage_800m,
            "passage_1000m": r.passage_1000m,
            "passage_1600m": r.passage_1600m,
            "passage_dernier_400m": r.passage_dernier_400m,
            "vitesse_max_kmh": r.vitesse_max_kmh,
            "position_500m": r.position_500m,
        }
        for r in rows
    ]


@router.get("/courses/{course_id}/confrontations")
async def get_confrontations(course_id: str, db: AsyncSession = Depends(get_db)):
    """
    Confrontations directes entre les partants : qui a déjà battu qui, combien
    de fois, écart moyen et dernière rencontre. Calculé depuis l'historique.
    """
    from services.confrontations import compute_confrontations
    return await compute_confrontations(db, course_id)


@router.get("/suspensions")
async def get_suspensions_actives(db: AsyncSession = Depends(get_db)):
    """Liste des suspensions actives aujourd'hui. Public."""
    from datetime import date as date_type
    today = date_type.today()
    result = await db.execute(
        select(SuspensionProfessionnel)
        .where(
            SuspensionProfessionnel.est_active.is_(True),
            SuspensionProfessionnel.date_debut <= today,
        )
        .order_by(SuspensionProfessionnel.nom)
    )
    return [
        {
            "nom": s.nom,
            "type_pro": s.type_pro,
            "source": s.source,
            "date_debut": s.date_debut,
            "date_fin": s.date_fin,
            "nb_jours": s.nb_jours,
            "motif": s.motif,
        }
        for s in result.scalars().all()
    ]


@router.get("/recherche")
async def recherche(
    q: str = Query(..., min_length=2, max_length=100),
    type: str = Query(default="all"),   # all / cheval / jockey / hippodrome / course
    limit: int = Query(default=10, le=20),
    db: AsyncSession = Depends(get_db),
):
    """
    Recherche full-text sur chevaux, jockeys, hippodromes, courses du jour.
    Tri : exact match → starts_with → contains.
    """
    results = []
    q_clean = q.strip()
    q_ilike = f"%{q_clean}%"
    q_starts = f"{q_clean}%"

    if type in ("all", "cheval"):
        # Chevaux — exact first, then starts-with, then contains
        chevaux_r = await db.execute(text("""
            SELECT cheval_id, nom, age, sexe, running_style, elo_score_global,
                CASE
                    WHEN UPPER(nom) = UPPER(:exact) THEN 0
                    WHEN UPPER(nom) LIKE UPPER(:starts) THEN 1
                    ELSE 2
                END AS relevance
            FROM chevaux
            WHERE nom ILIKE :contains
            ORDER BY relevance, nom
            LIMIT :lim
        """), {"exact": q_clean, "starts": q_starts, "contains": q_ilike, "lim": limit})
        for r in chevaux_r.fetchall():
            results.append({
                "type": "cheval",
                "id": r[0],
                "label": r[1],
                "sub": f"{r[2]}a · {r[3] or ''} · ELO {int(r[5] or 1500)}",
                "running_style": r[4],
                "relevance": r[6],
            })

    if type in ("all", "jockey"):
        jockeys_r = await db.execute(text("""
            SELECT j.jockey_id, j.nom, j.nationalite,
                sj.taux_victoire_global, sj.victoires_saison,
                CASE
                    WHEN UPPER(j.nom) = UPPER(:exact) THEN 0
                    WHEN UPPER(j.nom) LIKE UPPER(:starts) THEN 1
                    ELSE 2
                END AS relevance
            FROM jockeys j
            LEFT JOIN stats_jockeys sj ON sj.jockey_id = j.jockey_id
                AND sj.saison = EXTRACT(YEAR FROM NOW())
            WHERE j.nom ILIKE :contains
            ORDER BY relevance, j.nom
            LIMIT :lim
        """), {"exact": q_clean, "starts": q_starts, "contains": q_ilike, "lim": limit})
        for r in jockeys_r.fetchall():
            taux = round(float(r[3] or 0) * 100, 1)
            results.append({
                "type": "jockey",
                "id": r[0],
                "label": r[1],
                "sub": f"{r[2] or 'FR'} · {r[4] or 0} victoires · {taux}% win rate",
                "relevance": r[5],
            })

    if type in ("all", "hippodrome"):
        hippos_r = await db.execute(text("""
            SELECT hippodrome_id, nom, ville, type_piste,
                CASE
                    WHEN UPPER(nom) = UPPER(:exact) THEN 0
                    WHEN UPPER(nom) LIKE UPPER(:starts) THEN 1
                    ELSE 2
                END AS relevance
            FROM hippodromes
            WHERE nom ILIKE :contains
            ORDER BY relevance, nom
            LIMIT :lim
        """), {"exact": q_clean, "starts": q_starts, "contains": q_ilike, "lim": limit})
        for r in hippos_r.fetchall():
            results.append({
                "type": "hippodrome",
                "id": r[0],
                "label": r[1],
                "sub": f"{r[2] or ''} · {r[3] or 'Mixte'}",
                "relevance": r[4],
            })

    if type in ("all", "course"):
        from datetime import date as date_type
        today = date_type.today()
        courses_r = await db.execute(text("""
            SELECT course_id, nom, hippodrome_nom, date_heure, discipline, statut,
                CASE
                    WHEN UPPER(nom) = UPPER(:exact) THEN 0
                    WHEN UPPER(nom) LIKE UPPER(:starts) THEN 1
                    ELSE 2
                END AS relevance
            FROM courses
            WHERE nom ILIKE :contains AND DATE(date_heure) = :today
            ORDER BY relevance, date_heure
            LIMIT :lim
        """), {"exact": q_clean, "starts": q_starts, "contains": q_ilike, "today": today, "lim": limit})
        for r in courses_r.fetchall():
            heure = r[3].strftime("%H:%M") if r[3] else ""
            results.append({
                "type": "course",
                "id": r[0],
                "label": r[1] or f"Course {r[0]}",
                "sub": f"{r[2]} · {heure} · {r[4]} · {r[5]}",
                "relevance": r[6],
            })

    # Trier par relevance globale puis type
    results.sort(key=lambda x: (x.pop("relevance", 2), x["type"]))
    return results[:limit]


@router.get("/chevaux/{cheval_id}")
async def get_cheval(cheval_id: str, db: AsyncSession = Depends(get_db)):
    """Fiche cheval enrichie avec historique 30 courses, ELO trend, stats conditions."""
    from db.models import HistoriqueCourse, PerformanceCarriere, EloHistorique

    result = await db.execute(select(Cheval).where(Cheval.cheval_id == cheval_id))
    cheval = result.scalar_one_or_none()
    if not cheval:
        raise HTTPException(status_code=404, detail="Cheval introuvable")

    perf_res = await db.execute(
        select(PerformanceCarriere).where(PerformanceCarriere.cheval_id == cheval_id)
    )
    perf = perf_res.scalar_one_or_none()

    # Last 30 races
    hist_res = await db.execute(
        select(HistoriqueCourse)
        .where(HistoriqueCourse.cheval_id == cheval_id)
        .order_by(HistoriqueCourse.date_course.desc())
        .limit(30)
    )
    historique = hist_res.scalars().all()

    # ELO trend — last 10 entries (chronological order for chart)
    elo_res = await db.execute(
        select(EloHistorique)
        .where(EloHistorique.cheval_id == cheval_id)
        .order_by(EloHistorique.date_course.desc())
        .limit(10)
    )
    elo_hist = list(reversed(elo_res.scalars().all()))

    # Aggregate stats from historique
    hippo_stats: dict[str, dict] = {}
    dist_stats: dict[str, dict] = {}
    terrain_stats: dict[str, dict] = {}

    for h in historique:
        # --- Hippodromes ---
        hp = h.hippodrome or "Inconnu"
        if hp not in hippo_stats:
            hippo_stats[hp] = {"nb": 0, "wins": 0}
        hippo_stats[hp]["nb"] += 1
        if h.position_arrivee == 1:
            hippo_stats[hp]["wins"] += 1

        # --- Distances ---
        if h.distance:
            if h.distance < 1400:
                dk = "courte"
            elif h.distance <= 2000:
                dk = "moyenne"
            else:
                dk = "longue"
            if dk not in dist_stats:
                dist_stats[dk] = {"nb": 0, "wins": 0}
            dist_stats[dk]["nb"] += 1
            if h.position_arrivee == 1:
                dist_stats[dk]["wins"] += 1

        # --- Terrain ---
        if h.terrain:
            tk = h.terrain.lower()
            if "bon" in tk and "souple" not in tk:
                tk = "bon"
            elif "souple" in tk or "léger" in tk or "leger" in tk:
                tk = "souple"
            elif "lourd" in tk or "très souple" in tk or "tres souple" in tk:
                tk = "lourd"
            else:
                tk = h.terrain
            if tk not in terrain_stats:
                terrain_stats[tk] = {"nb": 0, "wins": 0}
            terrain_stats[tk]["nb"] += 1
            if h.position_arrivee == 1:
                terrain_stats[tk]["wins"] += 1

    top_hippodromes = sorted(
        [
            {
                "hippodrome": k,
                "nb_courses": v["nb"],
                "taux_victoire": round(v["wins"] / v["nb"], 3) if v["nb"] else 0,
            }
            for k, v in hippo_stats.items()
        ],
        key=lambda x: (-x["nb_courses"], -x["taux_victoire"]),
    )[:3]

    top_distances = sorted(
        [
            {
                "distance": k,
                "nb_courses": v["nb"],
                "taux_victoire": round(v["wins"] / v["nb"], 3) if v["nb"] else 0,
            }
            for k, v in dist_stats.items()
        ],
        key=lambda x: -x["nb_courses"],
    )[:3]

    top_terrain_entry = max(terrain_stats.items(), key=lambda x: x[1]["nb"], default=(None, {"nb": 0}))
    top_terrain = top_terrain_entry[0]

    taux_par_terrain = {
        k: {
            "nb": v["nb"],
            "taux_victoire": round(v["wins"] / v["nb"], 3) if v["nb"] else 0,
        }
        for k, v in terrain_stats.items()
    }

    return {
        "cheval_id": cheval.cheval_id,
        "nom": cheval.nom,
        "age": cheval.age,
        "sexe": cheval.sexe,
        "robe": cheval.robe,
        # Généalogie enrichie
        "pere": cheval.pere,
        "mere": cheval.mere,
        "pere_de_mere": cheval.pere_de_mere,
        "mere_de_mere": cheval.mere_de_mere,
        "eleveur": cheval.eleveur,
        "proprietaire": cheval.proprietaire,
        "prix_vente_yearling": cheval.prix_vente_yearling,
        # Style de course
        "running_style": cheval.running_style,
        "taux_en_tete": cheval.taux_en_tete,
        "racing_post_url": cheval.racing_post_url,
        # ELO
        "elo_global": cheval.elo_score_global,
        "elo_plat": cheval.elo_score_plat,
        "elo_trot": cheval.elo_score_trot,
        "elo_obstacle": cheval.elo_score_obstacle,
        "elo_trend": [
            {
                "date": e.date_course,
                "elo_avant": e.elo_avant,
                "elo_apres": e.elo_apres,
                "delta": e.delta_elo,
                "discipline": e.discipline,
            }
            for e in elo_hist
        ],
        # Performances carrière
        "performances": {
            "nb_courses": perf.nb_courses_total if perf else 0,
            "nb_victoires": perf.nb_victoires_total if perf else 0,
            "nb_places": perf.nb_places_total if perf else 0,
            "gains_total": perf.gains_carriere_total if perf else 0,
            "gains_annee_n": perf.gains_annee_n if perf else 0,
            "nb_courses_annee": perf.nb_courses_annee if perf else 0,
            "nb_victoires_annee": perf.nb_victoires_annee if perf else 0,
            "meilleur_temps_all": perf.meilleur_temps_all if perf else None,
            "record_hippodrome_actuel": perf.record_hippodrome_actuel if perf else None,
        } if perf else None,
        # Stats conditions
        "top_hippodromes": top_hippodromes,
        "top_distances": top_distances,
        "top_terrain": top_terrain,
        "taux_par_terrain": taux_par_terrain,
        # Historique 30 dernières
        "historique": [
            {
                "date": h.date_course,
                "hippodrome": h.hippodrome,
                "discipline": h.discipline,
                "distance": h.distance,
                "terrain": h.terrain,
                "position": h.position_arrivee,
                "nb_partants": h.nb_partants,
                "cote": h.cote_depart,
                "temps": h.temps_officiel,
                "gains": h.gains_rapportes,
                "jockey": h.jockey_course,
                "incident": h.incident,
            }
            for h in historique
        ],
    }


# ─────────────────────────────────────────────
# Portfolio multi-scénarios
# ─────────────────────────────────────────────

@router.get("/courses/{course_id}/portfolio")
async def get_portfolio(
    course_id: str,
    bankroll: float = Query(default=100.0, ge=10.0, le=50000.0, description="Bankroll totale en €"),
    budget: float = Query(default=None, ge=1.0, le=5000.0, description="Budget max pour cette course"),
    profil: str = Query(default="equilibre", description="conservateur | equilibre | agressif"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne le portfolio de paris multi-scénarios (ALPHA/BETA/GAMMA/DELTA/OMEGA)
    pour une course donnée, basé sur les prédictions IA + calibration adaptative.

    Accès Standard+ requis.
    """
    if current_user.plan not in ("standard", "expert", "starter"):
        raise HTTPException(status_code=403, detail="Plan Standard ou Expert requis pour le portfolio")

    if profil not in ("conservateur", "equilibre", "agressif"):
        raise HTTPException(status_code=400, detail="profil doit être : conservateur | equilibre | agressif")

    # Récupérer la course
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Récupérer les prédictions + features sauvegardées
    pred_result = await db.execute(text("""
        SELECT
            p.participation_id,
            p.proba_top3,
            p.proba_top1,
            p.confidence_score,
            pa.numero,
            ch.nom AS nom_cheval,
            pa.cote_pmu,
            pa.cote_geny,
            LEAST(pa.cote_pmu, pa.cote_geny, pa.cote_bzh, pa.cote_winamax,
                  pa.cote_betclic, pa.cote_unibet) AS cote_min,
            fm.features
        FROM predictions p
        JOIN participations pa ON p.participation_id = pa.participation_id
        JOIN chevaux ch ON pa.cheval_id = ch.cheval_id
        LEFT JOIN features_ml fm ON fm.participation_id = p.participation_id
        WHERE p.course_id = :cid
        ORDER BY p.proba_top3 DESC
    """), {"cid": course_id})
    pred_rows = pred_result.fetchall()

    if not pred_rows:
        raise HTTPException(status_code=404, detail="Prédictions non disponibles pour cette course")

    # Construire la liste de prédictions enrichies
    predictions = []
    for r in pred_rows:
        features = r[9] or {}
        predictions.append({
            "participation_id": r[0],
            "proba_top3": float(r[1] or 0),
            "proba_top1": float(r[2] or 0),
            "confidence_score": float(r[3] or 0),
            "numero": r[4],
            "nom": r[5],
            "cote_pmu": float(r[6]) if r[6] else None,
            "cote_geny": float(r[7]) if r[7] else None,
            "cote_min": float(r[8]) if r[8] else None,
            # Signaux DELTA (smart money) depuis features ML
            "spi": float(features.get("spi", 0) or 0),
            "mouvement_cote": float(features.get("mouvement_cote_relatif", 0) or 0),
            "valeur_latente": float(features.get("valeur_latente", 0) or 0),
            "decote_multi_source": float(features.get("decote_multi_source", 0) or 0),
        })

    # Contexte course
    course_info = {
        "course_id": course_id,
        "hippodrome": course.hippodrome_nom,
        "discipline": course.discipline,
        "distance": course.distance,
        "terrain": course.terrain_officiel,
        "nb_partants": course.nb_partants or len(predictions),
        "est_quinte": course.est_quinte,
        "est_quarte": course.est_quarte,
        "est_tierce": course.est_tierce,
    }

    # Récupérer les poids adaptatifs courants
    al = get_adaptive_learning()
    al_state = al.get_state_summary()

    # Construire le portfolio
    engine = BetPortfolioEngine()
    portfolio = engine.build_portfolio(
        predictions=predictions,
        course_info=course_info,
        bankroll=bankroll,
        budget_course=budget,
        profil=profil,
        adaptive_weights=al.feature_weights,
    )

    # ── Monte Carlo validation du portfolio ──────────────────────────────
    mc_results = None
    try:
        simulator = MonteCarloSimulator(seed=42)
        # Construire la structure attendue par simulate_portfolio
        mc_input = {
            "bets": [
                {
                    "proba_top3": float(p.get("proba_top3", 0.3)),
                    "cote": float(p.get("cote_pmu") or 5.0),
                    "mise": round((budget or bankroll * 0.05) / max(len(predictions), 1), 2),
                }
                for p in predictions[:8]  # Top-8 chevaux
            ]
        }
        mc = simulator.simulate_portfolio(mc_input, n_simulations=5000)
        mc_results = {
            "mean_roi": round(mc["mean_roi"], 3),
            "median_roi": round(mc["median_roi"], 3),
            "p5_roi": round(mc["p5_roi"], 3),
            "p95_roi": round(mc["p95_roi"], 3),
            "win_rate": round(mc["win_rate_portfolio"], 3),
            "max_drawdown": round(mc["max_drawdown"], 3),
            "sharpe_ratio": round(mc["sharpe_ratio"], 3),
            "var_95": round(mc["var_95"], 3),
            "cvar_95": round(mc["cvar_95"], 3),
            "interpretation": (
                "ROI positif attendu" if mc["mean_roi"] > 0
                else "ROI négatif attendu — vérifier les cotes"
            ),
        }
    except Exception as e:
        log.warning("portfolio.monte_carlo.failed", err=str(e))

    # ── Couverture diversification (P5) — arrivées cohérentes, vrais paris ─
    # Règle le portefeuille ENTIER (simples + combinés) contre des arrivées
    # Plackett-Luce, mesure la vraie couverture (≠ MC indépendant ci-dessus).
    coverage = None
    try:
        from ml.portfolio_simulator import (
            simulate_portfolio_coverage, validate_diversification, _SIMPLE, _norm,
        )
        cote_by_num = {p["numero"]: float(p.get("cote_pmu") or 0) for p in predictions}
        bets = []
        for scen in (portfolio.get("scenarios") or {}).values():
            if not scen:
                continue
            for pari in scen.get("paris", []):
                nums = [c["numero"] for c in pari.get("chevaux", []) if c.get("numero") is not None]
                mise = float(pari.get("mise") or 0)
                if not nums or mise <= 0:
                    continue
                bets.append({
                    "type": pari["type"], "numeros": nums, "stake": mise,
                    "cote": cote_by_num.get(nums[0], 0.0) if _norm(pari["type"]) in _SIMPLE else 0.0,
                })
        if bets:
            numeros = [p["numero"] for p in predictions]
            win_probs = [float(p.get("proba_top1") or p.get("proba_top3") or 0.0) for p in predictions]
            cov = simulate_portfolio_coverage(
                bets, numeros, win_probs,
                nb_partants=course_info["nb_partants"], n_simulations=5000, seed=42,
            )
            coverage = {**cov.to_dict(), "validation": validate_diversification(cov)}
    except Exception as e:
        log.warning("portfolio.coverage.failed", err=str(e))

    return {
        "course_id": course_id,
        "hippodrome": course.hippodrome_nom,
        "discipline": course.discipline,
        "profil_risque": profil,
        "bankroll": bankroll,
        "budget_course": budget or round(bankroll * 0.05, 2),
        "adaptive_learning": {
            "temperature": al_state["temperature"],
            "calibration_status": al_state["calibration_status"],
            "n_races_appris": al_state["n_races_processed"],
            "brier_ema": al_state["brier_ema"],
            "alerte": al_state["alerte_calibration"],
        },
        "portfolio": portfolio,
        "monte_carlo": mc_results,
        "coverage": coverage,
    }


# ─────────────────────────────────────────────
# Jockeys
# ─────────────────────────────────────────────

@router.get("/jockeys/{jockey_id}")
async def get_jockey(jockey_id: str, db: AsyncSession = Depends(get_db)):
    """Fiche jockey : stats saison, top hippodromes/distances/terrains, associations entraîneurs, dernières participations."""
    from db.models import StatsJockey
    from datetime import datetime as dt

    jockey_res = await db.execute(select(Jockey).where(Jockey.jockey_id == jockey_id))
    jockey = jockey_res.scalar_one_or_none()
    if not jockey:
        raise HTTPException(status_code=404, detail="Jockey introuvable")

    saison = dt.now().year
    stats_res = await db.execute(
        select(StatsJockey)
        .where(StatsJockey.jockey_id == jockey_id, StatsJockey.saison == saison)
    )
    stats = stats_res.scalar_one_or_none()

    # Top 5 hippodromes from JSON column
    top_hippodromes: list[dict] = []
    top_distances: list[dict] = []
    taux_par_terrain: dict = {}
    if stats:
        if stats.taux_par_hippodrome:
            raw_h = stats.taux_par_hippodrome
            top_hippodromes = sorted(
                [{"hippodrome": k, **v} for k, v in raw_h.items()],
                key=lambda x: -x.get("nb_courses", 0),
            )[:5]
        if stats.taux_par_distance:
            raw_d = stats.taux_par_distance
            top_distances = sorted(
                [{"distance": k, **v} for k, v in raw_d.items()],
                key=lambda x: -x.get("nb_courses", 0),
            )[:5]
        if stats.taux_par_terrain:
            taux_par_terrain = stats.taux_par_terrain

    # Top 5 associations entraîneurs (by nb_courses this season)
    asso_res = await db.execute(
        select(
            AssociationJockeyEntraineur.entraineur_id,
            AssociationJockeyEntraineur.nb_courses,
            AssociationJockeyEntraineur.nb_victoires,
            AssociationJockeyEntraineur.taux_victoire,
            Entraineur.nom,
        )
        .join(Entraineur, Entraineur.entraineur_id == AssociationJockeyEntraineur.entraineur_id)
        .where(
            AssociationJockeyEntraineur.jockey_id == jockey_id,
            AssociationJockeyEntraineur.saison == saison,
        )
        .order_by(AssociationJockeyEntraineur.nb_courses.desc())
        .limit(5)
    )
    associations = [
        {
            "entraineur_id": r.entraineur_id,
            "entraineur": r.nom,
            "nb_courses": r.nb_courses,
            "nb_victoires": r.nb_victoires,
            "taux_victoire": r.taux_victoire,
        }
        for r in asso_res.fetchall()
    ]

    # Last 20 participations
    participations_res = await db.execute(text("""
        SELECT
            c.date_heure,
            ch.nom AS nom_cheval,
            ch.cheval_id,
            co.hippodrome_nom,
            co.discipline,
            p.numero,
            h.position_arrivee,
            p.cote_pmu
        FROM participations p
        JOIN courses co ON co.course_id = p.course_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN historique_courses h ON h.course_id = co.course_id AND h.cheval_id = ch.cheval_id
        JOIN (SELECT date_heure FROM courses) c ON c.date_heure = co.date_heure
        WHERE p.jockey_id = :jid
        ORDER BY co.date_heure DESC
        LIMIT 20
    """), {"jid": jockey_id})

    # Simpler query without ambiguous joins
    participations_res2 = await db.execute(text("""
        SELECT
            co.date_heure,
            ch.nom AS nom_cheval,
            ch.cheval_id,
            co.hippodrome_nom,
            co.discipline,
            p.numero,
            p.cote_pmu
        FROM participations p
        JOIN courses co ON co.course_id = p.course_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        WHERE p.jockey_id = :jid
        ORDER BY co.date_heure DESC
        LIMIT 20
    """), {"jid": jockey_id})
    part_rows = participations_res2.fetchall()

    # Get positions from historique_courses
    derniere_participations = []
    for r in part_rows:
        derniere_participations.append({
            "date": r[0],
            "nom_cheval": r[1],
            "cheval_id": r[2],
            "hippodrome": r[3],
            "discipline": r[4],
            "numero": r[5],
            "cote": r[6],
            "position": None,  # enrichi depuis historique si disponible
        })

    return {
        "jockey_id": jockey.jockey_id,
        "nom": jockey.nom,
        "nationalite": jockey.nationalite,
        "saison": saison,
        "stats_saison": {
            "victoires": stats.victoires_saison if stats else 0,
            "places": stats.places_saison if stats else 0,
            "courses": stats.courses_saison if stats else 0,
            "taux_victoire": stats.taux_victoire_global if stats else 0.0,
            "taux_place": stats.taux_place_global if stats else 0.0,
            "roi": stats.roi_global if stats else 0.0,
            "montes_30j": stats.montes_30j if stats else 0,
        },
        "top_hippodromes": top_hippodromes,
        "top_distances": top_distances,
        "taux_par_terrain": taux_par_terrain,
        "associations_entraineurs": associations,
        "derniere_participations": derniere_participations,
    }


# ─────────────────────────────────────────────
# Entraîneurs
# ─────────────────────────────────────────────

@router.get("/entraineurs/{entraineur_id}")
async def get_entraineur(entraineur_id: str, db: AsyncSession = Depends(get_db)):
    """Fiche entraîneur : stats saison, top hippodromes/distances/terrains, associations jockeys, dernières participations."""
    from db.models import StatsEntraineur
    from datetime import datetime as dt

    entraineur_res = await db.execute(
        select(Entraineur).where(Entraineur.entraineur_id == entraineur_id)
    )
    entraineur = entraineur_res.scalar_one_or_none()
    if not entraineur:
        raise HTTPException(status_code=404, detail="Entraîneur introuvable")

    saison = dt.now().year
    stats_res = await db.execute(
        select(StatsEntraineur)
        .where(
            StatsEntraineur.entraineur_id == entraineur_id,
            StatsEntraineur.saison == saison,
        )
    )
    stats = stats_res.scalar_one_or_none()

    top_hippodromes: list[dict] = []
    top_distances: list[dict] = []
    taux_par_terrain: dict = {}
    if stats:
        if stats.taux_par_hippodrome:
            raw_h = stats.taux_par_hippodrome
            top_hippodromes = sorted(
                [{"hippodrome": k, **v} for k, v in raw_h.items()],
                key=lambda x: -x.get("nb_courses", 0),
            )[:5]
        if stats.taux_par_distance:
            raw_d = stats.taux_par_distance
            top_distances = sorted(
                [{"distance": k, **v} for k, v in raw_d.items()],
                key=lambda x: -x.get("nb_courses", 0),
            )[:5]
        # StatsEntraineur doesn't have taux_par_terrain, handle gracefully
        taux_par_terrain = getattr(stats, "taux_par_terrain", None) or {}

    # Top 5 associations jockeys (by nb_courses this season)
    asso_res = await db.execute(
        select(
            AssociationJockeyEntraineur.jockey_id,
            AssociationJockeyEntraineur.nb_courses,
            AssociationJockeyEntraineur.nb_victoires,
            AssociationJockeyEntraineur.taux_victoire,
            Jockey.nom,
        )
        .join(Jockey, Jockey.jockey_id == AssociationJockeyEntraineur.jockey_id)
        .where(
            AssociationJockeyEntraineur.entraineur_id == entraineur_id,
            AssociationJockeyEntraineur.saison == saison,
        )
        .order_by(AssociationJockeyEntraineur.nb_courses.desc())
        .limit(5)
    )
    associations = [
        {
            "jockey_id": r.jockey_id,
            "jockey": r.nom,
            "nb_courses": r.nb_courses,
            "nb_victoires": r.nb_victoires,
            "taux_victoire": r.taux_victoire,
        }
        for r in asso_res.fetchall()
    ]

    # Last 20 participations coached
    participations_res = await db.execute(text("""
        SELECT
            co.date_heure,
            ch.nom AS nom_cheval,
            ch.cheval_id,
            co.hippodrome_nom,
            co.discipline,
            p.numero,
            p.cote_pmu,
            j.nom AS jockey_nom
        FROM participations p
        JOIN courses co ON co.course_id = p.course_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN jockeys j ON j.jockey_id = p.jockey_id
        WHERE p.entraineur_id = :eid
        ORDER BY co.date_heure DESC
        LIMIT 20
    """), {"eid": entraineur_id})
    part_rows = participations_res.fetchall()

    derniere_participations = [
        {
            "date": r[0],
            "nom_cheval": r[1],
            "cheval_id": r[2],
            "hippodrome": r[3],
            "discipline": r[4],
            "numero": r[5],
            "cote": r[6],
            "jockey": r[7],
            "position": None,
        }
        for r in part_rows
    ]

    return {
        "entraineur_id": entraineur.entraineur_id,
        "nom": entraineur.nom,
        "nationalite": entraineur.nationalite,
        "saison": saison,
        "stats_saison": {
            "victoires": stats.victoires_saison if stats else 0,
            "places": stats.places_saison if stats else 0,
            "courses": stats.courses_saison if stats else 0,
            "taux_victoire": stats.taux_victoire_global if stats else 0.0,
            "taux_place": stats.taux_place_global if stats else 0.0,
            "roi": stats.roi_global if stats else 0.0,
        },
        "top_hippodromes": top_hippodromes,
        "top_distances": top_distances,
        "taux_par_terrain": taux_par_terrain,
        "associations_jockeys": associations,
        "derniere_participations": derniere_participations,
    }
