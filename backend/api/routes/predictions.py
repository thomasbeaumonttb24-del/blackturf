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

from api.model_metrics import real_model_metrics, plausible_brier
from api.middleware.rate_limit import rate_limit_predictions
from api.routes.auth import get_current_user, require_pro
from db.database import get_db
from db.models import (
    Prediction, ValueBet, Recommandation, Participation,
    Cheval, Course, User
)

log = structlog.get_logger()
router = APIRouter()

# Gel du pronostic à T-10 min (cf. courses.PRONO_LOCK_MIN). Avant le gel, l'EV et le
# value bet affichés sont recalculés EN DIRECT sur la cote live (l'estimation de gain
# suit le marché → impacte la sélection) ; après le gel, on sert la cote figée.
PRONO_LOCK_MIN = 10


def _is_prono_fige(date_heure) -> bool:
    """True dès qu'on est à ≤ T-10 min du départ (prono gelé)."""
    if not date_heure:
        return False
    now = datetime.now(timezone.utc) if date_heure.tzinfo else datetime.now()
    return now >= date_heure - timedelta(minutes=PRONO_LOCK_MIN)


# Quota journalier de pronostics consultés (funnel freemium).
# 1 prono = 1 course dont on ouvre les prédictions IA. Re-consulter une course déjà
# ouverte aujourd'hui ne reconsomme pas le quota.
# Valeurs arrêtées par Thomas le 2026-08-16 : Free/Découverte 1/jour, Standard/Starter
# 5/jour, Expert/admin illimité. Identiques à MISE_PLAN_DAILY_LIMITS (courses.py) :
# un compte Free ouvre le classement IA ET son plan de mise sur la MÊME course du jour.
PRONO_DAILY_LIMITS = {"free": 1, "decouverte": 1, "standard": 5, "starter": 5}


async def _prono_quota_check(user: User, course_id: str) -> tuple[bool, int]:
    """(autorisé, quota_restant). Compteur Redis par user/jour (set de course_ids,
    TTL 36h). -1 = illimité. Fail-open si Redis indisponible (dispo > paywall strict)."""
    if getattr(user, "is_admin", False):
        return True, -1
    limit = PRONO_DAILY_LIMITS.get(user.plan)
    if limit is None:  # expert / pro = illimité
        return True, -1
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"prono_quota:{user.user_id}:{day}"
        if await redis.sismember(key, course_id):
            return True, max(0, limit - await redis.scard(key))
        used = await redis.scard(key)
        if used >= limit:
            return False, 0
        await redis.sadd(key, course_id)
        await redis.expire(key, 129600)  # 36h
        return True, max(0, limit - (used + 1))
    except Exception:
        log.warning("prono_quota.redis_unavailable", user_id=getattr(user, "user_id", None))
        return True, -1


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
    proba_top1_low: Optional[float] = None
    proba_top1_high: Optional[float] = None
    rang_predit: int
    confidence_score: Optional[float]
    cote_pmu: Optional[float]
    cote_juste: Optional[float] = None  # cote "juste" IA = 1/proba_top1 (sans marge)
    value_bet: Optional[dict]


class CoursePredictionsOut(BaseModel):
    course_id: str
    statut: str
    predictions: list[PredictionOut]
    recommandations: list[dict]
    verrouille: bool = False      # True = quota journalier dépassé → données IA masquées
    quota_restant: int = -1       # pronos restants aujourd'hui ; -1 = illimité


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
    """Prédictions IA pour une course. Quota journalier selon le plan (funnel freemium)."""
    course_res = await db.execute(select(Course).where(Course.course_id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Quota journalier UNIQUEMENT sur courses bettables (a_venir / en_cours). Ouvrir une
    # course terminee pour consulter l'arrivee (info publique) ne consomme PAS le prono
    # du jour -> evite le faux "deja utilise" quand on a juste regarde une course finie.
    if course.statut in ("a_venir", "en_cours"):
        autorise, quota_restant = await _prono_quota_check(user, course_id)
    else:
        autorise, quota_restant = True, -1

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

    # ── EV LIVE (avant gel) ──────────────────────────────────────────────────
    # Le value bet stocké est recalculé toutes les ~8 min par le cycle. Tant que le
    # prono n'est PAS figé (> T-10 min), on RECALCULE l'EV/le niveau en direct sur la
    # cote du marché → l'estimation de gain bouge avec les cotes (et change donc la
    # sélection : un cheval dont la cote monte peut redevenir un value bet). Après le
    # gel, on garde le value bet figé (cohérence avec le plan/bilan).
    fige = _is_prono_fige(course.date_heure)
    live_cotes: dict[int, float] = {}
    cote_calib = None
    ev_band_perf = None
    if not fige and course.statut in ("a_venir", "en_cours"):
        try:
            from services.pmu_cotes import fetch_live_cotes
            live_cotes = {int(c["numero"]): float(c["cote"])
                          for c in await fetch_live_cotes(course_id) if c.get("cote")}
        except Exception:
            live_cotes = {}
        try:
            from ml.cote_calibration import load_cote_calibration
            cote_calib = await load_cote_calibration(db)
        except Exception:
            cote_calib = None
        try:
            from ml.signal_performance import load_ev_band_performance
            ev_band_perf = await load_ev_band_performance(db)
        except Exception:
            ev_band_perf = None

    def _live_vb(pred, part):
        """Recalcule le value bet à la cote LIVE (mêmes garde-fous que le cycle :
        triangulation multi-sources + calibration par tranche de cote). None si le
        cheval n'est plus un value bet à la cote actuelle."""
        cote_live = live_cotes.get(part.numero)
        if not cote_live or not pred.proba_top1:
            return None
        try:
            from ml.valuebets import detect_value_bet
            return detect_value_bet(
                pred.proba_top1,
                cote_pmu=cote_live,
                cote_geny=part.cote_geny,
                cote_bzh=part.cote_bzh,
                cote_winamax=part.cote_winamax,
                cote_betclic=part.cote_betclic,
                cote_unibet=part.cote_unibet,
                cote_betfair=part.cote_betfair_exchange,
                non_partant=bool(part.non_partant),
                cote_calib=cote_calib,
                ev_band_perf=ev_band_perf,
            )
        except Exception:
            return None

    predictions = []
    for pred, part, cheval in rows:
        vb = vbs_by_pid.get(part.participation_id)
        # Cote affichée : live avant gel, figée (stockée) après.
        cote_aff = (live_cotes.get(part.numero) if not fige else None) or part.cote_pmu
        # Value bet : recalcul live avant gel, sinon stocké.
        vb_live = _live_vb(pred, part) if not fige else None
        if vb_live:
            value_bet = {
                "ev_max": round(vb_live["ev_max"], 4),
                "niveau": vb_live["niveau"],
                "meilleure_source": vb_live["meilleure_source"],
                "spi_detected": vb.spi_detected if vb else vb_live.get("spi_detected", False),
                "spi_score": round(vb.spi_score, 3) if vb and vb.spi_score else None,
                "live": True,
            }
        elif vb and fige:
            value_bet = {
                "ev_max": round(vb.ev_max, 4),
                "niveau": vb.niveau,
                "meilleure_source": vb.meilleure_source,
                "spi_detected": vb.spi_detected,
                "spi_score": round(vb.spi_score, 3) if vb.spi_score else None,
            }
        else:
            # Avant gel sans value bet live = plus de valeur à la cote actuelle (ne pas
            # servir l'ancien VB stocké, qui contredirait la cote affichée).
            value_bet = None
        predictions.append(PredictionOut(
            prediction_id=pred.prediction_id,
            participation_id=part.participation_id,
            numero=part.numero,
            nom_cheval=cheval.nom,
            proba_top1=round(pred.proba_top1, 4),
            proba_top3=round(pred.proba_top3, 4),
            proba_top1_low=round(pred.proba_top1_low, 4) if pred.proba_top1_low is not None else None,
            proba_top1_high=round(pred.proba_top1_high, 4) if pred.proba_top1_high is not None else None,
            # Cote juste IA = 1/proba de victoire (cote "équitable" sans marge bookmaker),
            # bornée [1.01, 100] : éviter une cote absurde (1000) ou < seuil de rentabilité.
            cote_juste=(round(min(100.0, max(1.01, 1.0 / pred.proba_top1)), 1)
                        if pred.proba_top1 and pred.proba_top1 > 0.001 else None),
            rang_predit=pred.rang_predit,
            confidence_score=pred.confidence_score,
            cote_pmu=cote_aff,
            value_bet=value_bet,
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

    if not autorise:
        # Quota journalier dépassé → réponse VERROUILLÉE. On ne renvoie PAS les valeurs
        # IA (sinon lisibles via l'inspecteur réseau malgré le flou CSS). Le front affiche
        # le flou + cadenas + CTA upsell. La cote PMU reste (publique via le programme).
        predictions_masquees = [
            PredictionOut(
                prediction_id=p.prediction_id,
                participation_id=p.participation_id,
                numero=p.numero,
                nom_cheval=p.nom_cheval,
                proba_top1=0.0,
                proba_top3=0.0,
                rang_predit=0,
                confidence_score=None,
                cote_pmu=p.cote_pmu,
                cote_juste=None,
                value_bet=None,
            )
            for p in sorted(predictions, key=lambda x: x.numero)
        ]
        return CoursePredictionsOut(
            course_id=course_id,
            statut=course.statut,
            predictions=predictions_masquees,
            recommandations=[],
            verrouille=True,
            quota_restant=0,
        )

    return CoursePredictionsOut(
        course_id=course_id,
        statut=course.statut,
        predictions=predictions,
        recommandations=recos,
        verrouille=False,
        quota_restant=quota_restant,
    )


@router.post("/courses/{course_id}/predict")
async def trigger_prediction(
    course_id: str,
    background_tasks: BackgroundTasks,
    bankroll: float = Query(default=100.0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_pro),
    _rl: None = Depends(rate_limit_predictions),  # anti-abus de calcul (pipeline ML)
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


@router.get("/value-bets/compteur")
async def get_value_bets_compteur(
    niveau_min: int = Query(default=3, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
):
    """
    Compteur AGRÉGÉ de value bets actifs (funnel Free, décision produit 2026-08-16,
    Thomas) : bandeau "N paris de valeur ★★★+ actifs maintenant — visibles dès
    Standard" sur le programme/dashboard, pour donner à Free un signal honnête de
    ce qu'il rate EN CE MOMENT.

    Public et volontairement minimal : UNIQUEMENT un entier (`count`), JAMAIS le
    détail d'un value bet (cheval / course / cote) — même principe d'autorisation
    que le fix appliqué à /ws/value-bets (authentification ≠ autorisation : on ne
    sert pas la donnée protégée juste parce que la requête est "en lecture seule"
    ou "juste pour un total"). Le nombre est un vrai `COUNT(*)` en base, jamais une
    estimation ni un chiffre arrondi à la hausse.
    """
    q = (
        select(func.count(ValueBet.vb_id))
        .select_from(ValueBet)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(
            ValueBet.actif == True,
            ValueBet.niveau >= niveau_min,
            Course.statut.in_(["a_venir", "en_cours"]),
        )
    )
    count = (await db.execute(q)).scalar_one()
    return {"count": int(count), "niveau_min": niveau_min}


@router.get("/pari-du-jour-profils")
async def get_pari_du_jour_profils(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """LE meilleur pari du jour POUR CHAQUE PROFIL (Prudent / Modéré / Risqué).
    Lit les plans DÉJÀ FIGÉS avant course (profil_run_log pending) sur les courses
    à venir, et choisit pour chaque profil le pari à plus forte conviction. 100% issu
    de l'analyse + apprentissage par profil. null par profil si rien de crédible."""
    if user.plan in ("free", "decouverte"):
        return {"profils": []}
    from sqlalchemy import text as _t
    import json as _json
    LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
    try:
        rows = (await db.execute(_t("""
            SELECT r.profil, r.plan, c.course_id, c.hippodrome_nom, c.date_heure,
                   c.numero_reunion, c.numero, c.discipline
            FROM profil_run_log r
            JOIN courses c ON c.course_id = r.course_id
            WHERE r.statut = 'pending' AND c.statut IN ('a_venir', 'en_cours')
              AND c.date_heure >= now() - interval '2 hours'
        """))).all()
    except Exception:
        return {"profils": []}

    best: dict = {}
    for profil, plan, cid, hippo, dh, n_r, n_c, disc in rows:
        pl = plan if isinstance(plan, dict) else _json.loads(plan or "{}")
        for niv in pl.get("niveaux", []):
            for p in niv.get("paris", []):
                proba = float(p.get("probabilite") or 0)
                ev = float(p.get("ev_estime") or 0)
                # Score : on veut une vraie chance ET de la valeur. Prudent privilégie
                # la proba, Risqué le rapport ; ici score commun proba×(1+max(ev,0)).
                score = proba * (1.0 + max(ev, 0.0)) * (1.0 + max(float(p.get("gain_potentiel") or 0) / max(float(p.get("mise") or 1), 1) / 50.0, 0))
                cur = best.get(profil)
                if cur is None or score > cur["_score"]:
                    code = (f"R{n_r}C{n_c}" if n_r and n_c else
                            (cid[8:] if len(cid) > 8 and "R" in cid[8:] else cid))
                    best[profil] = {
                        "_score": score, "profil": profil, "profil_label": LBL.get(profil, profil),
                        "course_id": cid, "code": code, "hippodrome": hippo,
                        "date_heure": dh.isoformat() if dh else None, "discipline": disc,
                        "type_pari": p.get("type"),
                        "chevaux": p.get("chevaux", []),
                        "mise": p.get("mise"), "gain_potentiel": p.get("gain_potentiel"),
                        "probabilite": round(proba, 4), "ev": round(ev, 4),
                        "raisons": p.get("raisons", []),
                    }
    out = []
    for k in ("conservateur", "equilibre", "agressif"):
        if k in best:
            b = best[k]; b.pop("_score", None); out.append(b)
    return {"profils": out}


@router.get("/pari-du-jour")
async def get_pari_du_jour(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    LE pari du jour : meilleur value bet à venir, classé par score composite
    edge × chance de gain × accord des modèles (calibration). On exige une vraie
    chance de victoire (proba_top1 ≥ 0.10) pour éviter les longshots à EV gonflé.
    Renvoie null si aucun pari crédible (intégrité : pas de pari forcé).
    """
    if user.plan in ("free", "decouverte"):
        return None

    q = (
        select(ValueBet, Prediction, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Prediction, Prediction.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(and_(
            ValueBet.actif == True,
            Course.statut.in_(["a_venir", "en_cours"]),
            Prediction.proba_top1 >= 0.10,
            ValueBet.ev_max > 0.05,
        ))
    )
    rows = (await db.execute(q)).all()
    if not rows:
        return None

    # Conviction signal (appris du ROI réel par signal) — l'edge validé hors-échantillon :
    # le filtre conviction≥1.1 a un taux de gain 3-4× le marché sur 5 fenêtres jamais vues.
    # On en fait LE critère du "coup sûr" → on privilégie les paris à edge prouvé.
    feats_by_pid: dict = {}
    signal_perf = None
    try:
        from db.models import FeatureML
        from ml.signal_performance import load_signal_performance, signal_multiplier
        signal_perf = await load_signal_performance(db)
        pids = [vb.participation_id for vb, *_ in rows]
        if signal_perf and pids:
            fr = await db.execute(select(FeatureML.participation_id, FeatureML.features)
                                  .where(FeatureML.participation_id.in_(pids)))
            feats_by_pid = {pid: f for pid, f in fr.all()}
    except Exception:
        signal_perf = None

    def _conv(vb) -> float:
        if not signal_perf:
            return 1.0
        f = feats_by_pid.get(vb.participation_id)
        return signal_multiplier(f or {}, signal_perf) if f else 1.0

    best = best_edge = None
    best_score = best_edge_score = -1.0
    for vb, pred, part, cheval, course in rows:
        proba = float(pred.proba_top1 or 0)
        conf = float(pred.confidence_score or 0) / 100.0  # 0-1 (accord des modèles)
        ev = float(vb.ev_max or 0)
        sig = _conv(vb)
        # Score composite : edge (EV) × chance réelle × confiance × CONVICTION SIGNAL.
        score = ev * proba * (0.5 + 0.5 * conf) * sig
        if score > best_score:
            best_score = score
            best = (vb, pred, part, cheval, course)
        if sig >= 1.1 and score > best_edge_score:   # edge signal validé
            best_edge_score = score
            best_edge = (vb, pred, part, cheval, course)

    # "Coup sûr" = priorité au pari à edge signal prouvé ; sinon meilleur score.
    chosen = best_edge or best
    if not chosen:
        return None
    vb, pred, part, cheval, course = chosen
    best_score = best_edge_score if best_edge else best_score
    conviction = round(_conv(vb), 2)
    edge_valide = conviction >= 1.1
    cid = course.course_id
    # Code public R{réunion}C{course} : réunion = numExterne (numero_reunion) pour
    # matcher pmu.fr ; fallback sur le suffixe du course_id (numOfficiel) si absent.
    if course.numero_reunion:
        code = f"R{course.numero_reunion}C{part.numero}"
    else:
        code = cid[8:] if len(cid) > 8 and "R" in cid[8:] else cid
    proba = float(pred.proba_top1 or 0)
    conf = round(float(pred.confidence_score or 0))
    # cote_pmu peut être None (value bet détecté via une autre source) → éviter
    # le crash f"{None:.1f}" et formater la cote seulement si présente.
    _cote_aff = part.cote_pmu or part.cote_geny or part.cote_betclic or part.cote_winamax or None
    return {
        "course_id": cid,
        "code": code,
        "hippodrome": course.hippodrome_nom,
        "date_heure": course.date_heure,
        "discipline": course.discipline,
        "numero": part.numero,
        "nom_cheval": cheval.nom,
        "cote_pmu": part.cote_pmu,
        "ev": round(float(vb.ev_max or 0), 4),
        "proba_top1": round(proba, 4),
        "proba_top1_low": round(pred.proba_top1_low, 4) if pred.proba_top1_low is not None else None,
        "proba_top1_high": round(pred.proba_top1_high, 4) if pred.proba_top1_high is not None else None,
        "confidence": conf,
        "niveau": vb.niveau,
        "spi_detected": vb.spi_detected,
        "score": round(best_score, 5),
        "conviction": conviction,        # multiplicateur signal appris (≥1.1 = edge prouvé)
        "edge_valide": edge_valide,      # True = signaux historiquement gagnants présents
        "raison": (
            f"N°{part.numero} {cheval.nom} — le modèle lui donne {proba*100:.0f}% de gagner "
            + (f"(cote {_cote_aff:.1f}) " if _cote_aff else "")
            + f"soit une valeur de +{float(vb.ev_max or 0)*100:.0f}%, "
            f"avec {conf}% d'accord entre les 3 modèles."
            + (" · signaux historiquement gagnants confirmés (edge validé)" if edge_valide else "")
        ),
    }


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
    _rl: None = Depends(rate_limit_predictions),  # Claude + Monte Carlo = coûteux
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

    # ── Cotes LIVE + recalcul EV avant le gel (T-10) ──
    # Comme la fiche prédictions, l'analyse (coverage jackpot, coup à tenter, dutch)
    # suit le marché en direct tant que le prono n'est pas figé → les estimations de
    # gain bougent avec les cotes. Après le gel, on sert les cotes/VB figés.
    fige = _is_prono_fige(course.date_heure)
    live_cotes: dict[int, float] = {}
    cote_calib = None
    ev_band_perf = None
    if not fige and course.statut in ("a_venir", "en_cours"):
        try:
            from services.pmu_cotes import fetch_live_cotes
            live_cotes = {int(c["numero"]): float(c["cote"])
                          for c in await fetch_live_cotes(course_id) if c.get("cote")}
        except Exception:
            live_cotes = {}
        try:
            from ml.cote_calibration import load_cote_calibration
            cote_calib = await load_cote_calibration(db)
        except Exception:
            cote_calib = None
        try:
            from ml.signal_performance import load_ev_band_performance
            ev_band_perf = await load_ev_band_performance(db)
        except Exception:
            ev_band_perf = None

    predictions = []
    features_by_pid = {}
    for pid, feat, p3, p1, rang, num, nom, cote_pmu, cote_min in rows:
        features_by_pid[pid] = feat or {}
        cote_live = live_cotes.get(int(num)) if not fige else None
        cote_aff = cote_live or cote_pmu
        vb_aff = vb_map.get(pid)
        if cote_live and p1:
            # Recalcul EV/value-bet à la cote live (calibration par tranche de cote).
            try:
                from ml.valuebets import detect_value_bet
                _vbl = detect_value_bet(float(p1), cote_pmu=cote_live, cote_calib=cote_calib, ev_band_perf=ev_band_perf)
                vb_aff = ({"ev_max": _vbl["ev_max"], "niveau": _vbl["niveau"],
                           "spi_detected": _vbl.get("spi_detected", False),
                           "spi_score": _vbl.get("spi_score")} if _vbl else None)
            except Exception:
                pass
        predictions.append({
            "participation_id": pid,
            "numero": num,
            "nom": nom,
            "proba_top3": float(p3 or 0),
            "proba_top1": float(p1 or 0),
            "rang_predit": rang or 99,
            "cote_pmu": cote_aff,
            "cote_min": min(cote_aff, cote_min) if (cote_aff and cote_min) else (cote_aff or cote_min),
            "vb": vb_aff,
        })

    # Cache Redis : court avant le gel (cotes live), 2 min après (prono figé).
    cache_ttl = 20 if not fige else 120
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
        "est_2sur4": course.est_2sur4,
    }
    # Drapeaux canoniques de disponibilité (Couplé/Trio ordre, Super4, MULTI, PICK5…)
    # dérivés de la vérité PMU (paris_disponibles) — sinon le moteur ne propose jamais
    # Multi/Pick5 ni les variantes à l'ordre. Centralisé dans bet_catalog.
    try:
        from services.bet_catalog import derive_bet_flags
        course_info["paris_disponibles"] = course.paris_disponibles
        course_info.update(derive_bet_flags(
            course.paris_disponibles,
            est_tierce=bool(course.est_tierce), est_quarte=bool(course.est_quarte),
            est_quinte=bool(course.est_quinte), est_2sur4=bool(course.est_2sur4),
        ))
    except Exception:
        pass

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
        from ml.combo_bets import build_combo_proposals, build_coverage_bets
        result["paris_multiples"] = build_combo_proposals(predictions, course_info, bankroll=100.0)
        # Couverture jackpot (base+champ) + « coup à tenter » — gros gains
        cov = build_coverage_bets(predictions, course_info, bankroll=100.0)
        result["coverage_jackpot"] = cov.get("proposals", [])
        result["coup_a_tenter"] = cov.get("coup_a_tenter")
    except Exception as e:
        log.warning("analyse.combo_bets_failed", course_id=course_id, err=str(e)[:160])

    # ── Détection COURSE À OUTSIDER (champ ouvert + grosses cotes à edge +
    # taux de surprises historique réel) — pour le profil risqué et l'affichage.
    # On passe les prédictions ENRICHIES (avec `explanation`) → chaque candidat
    # outsider porte ses facteurs réels + une justification complète.
    try:
        from ml.outsider_detector import detect_for_course
        enriched_preds = result.get("predictions", predictions)
        det = await detect_for_course(
            db, course_id, enriched_preds, course.discipline, course.nb_partants,
        )
        result["detection_outsider"] = det
        # « Chevaux à éviter » supprimé définitivement (décision produit) — plus calculé
        # ni renvoyé.
    except Exception as e:
        log.warning("analyse.outsider_detect_failed", course_id=course_id, err=str(e)[:160])

    # Cache : court avant le gel (cotes live), 2 min après.
    try:
        await redis.setex(cache_key, cache_ttl, json.dumps(result, default=str))
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
    # Métriques fiables : précision réelle observée + ROI masqué si aberrant.
    m_real = await real_model_metrics(db, mv)
    # Modèle de victoire dédié (P(top1) apprise) — présence + métriques de holdout.
    win_model_actif = False
    win_auc = None
    win_brier = None
    try:
        from ml.models import BlackTurfEnsemble
        _m = BlackTurfEnsemble.load_current()
        if _m is not None and getattr(_m, "win_model", None) is not None:
            win_model_actif = True
            win_auc = round(float(getattr(_m, "win_auc", 0.0)), 4) or None
            win_brier = round(float(getattr(_m, "win_brier", 0.0)), 4) or None
    except Exception:
        pass
    return {
        "version_num": mv.version_num,
        # Endpoint PUBLIC : ne jamais exposer une AUC/Brier aberrante (ex. AUC 0.06
        # d'un modèle seed) → masquées si hors plage plausible (None → front "—").
        "auc_roc": m_real["auc_roc"],
        "brier_score": plausible_brier(mv.brier_score),
        "precision_top3": m_real["precision_top3"],
        "roi_simule": m_real["roi_simule"],
        "nb_courses_evaluees": m_real["nb_courses_evaluees"],
        "nb_courses_train": mv.nb_courses_train,
        "win_model_actif": win_model_actif,
        "win_auc": win_auc,
        "win_brier": win_brier,
        "created_at": mv.created_at,
    }
