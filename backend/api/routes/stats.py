"""
Stats publiques — BlackTurf.
Métriques du modèle + courbe équité simulée + ML monitoring.
Cache Redis pour éviter requêtes lourdes répétées.
"""
import json
import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from api.model_metrics import real_model_metrics, plausible_auc
from api.profil_backtest import backtest_profils
from api.routes.auth import get_current_user, require_admin
from db.database import get_db
from db.redis_client import get_redis
from db.models import (
    ModelVersion, Course, User, ValueBet, Participation,
    Resultat, Cheval, AdaptiveLearningState, DriftDetectorState,
    BankrollEntry, Recommandation, PredictionEvaluation, RaceLearningLog,
)
from services.course_resolution import STATUTS_NON_COURUES
import redis.asyncio as aioredis

log = structlog.get_logger()
router = APIRouter()


async def _cache_get(redis: aioredis.Redis, key: str) -> Any | None:
    try:
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(redis: aioredis.Redis, key: str, data: Any, ttl: int) -> None:
    try:
        await redis.setex(key, ttl, json.dumps(data, default=str))
    except Exception:
        pass


# ── Cache « stale-while-revalidate » ─────────────────────────────────────────
# Pourquoi (panne Palmarès du 2026-08-18) : /stats/track-record coûte ~29 s à froid
# alors que le client axios coupe à 15 s. Avec un TTL unique, l'expiration rendait la
# page DÉFINITIVEMENT inutilisable pendant toute la fenêtre froide — chaque tentative
# dépassait le timeout et `refreshInterval: 60_000` relançait à l'infini, donc
# skeleton perpétuel. `job_warm_caches` ne rattrapait rien : cache encore chaud →
# l'endpoint renvoyait tôt SANS réécrire la clé, le TTL n'était jamais prolongé et
# l'expiration tombait à une heure décorrélée du cron /30 min.
#
# On découple donc conservation et fraîcheur : la charge utile survit `stale_ttl`, un
# drapeau séparé porte la fraîcheur. Périmé mais présent → on sert immédiatement la
# version précédente et on recalcule en fond. L'utilisateur n'attend jamais le calcul
# froid ; seul un Redis totalement vide bloque, une seule fois.
_SWR_STALE_TTL = 86400  # 24 h de conservation de secours


async def _cache_get_swr(redis: aioredis.Redis, key: str) -> tuple[Any | None, bool]:
    """Renvoie (charge_utile ou None, est_frais)."""
    try:
        raw = await redis.get(key)
        if not raw:
            return None, False
        frais = await redis.exists(f"{key}:fresh")
        return json.loads(raw), bool(frais)
    except Exception:
        return None, False


async def _cache_set_swr(redis: aioredis.Redis, key: str, data: Any,
                         fresh_ttl: int, stale_ttl: int = _SWR_STALE_TTL) -> None:
    try:
        payload = json.dumps(data, default=str)
        await redis.setex(key, stale_ttl, payload)
        await redis.setex(f"{key}:fresh", fresh_ttl, "1")
    except Exception:
        pass

def _winner_entry(classement) -> Optional[dict]:
    """Entrée du VAINQUEUR (position == 1), robuste à l'ordre du tableau JSON.
    ⚠️ `classement[0]` n'est PAS garanti être le 1er : le tableau peut être trié
    par numéro ou non ordonné → régler au gagnant via classement[0] fausse le ROI.
    On prend l'entrée de position minimale (== 1)."""
    if not classement or not isinstance(classement, list):
        return None
    best = None
    best_pos = None
    for e in classement:
        if not isinstance(e, dict):
            continue
        p = e.get("position")
        if not isinstance(p, (int, float)):
            continue
        if best_pos is None or p < best_pos:
            best_pos, best = int(p), e
    return best


async def _vb_flat_backtest(db: AsyncSession, since_days: int = 180, mise: float = 10.0, start: float = 1000.0) -> dict:
    """Backtest HONNÊTE : 10€ flat en Simple Gagnant sur chaque value bet ★★★+
    (niveau ≥ 3) des `since_days` derniers jours, réglé sur l'arrivée RÉELLE à la
    COTE FIGÉE pré-départ (jamais la cote de clôture) et UNIQUEMENT sur les value
    bets détectés AVANT le départ (garde anti-backfill). Même méthode honnête que
    backtest.py / edge_monitor.py — cf. audit 2026-07-21. Source unique pour la
    courbe d'équité ET le ROI simulé 6 mois. is_real=False si < 10 paris."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = (await db.execute(
        select(ValueBet, Participation, Course, Resultat, PredictionEvaluation)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .outerjoin(PredictionEvaluation, PredictionEvaluation.prediction_id == ValueBet.prediction_id)
        .outerjoin(Resultat, Resultat.course_id == ValueBet.course_id)
        .where(
            ValueBet.niveau >= 3,
            Course.statut == "termine",
            Course.date_heure >= since,
            # Garde ANTI-BACKFILL : le value bet doit avoir été détecté AVANT le
            # départ. Sinon = pari reconstruit a posteriori sur une course connue
            # (in-sample) → ROI gonflé.
            ValueBet.detecte_a < Course.date_heure,
            PredictionEvaluation.created_at.is_not(None),
            PredictionEvaluation.created_at < Course.date_heure,
            PredictionEvaluation.is_replayable.is_(True),
        )
        .order_by(Course.date_heure)
        .limit(500)
    )).all()

    if len(rows) < 10:
        return {"is_real": False, "points": [], "n_bets": len(rows), "roi_pct": None, "gain_net": None, "mise": mise}

    bankroll = start
    points = []
    for vb, part, course, resultat, pred in rows:
        _w = _winner_entry(resultat.classement) if resultat else None
        gagne = bool(_w and _w.get("numero") == part.numero)
        # COTE FIGÉE au moment du prono (pré-départ) ; fallback cote_pmu si absente.
        # Régler à cote_pmu seule pouvait utiliser une cote de clôture → ROI biaisé.
        cote = pred.cote_figee if (pred and pred.cote_figee and pred.cote_figee > 1) else part.cote_pmu
        if gagne and cote and cote > 1:
            bankroll += (cote - 1) * mise
        else:
            bankroll -= mise
        points.append({"date": course.date_heure.strftime("%Y-%m-%d"), "bankroll": round(bankroll, 2)})

    n = len(rows)
    gain = bankroll - start
    roi = round(gain / (n * mise) * 100, 1) if n else None
    return {"is_real": True, "points": points, "n_bets": n, "roi_pct": roi, "gain_net": round(gain, 2), "mise": mise}


@router.get("/stats/public")
async def public_stats(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Métriques publiques — DB live avec fallback statique. Cache 5 min."""
    CACHE_KEY = "stats:public"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    mv = (await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )).scalar_one_or_none()

    nb_courses = (await db.execute(
        select(func.count(Course.course_id)).where(Course.statut == "termine")
    )).scalar() or 0

    nb_users = (await db.execute(
        select(func.count(User.user_id))
    )).scalar() or 0

    # Métriques 100% RÉELLES (règle d'intégrité : aucune valeur inventée). Une donnée
    # non fiable/indisponible renvoie null → le front affiche "—", jamais un placeholder
    # marketing. Plus de _STATIC_STATS (487 users / 12 450 courses / roi 8,4% fictifs).
    metrics = await real_model_metrics(db, mv)
    # ROI VOLONTAIREMENT ABSENT du public (exigence produit : le ROI n'est visible
    # que par l'admin, cf. endpoints /stats/equity-curve & /stats/palmares-gagnants
    # gardés par require_admin). Public = qualité du modèle uniquement (AUC, précision).
    result = {
        "auc_roc": metrics["auc_roc"],               # gardé ∈ [0.5,1], sinon null (jamais 0.06)
        "nb_courses_analysees": nb_courses,          # vrai nombre de courses terminées
        "nb_utilisateurs": nb_users,                 # vrai nombre d'utilisateurs
        "precision_top3": metrics["precision_top3"], # réelle (race_learning_log) ou null
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=300)  # 5 min
    return result


@router.get("/stats/equity-curve")
async def equity_curve(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _: User = Depends(require_admin),   # ROI/courbe capital = admin uniquement
):
    """
    Courbe capital simulée — basée sur NOS PLANS DE MISE 10€ PAR PROFIL, joués sur
    chaque course du programme et réglés au réel (vrais rapports PMU). Source =
    backtest profils (cache stats:profils). Retourne une courbe par profil
    (conservateur/equilibre/agressif) + `points` = profil par défaut (équilibre).
    Repli sur l'ancien backtest value-bets si le cache profils n'est pas peuplé.
    """
    cached = await _cache_get(redis, "stats:profils")
    if cached and cached.get("equity"):
        eq = cached["equity"]
        profils_series = {k: v for k, v in eq.items() if v}
        if profils_series:
            # Résumé RÉEL par profil (misé / gagné / net / ROI) issu du backtest.
            summ = {p["profil"]: p for p in (cached.get("profils") or [])}
            profils_resume = {}
            for k, pts in profils_series.items():
                s = summ.get(k, {})
                mise_tot = s.get("mise_totale")
                gain_tot = s.get("gain_total")
                net = s.get("gain_net")
                profils_resume[k] = {
                    "mise_totale": mise_tot,
                    "gain_total": gain_tot,
                    "gain_net": net,
                    "roi": s.get("roi"),
                    "roi_typique": s.get("roi_winsorise"),
                    "nb_courses": s.get("nb_courses"),
                }
            default_k = "equilibre" if "equilibre" in profils_series else next(iter(profils_series))
            return {
                "is_real": True,
                "source": "plan_profils",
                "mise_par_course": cached.get("mise_par_course", 10),
                "points": profils_series[default_k],   # rétro-compat : courbe P&L défaut
                "profils": profils_series,             # courbe P&L cumulé par profil
                "profils_resume": profils_resume,      # misé / gagné / net / ROI réels
                "gain_net": (profils_resume.get(default_k) or {}).get("gain_net"),
            }

    # ── Repli : ancien backtest value bets ★★★+ (si profils pas encore calculés) ──
    CACHE_KEY = "stats:equity-curve"
    fb = await _cache_get(redis, CACHE_KEY)
    if fb:
        return fb
    bt = await _vb_flat_backtest(db)
    if not bt["is_real"]:
        empty = {"is_real": False, "points": []}
        await _cache_set(redis, CACHE_KEY, empty, ttl=300)
        return empty
    result = {"is_real": True, "source": "value_bets", "points": bt["points"],
              "roi_pct": bt["roi_pct"], "gain_net": bt["gain_net"], "n_bets": bt["n_bets"]}
    await _cache_set(redis, CACHE_KEY, result, ttl=1800)
    return result


@router.get("/stats/ml-status")
async def ml_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Statut consolidé ML : adaptive learning + drift detector + modèle actif.
    Accessible à tous les utilisateurs authentifiés. Cache 5 min.
    """
    CACHE_KEY = "stats:ml-status"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    al_state = (await db.execute(
        select(AdaptiveLearningState).limit(1)
    )).scalar_one_or_none()

    dd_state = (await db.execute(
        select(DriftDetectorState).limit(1)
    )).scalar_one_or_none()

    model = (await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )).scalar_one_or_none()

    al_data: dict = {}
    if al_state:
        fw = al_state.feature_weights_json or {}
        top_features = sorted(fw.items(), key=lambda x: -abs(x[1]))[:10] if fw else []
        al_data = {
            "temperature": round(al_state.temperature, 4),
            "n_races": al_state.n_races,
            "brier_ema": round(al_state.brier_ema, 4),
            "surprise_ema": round(al_state.surprise_ema, 4),
            "top_features": [{"name": k, "weight": round(v, 4)} for k, v in top_features],
            "updated_at": al_state.updated_at.isoformat() if al_state.updated_at else None,
        }

    dd_data: dict = {}
    if dd_state:
        state_json = dd_state.state_json or {}
        dd_data = {
            "severity": dd_state.severity,
            "n_updates": dd_state.n_updates,
            # Pas de défaut inventé : si non mesuré → null (le front affiche "—"),
            # jamais un 0.20/0.30 présenté comme une vraie mesure.
            "brier_mean": (round(float(state_json["brier_mean"]), 4)
                           if state_json.get("brier_mean") is not None else None),
            "surprise_rate": (round(float(state_json["surprise_rate"]), 4)
                              if state_json.get("surprise_rate") is not None else None),
            "adwin_triggered": bool(state_json.get("adwin_triggered", False)),
            "ph_triggered": bool(state_json.get("ph_triggered", False)),
            "last_drift_at": dd_state.last_drift_at.isoformat() if dd_state.last_drift_at else None,
            "updated_at": dd_state.updated_at.isoformat() if dd_state.updated_at else None,
        }

    model_data: dict = {}
    if model:
        # Métriques fiables : précision réelle observée + ROI masqué si aberrant.
        m_real = await real_model_metrics(db, model)
        model_data = {
            "version": model.version_num,
            "auc_roc": m_real["auc_roc"],
            "brier_score": round(model.brier_score, 4) if model.brier_score else None,
            "precision_top3": m_real["precision_top3"],
            "roi_simule": round(m_real["roi_simule"] * 100, 2) if m_real["roi_simule"] is not None else None,
            "nb_courses_evaluees": m_real["nb_courses_evaluees"],
            "walk_forward_auc": round(model.walk_forward_auc, 4) if model.walk_forward_auc else None,
            "nb_courses_train": model.nb_courses_train,
            "feature_importance": dict(
                sorted((model.feature_importance or {}).items(), key=lambda x: -x[1])[:15]
            ),
            "trained_at": model.created_at.isoformat() if model.created_at else None,
        }

    # Meta-learner
    try:
        from ml.meta_learner import get_meta_learner
        meta = get_meta_learner()
        meta_data = {"is_trained": meta.is_trained}
    except Exception:
        meta_data = {"is_trained": False}

    result = {
        "adaptive_learning": al_data,
        "drift_detector": dd_data,
        "model": model_data,
        "meta_learner": meta_data,
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=300)  # 5 min
    return result


@router.get("/stats/dashboard-summary")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Données agrégées pour le tableau de bord utilisateur.
    Nombre de courses du jour, value bets actifs, top 3 VBs. Cache 2 min.
    """
    CACHE_KEY = "stats:dashboard-summary"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Courses du jour
    nb_courses_jour = (await db.execute(
        select(func.count(Course.course_id)).where(
            Course.date_heure >= today_start,
            Course.date_heure < today_end,
            Course.statut.notin_(STATUTS_NON_COURUES),  # annulées / jamais résultées
        )
    )).scalar() or 0

    # Courses en cours
    nb_en_cours = (await db.execute(
        select(func.count(Course.course_id)).where(
            Course.date_heure >= today_start,
            Course.date_heure < today_end,
            Course.statut == "en_cours",
        )
    )).scalar() or 0

    # Value bets actifs
    nb_vbs_actifs = (await db.execute(
        select(func.count(ValueBet.vb_id)).where(ValueBet.actif == True)
    )).scalar() or 0

    # VBs haute valeur (≥3 étoiles)
    nb_vbs_premium = (await db.execute(
        select(func.count(ValueBet.vb_id)).where(
            ValueBet.actif == True,
            ValueBet.niveau >= 3,
        )
    )).scalar() or 0

    # Top 3 value bets du moment
    q_vbs = (
        select(ValueBet, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(ValueBet.actif == True, ValueBet.niveau >= 2)
        .order_by(ValueBet.ev_max.desc())
        .limit(3)
    )
    top_vbs_rows = (await db.execute(q_vbs)).all()
    top_vbs = [
        {
            "nom_cheval": cheval.nom,
            "hippodrome": course.hippodrome_nom,
            "discipline": course.discipline,
            "heure": course.date_heure.strftime("%H:%M") if course.date_heure else None,
            "ev": round(vb.ev_max, 2),
            "niveau": vb.niveau,
            "cote": round(part.cote_pmu, 1) if part.cote_pmu else None,
            "course_id": vb.course_id,
        }
        for vb, part, cheval, course in top_vbs_rows
    ]

    # Drift status (minimal, sans auth admin)
    dd_state = (await db.execute(
        select(DriftDetectorState).limit(1)
    )).scalar_one_or_none()
    drift_severity = dd_state.severity if dd_state else "none"

    # Métriques RÉELLES du modèle actif (au lieu de valeurs hardcodées côté front).
    # precision_top3 : préférer la précision RÉELLE observée (race_learning_log)
    # à la métrique d'entraînement.
    from db.models import ModelVersion, RaceLearningLog
    mv = (await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )).scalars().first()
    # AUC bornée à [0.5,1] (jamais 0.06). Modèle non crédible ⇒ on ne publie pas non
    # plus la précision (sinon 0% trompeur), et on évite le fallback seed peu fiable.
    _auc = plausible_auc(float(mv.auc_roc)) if mv and mv.auc_roc is not None else None
    model_auc = round(_auc, 3) if _auc is not None else None
    rll_total = (await db.execute(select(func.count()).select_from(RaceLearningLog))).scalar() or 0
    rll_top3 = (await db.execute(
        select(func.count()).select_from(RaceLearningLog)
        .where(RaceLearningLog.gagnant_rang_predit <= 3)
    )).scalar() or 0
    precision_top3 = (
        round(rll_top3 / rll_total, 3) if rll_total >= 10 and model_auc is not None else None
    )

    result = {
        "nb_courses_jour": nb_courses_jour,
        "nb_en_cours": nb_en_cours,
        "nb_vbs_actifs": nb_vbs_actifs,
        "nb_vbs_premium": nb_vbs_premium,
        "top_vbs": top_vbs,
        "drift_severity": drift_severity,
        "model_auc": model_auc,
        "precision_top3": precision_top3,
        "nb_courses_evaluees": rll_total,
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=120)  # 2 min
    return result


# ─────────────────────────────────────────────────────────────
# Statistiques personnelles utilisateur
# ─────────────────────────────────────────────────────────────

@router.get("/stats/perf-personnelle")
async def perf_personnelle(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Performance personnelle de l'utilisateur authentifié.
    Calculs depuis bankroll_entries + recommandations.
    Pas de cache Redis car données per-user.
    """
    uid = current_user.user_id

    # ── 1. Toutes les entrées de l'utilisateur ────────────────
    entries_rows = (await db.execute(
        select(BankrollEntry)
        .where(BankrollEntry.user_id == uid)
        .order_by(BankrollEntry.date)
    )).scalars().all()

    entries = list(entries_rows)

    nb_paris = len(entries)
    mise_totale = sum(e.mise for e in entries)
    gagnants = [e for e in entries if e.resultat == "gagne"]
    perdants = [e for e in entries if e.resultat == "perd"]
    nb_gagnants = len(gagnants)
    win_rate = round(nb_gagnants / nb_paris * 100, 2) if nb_paris else 0.0
    gains_totaux = sum(e.gain_perte for e in gagnants if e.gain_perte)
    pertes_totales = abs(sum(e.gain_perte for e in perdants if e.gain_perte))
    gain_net = gains_totaux - pertes_totales
    roi = round(gain_net / mise_totale * 100, 2) if mise_totale else 0.0
    cotes = [e.cote for e in entries if e.cote]
    cote_moyenne = round(sum(cotes) / len(cotes), 2) if cotes else 0.0

    # ── 2. ROI par discipline ─────────────────────────────────
    disc_stats: dict[str, dict] = {}
    for e in entries:
        if not e.course_id:
            continue
        # We aggregate later with a JOIN; for simplicity compute from type_pari as proxy
        # A proper join with courses would require a subquery — using type_pari label here
    # Discipline join
    if entries:
        course_ids = [e.course_id for e in entries if e.course_id]
        if course_ids:
            course_rows = (await db.execute(
                select(Course.course_id, Course.discipline)
                .where(Course.course_id.in_(course_ids))
            )).all()
            disc_map = {r.course_id: r.discipline for r in course_rows}
            for e in entries:
                disc = disc_map.get(e.course_id, "Autre") if e.course_id else "Autre"
                if disc not in disc_stats:
                    disc_stats[disc] = {"mise": 0.0, "gain": 0.0, "nb": 0, "wins": 0}
                # On ne compte QUE les paris réglés (gagné/perdu) : sinon la mise des
                # paris en attente gonflait le dénominateur sans gain au numérateur
                # → ROI par discipline biaisé à la baisse.
                if e.resultat == "gagne" and e.gain_perte is not None:
                    disc_stats[disc]["mise"] += e.mise
                    disc_stats[disc]["nb"] += 1
                    disc_stats[disc]["gain"] += e.gain_perte
                    disc_stats[disc]["wins"] += 1
                elif e.resultat == "perd" and e.gain_perte is not None:
                    disc_stats[disc]["mise"] += e.mise
                    disc_stats[disc]["nb"] += 1
                    disc_stats[disc]["gain"] += e.gain_perte

    roi_par_discipline = [
        {
            "discipline": d,
            "nb_paris": v["nb"],
            "roi": round(v["gain"] / v["mise"] * 100, 2) if v["mise"] else 0.0,
            "win_rate": round(v["wins"] / v["nb"] * 100, 2) if v["nb"] else 0.0,
        }
        for d, v in disc_stats.items()
    ]

    # ── 3. P&L mensuel (12 derniers mois) ────────────────────
    now = datetime.now(timezone.utc)
    monthly: dict[str, dict] = {}
    # Vrais mois CALENDAIRES (avant : now − 30*i jours → dérive, un mois pouvait être
    # sauté ou compté deux fois → paris exclus du graphe).
    base_idx = now.year * 12 + (now.month - 1)
    for i in range(11, -1, -1):
        yy, mm = divmod(base_idx - i, 12)
        month_dt = datetime(yy, mm + 1, 1, tzinfo=timezone.utc)
        key = month_dt.strftime("%Y-%m")
        monthly[key] = {"mois": month_dt.strftime("%b %Y"), "gain_perte": 0.0, "nb_paris": 0}
    for e in entries:
        if not e.date:
            continue
        key = e.date.strftime("%Y-%m")
        if key not in monthly:
            continue
        monthly[key]["nb_paris"] += 1
        if e.gain_perte:
            monthly[key]["gain_perte"] += e.gain_perte
    monthly_pnl = [
        {"mois": v["mois"], "gain_perte": round(v["gain_perte"], 2), "nb_paris": v["nb_paris"]}
        for v in monthly.values()
    ]

    # ── 4. Meilleurs / pires paris ────────────────────────────
    entries_with_gain = [e for e in entries if e.gain_perte is not None and e.resultat in ("gagne", "perd")]
    best_bets = sorted(entries_with_gain, key=lambda e: e.gain_perte or 0, reverse=True)[:5]
    worst_bets = sorted(entries_with_gain, key=lambda e: e.gain_perte or 0)[:5]

    def _entry_dict(e: BankrollEntry) -> dict:
        return {
            "entry_id": e.entry_id,
            "date": e.date.isoformat() if e.date else None,
            "type_pari": e.type_pari,
            "chevaux": e.chevaux,
            "mise": e.mise,
            "cote": e.cote,
            "resultat": e.resultat,
            "gain_perte": e.gain_perte,
            "course_id": e.course_id,
            "suivi_reco_ia": e.suivi_reco_ia,
        }

    # ── 5. Suivi IA ───────────────────────────────────────────
    ia_entries = [e for e in entries if e.suivi_reco_ia]
    non_ia_entries = [e for e in entries if not e.suivi_reco_ia]

    def _roi_for(lst: list[BankrollEntry]) -> float:
        mise = sum(e.mise for e in lst)
        gain = sum((e.gain_perte or 0) for e in lst)
        return round(gain / mise * 100, 2) if mise else 0.0

    def _wr_for(lst: list[BankrollEntry]) -> float:
        g = len([e for e in lst if e.resultat == "gagne"])
        return round(g / len(lst) * 100, 2) if lst else 0.0

    pct_ia_suivi = round(len(ia_entries) / nb_paris * 100, 1) if nb_paris else 0.0

    # ── 6. Streak ─────────────────────────────────────────────
    resolved = [e for e in reversed(entries) if e.resultat in ("gagne", "perd")]
    streak = 0
    streak_type = "none"
    if resolved:
        streak_type = "win" if resolved[0].resultat == "gagne" else "loss"
        for e in resolved:
            if e.resultat == ("gagne" if streak_type == "win" else "perd"):
                streak += 1
            else:
                break

    return {
        "nb_paris": nb_paris,
        "mise_totale": round(mise_totale, 2),
        "win_rate": win_rate,
        "cote_moyenne": cote_moyenne,
        "roi": roi,
        "gain_net": round(gain_net, 2),
        "roi_par_discipline": roi_par_discipline,
        "monthly_pnl": monthly_pnl,
        "best_bets": [_entry_dict(e) for e in best_bets],
        "worst_bets": [_entry_dict(e) for e in worst_bets],
        "suivi_ia": {
            "pct_suivi": pct_ia_suivi,
            "nb_ia": len(ia_entries),
            "nb_non_ia": len(non_ia_entries),
            "roi_ia": _roi_for(ia_entries),
            "roi_non_ia": _roi_for(non_ia_entries),
            "win_rate_ia": _wr_for(ia_entries),
            "win_rate_non_ia": _wr_for(non_ia_entries),
        },
        "streak": {
            "type": streak_type,
            "count": streak,
        },
    }


# ─────────────────────────────────────────────────────────────
# Track-record IA (public, cache 1h)
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Track record (page publique Palmarès) — calcul lourd, cache SWR
# ─────────────────────────────────────────────────────────────
TRACK_RECORD_CACHE_KEY = "stats:track-record"
TRACK_RECORD_FRESH_TTL = 3600   # 1 h de fraîcheur

# Références fortes sur les tâches de fond : sans ça, asyncio peut collecter une
# tâche non référencée avant sa fin (le recalcul serait tué en cours de route).
_bg_tasks: set = set()


@router.get("/stats/track-record")
async def track_record(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Performance historique de l'IA — page publique marketing.

    Cache « stale-while-revalidate » : le calcul complet coûte ~29 s (mesuré en prod
    le 2026-08-18) pour un client qui abandonne à 15 s. On ne le fait donc JAMAIS
    dans le chemin d'une requête utilisateur tant qu'une version antérieure existe.
    """
    cached, frais = await _cache_get_swr(redis, TRACK_RECORD_CACHE_KEY)
    if cached is not None and frais:
        return cached
    if cached is not None:
        # Périmé mais exploitable : réponse immédiate, recalcul en arrière-plan.
        task = asyncio.create_task(refresh_track_record_cache())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
        return cached

    # Aucune version en cache (Redis vide / premier démarrage) : on paie le calcul.
    result = await _compute_track_record(db)
    await _cache_set_swr(redis, TRACK_RECORD_CACHE_KEY, result,
                         fresh_ttl=TRACK_RECORD_FRESH_TTL)
    return result


async def refresh_track_record_cache() -> bool:
    """Recalcule le track record et réécrit son cache. True si réécrit.

    Appelé (a) en tâche de fond quand un utilisateur a reçu une version périmée,
    (b) par `job_warm_caches`, pour renouveler la fraîcheur AVANT expiration :
    l'ancien job tapait l'endpoint en HTTP, qui lui renvoyait le cache chaud sans
    rien réécrire — il ne prolongeait donc jamais le TTL.

    Verrou Redis : le calcul martèle la base ~29 s ; sans verrou, N requêtes périmées
    simultanées déclencheraient N recalculs concurrents.
    """
    from db.database import AsyncSessionLocal
    from db.redis_client import get_redis as _get_redis

    lock_key = f"{TRACK_RECORD_CACHE_KEY}:lock"
    try:
        redis = await _get_redis()
        verrou = await redis.set(lock_key, "1", ex=300, nx=True)
    except Exception as e:
        log.warning("stats.track_record.refresh_lock_failed", error=str(e)[:200])
        return False
    if not verrou:
        return False            # un recalcul est déjà en cours ailleurs
    try:
        async with AsyncSessionLocal() as session:
            result = await _compute_track_record(session)
        await _cache_set_swr(redis, TRACK_RECORD_CACHE_KEY, result,
                             fresh_ttl=TRACK_RECORD_FRESH_TTL)
        log.info("stats.track_record.refreshed")
        return True
    except Exception as e:
        log.warning("stats.track_record.refresh_failed", error=str(e)[:200])
        return False
    finally:
        try:
            await redis.delete(lock_key)
        except Exception:
            pass


async def _compute_track_record(db: AsyncSession) -> dict:
    """Calcul complet du track record (~29 s en prod). Ne jamais appeler depuis une
    requête utilisateur tant qu'une version en cache existe (cf. `track_record`).

    COHORTE MESURÉE — une course compte dans les taux publiés si, et seulement si,
    sa prédiction existait AVANT le départ (`p.created_at < c.date_heure`) : c'est
    la garde anti-backfill, la même que celle du palmarès des gains.

    `is_replayable` n'est VOLONTAIREMENT pas exigé (retiré le 19/08). Ce drapeau
    (migration 0030) distingue le snapshot immuable — rejouable en backtest — de la
    ligne `predictions` héritée, mutable : c'est une propriété de REJOUABILITÉ, pas
    d'intégrité temporelle. L'exiger réduisait le palmarès PUBLIC aux courses
    postérieures au 18/08 — 44 courses, dont 4 en monté — alors que 3 627 courses
    pré-course sont mesurées depuis le 06/06 : la page annonçait « 19 courses
    analysées » en attelé pour 1 598 réelles.

    Pourquoi la cohorte longue n'est pas contaminée : `race_learning_log` est écrit
    JUSTE APRÈS l'arrivée à partir des prédictions du moment (le cycle de prédiction
    s'arrête à T-10 min), donc une mutation ultérieure d'une ligne `predictions` ne
    peut pas réécrire un rang déjà journalisé. Contrôle en base le 19/08 : la cohorte
    héritée mesure 55-66 % de Top-3 et 31,9 % de favoris gagnants, contre 62-75 % et
    34,8 % pour la cohorte rejouable — l'historique long est PLUS SÉVÈRE, pas gonflé.
    Le compte strict reste publié à part (`global.nb_courses_rejouables`)."""
    # ── 1. Précision globale depuis race_learning_log ─────────
    # Agrégats en SQL (PAS de chargement de toute la table en mémoire : elle grossit
    # d'une ligne par course analysée → des dizaines de milliers de lignes = page lente).
    _glob = (await db.execute(text("""
        SELECT COUNT(*)                                                       AS nb,
               AVG(brier_score)                                               AS brier,
               COUNT(*) FILTER (WHERE gagnant_rang_predit = 1)                AS top1,
               COUNT(*) FILTER (WHERE gagnant_rang_predit IS NOT NULL
                                  AND gagnant_rang_predit <= 3)               AS top3,
               COUNT(*) FILTER (WHERE was_surprise)                           AS surprises,
               -- Repère « hasard » CALCULÉ, jamais posé à la main : espérance d'un
               -- tirage au sort sur le champ réel de chaque course (3 chevaux sur
               -- nb_partants pour le Top-3, 1 sur nb_partants pour le Top-1). Sans
               -- lui, « 59,8 % » ne dit pas au lecteur ce qu'il bat.
               AVG(CASE WHEN nb_partants > 0
                        THEN LEAST(3.0, nb_partants::numeric) / nb_partants END)  AS hasard3,
               AVG(CASE WHEN nb_partants > 0
                        THEN 1.0 / nb_partants END)                              AS hasard1,
               AVG(nb_partants)                                                  AS partants
        FROM race_learning_log
        WHERE EXISTS (
            SELECT 1 FROM prediction_evaluation p
            JOIN courses c ON c.course_id = p.course_id
            WHERE p.course_id = race_learning_log.course_id
              AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
              AND p.created_at < c.date_heure
        )
    """))).first()
    nb_total = int(_glob.nb or 0)
    # Depuis QUAND ces taux sont-ils mesurés ? Le read-model ne retient que la cohorte
    # rejouable (snapshots pré-course), qui a commencé le 2026-08-18 : sans cette date,
    # la page publique affiche un pourcentage sans dire qu'il porte sur quelques jours.
    _depuis = (await db.execute(text("""
        SELECT MIN(c.date_heure)
        FROM race_learning_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE c.date_heure IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM prediction_evaluation p
              WHERE p.course_id = r.course_id
                AND p.created_at IS NOT NULL
                AND p.created_at < c.date_heure
          )
    """))).scalar()
    mesure_depuis = _depuis.date().isoformat() if _depuis else None
    # Sous-ensemble STRICT : courses dont le pronostic est figé dans un snapshot
    # immuable (rejouable à l'identique en backtest). Publié à côté du compte
    # mesuré pour que « vérifiable » garde un chiffre, sans amputer l'historique.
    nb_rejouables = int((await db.execute(text("""
        SELECT COUNT(*) FROM race_learning_log r
        WHERE EXISTS (
            SELECT 1 FROM prediction_evaluation p
            JOIN courses c ON c.course_id = p.course_id
            WHERE p.course_id = r.course_id
              AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
              AND p.created_at < c.date_heure
              AND p.is_replayable = true
        )
    """))).scalar() or 0)
    brier_moyen = round(float(_glob.brier), 4) if _glob.brier is not None else 0.0
    accuracy_top1 = round(int(_glob.top1 or 0) / nb_total * 100, 1) if nb_total else 0.0
    accuracy_top3 = round(int(_glob.top3 or 0) / nb_total * 100, 1) if nb_total else 0.0
    nb_surprises = int(_glob.surprises or 0)
    hasard_top3 = round(float(_glob.hasard3) * 100, 1) if _glob.hasard3 is not None else None
    hasard_top1 = round(float(_glob.hasard1) * 100, 1) if _glob.hasard1 is not None else None
    partants_moyen = round(float(_glob.partants), 1) if _glob.partants is not None else None

    # ── 2. Par jour (7 derniers jours, fuseau Europe/Paris) ──
    # Coupure de journée à minuit heure française (pas UTC) → group by date FR en SQL.
    paris_tz = ZoneInfo("Europe/Paris")
    today = datetime.now(paris_tz).date()
    daily_acc: dict[str, dict] = {}
    for i in range(6, -1, -1):
        day_dt = today - timedelta(days=i)
        key = day_dt.strftime("%Y-%m-%d")
        daily_acc[key] = {
            "jour": day_dt.strftime("%d/%m"),
            "accuracy_top3": 0.0,
            "brier_moyen": None,
            "nb_predictions": 0,
            "nb_surprises": 0,
        }
    _since = datetime.now(timezone.utc) - timedelta(days=8)   # marge tz
    _drows = (await db.execute(text("""
        SELECT (analyzed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Paris')::date AS jour,
               COUNT(*)                                                       AS nb,
               COUNT(*) FILTER (WHERE gagnant_rang_predit IS NOT NULL
                                  AND gagnant_rang_predit <= 3)               AS top3,
               AVG(brier_score)                                               AS brier,
               COUNT(*) FILTER (WHERE was_surprise)                           AS surprises
        FROM race_learning_log
        WHERE analyzed_at IS NOT NULL AND analyzed_at >= :since
          AND EXISTS (
              SELECT 1 FROM prediction_evaluation p
              JOIN courses c ON c.course_id = p.course_id
              WHERE p.course_id = race_learning_log.course_id
                AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
                AND p.created_at < c.date_heure
          )
        GROUP BY 1
    """), {"since": _since.replace(tzinfo=None)})).all()
    for r in _drows:
        key = r.jour.strftime("%Y-%m-%d")
        v = daily_acc.get(key)
        if not v:
            continue
        nb = int(r.nb or 0)
        v["nb_predictions"] = nb
        v["nb_surprises"] = int(r.surprises or 0)
        v["accuracy_top3"] = round(int(r.top3 or 0) / nb * 100, 1) if nb else 0.0
        v["brier_moyen"] = round(float(r.brier), 4) if r.brier is not None else None

    daily_list = list(daily_acc.values())

    # ── 3. Par discipline ─────────────────────────────────────
    _disc = (await db.execute(text("""
        SELECT COALESCE(NULLIF(discipline, ''), 'Autre')                      AS d,
               COUNT(*)                                                       AS nb,
               COUNT(*) FILTER (WHERE gagnant_rang_predit IS NOT NULL
                                  AND gagnant_rang_predit <= 3)               AS top3,
               COUNT(*) FILTER (WHERE gagnant_rang_predit = 1)                AS top1,
               AVG(brier_score)                                               AS brier
        FROM race_learning_log
        WHERE EXISTS (
            SELECT 1 FROM prediction_evaluation p
            JOIN courses c ON c.course_id = p.course_id
            WHERE p.course_id = race_learning_log.course_id
              AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
              AND p.created_at < c.date_heure
        )
        GROUP BY 1
    """))).all()
    by_discipline = [
        {
            "discipline": r.d,
            "nb_courses": int(r.nb or 0),
            "accuracy_top3": round(int(r.top3 or 0) / int(r.nb) * 100, 1) if r.nb else 0.0,
            "accuracy_top1": round(int(r.top1 or 0) / int(r.nb) * 100, 1) if r.nb else 0.0,
            "brier_moyen": round(float(r.brier), 4) if r.brier is not None else None,
        }
        for r in _disc
    ]
    by_discipline.sort(key=lambda d: d["nb_courses"], reverse=True)

    # ── 3b. Tendance 30 jours ─────────────────────────────────
    # `by_day` reste sur 7 jours (l'accueil l'affiche en 7 barres) ; la page palmarès
    # a besoin d'une série assez longue pour qu'une tendance soit lisible. Les jours
    # SANS course mesurée sont absents du tableau — le front les affiche en trou
    # plutôt qu'en 0 %, qui se lirait comme un échec du modèle.
    _since30 = datetime.now(timezone.utc) - timedelta(days=31)
    _t30 = (await db.execute(text("""
        SELECT (analyzed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Paris')::date AS jour,
               COUNT(*)                                                       AS nb,
               COUNT(*) FILTER (WHERE gagnant_rang_predit IS NOT NULL
                                  AND gagnant_rang_predit <= 3)               AS top3,
               COUNT(*) FILTER (WHERE gagnant_rang_predit = 1)                AS top1
        FROM race_learning_log
        WHERE analyzed_at IS NOT NULL AND analyzed_at >= :since
          AND EXISTS (
              SELECT 1 FROM prediction_evaluation p
              JOIN courses c ON c.course_id = p.course_id
              WHERE p.course_id = race_learning_log.course_id
                AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
                AND p.created_at < c.date_heure
          )
        GROUP BY 1
        ORDER BY 1
    """), {"since": _since30.replace(tzinfo=None)})).all()
    tendance_30j = [
        {
            "date": r.jour.isoformat(),
            "jour": r.jour.strftime("%d/%m"),
            "nb_predictions": int(r.nb or 0),
            "accuracy_top3": round(int(r.top3 or 0) / int(r.nb) * 100, 1) if r.nb else 0.0,
            "accuracy_top1": round(int(r.top1 or 0) / int(r.nb) * 100, 1) if r.nb else 0.0,
        }
        for r in _t30
    ]

    # ── 4. Meilleurs pronostics (gagnant prédit rang 1, cote > 5) ─
    q_best = (
        select(PredictionEvaluation, Participation, Cheval, Course, Resultat)
        .join(Participation, Participation.participation_id == PredictionEvaluation.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == PredictionEvaluation.course_id)
        .outerjoin(Resultat, Resultat.course_id == PredictionEvaluation.course_id)
        .where(
            PredictionEvaluation.rang_predit == 1,
            Participation.cote_pmu >= 5.0,
            Course.statut == "termine",
            PredictionEvaluation.created_at.is_not(None),
            Course.date_heure.is_not(None),
            PredictionEvaluation.created_at < Course.date_heure,
        )
        .order_by(PredictionEvaluation.created_at.desc())
        .limit(10)
    )
    best_rows = (await db.execute(q_best)).all()
    best_pronostics = []
    for pred, part, cheval, course, resultat in best_rows:
        gagnant_reel = None
        _w = _winner_entry(resultat.classement) if resultat else None
        if _w:
            gagnant_reel = _w.get("cheval") or _w.get("nom")
        best_pronostics.append({
            "course_id": course.course_id,
            "hippodrome": course.hippodrome_nom,
            "discipline": course.discipline,
            "date": course.date_heure.strftime("%d/%m/%Y") if course.date_heure else None,
            "cheval_predit": cheval.nom,
            "cote": round(part.cote_pmu, 1) if part.cote_pmu else None,
            "proba_top1": round(pred.proba_top1 * 100, 1),
            "gagnant_reel": gagnant_reel,
            "correct": (gagnant_reel or "").lower() == cheval.nom.lower() if gagnant_reel else None,
        })

    # ── 5. VB performance par niveau ─────────────────────────
    vb_stats: dict[int, dict] = {n: {"nb": 0, "wins": 0, "mise": 0.0, "gains": 0.0} for n in range(1, 5)}
    # PERF : projection des seules colonnes lues ci-dessous. Charger les entites
    # ORM completes materialisait 3 objets par ligne, dont Resultat et son JSON.
    q_vbs = (
        select(ValueBet.niveau, Participation.numero, Participation.cote_pmu,
               Resultat.classement)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .join(PredictionEvaluation, PredictionEvaluation.prediction_id == ValueBet.prediction_id)
        .outerjoin(Resultat, Resultat.course_id == ValueBet.course_id)
        .where(
            ValueBet.actif == False,  # resolved bets only
            Course.date_heure.is_not(None),
            ValueBet.detecte_a < Course.date_heure,
            PredictionEvaluation.created_at.is_not(None),
            PredictionEvaluation.created_at < Course.date_heure,
        )
        .limit(2000)
    )
    vb_rows = (await db.execute(q_vbs)).all()
    for n, vb_numero, vb_cote, vb_classement in vb_rows:
        if n not in vb_stats:
            continue
        # Pas d'arrivée publiée (outerjoin → classement None) : on NE règle PAS le pari.
        # Avant, il tombait dans le `else` et était compté perdant → ROI faussé à la baisse.
        if not (isinstance(vb_classement, list) and vb_classement):
            continue
        mise = 10.0
        vb_stats[n]["nb"] += 1
        vb_stats[n]["mise"] += mise
        _w = _winner_entry(vb_classement)
        gagne = bool(_w and _w.get("numero") == vb_numero)
        if gagne and vb_cote and vb_cote > 1:
            vb_stats[n]["wins"] += 1
            vb_stats[n]["gains"] += (vb_cote - 1) * mise
        else:
            vb_stats[n]["gains"] -= mise

    vb_performance = [
        {
            "niveau": n,
            "nb_vbs": v["nb"],
            "win_rate": round(v["wins"] / v["nb"] * 100, 1) if v["nb"] else 0.0,
            "roi": round(v["gains"] / v["mise"] * 100, 1) if v["mise"] else 0.0,
        }
        for n, v in sorted(vb_stats.items())
    ]

    # ── 6b. Favori IA : taux gagnant / placé + derniers pronostics ────────────
    # Le favori IA = prédiction rang_predit==1 de chaque course. On le confronte à
    # l'arrivée réelle (sa position dans le classement officiel). Données réelles
    # uniquement (Prediction figée + Resultat), borné aux 2000 derniers résolus.
    # PERF : projection des seules colonnes lues (2 000 lignes x 5 entites ORM
    # completes = ~10 000 objets, dont le JSON `classement` integral a chaque fois).
    # ORDER BY created_at DESC LIMIT 2000 reste deterministe : aucun ex aequo sur
    # predictions.created_at (verifie : 2 100 horodatages distincts sur 2 100).
    q_fav = (
        select(PredictionEvaluation.proba_top1, Participation.numero, Participation.cote_pmu,
               Cheval.nom.label("cheval_nom"), Course.course_id,
               Course.hippodrome_nom, Course.discipline, Course.date_heure,
               Resultat.classement)
        .join(Participation, Participation.participation_id == PredictionEvaluation.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == PredictionEvaluation.course_id)
        .join(Resultat, Resultat.course_id == PredictionEvaluation.course_id)
        .where(
            PredictionEvaluation.rang_predit == 1,
            Course.statut == "termine",
            PredictionEvaluation.created_at.is_not(None),
            Course.date_heure.is_not(None),
            PredictionEvaluation.created_at < Course.date_heure,
        )
        .order_by(PredictionEvaluation.created_at.desc())
        .limit(2000)
    )
    fav_rows = (await db.execute(q_fav)).all()

    # Rang IA du vainqueur réel par course (depuis race_learning_log)
    course_ids = [r.course_id for r in fav_rows]
    rll_by_course: dict[str, int] = {}
    if course_ids:
        rll_rows = (await db.execute(
            select(RaceLearningLog.course_id, RaceLearningLog.gagnant_rang_predit)
            .where(RaceLearningLog.course_id.in_(course_ids))
        )).all()
        rll_by_course = {cid: rang for cid, rang in rll_rows if rang is not None}

    def _pos_in_classement(classement, numero: int):
        if not classement or not isinstance(classement, list):
            return None
        for entry in classement:
            if isinstance(entry, dict) and entry.get("numero") == numero:
                p = entry.get("position")
                return int(p) if isinstance(p, (int, float)) else None
        return None

    fav_total = fav_wins = fav_places = 0
    # ROI RÉEL prouvé : 1€ Simple Gagnant sur le favori IA de chaque course,
    # réglé sur l'arrivée officielle (cote_pmu réelle). Aucune valeur inventée.
    mise_fav = gain_fav = 0.0
    derniers_pronostics: list[dict] = []
    for (proba_top1, numero, cote_pmu, cheval_nom, course_id,
         hippodrome_nom, discipline, date_heure, classement) in fav_rows:
        pos = _pos_in_classement(classement, numero)
        if pos is None:
            continue  # non-partant / arrivée incomplète → hors taux
        fav_total += 1
        is_win = pos == 1
        is_place = pos <= 3
        fav_wins += int(is_win)
        fav_places += int(is_place)

        # ROI : on ne compte que les courses où la cote PMU réelle est connue
        if cote_pmu and cote_pmu > 1.0:
            mise_fav += 1.0
            if is_win:
                gain_fav += float(cote_pmu)

        if len(derniers_pronostics) < 20:
            gagnant_nom = None
            if isinstance(classement, list) and classement:
                premier = min(
                    (e for e in classement
                     if isinstance(e, dict) and isinstance(e.get("position"), (int, float))),
                    key=lambda e: e["position"], default=None,
                )
                if premier:
                    gagnant_nom = premier.get("cheval") or premier.get("nom")
            rang_gagnant_ia = rll_by_course.get(course_id)
            verdict = (
                "gagnant" if is_win
                else "place" if is_place
                else "top3" if (rang_gagnant_ia is not None and rang_gagnant_ia <= 3)
                else "manque"
            )
            derniers_pronostics.append({
                "course_id": course_id,
                "hippodrome": hippodrome_nom,
                "discipline": discipline,
                "date": date_heure.strftime("%d/%m/%Y") if date_heure else None,
                "favori_nom": cheval_nom,
                "favori_numero": numero,
                "proba_top1": round(proba_top1 * 100, 1),
                "cote": round(cote_pmu, 1) if cote_pmu else None,
                "favori_position": pos,
                "gagnant_nom": gagnant_nom,
                "rang_ia_gagnant": rang_gagnant_ia,
                "verdict": verdict,
            })

    favori_win_rate = round(fav_wins / fav_total * 100, 1) if fav_total else 0.0
    favori_place_rate = round(fav_places / fav_total * 100, 1) if fav_total else 0.0
    net_fav = round(gain_fav - mise_fav, 2)
    roi_fav = round(net_fav / mise_fav * 100, 1) if mise_fav else 0.0

    # ── 6. Adaptive learning state ────────────────────────────
    al_state = (await db.execute(
        select(AdaptiveLearningState).limit(1)
    )).scalar_one_or_none()
    al_data = {}
    if al_state:
        al_data = {
            "temperature": round(al_state.temperature, 4),
            "n_races": al_state.n_races,
            "brier_ema": round(al_state.brier_ema, 4),
        }

    # ── CLV (Closing Line Value) : l'IA bat-elle la ligne de clôture ? ──────
    # Pour chaque favori IA (rang 1), compare la cote d'OUVERTURE (1ère relevée)
    # à la cote de CLÔTURE (dernière relevée). Si la cote baisse, le marché a
    # bougé VERS le pick → l'IA a anticipé = vrai signal d'edge. Données réelles
    # (cotes_historique). CLV robuste : % de picks battant la ligne + médiane +
    # gain de proba implicite moyen (insensible aux outliers de cote).
    clv = None
    try:
        # PERF : ne JAMAIS agreger cotes_historique en entier. L'ecriture naive
        # (GROUP BY participation_id sur toute la table, puis JOIN fav) agregeait
        # 5,8 M lignes / 11 chunks TimescaleDB -- 20 s, 6 M buffers -- pour n'en
        # garder que ~3 700 : le filtre `fav` ne peut pas descendre sous le GROUP BY.
        # On inverse : on part des ~3 700 favoris et on va chercher pour chacun sa
        # premiere et sa derniere cote via l'index (participation_id, time).
        # Valeur identique : memes filtres, et la PK UNIQUE (time, participation_id)
        # interdit les ex aequo, donc ORDER BY time LIMIT 1 == (array_agg(...))[1].
        clv_row = (await db.execute(text("""
            WITH fav AS MATERIALIZED (
                SELECT p.participation_id FROM prediction_evaluation p
                JOIN courses c ON c.course_id = p.course_id
                WHERE p.rang_predit = 1 AND c.statut = 'termine'
                  AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
                  AND p.created_at < c.date_heure
            ),
            ch AS MATERIALIZED (
                SELECT f.participation_id,
                       (SELECT h.cote FROM cotes_historique h
                         WHERE h.participation_id = f.participation_id AND h.cote > 1
                         ORDER BY h.time ASC  LIMIT 1) AS o,
                       (SELECT h.cote FROM cotes_historique h
                         WHERE h.participation_id = f.participation_id AND h.cote > 1
                         ORDER BY h.time DESC LIMIT 1) AS c
                FROM fav f
            )
            SELECT count(*) AS n,
                   round((count(*) FILTER (WHERE o > c)::numeric / nullif(count(*),0) * 100), 1) AS pct_beat,
                   round(avg(1.0/c - 1.0/o)::numeric * 100, 2) AS clv_implied,
                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY o/c - 1))::numeric * 100, 1) AS clv_median
            FROM ch
            WHERE o IS NOT NULL AND c IS NOT NULL AND o <> c
        """))).first()
        if clv_row and clv_row[0] and clv_row[0] >= 10:
            clv = {
                "n": int(clv_row[0]),
                "pct_beat_line": float(clv_row[1] or 0),
                "clv_implied": float(clv_row[2] or 0),
                "clv_median": float(clv_row[3] or 0),
            }
    except Exception as e:
        log.warning("track_record.clv_failed", error=str(e))

    # ── LE SEUL COMPARATEUR QUI COMPTE : le marché ─────────────────────────
    # Le site se comparait au HASARD (« 60,2 % contre 29 % pour un tirage au
    # sort »). Le chiffre est vrai, la comparaison est celle qui flatte : sur un
    # site dont l'argument central est l'honnêteté de la mesure, c'est la faille
    # la plus coûteuse en crédibilité. Le vrai adversaire est le classement par
    # la cote, et il faut publier qu'il fait JEU ÉGAL, voire un peu mieux.
    #
    # Mesuré en production le 2026-08-31 sur les 4 023 courses de la cohorte :
    #     gagnant trouvé      IA 28,54 %   marché 28,83 %
    #     gagnant dans le top-3  IA 61,35 %   marché 62,32 %
    #     ROI 1 € Gagnant sur le favori   IA −11,9 %   marché −17,6 %
    # L'IA n'est donc PAS plus précise. Son avantage est un effet de PRIX : à
    # précision égale elle désigne des chevaux plus chers, ce qui vaut ~+5,5
    # points de ROI. C'est ce qu'il faut vendre, et rien d'autre.
    #
    # `cote_figee` et non la cote courante : c'est la cote enregistrée AVEC le
    # pronostic, donc un classement de marché contemporain de la prédiction. Le
    # rang IA est recalculé sur les MÊMES partants (non-partants exclus) pour que
    # les deux colonnes portent sur exactement la même population.
    marche = None
    try:
        m = (await db.execute(text("""
            WITH cohorte AS (
                SELECT p.course_id, p.participation_id, p.rang_predit, p.cote_figee
                FROM prediction_evaluation p
                JOIN courses c ON c.course_id = p.course_id
                WHERE c.statut = 'termine'
                  AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
                  AND p.created_at < c.date_heure
                  AND p.cote_figee IS NOT NULL AND p.cote_figee > 1
            ),
            partants AS (
                SELECT co.*, pa.numero
                FROM cohorte co
                JOIN participations pa ON pa.participation_id = co.participation_id
                WHERE pa.non_partant = false
            ),
            classe AS (
                SELECT a.*,
                       ROW_NUMBER() OVER (PARTITION BY a.course_id
                                          ORDER BY a.cote_figee ASC, a.numero ASC) AS rang_marche,
                       ROW_NUMBER() OVER (PARTITION BY a.course_id
                                          ORDER BY a.rang_predit ASC, a.numero ASC) AS rang_ia
                FROM partants a
            ),
            gagnants AS (
                SELECT r.course_id, (e->>'numero')::int AS numero
                FROM resultats r, LATERAL jsonb_array_elements(r.classement) e
                WHERE jsonb_typeof(r.classement) = 'array' AND (e->>'position')::int = 1
            ),
            par_course AS (
                SELECT c.course_id,
                       MAX(CASE WHEN c.rang_marche = 1 THEN c.cote_figee END) AS cote_fav,
                       -- Cote FIGÉE du favori IA : les deux rendements sont ainsi
                       -- calculés sur la même base de prix et la même cohorte. Les
                       -- comparer au `favori_roi` global (cohorte plus large, sans
                       -- exigence de cote figée) donnerait −6,8 % contre −17,6 % et
                       -- surestimerait l'avantage de dix points.
                       MAX(CASE WHEN c.rang_ia = 1 THEN c.cote_figee END) AS cote_fav_ia,
                       BOOL_OR(c.rang_marche = 1 AND c.numero = g.numero) AS m1,
                       BOOL_OR(c.rang_marche <= 3 AND c.numero = g.numero) AS m3,
                       BOOL_OR(c.rang_ia = 1 AND c.numero = g.numero)     AS i1,
                       BOOL_OR(c.rang_ia <= 3 AND c.numero = g.numero)    AS i3
                FROM classe c JOIN gagnants g ON g.course_id = c.course_id
                GROUP BY c.course_id
            )
            SELECT count(*)                                                          AS n,
                   avg(m1::int) * 100                                                AS marche_top1,
                   avg(m3::int) * 100                                                AS marche_top3,
                   avg(i1::int) * 100                                                AS ia_top1,
                   avg(i3::int) * 100                                                AS ia_top3,
                   (sum(CASE WHEN m1 THEN cote_fav ELSE 0 END) - count(*))::numeric
                       / nullif(count(*), 0) * 100                                   AS marche_roi,
                   (sum(CASE WHEN i1 THEN cote_fav_ia ELSE 0 END) - count(*))::numeric
                       / nullif(count(*), 0) * 100                                   AS ia_roi
            FROM par_course
        """))).first()
        if m and (m.n or 0) >= 200:
            marche = {
                "nb_courses": int(m.n),
                "marche_top1": round(float(m.marche_top1), 2),
                "marche_top3": round(float(m.marche_top3), 2),
                # Taux de l'IA RECALCULÉS sur cette cohorte-là : les comparer aux
                # taux globaux (cohortes différentes) donnerait un écart faux.
                "ia_top1": round(float(m.ia_top1), 2),
                "ia_top3": round(float(m.ia_top3), 2),
                "marche_favori_roi": round(float(m.marche_roi), 2),
                # ROI de NOTRE favori sur CETTE cohorte : le seul chiffre qui se
                # compare légitimement à `marche_favori_roi`.
                "ia_favori_roi": round(float(m.ia_roi), 2),
            }
    except Exception as e:
        log.warning("track_record.marche_failed", error=str(e)[:200])

    result = {
        "global": {
            "accuracy_top1": accuracy_top1,
            "accuracy_top3": accuracy_top3,
            "brier_moyen": brier_moyen,
            "nb_courses_analysees": nb_total,
            # Sous-ensemble rejouable à l'identique (snapshots immuables) : sert la
            # mention « vérifiable » sans réduire l'historique mesuré à ce sous-ensemble.
            "nb_courses_rejouables": nb_rejouables,
            # Date de la plus ancienne course de la cohorte mesurée (ISO) — sert à
            # dire honnêtement sur quelle période portent les taux affichés.
            "mesure_depuis": mesure_depuis,
            "nb_surprises": nb_surprises,
            # Référence : ce que rapporterait un tirage au sort sur les mêmes courses.
            "hasard_top3": hasard_top3,
            "hasard_top1": hasard_top1,
            "nb_partants_moyen": partants_moyen,
            "favori_win_rate": favori_win_rate,
            "favori_place_rate": favori_place_rate,
            "nb_favoris_evalues": fav_total,
            # ROI réel : 1€ Gagnant sur le favori IA, réglé sur l'arrivée réelle
            "favori_roi": roi_fav,
            "favori_mise_totale": round(mise_fav, 0),
            "favori_gain_total": round(gain_fav, 2),
            "favori_net": net_fav,
        },
        "by_day": daily_list,
        "tendance_30j": tendance_30j,
        "by_discipline": by_discipline,
        "best_pronostics": best_pronostics,
        "derniers_pronostics": derniers_pronostics,
        "vb_performance": vb_performance,
        "adaptive_learning": al_data,
        "clv": clv,
        # None si la mesure a échoué ou si la cohorte est trop courte : l'affichage
        # doit alors TAIRE la comparaison, jamais la remplacer par le hasard.
        "marche": marche,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


# ─────────────────────────────────────────────────────────────
# Backtest par PROFIL de risque (public, cache 6h — calcul lourd)
# ─────────────────────────────────────────────────────────────
@router.get("/stats/profils")
async def stats_profils(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Performance simulée des 3 profils (conservateur/équilibré/agressif) sur
    l'historique réel : plan de mise figé avant course, réglé sur l'arrivée
    officielle. Calcul lourd → cache Redis 6h."""
    CACHE_KEY = "stats:profils"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    data = await backtest_profils(db, limit=400, n_sims=3000)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Cache 1h en filet ; surtout invalidé à CHAQUE fin de course
    # (_invalidate_stats_caches) → recalcul immédiat sur données réelles.
    await _cache_set(redis, CACHE_KEY, data, ttl=3600)
    return data


def _rapports_vises(plan) -> dict:
    """Rapport ANNONCÉ par un plan figé, indexé par (type de pari, numéros triés).

    Le plan ne stocke pas le rapport mais le gain potentiel du ticket : le rapport
    visé s'en déduit par gain_potentiel / mise. Les numéros sont triés parce que
    l'ordre des chevaux d'une combinaison n'est pas stable entre le plan et le
    bilan — apparier sur la liste brute perdrait la moitié des combinés.
    """
    plan_d = (plan if isinstance(plan, dict) else json.loads(plan or "{}")) or {}
    out: dict = {}
    for niv in plan_d.get("niveaux", []):
        for p in niv.get("paris", []):
            mise = float(p.get("mise") or 0)
            if mise <= 0:
                continue
            nums = tuple(sorted(int(h["numero"]) for h in (p.get("chevaux") or [])
                                if h.get("numero") is not None))
            out[(p.get("type"), nums)] = float(p.get("gain_potentiel") or 0) / mise
    return out


async def _palmares_rows(db: AsyncSession) -> dict:
    """Cœur du palmarès, partagé par la version admin et la version publique.

    Factorisé pour qu'il n'existe qu'UNE définition des règles d'intégrité : un pari
    ne compte QUE s'il a été figé avant le départ et n'est pas un backfill. Deux
    copies de cette requête divergeraient tôt ou tard, et le palmarès public
    afficherait alors des paris que la version admin refuse (ou l'inverse).
    """
    from sqlalchemy import text as _text
    try:
        rows = (await db.execute(_text("""
            SELECT r.profil, r.resultat, r.settled_at, r.created_at,
                   c.hippodrome_nom, c.date_heure, c.course_id, c.numero_reunion, c.numero,
                   r.plan
            FROM profil_run_log r
            JOIN courses c ON c.course_id = r.course_id
            WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
              -- Pronostic FIGÉ AVANT LE DÉPART (preuve temporelle réelle)
              AND c.date_heure IS NOT NULL
              AND r.created_at < c.date_heure
              -- Jamais une reconstruction post-course (backfill = pas un vrai prono émis)
              AND COALESCE(r.meta->>'backfill', '') <> 'true'
            ORDER BY r.settled_at DESC NULLS LAST
        """))).all()
    except Exception:
        return {"gagnants": [], "top_gains": [], "n": 0, "n_courses": 0,
                "n_courses_reglees": 0, "by_profil": {}, "total_gain": 0.0,
                "total_mise": 0.0, "integrite": _PALMARES_INTEGRITE}

    PROFIL_LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
    gagnants = []
    courses_reglees: set = set()
    by_profil: dict = {p: {"courses": set(), "mise": 0.0, "gain": 0.0,
                           "courses_benef": 0, "paris_gagnes": 0} for p in PROFIL_LBL}
    for profil, resultat, settled_at, created_at, hippo, dh, cid, n_reunion, n_course, plan in rows:
        res = resultat if isinstance(resultat, dict) else json.loads(resultat or "{}")
        # RAPPORT VISÉ = celui du plan FIGÉ avant le départ (gain_potentiel / mise), à
        # côté du rapport RÉELLEMENT payé. Les deux sont nécessaires et différents :
        #   • la tranche d'un profil (prudent ×1,8-5, modéré ×4-15, risqué ≥×10) est un
        #     engagement pris AVANT la course, sur le rapport estimé ;
        #   • le rapport parimutuel réel n'est connu qu'après la clôture des paris et
        #     dépend, pour un placé ou un couplé, de QUELS autres chevaux arrivent.
        # N'afficher que le réel donnait un palmarès qui semble contredire la tranche du
        # profil (un ticket risqué figé à ×14,1 payé ×3,3 le 2026-08-27 à Saratoga).
        vise = _rapports_vises(plan)
        courses_reglees.add(cid)
        agg = by_profil.get(profil)
        if agg is not None:
            agg["courses"].add(cid)
            agg["mise"] += float(res.get("total_mise") or 0)
            agg["gain"] += float(res.get("total_gain") or 0)
            if float(res.get("net") or 0) > 0:
                agg["courses_benef"] += 1
        for pari in res.get("paris", []):
            if pari.get("statut") != "gagne" or pari.get("gain") is None:
                continue
            if agg is not None:
                agg["paris_gagnes"] += 1
            mise = float(pari.get("mise") or 0)
            gain = float(pari.get("gain") or 0)
            # Code RxCy : numero_reunion public si dispo, sinon extrait du course_id
            # ("05062026R3C1" → "R3C1") pour les courses legacy sans numero_reunion.
            if n_reunion and n_course:
                _code = f"R{n_reunion}C{n_course}"
            else:
                _m = re.search(r"(R\d+C\d+)", str(cid))
                _code = _m.group(1) if _m else None
            _nums_g = tuple(sorted(int(c["numero"]) for c in pari.get("chevaux", [])
                                   if c.get("numero") is not None))
            _vise = vise.get((pari.get("type"), _nums_g))
            gagnants.append({
                "profil": profil,
                "course_id": cid,
                "code": _code,
                "hippodrome": hippo,
                "date": dh.isoformat() if dh else None,
                "type_pari": pari.get("type"),
                "chevaux": [c.get("numero") for c in pari.get("chevaux", [])],
                "mise": round(mise, 2),
                "gain": round(gain, 2),
                "benefice": round(gain - mise, 2),
                "rapport": round(gain / mise, 2) if mise > 0 else None,
                # Rapport annoncé par le plan figé (None si le pari n'est pas retrouvé
                # dans le plan — run legacy dont le plan ne portait pas gain_potentiel).
                "rapport_vise": round(_vise, 2) if _vise else None,
                # Preuve d'intégrité : prono figé AVANT le départ, réglé après l'arrivée.
                "fige_avant_course": True,
                "fige_le": created_at.isoformat() if created_at else None,
                "regle_le": settled_at.isoformat() if settled_at else None,
            })
    gagnants.sort(key=lambda g: g.get("date") or "", reverse=True)
    return {
        "gagnants": gagnants,
        "top_gains": sorted(gagnants, key=lambda x: x["benefice"], reverse=True)[:30],
        "n": len(gagnants),
        "n_courses": len({x["course_id"] for x in gagnants}),
        "n_courses_reglees": len(courses_reglees),
        "by_profil": by_profil,
        "profil_labels": PROFIL_LBL,
        "total_gain": round(sum(x["gain"] for x in gagnants), 2),
        "total_mise": round(sum(x["mise"] for x in gagnants), 2),
        "integrite": _PALMARES_INTEGRITE,
    }


_PALMARES_INTEGRITE = (
    "Tous les paris affichés ont été figés AVANT le départ de la course "
    "puis réglés aux vrais rapports PMU à l'arrivée. Aucune reconstruction "
    "a posteriori (backfill) n'est comptée."
)


@router.get("/stats/preuves-recentes")
async def stats_preuves_recentes(
    limite: int = 6,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Ce que le modèle a dit sur les DERNIÈRES courses courues — public.

    Raison d'être (funnel) : un prospect qui arrive sur une fiche course depuis
    Google ne sait pas ce que produit le site. Les agrégats (« 66 % de top-3 »)
    sont abstraits ; une poignée de courses réelles, nommées, avec le rang que
    le modèle avait donné au gagnant, est vérifiable et concrète.

    Honnêteté — les trois règles qui tiennent ce bloc :
      - on prend les courses les PLUS RÉCENTES, jamais les meilleures : aucun
        tri sur la réussite, donc les ratés sortent aussi ;
      - le pronostic devait être FIGÉ AVANT LE DÉPART (`predictions.created_at
        < courses.date_heure`) : sinon on afficherait une prédiction écrite
        après l'arrivée, ce qui ne prouve rien ;
      - `n_courses` et `n_gagnant_top3` sont renvoyés ensemble : sans le
        dénominateur, une liste d'exemples serait un biais du survivant.

    Aucun risque de paywall : uniquement des courses TERMINÉES, dont l'arrivée
    est publique. La valeur payante porte sur les courses à venir.
    """
    limite = max(3, min(12, limite))
    CACHE_KEY = f"stats:preuves-recentes:{limite}"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    # Une seule requête : pour chaque course terminée récente, le rang prédit du
    # vainqueur officiel, plus le rang 1 du modèle et sa place réelle.
    rows = (await db.execute(text("""
        WITH courues AS (
            SELECT c.course_id, c.nom, c.hippodrome_nom, c.date_heure, c.discipline,
                   c.nb_partants, c.est_quinte,
                   (SELECT (e->>'numero')::int
                      FROM jsonb_array_elements(r.classement::jsonb) e
                     WHERE (e->>'position') = '1' LIMIT 1) AS gagnant_numero,
                   (SELECT e->>'nom'
                      FROM jsonb_array_elements(r.classement::jsonb) e
                     WHERE (e->>'position') = '1' LIMIT 1) AS gagnant_nom,
                   r.rapports
              FROM courses c
              JOIN resultats r ON r.course_id = c.course_id
             WHERE c.statut = 'termine'
               AND jsonb_typeof(r.classement::jsonb) = 'array'
               AND c.date_heure > now() - interval '7 days'
             ORDER BY c.date_heure DESC
             LIMIT 60
        )
        SELECT k.course_id, k.nom, k.hippodrome_nom, k.date_heure, k.discipline,
               k.nb_partants, k.est_quinte, k.gagnant_numero, k.gagnant_nom, k.rapports,
               pg.rang_predit  AS rang_du_gagnant,
               p1.numero       AS favori_numero,
               ch1.nom         AS favori_nom,
               p1.cote_figee   AS favori_cote,
               (SELECT (e->>'position')::int
                  FROM resultats rr, jsonb_array_elements(rr.classement::jsonb) e
                 WHERE rr.course_id = k.course_id
                   AND (e->>'numero')::int = p1.numero LIMIT 1) AS favori_position
          FROM courues k
          -- rang que le modèle donnait au vainqueur
          LEFT JOIN LATERAL (
              SELECT pr.rang_predit
                FROM predictions pr
                JOIN participations pa ON pa.participation_id = pr.participation_id
               WHERE pr.course_id = k.course_id
                 AND pa.numero = k.gagnant_numero
                 AND pr.created_at < k.date_heure
               LIMIT 1
          ) pg ON TRUE
          -- le n°1 du modèle sur cette course
          LEFT JOIN LATERAL (
              SELECT pa.numero, pa.cheval_id, pr.cote_figee
                FROM predictions pr
                JOIN participations pa ON pa.participation_id = pr.participation_id
               WHERE pr.course_id = k.course_id
                 AND pr.rang_predit = 1
                 AND pr.created_at < k.date_heure
               LIMIT 1
          ) p1 ON TRUE
          LEFT JOIN chevaux ch1 ON ch1.cheval_id = p1.cheval_id
         WHERE pg.rang_predit IS NOT NULL
         ORDER BY k.date_heure DESC
         LIMIT :lim
    """), {"lim": limite})).mappings().all()

    courses = []
    for r in rows:
        rapports = r["rapports"] or {}
        if isinstance(rapports, str):
            try:
                rapports = json.loads(rapports)
            except Exception:
                rapports = {}
        sg = None
        for cle in ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"):
            if rapports.get(cle) is not None:
                sg = float(rapports[cle])
                break
        courses.append({
            "course_id": r["course_id"],
            "nom": r["nom"],
            "hippodrome": r["hippodrome_nom"],
            "date_heure": r["date_heure"].isoformat() if r["date_heure"] else None,
            "discipline": r["discipline"],
            "nb_partants": r["nb_partants"],
            "est_quinte": bool(r["est_quinte"]),
            "gagnant_numero": r["gagnant_numero"],
            "gagnant_nom": r["gagnant_nom"],
            "rang_du_gagnant": r["rang_du_gagnant"],
            "gagnant_top1": r["rang_du_gagnant"] == 1,
            "gagnant_top3": r["rang_du_gagnant"] is not None and r["rang_du_gagnant"] <= 3,
            "favori_numero": r["favori_numero"],
            "favori_nom": r["favori_nom"],
            "favori_cote": float(r["favori_cote"]) if r["favori_cote"] else None,
            "favori_position": r["favori_position"],
            "rapport_gagnant": sg,
        })

    resultat = {
        "courses": courses,
        "n_courses": len(courses),
        "n_gagnant_top1": sum(1 for c in courses if c["gagnant_top1"]),
        "n_gagnant_top3": sum(1 for c in courses if c["gagnant_top3"]),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _cache_set(redis, CACHE_KEY, resultat, ttl=600)  # 10 min
    return resultat


@router.get("/stats/palmares-public")
async def stats_palmares_public(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Palmarès PUBLIC (page d'accueil / track-record) — version non authentifiée de
    `/stats/palmares-gagnants`.

    Pourquoi cet endpoint existe (bug constaté 2026-08-17) : la section « Palmarès en
    direct » de la page d'accueil appelait `/stats/palmares-gagnants`, gardé par
    `require_admin` → **401 pour tout visiteur**. La principale preuve sociale du site
    n'était donc visible QUE par le compte admin ; chaque prospect voyait l'état vide
    « Les premiers paris gagnants s'afficheront ici ».

    Ce qui est exposé ici, et pourquoi c'est sans risque :
      - uniquement des courses PASSÉES et réglées, aux rapports PMU déjà publics —
        la valeur payante du produit porte sur les prédictions À VENIR, pas sur
        l'historique ;
      - mêmes garde-fous d'intégrité que la version admin (prono figé AVANT le
        départ, backfill exclu) ;
      - `nb_courses_reglees` est renvoyé VOLONTAIREMENT à côté de la liste des
        gagnants : sans ce dénominateur, n'afficher que les paris gagnants serait un
        biais du survivant. Le front doit présenter les deux ensemble.

    Ce qui N'EST PAS exposé : le ROI et les agrégats de gains par profil restent
    réservés à l'admin (exigence produit déjà appliquée à `/stats/public`).
    """
    CACHE_KEY = "stats:palmares-public"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    data = await _palmares_rows(db)
    result = {
        # Volumes alignés sur ce que la page track-record sait dérouler via ses
        # boutons « voir plus » (50 récents / 30 records). Avec l'ancien cap à 10,
        # un visiteur anonyme recevait exactement 10 lignes : le bouton, conditionné
        # à `limite < longueur`, ne s'affichait jamais et la liste semblait close.
        "top_gains": data["top_gains"][:30],
        "gagnants": data["gagnants"][:50],
        "nb_paris_gagnes": data["n"],
        "nb_courses_gagnantes": data["n_courses"],
        "nb_courses_reglees": data["n_courses_reglees"],
        "integrite": data["integrite"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=300)  # 5 min
    return result


@router.get("/stats/chiffres-site")
async def stats_chiffres_site(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Les chiffres de fond du service, pour les visuels de communication.

    POURQUOI UN ENDPOINT PLUTÔT QUE DES NOMBRES ÉCRITS DANS LE VISUEL : une
    publication Instagram est définitive. Un chiffre figé dans le code aurait été
    exact le soir de la publication puis faux pour toujours, et surtout il aurait
    fini par contredire la page track-record, qui le calcule, elle, en direct.

    `courses_reglees` et `journees_publiees` sortent EXACTEMENT de la même cohorte
    que le palmarès public — `_palmares_rows`, donc pronostic figé avant le départ et
    backfill exclu. Deux définitions du même chiffre finiraient par diverger, et
    c'est précisément le chiffre sur lequel repose l'argument d'intégrité.

    À NE PAS EXPOSER ICI : le nombre de paris gagnés et le nombre de courses
    gagnantes. Rapportés au dénominateur ils se lisent comme un taux de réussite,
    donc comme une rentabilité — alors que le ROI mesuré est négatif. Ils restent sur
    le track-record, où ils sont présentés avec leur contexte.
    """
    CACHE_KEY = "stats:chiffres-site"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    volumes = await db.execute(text("""
        SELECT (SELECT COUNT(*) FROM courses)         AS courses_en_base,
               (SELECT COUNT(*) FROM participations)  AS partants_analyses
    """))
    v = volumes.mappings().first() or {}

    cohorte = await db.execute(text("""
        SELECT COUNT(DISTINCT r.course_id)                       AS courses_reglees,
               COUNT(DISTINCT substring(r.course_id, 1, 8))      AS journees_publiees,
               MIN(c.date_heure)::date                           AS depuis
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND r.created_at < c.date_heure
          AND COALESCE(r.meta->>'backfill', '') <> 'true'
    """))
    co = cohorte.mappings().first() or {}

    # Les taux de réussite sortent du MÊME cache que la page track-record publique.
    # Les recalculer ici donnerait deux chiffres pour la même chose, et le jour où
    # ils divergeraient d'un dixième, c'est le visuel — définitif — qui aurait tort.
    tr, _frais = await _cache_get_swr(redis, TRACK_RECORD_CACHE_KEY)
    if tr is None:
        # Cache froid : on paie le calcul une fois. `chiffres-site` étant lui-même
        # gardé une heure, ça n'arrive qu'au premier appel après un vidage de Redis.
        tr = await _compute_track_record(db)
        await _cache_set_swr(redis, TRACK_RECORD_CACHE_KEY, tr, fresh_ttl=TRACK_RECORD_FRESH_TTL)
    g = (tr or {}).get("global", {}) or {}

    result = {
        "courses_en_base": int(v.get("courses_en_base") or 0),
        "partants_analyses": int(v.get("partants_analyses") or 0),
        "courses_reglees": int(co.get("courses_reglees") or 0),
        "journees_publiees": int(co.get("journees_publiees") or 0),
        "depuis": co.get("depuis").isoformat() if co.get("depuis") else None,
        # Taux mesurés, et le HASARD sur les mêmes courses. Le second n'est pas
        # décoratif : « 60 % » ne veut rien dire sans savoir ce que vaut un tirage
        # au sort sur des champs de 11 partants. C'est la comparaison qui prouve,
        # et c'est la seule façon honnête de vendre une précision.
        "precision_top3": g.get("accuracy_top3"),
        "hasard_top3": g.get("hasard_top3"),
        "favori_place": g.get("favori_place_rate"),
        "favori_gagnant": g.get("favori_win_rate"),
        "courses_mesurees": g.get("nb_courses_analysees"),
        "mesure_depuis": g.get("mesure_depuis"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=3600)  # 1 h : ces chiffres bougent lentement
    return result


@router.get("/stats/palmares-gagnants")
async def stats_palmares_gagnants(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),   # ROI/gains par profil = admin uniquement
):
    """Liste des PARIS RÉELLEMENT GAGNÉS par l'algorithme, par profil — UNIQUEMENT
    les pronostics RÉELLEMENT FIGÉS AVANT LE DÉPART de la course (profil_run_log),
    puis réglés aux VRAIS rapports PMU à l'arrivée.

    INTÉGRITÉ STRICTE (exigence produit) — un pari ne compte au palmarès QUE si :
      1. il a été journalisé AVANT le départ : `r.created_at < c.date_heure`
         (preuve temporelle : le prono existait avant que la course parte) ;
      2. ce n'est PAS une reconstruction a posteriori (`meta.backfill` exclu) :
         un plan régénéré après la course n'a jamais été « proposé » → mensonge ;
      3. le pari est réglé gagnant avec rapport PMU publié.
    Sans ces gardes, le palmarès afficherait des paris jamais réellement émis.

    La requête et les garde-fous vivent dans `_palmares_rows()` (partagé avec
    `/stats/palmares-public`) ; seuls les agrégats ROI/gains par profil, réservés à
    l'admin, sont calculés ici."""
    data = await _palmares_rows(db)
    gagnants = data["gagnants"]
    by_profil = data["by_profil"]

    profils = []
    for pk, lbl in data.get("profil_labels", {}).items():
        a = by_profil[pk]
        nc = len(a["courses"])
        profils.append({
            "profil": pk, "label": lbl,
            "nb_courses": nc,
            "mise_totale": round(a["mise"], 2),
            "gain_total": round(a["gain"], 2),
            "gain_net": round(a["gain"] - a["mise"], 2),
            "roi": round((a["gain"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None,
            "paris_gagnes": a["paris_gagnes"],
            "taux_courses_beneficiaires": round(a["courses_benef"] / nc * 100, 1) if nc else None,
        })

    return {
        # Liste = 100 paris gagnants les plus récents (le résumé par profil + les
        # totaux ci-dessous portent eux sur TOUTES les courses analysées).
        "gagnants": gagnants[:100],
        "top_gains": data["top_gains"],
        "n": data["n"],
        "n_courses": data["n_courses"],
        "nb_courses_reglees": data["n_courses_reglees"],
        "total_gain": data["total_gain"],
        "total_benefice": round(data["total_gain"] - data["total_mise"], 2),
        "profils": profils,
        "integrite": data["integrite"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# Point 11 — Rentabilité FORWARD des plans réellement émis (admin)
# ─────────────────────────────────────────────────────────────
BET_PLAN_PERF_DIMENSIONS = (
    "profil", "type_pari", "cote_band", "ev_band", "discipline", "hippodrome",
    "peloton", "model_version", "snapshot_age", "bankroll", "combo",
)


@router.get("/stats/bet-plan-performance")
async def stats_bet_plan_performance(
    dimension: str = "type_pari",
    days: Optional[int] = 90,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),   # ROI segmenté par plan = admin uniquement
):
    """Rentabilité FORWARD des plans de mise RÉELLEMENT émis (bet_plan_snapshots
    réglés sur les vrais rapports PMU), jamais une reconstruction a posteriori.

    `dimension` : une des colonnes de segmentation (profil, type_pari, cote_band,
    ev_band, discipline, hippodrome, peloton, model_version, snapshot_age,
    bankroll, combo). `days` : fenêtre glissante en jours (None = tout l'historique).
    Un segment sous le seuil de fiabilité reste `status="observed"` — jamais
    déclaré rentable ou perdant sur un petit échantillon.
    """
    from fastapi import HTTPException as _H
    from ml.bet_plan_performance import (
        DIMENSIONS, compute_forward_performance, evaluate_segment_gates,
    )
    if dimension not in DIMENSIONS:
        raise _H(status_code=422,
                 detail=f"dimension invalide (attendu: {', '.join(DIMENSIONS)})")
    since = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    perf = await compute_forward_performance(db, dimension, since=since)
    perf["gates"] = evaluate_segment_gates(perf)
    return perf


@router.get("/stats/meilleurs-plans-jour")
async def stats_meilleurs_plans_jour(
    jour: Optional[str] = Query(
        None,
        description="Journée présentée, au format AAAA-MM-JJ. Par défaut : aujourd'hui à Paris.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Les meilleurs plans d'une journée, pour les visuels de communication.

    `jour` EXISTE POUR LA MOSAÏQUE INSTAGRAM, et ce n'est pas un confort.
    Elle se publie le lendemain matin, une fois la journée complète : les dernières
    courses du programme sont sud-américaines et se courent jusqu'à 23 h 30, réglées
    une vingtaine de minutes plus tard. Publier « aujourd'hui » laissait donc une
    fenêtre de dix minutes avant que la journée ne bascule — et une mosaïque publiée
    de l'autre côté de minuit aurait figé, pour toujours, une journée vide.

    Deuxième raison, aussi importante : les six publications s'étalent sur deux
    minutes. Sans journée figée, une série lancée à cheval sur minuit produirait des
    tuiles qui ne parlent pas du même jour.

    ATTENTION AU VOCABULAIRE — ces montants sont ceux de PLANS calculés et réglés aux
    rapports réels du PMU, pas d'argent encaissé par qui que ce soit. Tout libellé du
    type « nos gains » serait faux : on parle de `mise` et de `retour` d'un plan, jamais
    de bénéfice réalisé.

    LE PLAN MONTRÉ EST LE DERNIER ÉMIS AVANT LE DÉPART, jamais le meilleur de la
    journée. Un plan est ré-émis à chaque mouvement de cote (~33 fois par course), et
    trier ces ré-émissions sur `net DESC` remontait un conseil PÉRIMÉ : le 2026-09-04,
    04092026R5C4 sortait à 10 € → 1 286 € (snapshots de 07:14 à 13:43) alors que le
    plan effectivement conseillé au départ perdait, et que la fiche course publique
    affichait « Risqué −10 € ». La règle de sélection est unique et vit dans
    `services.bet_plan_snapshots.CTE_PLAN_PUBLIE_DU_JOUR` — voir son commentaire pour
    les trois filtres (plan du site, pré-course, règlement définitif) et pour la
    vérification qui prouve qu'elle donne exactement ce qu'affiche la fiche course.

    LE JOUR EST CELUI DU PMU, lu dans les 8 premiers caractères de `course_id`
    (JJMMAAAA) — surtout pas `date_heure`. Une course courue à 22 h 50 UTC tombe après
    minuit heure de Paris : filtrer sur l'horodatage la rattachait au lendemain, et le
    visuel du 23 août affichait une course du 22 (constaté sur 22082026R8C10).
    """
    # Le PMU écrit le jour en JJMMAAAA en tête du `course_id`. On le construit ici une
    # seule fois, et les DEUX requêtes s'en servent : elles doivent parler du même jour,
    # sans quoi le nombre de courses annoncé ne serait pas celui des plans montrés.
    from services.bet_plan_snapshots import CTE_PLAN_PUBLIE_DU_JOUR
    from services.temps_courses import jour_courses

    if jour:
        try:
            jjmmaaaa = date.fromisoformat(jour).strftime("%d%m%Y")
        except ValueError:
            raise HTTPException(status_code=422, detail="jour attendu au format AAAA-MM-JJ")
    else:
        jjmmaaaa = jour_courses().strftime("%d%m%Y")

    # `c.hippodrome_nom` et SURTOUT PAS `reunions → hippodromes` : `reunions` ne
    # compte que quinze lignes recyclées d'une journée à l'autre, et son
    # `hippodrome_id` désigne donc la mauvaise piste. Mesuré le 2026-09-04 : 36 des
    # 52 courses du jour recevaient un faux hippodrome par cette jointure (Lyon-
    # Parilly annoncé « Nancy-Brabois », Duindigt annoncé « Toulouse La Cépière »),
    # et 04092026R3C3 — annoncé au mauvais hippodrome — figure dans le top du jour.
    lignes = await db.execute(
        text("WITH " + CTE_PLAN_PUBLIE_DU_JOUR + """
        SELECT p.course_id, p.profil,
               COALESCE(c.hippodrome_nom, '') AS hippodrome,
               p.montant_mise, p.montant_retour, p.net, p.nb_gagnes, p.nb_paris
        FROM plan_publie p
        JOIN courses c ON c.course_id = p.course_id
        WHERE p.net > 0
        ORDER BY p.net DESC
        LIMIT 20
    """),
        {"jjmmaaaa": jjmmaaaa},
    )

    vus: set[str] = set()
    plans: list[dict] = []
    for r in lignes.mappings():
        # Un même plan gagnant peut exister pour plusieurs profils sur la même course :
        # les lister deux fois donnerait l'impression d'un doublon dans le visuel.
        if r["course_id"] in vus:
            continue
        vus.add(r["course_id"])
        plans.append({
            "course_id": r["course_id"],
            # `profil` est exposé pour que le chiffre reste VÉRIFIABLE : c'est la clé
            # qui permet de retrouver la même ligne sur la fiche course publique.
            "profil": r["profil"],
            "hippodrome": (r["hippodrome"] or "").replace("HIPPODROME DE ", "").replace("HIPPODROME DU ", "").title(),
            "code": (r["course_id"][8:] if len(r["course_id"]) > 8 else r["course_id"]),
            "mise": round(float(r["montant_mise"] or 0), 2),
            "retour": round(float(r["montant_retour"] or 0), 2),
            "net": round(float(r["net"] or 0), 2),
            "nb_gagnes": int(r["nb_gagnes"] or 0),
            "nb_paris": int(r["nb_paris"] or 0),
        })
        if len(plans) >= 3:
            break

    volume = await db.execute(
        text("""
        SELECT COUNT(DISTINCT c.course_id) AS nb_courses,
               COUNT(DISTINCT c.reunion_id) AS nb_reunions
        FROM courses c
        WHERE substring(c.course_id, 1, 8) = :jjmmaaaa
    """),
        {"jjmmaaaa": jjmmaaaa},
    )
    v = volume.mappings().first() or {}

    # `jour` est renvoyé tel qu'il a été RÉSOLU, jamais tel qu'il a été demandé : le
    # visuel affiche cette date, et une date d'affichage qui ne serait pas celle des
    # chiffres est le pire défaut possible sur une publication qu'on ne peut plus
    # corriger.
    return {
        "jour": f"{jjmmaaaa[4:]}-{jjmmaaaa[2:4]}-{jjmmaaaa[:2]}",
        "plans": plans,
        "nb_courses": int(v.get("nb_courses") or 0),
        "nb_reunions": int(v.get("nb_reunions") or 0),
    }
