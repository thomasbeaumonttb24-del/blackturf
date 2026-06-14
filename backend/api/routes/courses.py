"""
Courses routes — BlackTurf.
Programme du jour, détail course, partants.
"""
import structlog
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text

from api.routes.auth import get_current_user, require_pro
from api.middleware.rate_limit import rate_limit_public, rate_limit_predictions
from db.database import get_db
from db.redis_client import get_redis
from db.models import (
    Course, Reunion, Hippodrome, Participation, Cheval,
    Jockey, Entraineur, Equipement, MeteoCourse, Resultat,
    Prediction as PredictionModel,
    SuspensionProfessionnel, PronosticPresse, TempsPassage,
    AssociationJockeyEntraineur, PenetrometreLog, PerformanceCarriere,
)
from db.models import User
from ml.portfolio import BetPortfolioEngine
from ml.adaptive_learning import get_adaptive_learning
from ml.monte_carlo import MonteCarloSimulator

log = structlog.get_logger()
router = APIRouter()

# Gel du pronostic : à moins de PRONO_LOCK_MIN minutes du départ, le pronostic
# (proba + sélection + plan de mise) est FIGÉ. Le plan s'appuie alors sur la cote
# figée (predictions.cote_figee) et non sur la cote live → il ne change plus, que
# l'utilisateur l'ouvre 9 min ou 2 min avant le départ. Les cotes affichées
# continuent d'évoluer (scraper cotes-live).
PRONO_LOCK_MIN = 10


def _prono_lock_state(date_heure: Optional[datetime]) -> tuple[bool, Optional[datetime]]:
    """(prono_figé, instant_de_gel). Le gel intervient à date_heure - PRONO_LOCK_MIN."""
    if not date_heure:
        return False, None
    fige_a = date_heure - timedelta(minutes=PRONO_LOCK_MIN)
    now = datetime.now(timezone.utc) if date_heure.tzinfo else datetime.now()
    return now >= fige_a, fige_a


def _cote_plan(pred, part) -> Optional[float]:
    """Cote utilisée par le plan de mise : la cote FIGÉE au calcul du prono si
    disponible, sinon la cote live (legacy / tout premier calcul). Garantit que le
    plan est stable une fois le prono gelé."""
    cf = getattr(pred, "cote_figee", None)
    return cf if cf else part.cote_pmu


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
    # Handicap / poids / corde (selon discipline)
    handicap_poids: Optional[float] = None    # poids porté en handicap (kg)
    poids_prevu: Optional[float] = None        # poids prévu (kg)
    numero_corde: Optional[int] = None         # position au départ (plat)
    # Carrière
    gains_carriere: Optional[int] = None
    nb_victoires: Optional[int] = None
    nb_courses: Optional[int] = None
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
    # Analyse détaillée (features ML réelles + stats saison) — None si indispo.
    # Sert la fiche cheval enrichie : forme, préférences contexte, stats jockey/
    # entraîneur, signaux marché, ELO détaillé, explication. 100% données réelles.
    analyse: Optional[dict] = None


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
    numero_reunion: Optional[int] = None  # n° réunion public (PMU numExterne)
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
    est_2sur4: bool = False
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
    # Gel du pronostic à T-10 min : prono_fige=True → la sélection/plan ne bouge plus
    # (cotes affichées continuent d'évoluer). prono_fige_a = instant du gel.
    prono_fige: bool = False
    prono_fige_a: Optional[datetime] = None
    meteo: Optional[MeteoOut]
    pronostics_presse: list[PronosticPresseOut] = []
    partants: list[PartantOut]


class CourseSummary(BaseModel):
    course_id: str
    nom: Optional[str]
    reunion_id: str
    numero_reunion: Optional[int] = None  # n° réunion public (PMU numExterne)
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
    est_2sur4: bool = False
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
    from db.models import FeatureML, StatsJockey, StatsEntraineur
    today = date_type.today()
    saison_now = today.year

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
        select(Participation, Cheval, Jockey, Entraineur, Equipement, PerformanceCarriere, FeatureML)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .outerjoin(Jockey, Jockey.jockey_id == Participation.jockey_id)
        .outerjoin(Entraineur, Entraineur.entraineur_id == Participation.entraineur_id)
        .outerjoin(Equipement, Equipement.participation_id == Participation.participation_id)
        .outerjoin(PerformanceCarriere, PerformanceCarriere.cheval_id == Cheval.cheval_id)
        .outerjoin(FeatureML, FeatureML.participation_id == Participation.participation_id)
        .where(Participation.course_id == course_id)
        .order_by(Participation.numero)
    )
    rows = (await db.execute(q)).all()

    # Stats SAISON jockey + entraîneur (tables dédiées) pour les acteurs de la course.
    jockey_ids = [p.jockey_id for p, *_ in rows if p.jockey_id]
    entraineur_ids = [p.entraineur_id for p, *_ in rows if p.entraineur_id]
    sj_map: dict = {}
    se_map: dict = {}
    try:
        if jockey_ids:
            for sj in (await db.execute(select(StatsJockey).where(
                StatsJockey.jockey_id.in_(jockey_ids), StatsJockey.saison == saison_now))).scalars():
                sj_map[sj.jockey_id] = sj
        if entraineur_ids:
            for se in (await db.execute(select(StatsEntraineur).where(
                StatsEntraineur.entraineur_id.in_(entraineur_ids), StatsEntraineur.saison == saison_now))).scalars():
                se_map[se.entraineur_id] = se
    except Exception as e:
        log.warning("courses.stats_saison_failed", error=str(e)[:120])

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
    except Exception as e:
        log.warning("courses.asso_map_failed", error=str(e))

    partants = []
    for p, ch, j, en, eq, pc, fm in rows:
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

        # ── Analyse détaillée (features ML réelles + stats saison) ──
        analyse = _build_analyse(
            fm.features if fm else None,
            sj_map.get(p.jockey_id), se_map.get(p.entraineur_id),
        )

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
            # Handicap / poids / corde
            handicap_poids=p.handicap_poids,
            poids_prevu=p.poids_prevu,
            numero_corde=p.numero_corde,
            # Carrière (PerformanceCarriere, 1:1 cheval)
            gains_carriere=pc.gains_carriere_total if pc else None,
            nb_victoires=pc.nb_victoires_total if pc else None,
            nb_courses=pc.nb_courses_total if pc else None,
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
            analyse=analyse,
        ))
    return partants


def _build_analyse(feat: Optional[dict], sj, se) -> Optional[dict]:
    """Construit le bloc d'analyse détaillée d'un partant à partir des features ML
    RÉELLES + stats saison jockey/entraîneur. Renvoie None si rien d'exploitable.
    Aucune valeur inventée : on n'expose que ce qui est présent."""
    f = feat or {}

    def num(v):
        try:
            return round(float(v), 4) if v is not None else None
        except (TypeError, ValueError):
            return None

    forme = {
        "taux_top3": num(f.get("taux_top3")),
        "recent_win_rate": num(f.get("recent_win_rate")),
        "forme_5": num(f.get("forme_5_courses")),
        "regularite": num(f.get("regularite")),
        "tendance": num(f.get("forme_tendance")),
        "momentum": num(f.get("career_momentum")),
    }
    contexte = {
        "pref_distance": num(f.get("pref_distance_actuelle")),
        "pref_terrain": num(f.get("pref_terrain_actuel")),
        "pref_hippodrome": num(f.get("pref_hippodrome")),
        "nb_distance": f.get("nb_courses_distance"),
        "nb_terrain": f.get("nb_courses_terrain"),
        "nb_hippodrome": f.get("nb_courses_hippodrome"),
        "corde_pref": num(f.get("corde_preference")),
    }
    elo = {
        "trend_30j": num(f.get("elo_trend_30j")),
        "pct_rank": num(f.get("elo_pct_rank")),
        "discipline": num(f.get("elo_discipline")),
    }
    marche = {
        "spi": num(f.get("spi_score")),
        "steam": num(f.get("steam_move_betclic")),
        "valeur_latente": num(f.get("valeur_latente")),
        "decote": num(f.get("decote_detectee")),
        "tendance_force": num(f.get("tendance_cote_force")),
        "mouvement_30min": num(f.get("mouvement_30min")),
    }
    vitesse = {
        "vitesse_theorique": num(f.get("vitesse_theorique")),
        "stamina": num(f.get("stamina_index")),
        "indice_valeur": num(f.get("indice_valeur")),
    }
    jockey_stats = None
    if sj:
        jockey_stats = {
            "taux_victoire": num(sj.taux_victoire_global),
            "taux_place": num(sj.taux_place_global),
            "roi": num(sj.roi_global),
            "victoires_saison": sj.victoires_saison,
            "courses_saison": sj.courses_saison,
            "montes_30j": sj.montes_30j,
        }
    entraineur_stats = None
    if se:
        entraineur_stats = {
            "taux_victoire": num(se.taux_victoire_global),
            "taux_place": num(se.taux_place_global),
            "roi": num(se.roi_global),
            "victoires_saison": se.victoires_saison,
            "courses_saison": se.courses_saison,
        }

    # ── Points clés (le "pourquoi") dérivés des features réelles ──
    points: list[dict] = []  # {txt, type: +/-}
    if forme["taux_top3"] is not None and forme["taux_top3"] >= 0.5:
        points.append({"txt": f"Régulier : {round(forme['taux_top3']*100)}% dans les 3", "type": "+"})
    if forme["tendance"] is not None and forme["tendance"] > 0.1:
        points.append({"txt": "Forme en progression", "type": "+"})
    elif forme["tendance"] is not None and forme["tendance"] < -0.1:
        points.append({"txt": "Forme en baisse", "type": "-"})
    if contexte["pref_distance"] is not None and contexte["pref_distance"] >= 0.6:
        points.append({"txt": "À l'aise sur la distance", "type": "+"})
    if contexte["pref_terrain"] is not None and contexte["pref_terrain"] >= 0.6:
        points.append({"txt": "Aime ce terrain", "type": "+"})
    if marche["spi"] is not None and marche["spi"] >= 0.2:
        points.append({"txt": "Argent professionnel détecté (SPI)", "type": "+"})
    if marche["valeur_latente"] is not None and marche["valeur_latente"] >= 0.25:
        points.append({"txt": "Sous-coté vs marché (valeur)", "type": "+"})
    if elo["pct_rank"] is not None and elo["pct_rank"] >= 0.8:
        points.append({"txt": f"Top {round((1-elo['pct_rank'])*100)}% du champ (ELO)", "type": "+"})

    blocks = {"forme": forme, "contexte": contexte, "elo": elo, "marche": marche,
              "vitesse": vitesse, "jockey_stats": jockey_stats, "entraineur_stats": entraineur_stats,
              "points": points}
    # None si aucune donnée réelle (toutes valeurs nulles + pas de stats)
    has_data = any(v is not None for d in (forme, contexte, elo, marche, vitesse) for v in d.values()) \
        or jockey_stats or entraineur_stats
    return blocks if has_data else None


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
    except Exception as e:
        log.debug("courses.programme_cache_read_failed", error=str(e))  # Redis indispo → continuer sans cache

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
                # N° public (PMU numExterne) pour matcher pmu.fr — porté par la course
                # (numero_reunion) ; fallback sur reunion.numero (numOfficiel).
                "numero": course.numero_reunion or reunion.numero,
                "courses": [],
            }
        reunions_dict[rid]["courses"].append(CourseSummary(
            course_id=course.course_id,
            nom=course.nom,
            reunion_id=course.reunion_id,
            numero_reunion=course.numero_reunion,
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
            est_2sur4=course.est_2sur4,
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
    except Exception as e:
        log.debug("courses.programme_cache_write_failed", error=str(e))

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
            out = CourseDetailOut(**json.loads(cached))
            # Le gel dépend de l'heure courante → recalculé hors cache (sinon il
            # basculerait avec jusqu'à 30s de retard près de la limite T-10 min).
            if out.statut == "a_venir":
                out.prono_fige, out.prono_fige_a = _prono_lock_state(out.date_heure)
            return out
    except Exception as e:
        log.debug("courses.detail_cache_read_failed", error=str(e))

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
        numero_reunion=course.numero_reunion,
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
        est_2sur4=course.est_2sur4,
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
    # Gel du pronostic (seulement pertinent sur une course à venir)
    if course.statut == "a_venir":
        fige, fige_a = _prono_lock_state(course.date_heure)
        response.prono_fige = fige
        response.prono_fige_a = fige_a

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
    except Exception as e:
        log.debug("courses.detail_cache_write_failed", error=str(e))

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
        "rapports_detail": res.rapports_detail,      # détail PMU complet par combinaison
        "temps_gagnant": res.temps_gagnant,
        "incidents": res.incidents,
        "commentaire": res.commentaire,              # narratif post-course PMU/GENY
        "duree_course": res.duree_course,            # ms
    }


@router.get("/courses/{course_id}/paris-disponibles")
async def get_paris_disponibles(course_id: str, db: AsyncSession = Depends(get_db)):
    """Types de paris RÉELLEMENT proposés par le PMU pour cette course.

    Déduit des désignations officielles captées au scrape (`paris[].codePari` du
    programme PMU) : est_tierce / est_quarte / est_quinte / est_2sur4. Permet au
    frontend de n'afficher / ne laisser sélectionner que des paris JOUABLES — on ne
    propose plus un 2sur4 sur une course qui n'en offre pas (ex. R6C7). Couplé /
    Simple / Trio sont offerts sur toute course à assez de partants.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    from ml.recommendations import disponibles_selon_course
    paris = disponibles_selon_course(
        course.nb_partants or 0,
        bool(course.est_quinte), bool(course.est_quarte),
        bool(course.est_tierce), bool(course.est_2sur4),
        paris_disponibles=course.paris_disponibles,
    )
    return {
        "course_id": course_id,
        "paris_disponibles": paris,
        "designations": {
            "est_tierce": bool(course.est_tierce),
            "est_quarte": bool(course.est_quarte),
            "est_quinte": bool(course.est_quinte),
            "est_2sur4": bool(course.est_2sur4),
            # Paris à l'ORDRE réellement offerts (champ réduit).
            "codes_pmu": course.paris_disponibles or None,
        },
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


@router.get("/courses/{course_id}/cotes-live")
async def get_cotes_live(
    course_id: str,
    _: User = Depends(require_pro),
):
    """
    Cotes PMU EN DIRECT pour une course (lecture à la demande de l'API PMU).
    Cache court partagé (4 s) pour rester proche du temps réel sans marteler le PMU.
    Retourne {"time": iso, "cotes": [{"numero", "cote"}]}.
    """
    import json
    from datetime import datetime, timezone
    from services.pmu_cotes import fetch_live_cotes

    cache_key = f"cotes_live:{course_id}"
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        log.debug("courses.cotes_live_cache_read_failed", error=str(e))
        redis = None

    cotes = await fetch_live_cotes(course_id)
    payload = {"time": datetime.now(timezone.utc).isoformat(), "cotes": cotes}

    if redis is not None and cotes:
        try:
            await redis.setex(cache_key, 4, json.dumps(payload))
        except Exception as e:
            log.debug("courses.cotes_live_cache_write_failed", error=str(e))

    return payload


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

    # ── PRONO FIGÉ (T-10) → plan figé tel quel, UNIQUEMENT à la mise de référence 10€ ──
    # Le plan figé (profil_run_log) est journalisé à 10€ = celui qui apparaîtra dans le
    # bilan/palmarès après course. On ne le sert donc QUE si l'utilisateur demande 10€
    # (→ prono AVANT = résultat APRÈS, identiques). Pour TOUTE autre mise (5€, 20€…), on
    # recalcule plus bas au montant saisi (cotes figées une fois gelé → même sélection,
    # mises mises à l'échelle du montant). Avant le gel : recalcul en live.
    fige_now, fige_a_now = _prono_lock_state(course.date_heure)
    from ml.profil_learning import MISE_REF as _MISE_REF
    if fige_now and int(round(montant)) == int(_MISE_REF):
        try:
            from sqlalchemy import text as _text
            from ml.profil_learning import ensure_tables
            import json as _json
            await ensure_tables(db)
            _row = (await db.execute(_text("""
                SELECT plan FROM profil_run_log
                WHERE course_id = :cid AND profil = :prof
                  AND COALESCE(meta->>'backfill','') <> 'true'
                ORDER BY created_at DESC LIMIT 1
            """), {"cid": course_id, "prof": profil})).first()
            if _row and _row[0]:
                frozen = _row[0] if isinstance(_row[0], dict) else _json.loads(_row[0])
                frozen["prono_fige"] = True
                frozen["prono_fige_a"] = fige_a_now.isoformat() if fige_a_now else None
                frozen["cotes_live_utilisees"] = False
                frozen["plan_fige_servi"] = True       # plan figé = bilan (cohérence)
                return frozen
        except Exception:
            pass  # pas de plan figé (legacy/échec) → on recalcule en live ci-dessous

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

    # COTES : AVANT le gel (T-10), l'estimatif suit le marché LIVE (même cote que le
    # tableau et le widget « Marché EN DIRECT »). APRÈS le gel, on utilise la cote FIGÉE
    # (cote_figee) → à 10€ la sélection est IDENTIQUE au plan figé = bilan ; pour les
    # autres mises, même sélection, mises à l'échelle du montant. Le bilan/palmarès
    # règlent aux VRAIS rapports PMU.
    fige, fige_a = _prono_lock_state(course.date_heure)
    live_cotes: dict[int, float] = {}
    if not fige:
        try:
            from services.pmu_cotes import fetch_live_cotes
            live_cotes = {int(c["numero"]): float(c["cote"])
                          for c in await fetch_live_cotes(course_id) if c.get("cote")}
        except Exception:
            live_cotes = {}

    preds = []
    for pred, part, cheval in rows:
        vb = vbs.get(pred.participation_id)
        # Cote = LIVE avant gel, FIGÉE après (sinon cote stockée du partant).
        cote = (live_cotes.get(part.numero) if not fige else None) or _cote_plan(pred, part)
        preds.append({
            "numero": part.numero,
            "nom_cheval": cheval.nom,
            "proba_top3": pred.proba_top3,
            "proba_top1": pred.proba_top1,
            "cote_pmu": cote,
            "non_partant": part.non_partant,
            "value_bet": {"ev_max": vb.ev_max, "niveau": vb.niveau} if vb else None,
        })

    # Drapeaux de disponibilité RÉELS (couplé/trio à l'ordre si champ réduit, etc.).
    from services.bet_catalog import course_info_bets
    course_info = course_info_bets(course)

    # Auto-amélioration : pondération ROI réel par type + thermostat adaptatif
    # (calibration du modèle + ROI récent → durcit/assouplit la sélection).
    try:
        from ml.bet_performance import get_learned_type_weights, get_model_heat
        roi_weights = await get_learned_type_weights(
            db, profil=profil,
            discipline=getattr(course, "discipline", None),
            nb_partants=getattr(course, "nb_partants", None))
        heat = await get_model_heat(db)
    except Exception:
        roi_weights, heat = {}, 0.0

    # Multiplicateurs appris PAR SIGNAL × PROFIL → le pronostic/plan s'adapte au profil
    # sélectionné (ex. "premier déferré" boosté en conservateur=placé, ignoré en agressif).
    # Les features chargées servent aussi aux JUSTIFICATIFS par pari (facteurs réels).
    signal_mults: dict = {}
    facteurs_chevaux: dict = {}
    try:
        from ml.signal_performance import load_signal_performance, signal_multiplier
        from ml.narrative import explain_prediction
        from db.models import FeatureML as _FM
        perf = await load_signal_performance(db)
        fq = (_s(Participation.numero, _FM.features)
              .join(_FM, _FM.participation_id == Participation.participation_id)
              .where(Participation.course_id == course_id))
        probas_by_num = {int(p["numero"]): p for p in preds}
        for numero, feats in (await db.execute(fq)).all():
            n = int(numero)
            if perf:
                signal_mults[n] = signal_multiplier(feats or {}, perf, profil)
            pr = probas_by_num.get(n) or {}
            exp = explain_prediction(feats or {}, float(pr.get("proba_top3") or 0),
                                     float(pr.get("proba_top1") or 0))
            facteurs_chevaux[n] = {
                "positifs": exp.get("facteurs_positifs", []),
                "negatifs": exp.get("facteurs_negatifs", []),
            }
    except Exception:
        signal_mults = {}
        facteurs_chevaux = {}

    # respect_montant : le montant SAISI par l'utilisateur est sa décision explicite →
    # on ne le rabote pas par le cap bankroll (sinon bankroll défaut 1.0 → plan 2€).
    plan = generer_plan(montant, profil, preds, course_info, bankroll, roi_weights, heat,
                        signal_mults, facteurs_chevaux=facteurs_chevaux, respect_montant=True)
    out = plan_to_dict(plan)
    # Indique si le pronostic est figé (T-10 min) → le plan ne changera plus.
    out["prono_fige"] = fige
    out["prono_fige_a"] = fige_a.isoformat() if fige_a else None
    # Transparence : cotes live (avant gel) → corrélé au marché ; figées après gel.
    out["cotes_live_utilisees"] = bool(live_cotes) and not fige
    return out


@router.post("/courses/{course_id}/enregistrer-paris")
async def enregistrer_paris(
    course_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Enregistre le plan de mise (montant + profil) dans la bankroll de l'utilisateur :
    un pari par ligne du plan, en attente de résultat. Les gains/pertes seront
    calculés automatiquement à la fin de la course (vrais rapports PMU).
    """
    import uuid as _uuid
    from datetime import datetime as _dt
    from sqlalchemy import delete as _delete, and_ as _and
    from services.mise_calculator import generer_plan, plan_to_dict
    from db.models import BankrollEntry, Bankroll, Prediction as _Pred

    if user.plan in ("free", "decouverte"):
        raise HTTPException(status_code=403, detail="Plan Standard ou Expert requis")

    montant = float(body.get("montant", 0))
    if montant <= 0 or montant > 10000:
        raise HTTPException(status_code=422, detail="Montant invalide (0.01–10000€)")
    profil = body.get("profil_risque") or (user.profil_risque or "equilibre")

    course = (await db.execute(select(Course).where(Course.course_id == course_id))).scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    rows = (await db.execute(
        select(_Pred, Participation, Cheval)
        .join(Participation, Participation.participation_id == _Pred.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(Participation.course_id == course_id)
        .order_by(_Pred.rang_predit)
    )).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Aucun pronostic — analyse IA requise")

    # Mêmes cotes que l'aperçu mise-plan : LIVE avant le gel, FIGÉES après (« ce que tu
    # vois = ce que tu enregistres »). Le règlement final se fera aux VRAIS rapports PMU.
    fige_e, _ = _prono_lock_state(course.date_heure)
    live_cotes: dict[int, float] = {}
    if not fige_e:
        try:
            from services.pmu_cotes import fetch_live_cotes
            live_cotes = {int(c["numero"]): float(c["cote"])
                          for c in await fetch_live_cotes(course_id) if c.get("cote")}
        except Exception:
            live_cotes = {}
    preds = [{
        "numero": part.numero, "nom_cheval": cheval.nom,
        "proba_top3": pred.proba_top3, "proba_top1": pred.proba_top1,
        "cote_pmu": (live_cotes.get(part.numero) if not fige_e else None) or _cote_plan(pred, part),
        "non_partant": part.non_partant,
    } for pred, part, cheval in rows]
    from services.bet_catalog import course_info_bets
    course_info = course_info_bets(course)

    # Mêmes signaux adaptatifs que l'aperçu (le plan enregistré = celui montré) :
    # poids par type APPRIS POUR CE PROFIL + multiplicateurs de signaux par profil.
    try:
        from ml.bet_performance import get_learned_type_weights, get_model_heat
        roi_weights = await get_learned_type_weights(
            db, profil=profil,
            discipline=getattr(course, "discipline", None),
            nb_partants=getattr(course, "nb_partants", None))
        heat = await get_model_heat(db)
    except Exception:
        roi_weights, heat = {}, 0.0
    signal_mults: dict = {}
    try:
        from ml.signal_performance import load_signal_performance, signal_multiplier
        from db.models import FeatureML as _FM2
        perf = await load_signal_performance(db)
        if perf:
            fq = (select(Participation.numero, _FM2.features)
                  .join(_FM2, _FM2.participation_id == Participation.participation_id)
                  .where(Participation.course_id == course_id))
            for numero, feats in (await db.execute(fq)).all():
                signal_mults[int(numero)] = signal_multiplier(feats or {}, perf, profil)
    except Exception:
        signal_mults = {}

    plan = plan_to_dict(generer_plan(montant, profil, preds, course_info, None,
                                     roi_weights, heat, signal_mults, respect_montant=True))

    # Bankroll principale
    main = (await db.execute(
        select(Bankroll).where(_and(
            Bankroll.user_id == user.user_id,
            Bankroll.est_principale == True,
            Bankroll.est_supprime == False,
        ))
    )).scalar_one_or_none()
    bankroll_id = main.bankroll_id if main else None

    # Remplace un éventuel plan déjà enregistré (non réglé) DU MÊME PROFIL pour
    # cette course — on peut donc cumuler Prudent + Modéré + Risqué sur une même
    # course (avant : tout plan IA non réglé était écrasé, seul le dernier restait).
    note_profil = f"Plan de mise IA · {profil}"
    await db.execute(_delete(BankrollEntry).where(_and(
        BankrollEntry.user_id == user.user_id,
        BankrollEntry.course_id == course_id,
        BankrollEntry.resultat.is_(None),
        BankrollEntry.suivi_reco_ia == True,
        BankrollEntry.notes.in_([note_profil, "Plan de mise IA"]),  # legacy sans profil
    )))

    now = _dt.now()
    nb = 0
    for niveau in plan.get("niveaux", []):
        for pari in niveau.get("paris", []):
            chevaux = " + ".join(f"N°{c['numero']}" for c in pari.get("chevaux", []))
            db.add(BankrollEntry(
                entry_id=str(_uuid.uuid4()),
                user_id=user.user_id,
                bankroll_id=bankroll_id,
                course_id=course_id,
                date=now,
                type_pari=pari["type"],
                chevaux=chevaux,
                mise=float(pari.get("mise", 0) or 0),
                suivi_reco_ia=True,
                resultat=None,
                gain_perte=None,
                notes=note_profil,
            ))
            nb += 1
    await db.commit()
    return {"enregistres": nb, "montant_total": plan.get("montant_joue", montant)}


@router.get("/courses/{course_id}/bilan-pronostic")
async def get_bilan_pronostic(
    course_id: str,
    montant: float = 20.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Bilan RÉTROSPECTIF d'une course TERMINÉE : applique le plan de mise (20€ par
    défaut) généré sur les pronostics réels, le règle contre le résultat officiel
    (rapports PMU réels) et indique si le pronostic était bon (net, ROI, comparaison
    top-3 prédit vs réel). Aucune donnée inventée.
    """
    from services.mise_calculator import generer_plan, plan_to_dict
    from services.bet_settlement import settle_plan
    from db.models import Resultat as ResultatModel

    course = (await db.execute(
        select(Course).where(Course.course_id == course_id)
    )).scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")
    if course.statut != "termine":
        raise HTTPException(status_code=409, detail="Course non terminée — bilan indisponible")

    resultat = await db.get(ResultatModel, course_id)
    if not resultat or not resultat.classement:
        raise HTTPException(status_code=404, detail="Résultat officiel indisponible")

    # Prédictions réellement émises pour cette course
    from sqlalchemy import select as _s
    from db.models import Prediction as Pred
    rows = (await db.execute(
        _s(Pred, Participation, Cheval)
        .join(Participation, Participation.participation_id == Pred.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(Participation.course_id == course_id)
        .order_by(Pred.rang_predit)
    )).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Aucun pronostic enregistré pour cette course")

    preds = []
    for pred, part, cheval in rows:
        preds.append({
            "numero": part.numero,
            "nom_cheval": cheval.nom,
            "proba_top3": pred.proba_top3,
            "proba_top1": pred.proba_top1,
            # Cote FIGÉE au prono (cohérence avec ce qui était affiché avant départ).
            "cote_pmu": _cote_plan(pred, part),
            "non_partant": part.non_partant,
            "rang_predit": pred.rang_predit,
        })

    from services.bet_catalog import course_info_bets
    course_info = course_info_bets(course)

    montant = max(2.0, min(float(montant or 20), 10000.0))
    nb_partants = course.nb_partants or len(preds)

    # Mêmes signaux adaptatifs que le live (le bilan reflète la VRAIE méthode de
    # chaque profil : sélection + mise + ROI passé + thermostat).
    try:
        from ml.bet_performance import get_learned_type_weights, get_model_heat
        roi_weights = await get_learned_type_weights(
            db, discipline=getattr(course, "discipline", None),
            nb_partants=getattr(course, "nb_partants", None))
        heat = await get_model_heat(db)
    except Exception:
        roi_weights, heat = {}, 0.0

    # Features par numéro → signal_mults par profil pour la SIMULATION (mêmes entrées
    # que le live/le gel : sans ça la simulation rétro diverge des paris affichés).
    feats_by_num: dict = {}
    sig_perf = None
    try:
        from ml.signal_performance import load_signal_performance
        from db.models import FeatureML as _FM
        sig_perf = await load_signal_performance(db)
        fq = (select(Participation.numero, _FM.features)
              .join(_FM, _FM.participation_id == Participation.participation_id)
              .where(Participation.course_id == course_id))
        for numero, feats in (await db.execute(fq)).all():
            feats_by_num[int(numero)] = feats or {}
    except Exception:
        feats_by_num, sig_perf = {}, None

    # ── Bilan PAR PROFIL (prudent / modéré / risqué) ─────────────────────
    # SOURCE DE VÉRITÉ : le PLAN RÉELLEMENT FIGÉ avant le départ (profil_run_log),
    # réglé aux vrais rapports PMU — EXACTEMENT ce que montre le palmarès. On NE
    # régénère PAS le plan à la volée (sinon le bilan diverge du prono figé : cotes,
    # heat et ROI weights ont changé depuis → paris différents = incohérence vue par
    # l'utilisateur). Fallback simulation UNIQUEMENT si aucune trace figée (course
    # legacy jamais figée en live), et CLAIREMENT marquée comme telle.
    from sqlalchemy import text as _text
    import json as _json
    from ml.profil_learning import PROFILS, MISE_REF, ensure_tables

    PROFIL_LABELS = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}

    try:
        await ensure_tables(db)
        frozen_rows = (await db.execute(_text("""
            SELECT profil, plan, resultat, created_at, settled_at, statut
            FROM profil_run_log
            WHERE course_id = :cid AND statut IN ('settled', 'partial')
              AND COALESCE(meta->>'backfill', '') <> 'true'
              AND created_at < :depart
        """), {"cid": course_id, "depart": course.date_heure})).all()
    except Exception:
        frozen_rows = []
    frozen: dict = {}
    for prof, plan_j, res_j, c_at, s_at, st in frozen_rows:
        frozen[prof] = {
            "plan": plan_j if isinstance(plan_j, dict) else _json.loads(plan_j or "{}"),
            "resultat": res_j if isinstance(res_j, dict) else _json.loads(res_j or "{}"),
            "created_at": c_at, "settled_at": s_at, "statut": st,
        }

    has_fige = any(fr.get("resultat") for fr in frozen.values())
    # Le BILAN (résultats) est TOUJOURS à la mise de référence 10€ par profil — figé
    # comme simulation. C'est une vue comparable « 10€ par type de risque » (demande
    # user), indépendante de la mise que l'utilisateur a pu saisir au calculateur.
    montant = float(MISE_REF)

    bilans_profils = []
    for prof in PROFILS:
        fr = frozen.get(prof)
        if fr and fr.get("resultat"):
            # VRAI prono figé avant course + réglé (identique au palmarès).
            plan_p = fr["plan"]
            bilan_p = fr["resultat"]
            source = "fige"
            fige_le = fr["created_at"].isoformat() if fr["created_at"] else None
            regle_le = fr["settled_at"].isoformat() if fr["settled_at"] else None
        else:
            # Aucune trace figée → SIMULATION rétrospective (pas un vrai prono émis).
            # Mêmes entrées que le live/le gel : ROI weights + signal_mults PAR PROFIL
            # → la simulation reflète la VRAIE méthode (réduit l'écart prono↔bilan).
            try:
                roi_weights_p = await get_learned_type_weights(
                    db, profil=prof,
                    discipline=getattr(course, "discipline", None),
                    nb_partants=getattr(course, "nb_partants", None))
            except Exception:
                roi_weights_p = roi_weights
            sig_mults_p = {}
            if sig_perf and feats_by_num:
                try:
                    from ml.signal_performance import signal_multiplier as _sm
                    sig_mults_p = {n: _sm(f, sig_perf, prof) for n, f in feats_by_num.items()}
                except Exception:
                    sig_mults_p = {}
            plan_p = plan_to_dict(generer_plan(montant, prof, preds, course_info, None,
                                               roi_weights_p, heat, sig_mults_p,
                                               respect_montant=True))
            bilan_p = settle_plan(plan_p, resultat.classement, resultat.rapports, nb_partants)
            source = "simulation"
            fige_le = regle_le = None
        if bilan_p.get("en_attente"):
            verdict_p = "en_attente"
        elif bilan_p["net"] >= 0:
            verdict_p = "gagnant"
        else:
            verdict_p = "perdant"
        bilans_profils.append({
            "profil": prof,
            "profil_label": PROFIL_LABELS[prof],
            "mode_adaptatif": plan_p.get("mode_adaptatif", "normal"),
            "esperance_gain": plan_p.get("esperance_gain", 0.0),
            "bilan": bilan_p,
            "verdict": verdict_p,
            "source": source,        # "fige" = vrai prono pré-course | "simulation" = legacy
            "fige_le": fige_le,
            "regle_le": regle_le,
        })

    # Bilan principal (Modéré) — rétro-compat avec l'ancien rendu.
    bilan = next(b["bilan"] for b in bilans_profils if b["profil"] == "equilibre")

    # ── Comparaison pronostic vs résultat réel ───────────────────────────
    pos_by_num = {}
    for e in resultat.classement:
        try:
            pos_by_num[int(e["numero"])] = int(e["position"]) if e.get("position") else None
        except (TypeError, ValueError, KeyError):
            continue
    # Arrivée officielle ordonnée — top-5 pour pouvoir justifier TOUS les types de
    # paris (2sur4/Quarté = 4 chevaux, Quinté = 5), pas seulement le top-3.
    arrivee_ordonnee = [int(e["numero"]) for e in sorted(
        [x for x in resultat.classement if x.get("position")],
        key=lambda x: x["position"]
    )]
    actual_top5 = arrivee_ordonnee[:5]
    actual_top3 = arrivee_ordonnee[:3]
    gagnant_reel = actual_top3[0] if actual_top3 else None

    # Top prédit par le modèle — ordonné par PROBABILITÉ (proba_top1 puis top3),
    # c.-à-d. la même base que le plan de mise (cohérence bilan ↔ paris).
    predicted = [p for p in preds if not p.get("non_partant")]
    predicted.sort(key=lambda p: (-(p.get("proba_top1") or 0.0), -(p.get("proba_top3") or 0.0)))
    predicted_top3 = [p["numero"] for p in predicted[:3]]
    predicted_top5 = [p["numero"] for p in predicted[:5]]
    rang_predit_gagnant = None
    if gagnant_reel is not None:
        for idx, p in enumerate(predicted, start=1):
            if p["numero"] == gagnant_reel:
                rang_predit_gagnant = idx
                break
    overlap_top3 = len(set(predicted_top3) & set(actual_top3))

    # Verdict : le plan a-t-il été rentable ? + le modèle a-t-il vu le gagnant ?
    modele_a_vu_gagnant = rang_predit_gagnant is not None and rang_predit_gagnant <= 3
    if bilan.get("en_attente"):
        verdict = "en_attente"  # un pari gagné dont le rapport PMU n'est pas encore publié
    elif bilan["net"] >= 0:
        verdict = "gagnant"
    else:
        verdict = "perdant"

    return {
        "course_id": course_id,
        "montant": montant,
        # source globale : "fige" = plans réellement figés avant départ (= palmarès) ;
        # "simulation" = aucune trace figée, rejeu rétrospectif (course legacy).
        "source": "fige" if has_fige else "simulation",
        "bilan": bilan,
        "bilans_profils": bilans_profils,
        "comparaison": {
            "predicted_top3": predicted_top3,
            "predicted_top5": predicted_top5,
            "actual_top3": actual_top3,
            "actual_top5": actual_top5,
            "gagnant_reel": gagnant_reel,
            "rang_predit_gagnant": rang_predit_gagnant,
            "overlap_top3": overlap_top3,
            "modele_a_vu_gagnant": modele_a_vu_gagnant,
        },
        "verdict": verdict,
    }


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
    _rl: None = Depends(rate_limit_predictions),  # Monte Carlo + coverage 5000 = lourd
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
        "est_2sur4": course.est_2sur4,
    }
    # Drapeaux fins de disponibilité (couplé/trio ordre si champ réduit, etc.).
    from services.bet_catalog import derive_bet_flags as _dbf
    course_info.update(_dbf(
        getattr(course, "paris_disponibles", None),
        est_tierce=bool(course.est_tierce), est_quarte=bool(course.est_quarte),
        est_quinte=bool(course.est_quinte), est_2sur4=bool(course.est_2sur4),
    ))

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

    # 20 dernières participations + position d'arrivée réelle (LEFT JOIN historique).
    # (Avant : une 1re requête morte avec une jointure cartésienne sur date_heure,
    # exécutée pour rien à chaque appel, et position toujours None.)
    participations_res = await db.execute(text("""
        SELECT
            co.date_heure,
            ch.nom AS nom_cheval,
            ch.cheval_id,
            co.hippodrome_nom,
            co.discipline,
            p.numero,
            p.cote_pmu,
            h.position_arrivee
        FROM participations p
        JOIN courses co ON co.course_id = p.course_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN historique_courses h
            ON h.course_id = co.course_id AND h.cheval_id = ch.cheval_id
        WHERE p.jockey_id = :jid
        ORDER BY co.date_heure DESC
        LIMIT 20
    """), {"jid": jockey_id})
    part_rows = participations_res.fetchall()

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
            "position": r[7],  # position d'arrivée réelle (None si non disponible)
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
