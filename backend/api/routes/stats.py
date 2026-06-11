"""
Stats publiques — BlackTurf.
Métriques du modèle + courbe équité simulée + ML monitoring.
Cache Redis pour éviter requêtes lourdes répétées.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from api.model_metrics import real_model_metrics, plausible_auc, plausible_roi_pct
from api.profil_backtest import backtest_profils
from api.routes.auth import get_current_user
from db.database import get_db
from db.redis_client import get_redis
from db.models import (
    ModelVersion, Course, User, ValueBet, Participation,
    Resultat, Cheval, AdaptiveLearningState, DriftDetectorState,
    BankrollEntry, Recommandation, Prediction, RaceLearningLog,
)
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

async def _vb_flat_backtest(db: AsyncSession, since_days: int = 180, mise: float = 10.0, start: float = 1000.0) -> dict:
    """Backtest HONNÊTE : 10€ flat en Simple Gagnant sur chaque value bet ★★★+
    (niveau ≥ 3) des `since_days` derniers jours, réglé sur l'arrivée RÉELLE à la
    COTE PMU RÉELLE. Source unique pour la courbe d'équité ET le ROI simulé 6 mois
    (évite toute divergence). is_real=False si < 10 paris."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = (await db.execute(
        select(ValueBet, Participation, Course, Resultat)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .outerjoin(Resultat, Resultat.course_id == ValueBet.course_id)
        .where(ValueBet.niveau >= 3, Course.statut == "termine", Course.date_heure >= since)
        .order_by(Course.date_heure)
        .limit(500)
    )).all()

    if len(rows) < 10:
        return {"is_real": False, "points": [], "n_bets": len(rows), "roi_pct": None, "gain_net": None, "mise": mise}

    bankroll = start
    points = []
    for vb, part, course, resultat in rows:
        gagne = (
            resultat and isinstance(resultat.classement, list) and resultat.classement
            and isinstance(resultat.classement[0], dict)
            and resultat.classement[0].get("numero") == part.numero
        )
        if gagne and part.cote_pmu and part.cote_pmu > 1:
            bankroll += (part.cote_pmu - 1) * mise
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
    # ROI simulé 6 mois = backtest réel 10€ flat sur value bets ★★★+ (même source que
    # la courbe d'équité). null si pas assez d'historique OU si aberrant (+307% =
    # biais longshot sur petit échantillon) → le front affiche "—".
    _bt = await _vb_flat_backtest(db)
    roi_pct = plausible_roi_pct(_bt["roi_pct"] if _bt["is_real"] else None)

    result = {
        "auc_roc": metrics["auc_roc"],               # gardé ∈ [0.5,1], sinon null (jamais 0.06)
        "roi_simule_6mois": roi_pct,
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
            Course.statut != "annule",
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

@router.get("/stats/track-record")
async def track_record(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Performance historique de l'IA — page publique marketing.
    Cache Redis 1h.
    """
    CACHE_KEY = "stats:track-record"
    cached = await _cache_get(redis, CACHE_KEY)
    if cached:
        return cached

    # ── 1. Précision globale depuis race_learning_log ─────────
    all_rll = (await db.execute(
        select(RaceLearningLog).order_by(RaceLearningLog.analyzed_at)
    )).scalars().all()

    nb_total = len(all_rll)
    brier_scores = [r.brier_score for r in all_rll if r.brier_score is not None]
    brier_moyen = round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else 0.0
    top1_hits = [r for r in all_rll if r.gagnant_rang_predit == 1]
    top3_hits = [r for r in all_rll if r.gagnant_rang_predit is not None and r.gagnant_rang_predit <= 3]
    accuracy_top1 = round(len(top1_hits) / nb_total * 100, 1) if nb_total else 0.0
    accuracy_top3 = round(len(top3_hits) / nb_total * 100, 1) if nb_total else 0.0
    nb_surprises = len([r for r in all_rll if r.was_surprise])

    # ── 2. Par jour (7 derniers jours, fuseau Europe/Paris) ──
    # Coupure de journée à minuit heure française (pas UTC) pour que
    # le point du jour reflète bien "la journée" côté utilisateur.
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
            "_top3": 0,
            "_brier": [],
        }
    for r in all_rll:
        if not r.analyzed_at:
            continue
        # analyzed_at est en UTC (naïf ou aware) → on le ramène en heure FR
        dt = r.analyzed_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        key = dt.astimezone(paris_tz).strftime("%Y-%m-%d")
        if key not in daily_acc:
            continue
        daily_acc[key]["nb_predictions"] += 1
        if r.was_surprise:
            daily_acc[key]["nb_surprises"] += 1
        if r.gagnant_rang_predit is not None and r.gagnant_rang_predit <= 3:
            daily_acc[key]["_top3"] += 1
        if r.brier_score is not None:
            daily_acc[key]["_brier"].append(float(r.brier_score))

    for v in daily_acc.values():
        nb = v["nb_predictions"]
        briers = v.pop("_brier", [])
        if nb:
            v["accuracy_top3"] = round(v.pop("_top3") / nb * 100, 1)
        else:
            v.pop("_top3")
        v["brier_moyen"] = round(sum(briers) / len(briers), 4) if briers else None

    daily_list = list(daily_acc.values())

    # ── 3. Par discipline ─────────────────────────────────────
    disc_acc: dict[str, dict] = {}
    for r in all_rll:
        d = r.discipline or "Autre"
        if d not in disc_acc:
            disc_acc[d] = {"nb": 0, "top3": 0}
        disc_acc[d]["nb"] += 1
        if r.gagnant_rang_predit is not None and r.gagnant_rang_predit <= 3:
            disc_acc[d]["top3"] += 1
    by_discipline = [
        {
            "discipline": d,
            "nb_courses": v["nb"],
            "accuracy_top3": round(v["top3"] / v["nb"] * 100, 1) if v["nb"] else 0.0,
        }
        for d, v in disc_acc.items()
    ]

    # ── 4. Meilleurs pronostics (gagnant prédit rang 1, cote > 5) ─
    q_best = (
        select(Prediction, Participation, Cheval, Course, Resultat)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == Prediction.course_id)
        .outerjoin(Resultat, Resultat.course_id == Prediction.course_id)
        .where(
            Prediction.rang_predit == 1,
            Participation.cote_pmu >= 5.0,
            Course.statut == "termine",
        )
        .order_by(Prediction.created_at.desc())
        .limit(10)
    )
    best_rows = (await db.execute(q_best)).all()
    best_pronostics = []
    for pred, part, cheval, course, resultat in best_rows:
        gagnant_reel = None
        if resultat and resultat.classement and isinstance(resultat.classement, list):
            if resultat.classement:
                premier = resultat.classement[0]
                if isinstance(premier, dict):
                    gagnant_reel = premier.get("cheval") or premier.get("nom")
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
    q_vbs = (
        select(ValueBet, Participation, Resultat)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .outerjoin(Resultat, Resultat.course_id == ValueBet.course_id)
        .where(ValueBet.actif == False)  # resolved bets only
        .limit(2000)
    )
    vb_rows = (await db.execute(q_vbs)).all()
    for vb, part, resultat in vb_rows:
        n = vb.niveau
        if n not in vb_stats:
            continue
        # Pas d'arrivée publiée (outerjoin → resultat None) : on NE règle PAS le pari.
        # Avant, il tombait dans le `else` et était compté perdant → ROI faussé à la baisse.
        if not (resultat and isinstance(resultat.classement, list) and resultat.classement):
            continue
        mise = 10.0
        vb_stats[n]["nb"] += 1
        vb_stats[n]["mise"] += mise
        premier = resultat.classement[0]
        gagne = isinstance(premier, dict) and premier.get("numero") == part.numero
        if gagne and part.cote_pmu and part.cote_pmu > 1:
            vb_stats[n]["wins"] += 1
            vb_stats[n]["gains"] += (part.cote_pmu - 1) * mise
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
    q_fav = (
        select(Prediction, Participation, Cheval, Course, Resultat)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == Prediction.course_id)
        .join(Resultat, Resultat.course_id == Prediction.course_id)
        .where(Prediction.rang_predit == 1, Course.statut == "termine")
        .order_by(Prediction.created_at.desc())
        .limit(2000)
    )
    fav_rows = (await db.execute(q_fav)).all()

    # Rang IA du vainqueur réel par course (depuis race_learning_log)
    course_ids = [c.course_id for _, _, _, c, _ in fav_rows]
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
    for pred, part, cheval, course, resultat in fav_rows:
        classement = resultat.classement if resultat else None
        pos = _pos_in_classement(classement, part.numero)
        if pos is None:
            continue  # non-partant / arrivée incomplète → hors taux
        fav_total += 1
        is_win = pos == 1
        is_place = pos <= 3
        fav_wins += int(is_win)
        fav_places += int(is_place)

        # ROI : on ne compte que les courses où la cote PMU réelle est connue
        if part.cote_pmu and part.cote_pmu > 1.0:
            mise_fav += 1.0
            if is_win:
                gain_fav += float(part.cote_pmu)

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
            rang_gagnant_ia = rll_by_course.get(course.course_id)
            verdict = (
                "gagnant" if is_win
                else "place" if is_place
                else "top3" if (rang_gagnant_ia is not None and rang_gagnant_ia <= 3)
                else "manque"
            )
            derniers_pronostics.append({
                "course_id": course.course_id,
                "hippodrome": course.hippodrome_nom,
                "discipline": course.discipline,
                "date": course.date_heure.strftime("%d/%m/%Y") if course.date_heure else None,
                "favori_nom": cheval.nom,
                "favori_numero": part.numero,
                "proba_top1": round(pred.proba_top1 * 100, 1),
                "cote": round(part.cote_pmu, 1) if part.cote_pmu else None,
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
        clv_row = (await db.execute(text("""
            WITH fav AS (
                SELECT p.participation_id FROM predictions p
                JOIN courses c ON c.course_id = p.course_id
                WHERE p.rang_predit = 1 AND c.statut = 'termine'
            ),
            ch AS (
                SELECT participation_id,
                       (array_agg(cote ORDER BY time ASC))[1]  AS o,
                       (array_agg(cote ORDER BY time DESC))[1] AS c
                FROM cotes_historique WHERE cote > 1 GROUP BY participation_id
            )
            SELECT count(*) AS n,
                   round((count(*) FILTER (WHERE o > c)::numeric / nullif(count(*),0) * 100), 1) AS pct_beat,
                   round(avg(1.0/c - 1.0/o)::numeric * 100, 2) AS clv_implied,
                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY o/c - 1))::numeric * 100, 1) AS clv_median
            FROM fav JOIN ch ON ch.participation_id = fav.participation_id
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

    result = {
        "global": {
            "accuracy_top1": accuracy_top1,
            "accuracy_top3": accuracy_top3,
            "brier_moyen": brier_moyen,
            "nb_courses_analysees": nb_total,
            "nb_surprises": nb_surprises,
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
        "by_discipline": by_discipline,
        "best_pronostics": best_pronostics,
        "derniers_pronostics": derniers_pronostics,
        "vb_performance": vb_performance,
        "adaptive_learning": al_data,
        "clv": clv,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _cache_set(redis, CACHE_KEY, result, ttl=120)  # 2 min — quasi temps réel
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


@router.get("/stats/palmares-gagnants")
async def stats_palmares_gagnants(
    db: AsyncSession = Depends(get_db),
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
    Sans ces gardes, le palmarès afficherait des paris jamais réellement émis."""
    from sqlalchemy import text as _text
    try:
        rows = (await db.execute(_text("""
            SELECT r.profil, r.resultat, r.settled_at, r.created_at,
                   c.hippodrome_nom, c.date_heure, c.course_id, c.numero_reunion, c.numero
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
        return {"gagnants": [], "n": 0, "n_courses": 0, "profils": [],
                "updated_at": datetime.now(timezone.utc).isoformat()}

    PROFIL_LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
    gagnants = []
    # Résumé par profil : compte TOUTES les courses réglées (gagnées + perdues)
    # pour un ROI honnête, et les courses bénéficiaires.
    by_profil: dict = {p: {"courses": set(), "mise": 0.0, "gain": 0.0,
                           "courses_benef": 0, "paris_gagnes": 0} for p in PROFIL_LBL}
    for profil, resultat, settled_at, created_at, hippo, dh, cid, n_reunion, n_course in rows:
        res = resultat if isinstance(resultat, dict) else json.loads(resultat or "{}")
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
                # Preuve d'intégrité : prono figé AVANT le départ, réglé après l'arrivée.
                "fige_avant_course": True,
                "fige_le": created_at.isoformat() if created_at else None,
                "regle_le": settled_at.isoformat() if settled_at else None,
            })
    gagnants.sort(key=lambda g: g.get("date") or "", reverse=True)
    total_gain = round(sum(x["gain"] for x in gagnants), 2)
    total_mise = round(sum(x["mise"] for x in gagnants), 2)

    profils = []
    for pk, lbl in PROFIL_LBL.items():
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

    # Top 30 des plus gros gains (par bénéfice net du pari), toutes courses.
    top_gains = sorted(gagnants, key=lambda x: x["benefice"], reverse=True)[:30]

    return {
        # Liste = 100 paris gagnants les plus récents (le résumé par profil + les
        # totaux ci-dessous portent eux sur TOUTES les courses analysées).
        "gagnants": gagnants[:100],
        "top_gains": top_gains,
        "n": len(gagnants),
        "n_courses": len({x["course_id"] for x in gagnants}),
        "total_gain": total_gain,
        "total_benefice": round(total_gain - total_mise, 2),
        "profils": profils,
        "integrite": (
            "Tous les paris affichés ont été figés AVANT le départ de la course "
            "puis réglés aux vrais rapports PMU à l'arrivée. Aucune reconstruction "
            "a posteriori (backfill) n'est comptée."
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
