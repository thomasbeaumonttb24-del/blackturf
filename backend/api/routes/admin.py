"""
Admin routes — BlackTurf back-office.
Accès admin uniquement.
"""
import json
import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, or_, case, text

from api.model_metrics import plausible_roi, real_model_metrics
from api.routes.auth import require_admin
from db.database import get_db
from db.models import (
    User, Subscription, ModelVersion, ScrapeLog,
    Course, Prediction, ValueBet, AlerteLog,
    AdaptiveLearningState, DriftDetectorState, BankrollEntry,
)
from ml.adaptive_learning import get_adaptive_learning
from ml.drift_detector import get_drift_detector

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────
@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Métriques générales du back-office."""
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)

    # Utilisateurs
    total_users = (await db.execute(select(func.count(User.user_id)))).scalar() or 0
    users_7d = (await db.execute(
        select(func.count(User.user_id)).where(User.created_at >= since_7d)
    )).scalar() or 0

    # Abonnements actifs
    subs_active = (await db.execute(
        select(func.count(Subscription.sub_id)).where(Subscription.statut == "active")
    )).scalar() or 0

    # Modèle actif
    mv_res = await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )
    mv = mv_res.scalar_one_or_none()
    # Métriques fiables : précision réelle observée (vs métadonnée d'entraînement).
    mv_metrics = await real_model_metrics(db, mv)

    # Cours 24h
    since_24h = now - timedelta(hours=24)
    courses_24h = (await db.execute(
        select(func.count(Course.course_id)).where(Course.created_at >= since_24h)
    )).scalar() or 0

    # Alertes en erreur
    alertes_erreur = (await db.execute(
        select(func.count(AlerteLog.alerte_id)).where(
            and_(AlerteLog.envoye == False, AlerteLog.erreur.is_not(None))
        )
    )).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "nouveaux_7j": users_7d,
            "abonnes_actifs": subs_active,
        },
        "modele": {
            "version": mv.version_num if mv else None,
            "auc_roc": round(mv.auc_roc, 4) if mv else None,
            "precision_top3": mv_metrics["precision_top3"],
            "nb_courses_evaluees": mv_metrics["nb_courses_evaluees"],
            "trained_at": mv.created_at if mv else None,
        },
        "courses_24h": courses_24h,
        "alertes_erreur": alertes_erreur,
    }


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────
@router.get("/users")
async def list_users(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    plan: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Liste les utilisateurs : identité, plan, profil, PORTEFEUILLE (misé/gagné/net/
    ROI/solde), nb paris, date création — tout ce qu'il faut pour suivre chaque compte.
    Agrégats calculés en requêtes GROUPÉES (pas de N+1). Jamais le mot de passe."""
    from db.models import Bankroll
    # Règle d'abord les paris en attente de TOUS les users (courses terminées) →
    # ROI/solde affichés à l'admin toujours réels et à jour. Best-effort.
    try:
        from api.routes.bankroll import settle_pending_bets
        await settle_pending_bets(db, None)
    except Exception as e:
        log.warning("admin.settle_skip", err=str(e)[:120])
    q = select(User)
    if plan:
        q = q.where(User.plan == plan)
    if search:
        like = f"%{search}%"
        q = q.where(or_(User.email.ilike(like), User.nom.ilike(like), User.prenom.ilike(like)))
    q = q.order_by(desc(User.created_at)).limit(limit).offset(offset)
    users = (await db.execute(q)).scalars().all()
    uids = [u.user_id for u in users]

    # ── Agrégats bankroll par user (1 requête groupée) ──
    agg: dict[str, dict] = {}
    if uids:
        rows = (await db.execute(
            select(
                BankrollEntry.user_id,
                func.count(BankrollEntry.entry_id),
                func.coalesce(func.sum(BankrollEntry.mise), 0.0),
                func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
                func.sum(case((BankrollEntry.resultat == "gagne", 1), else_=0)),
                func.sum(case((BankrollEntry.suivi_reco_ia == True, 1), else_=0)),
            ).where(BankrollEntry.user_id.in_(uids)).group_by(BankrollEntry.user_id)
        )).all()
        for uid, nb, mise, net, gagnes, ia in rows:
            agg[uid] = {"nb_paris": int(nb), "mise": float(mise), "net": float(net),
                        "nb_gagnes": int(gagnes or 0), "nb_ia": int(ia or 0)}
        # Solde = Σ montant_initial des portefeuilles + Σ gain_perte
        sol = (await db.execute(
            select(Bankroll.user_id, func.coalesce(func.sum(Bankroll.montant_initial), 0.0))
            .where(Bankroll.user_id.in_(uids), Bankroll.est_supprime == False)
            .group_by(Bankroll.user_id)
        )).all()
        for uid, init in sol:
            agg.setdefault(uid, {}).setdefault("nb_paris", 0)
            agg[uid]["capital_initial"] = float(init)

    result = []
    for u in users:
        a = agg.get(u.user_id, {})
        mise = a.get("mise", 0.0)
        net = a.get("net", 0.0)
        cap0 = a.get("capital_initial", 0.0) or (u.bankroll_initiale or 0.0)
        result.append({
            "user_id": u.user_id,
            "email": u.email,
            "nom": u.nom,
            "prenom": u.prenom,
            "plan": u.plan,
            "profil_risque": u.profil_risque,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "email_verified": u.email_verified,
            "auth_method": "google" if u.google_id else "email",
            "stripe_client": bool(u.stripe_customer_id),
            "created_at": u.created_at,
            "last_login": u.updated_at,
            # Portefeuille
            "bankroll_initiale": u.bankroll_initiale,
            "capital_initial": round(cap0, 2),
            "solde_actuel": round(cap0 + net, 2),
            "nb_paris": a.get("nb_paris", 0),
            "nb_gagnes": a.get("nb_gagnes", 0),
            "nb_predictions_used": a.get("nb_ia", 0),
            "mise_totale": round(mise, 2),
            "gain_net": round(net, 2),
            "roi": round(net / mise * 100, 1) if mise > 0 else None,
        })
    return result


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Détail utilisateur : paris, prédictions, abonnements."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    # Subscriptions
    subs = (await db.execute(
        select(Subscription).where(Subscription.user_id == user_id).order_by(desc(Subscription.created_at))
    )).scalars().all()

    # Bankroll entries (last 100)
    entries = (await db.execute(
        select(BankrollEntry).where(BankrollEntry.user_id == user_id)
        .order_by(desc(BankrollEntry.date)).limit(100)
    )).scalars().all()

    # Predictions used: count of IA-tracked bankroll entries
    nb_predictions = (await db.execute(
        select(func.count(BankrollEntry.entry_id)).where(
            and_(
                BankrollEntry.user_id == user_id,
                BankrollEntry.suivi_reco_ia == True,
            )
        )
    )).scalar() or 0

    return {
        "user": {
            "user_id": user.user_id,
            "email": user.email,
            "nom": user.nom,
            "prenom": user.prenom,
            "plan": user.plan,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "profil_risque": user.profil_risque,
            "bankroll_initiale": user.bankroll_initiale,
            "email_verified": user.email_verified,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        },
        "subscriptions": [
            {
                "sub_id": s.sub_id,
                "plan": s.plan,
                "periodicite": s.periodicite,
                "statut": s.statut,
                "periode_debut": s.periode_debut,
                "periode_fin": s.periode_fin,
            }
            for s in subs
        ],
        "nb_bets": len(entries),
        "nb_predictions_used": nb_predictions,
        "recent_bets": [
            {
                "entry_id": e.entry_id,
                "date": e.date,
                "type_pari": e.type_pari,
                "mise": e.mise,
                "resultat": e.resultat,
                "gain_perte": e.gain_perte,
            }
            for e in entries[:20]
        ],
    }


@router.put("/users/{user_id}/plan")
async def change_user_plan(
    user_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Change le plan d'un utilisateur manuellement (gift / test)."""
    new_plan = body.get("plan")
    if not new_plan or new_plan not in {"free", "standard", "expert", "pro", "starter"}:
        raise HTTPException(status_code=400, detail="Plan invalide. Valeurs: free/standard/expert")

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    old_plan = user.plan
    user.plan = new_plan
    await db.commit()
    log.info("admin.change_plan", user_id=user_id, old=old_plan, new=new_plan)
    return {"ok": True, "user_id": user_id, "old_plan": old_plan, "new_plan": new_plan}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    allowed = {"plan", "is_active", "is_admin", "profil_risque"}
    for k, v in body.items():
        if k in allowed:
            setattr(user, k, v)
    await db.commit()
    log.info("admin.update_user", user_id=user_id, changes={k: body[k] for k in body if k in allowed})
    return {"ok": True}


@router.post("/users/{user_id}/bankroll-adjust")
async def adjust_bankroll(
    user_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Crédite/débite le portefeuille d'un utilisateur (ajustement admin).
    body: {montant: float (delta, +crédit / -débit), note?: str}. Ajuste le capital
    initial du portefeuille principal + bankroll_initiale. Tracé dans les logs."""
    from db.models import Bankroll
    try:
        delta = float(body.get("montant"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Montant invalide")
    user = (await db.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    main = (await db.execute(
        select(Bankroll).where(and_(
            Bankroll.user_id == user_id, Bankroll.est_principale == True, Bankroll.est_supprime == False,
        ))
    )).scalar_one_or_none()
    if main:
        main.montant_initial = round((main.montant_initial or 0.0) + delta, 2)
        nouveau = main.montant_initial
    else:
        import uuid as _u
        main = Bankroll(bankroll_id=str(_u.uuid4()), user_id=user_id, nom="Principal",
                        montant_initial=round(delta, 2), est_principale=True)
        db.add(main)
        nouveau = main.montant_initial
    user.bankroll_initiale = round((user.bankroll_initiale or 0.0) + delta, 2)
    await db.commit()
    log.info("admin.bankroll_adjust", user_id=user_id, delta=delta, nouveau_capital=nouveau,
             note=str(body.get("note") or "")[:200])
    return {"ok": True, "delta": delta, "nouveau_capital_initial": nouveau}


@router.get("/users-export")
async def export_users_csv(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Export CSV de TOUS les comptes + portefeuille (données réelles)."""
    import csv as _csv
    import io
    from fastapi.responses import StreamingResponse
    from db.models import Bankroll
    try:
        from api.routes.bankroll import settle_pending_bets
        await settle_pending_bets(db, None)
    except Exception:
        pass

    users = (await db.execute(select(User).order_by(desc(User.created_at)).limit(5000))).scalars().all()
    uids = [u.user_id for u in users]
    agg: dict = {}
    if uids:
        for uid, nb, mise, net, gagnes in (await db.execute(
            select(BankrollEntry.user_id, func.count(BankrollEntry.entry_id),
                   func.coalesce(func.sum(BankrollEntry.mise), 0.0),
                   func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
                   func.sum(case((BankrollEntry.resultat == "gagne", 1), else_=0)))
            .where(BankrollEntry.user_id.in_(uids)).group_by(BankrollEntry.user_id)
        )).all():
            agg[uid] = {"nb": int(nb), "mise": float(mise), "net": float(net), "gagnes": int(gagnes or 0)}
        for uid, init in (await db.execute(
            select(Bankroll.user_id, func.coalesce(func.sum(Bankroll.montant_initial), 0.0))
            .where(Bankroll.user_id.in_(uids), Bankroll.est_supprime == False).group_by(Bankroll.user_id)
        )).all():
            agg.setdefault(uid, {})["cap"] = float(init)

    out = io.StringIO()
    w = _csv.writer(out)
    w.writerow(["Email", "Nom", "Prenom", "Plan", "Profil", "Auth", "Email verifie", "Actif",
                "Admin", "Inscrit le", "Capital", "Solde", "Mise totale", "Gain net", "ROI %",
                "Paris", "Gagnes"])
    for u in users:
        a = agg.get(u.user_id, {})
        mise = a.get("mise", 0.0); net = a.get("net", 0.0)
        cap = a.get("cap", 0.0) or (u.bankroll_initiale or 0.0)
        roi = round(net / mise * 100, 1) if mise > 0 else ""
        w.writerow([u.email, u.nom or "", u.prenom or "", u.plan, u.profil_risque,
                    "google" if u.google_id else "email", "oui" if u.email_verified else "non",
                    "oui" if u.is_active else "non", "oui" if u.is_admin else "non",
                    u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
                    round(cap, 2), round(cap + net, 2), round(mise, 2), round(net, 2), roi,
                    a.get("nb", 0), a.get("gagnes", 0)])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=blackturf_comptes.csv"})


# ─────────────────────────────────────────────
# Modèles ML
# ─────────────────────────────────────────────
@router.get("/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    rows = (await db.execute(
        select(ModelVersion).order_by(desc(ModelVersion.version_num)).limit(20)
    )).scalars().all()

    def _roi(m: ModelVersion) -> float | None:
        # ROI masqué si hors plage plausible (métadonnée train non fiable).
        roi = plausible_roi(m.roi_simule)
        return round(roi, 4) if roi is not None else None

    return [
        {
            "version_id": m.version_id,
            "version_num": m.version_num,
            "auc_roc": round(m.auc_roc, 4),
            "brier_score": round(m.brier_score, 4),
            "precision_top3": round(m.precision_top3, 4),
            "roi_simule": _roi(m),
            "walk_forward_auc": round(m.walk_forward_auc, 4) if m.walk_forward_auc else None,
            "walk_forward_variance": round(m.walk_forward_variance, 6) if m.walk_forward_variance else None,
            "nb_courses_train": m.nb_courses_train,
            "est_actif": m.est_actif,
            "est_rollback": m.est_rollback,
            "created_at": m.created_at,
        }
        for m in rows
    ]


@router.post("/models/{version_num}/deploy")
async def deploy_model(
    version_num: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Déploie manuellement une version spécifique."""
    from pathlib import Path
    import shutil
    from api.config import get_settings
    settings = get_settings()
    model_path = Path(settings.models_path) / f"model_v{version_num:04d}.pkl"
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="Fichier modèle introuvable")

    current = Path(settings.models_path) / "current_model.pkl"
    shutil.copy2(model_path, current)

    # Mettre à jour DB
    await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )
    all_mv = (await db.execute(select(ModelVersion))).scalars().all()
    for m in all_mv:
        m.est_actif = m.version_num == version_num
    await db.commit()
    log.info("admin.deploy_model", version=version_num)
    return {"ok": True, "deployed": version_num}


@router.post("/models/retrain")
async def trigger_retrain(
    _=Depends(require_admin),
):
    """Déclenche un retraining manuel (sync wrapper dans le worker ml)."""
    import redis as sync_redis
    from rq import Queue
    from api.config import get_settings
    r = sync_redis.from_url(get_settings().redis_url)
    q = Queue("ml", connection=r, default_timeout=3600)
    job = q.enqueue("ml.pipeline.retrain_if_needed", result_ttl=86400)
    log.info("admin.retrain_triggered", job_id=job.id)
    return {"ok": True, "job_id": job.id}


# ─────────────────────────────────────────────
# Scraper
# ─────────────────────────────────────────────
@router.get("/scraper/logs")
async def scraper_logs(
    limit: int = Query(default=50, le=200),
    source: Optional[str] = Query(default=None),
    statut: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    q = select(ScrapeLog)
    if source:
        q = q.where(ScrapeLog.source == source)
    if statut:
        q = q.where(ScrapeLog.statut == statut)
    q = q.order_by(desc(ScrapeLog.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    return [
        {
            "log_id": r.log_id,
            "source": r.source,
            "statut": r.statut,
            "nb_courses": r.nb_courses,
            "nb_partants": r.nb_partants,
            "erreur": r.erreur,
            "duree_ms": r.duree_ms,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/scraper/status")
async def scraper_status(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Dernier scrape par source."""
    from sqlalchemy import text
    # DISTINCT ON est PostgreSQL uniquement → ROW_NUMBER() OVER PARTITION compatible SQLite + PG
    rows = await db.execute(text("""
        SELECT source, statut, created_at, duree_ms, erreur
        FROM (
            SELECT source, statut, created_at, duree_ms, erreur,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY created_at DESC) AS rn
            FROM scrape_log
        ) sub
        WHERE rn = 1
    """))
    return {r.source: {
        "statut": r.statut,
        "derniere_maj": r.created_at,
        "duree_ms": r.duree_ms,
        "erreur": r.erreur,
    } for r in rows}


# ─────────────────────────────────────────────
# Alertes
# ─────────────────────────────────────────────
@router.get("/alertes")
async def list_alertes(
    limit: int = Query(default=100, le=500),
    envoye: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    q = select(AlerteLog)
    if envoye is not None:
        q = q.where(AlerteLog.envoye == envoye)
    q = q.order_by(desc(AlerteLog.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    return [
        {
            "alerte_id": a.alerte_id,
            "user_id": a.user_id,
            "type_alerte": a.type_alerte,
            "canal": a.canal,
            "envoye": a.envoye,
            "erreur": a.erreur,
            "created_at": a.created_at,
        }
        for a in rows
    ]


# ─────────────────────────────────────────────
# Adaptive Learning — état et monitoring
# ─────────────────────────────────────────────

@router.get("/adaptive-learning/state")
async def get_adaptive_learning_state(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Retourne l'état courant du moteur d'apprentissage adaptatif.
    Température, poids features, métriques EMA, alertes calibration.
    Inclut l'état du détecteur de drift (ADWIN + Page-Hinkley) et le statut des
    calibrations (isotonique + longshots) réellement appliquées à l'inférence.
    """
    from ml.adaptive_learning import TILT_MIN_RACES
    al = get_adaptive_learning()
    dd = get_drift_detector()

    # ── Statut calibration isotonique (proba_top1 finale → fréquence réelle) ──
    isotonic = {"actif": False, "n_points": 0, "n_obs": 0, "updated_at": None}
    try:
        r = await db.execute(text(
            "SELECT curve, n_obs, updated_at FROM isotonic_calibration WHERE id = 1"))
        row = r.fetchone()
        if row and row[0]:
            curve = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            n_pts = len(curve.get("x") or [])
            isotonic = {"actif": n_pts >= 2, "n_points": n_pts,
                        "n_obs": int(row[1] or 0),
                        "updated_at": row[2].isoformat() if row[2] else None}
    except Exception:
        pass

    # ── Statut calibration longshots (par bucket de cote) ──
    longshot = {"actif": False, "n_obs": 0, "updated_at": None}
    try:
        r = await db.execute(text(
            "SELECT n_obs, updated_at FROM longshot_calibration WHERE id = 1"))
        row = r.fetchone()
        if row:
            longshot = {"actif": True, "n_obs": int(row[0] or 0),
                        "updated_at": row[1].isoformat() if row[1] else None}
    except Exception:
        pass

    return {
        **al.get_state_summary(),
        "drift_detector": dd.get_drift_report(),
        "calibration": {
            "isotonique": isotonic,
            "longshots": longshot,
            "feature_weight_tilt": {
                "actif": al.n_races_processed >= TILT_MIN_RACES,
                "courses_requises": TILT_MIN_RACES,
                "courses_apprises": al.n_races_processed,
            },
        },
    }


@router.get("/calibration-quality")
async def get_calibration_quality(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Qualité de calibration de la proba de victoire (reliability + ECE + Brier),
    mesurée sur les courses terminées. Preuve honnête de la qualité des probas."""
    from ml.calibration_eval import compute_calibration_quality
    return await compute_calibration_quality(db)


@router.get("/adaptive-learning/history")
async def get_adaptive_learning_history(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Retourne l'historique d'apprentissage des dernières courses.
    """
    result = await db.execute(text("""
        SELECT
            rll.log_id,
            rll.course_id,
            c.hippodrome_nom,
            c.discipline,
            rll.brier_score,
            rll.was_surprise,
            rll.gagnant_proba_ia,
            rll.gagnant_rang_predit,
            rll.feature_autopsy,
            rll.adaptive_updates,
            rll.analyzed_at
        FROM race_learning_log rll
        LEFT JOIN courses c ON rll.course_id = c.course_id
        ORDER BY rll.analyzed_at DESC
        LIMIT :lim
    """), {"lim": limit})
    rows = result.fetchall()

    return [
        {
            "log_id": r[0],
            "course_id": r[1],
            "hippodrome": r[2],
            "discipline": r[3],
            "brier_score": round(float(r[4]), 4) if r[4] else None,
            "was_surprise": r[5],
            "gagnant_proba_ia": round(float(r[6]), 3) if r[6] else None,
            "gagnant_rang_predit": r[7],
            "signaux_manques": list((r[8] or {}).keys()),
            "temperature_update": (r[9] or {}).get("temperature"),
            "analyzed_at": r[10],
        }
        for r in rows
    ]


@router.get("/adaptive-learning/bias-matrix")
async def get_bias_matrix(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Retourne la matrice de biais par contexte (discipline × terrain × hippodrome).
    Triée par correction_factor pour voir les biais les plus forts.
    """
    result = await db.execute(text("""
        SELECT
            bias_key,
            discipline,
            terrain,
            hippodrome,
            nb_courses,
            nb_surprises,
            brier_moyen,
            correction_factor,
            favori_win_rate,
            updated_at
        FROM bias_matrix
        WHERE nb_courses >= 5
        ORDER BY ABS(correction_factor) DESC
        LIMIT 100
    """))
    rows = result.fetchall()

    return [
        {
            "contexte": r[0],
            "discipline": r[1],
            "terrain": r[2],
            "hippodrome": r[3],
            "nb_courses": r[4],
            "nb_surprises": r[5],
            "taux_surprise": round(r[5] / r[4], 3) if r[4] > 0 else 0,
            "brier_moyen": round(float(r[6]), 4) if r[6] else None,
            "correction_factor": round(float(r[7]), 4) if r[7] else 0.0,
            "favori_win_rate": round(float(r[8]), 3) if r[8] else None,
            "updated_at": r[9],
        }
        for r in rows
    ]


# ─────────────────────────────────────────────
# Scrape status + circuit breaker
# ─────────────────────────────────────────────
@router.get("/scrape-status")
async def scrape_status_enhanced(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Dernier scrape par source + état circuit breaker (redis)."""
    rows = await db.execute(text("""
        SELECT source, statut, created_at, duree_ms, erreur
        FROM (
            SELECT source, statut, created_at, duree_ms, erreur,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY created_at DESC) AS rn
            FROM scrape_log
        ) sub
        WHERE rn = 1
    """))

    # Erreurs récentes par source (circuit breaker heuristique)
    err_rows = await db.execute(text("""
        SELECT source, COUNT(*) as nb_err
        FROM scrape_log
        WHERE statut = 'erreur'
          AND created_at >= NOW() - INTERVAL '1 hour'
        GROUP BY source
    """))
    err_counts = {r.source: r.nb_err for r in err_rows.fetchall()}

    result = {}
    for r in rows:
        nb_err = err_counts.get(r.source, 0)
        circuit_state = "open" if nb_err >= 5 else ("half_open" if nb_err >= 3 else "closed")
        result[r.source] = {
            "statut": r.statut,
            "derniere_maj": r.created_at,
            "duree_ms": r.duree_ms,
            "erreur": r.erreur,
            "erreurs_1h": nb_err,
            "circuit_breaker": circuit_state,
        }
    return result


# ─────────────────────────────────────────────
# ML health
# ─────────────────────────────────────────────
@router.get("/ml-health")
async def ml_health(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Santé du modèle ML : version active, brier_ema, drift severity, n_races."""
    mv_res = await db.execute(
        select(ModelVersion).where(ModelVersion.est_actif == True)
    )
    mv = mv_res.scalar_one_or_none()
    # Métriques fiables : précision réelle observée + ROI masqué si aberrant.
    mv_metrics = await real_model_metrics(db, mv)

    al_res = await db.execute(
        select(AdaptiveLearningState).where(AdaptiveLearningState.state_id == "singleton")
    )
    al = al_res.scalar_one_or_none()

    dd_res = await db.execute(
        select(DriftDetectorState).where(DriftDetectorState.state_id == "singleton")
    )
    dd = dd_res.scalar_one_or_none()

    return {
        "model": {
            "version_num": mv.version_num if mv else None,
            "auc_roc": round(mv.auc_roc, 4) if mv else None,
            "brier_score": round(mv.brier_score, 4) if mv else None,
            "precision_top3": mv_metrics["precision_top3"],
            "roi_simule": mv_metrics["roi_simule"],
            "nb_courses_evaluees": mv_metrics["nb_courses_evaluees"],
            "nb_courses_train": mv.nb_courses_train if mv else None,
            "trained_at": mv.created_at if mv else None,
        },
        "adaptive_learning": {
            "brier_ema": round(al.brier_ema, 4) if al else None,
            "surprise_ema": round(al.surprise_ema, 4) if al else None,
            "temperature": round(al.temperature, 4) if al else None,
            "n_races": al.n_races if al else None,
            "updated_at": al.updated_at if al else None,
        },
        "drift": {
            "severity": dd.severity if dd else "unknown",
            "n_updates": dd.n_updates if dd else None,
            "last_drift_at": dd.last_drift_at if dd else None,
        },
    }


# ─────────────────────────────────────────────
# Revenue
# ─────────────────────────────────────────────
@router.get("/revenue")
async def revenue_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """MRR, ARR, churn estimé depuis la table subscriptions."""
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)
    since_12m = now - timedelta(days=365)

    # Prix par plan (centimes → euros mapping)
    PLAN_PRICE_MONTHLY = {"standard": 9.90, "expert": 19.90, "pro": 19.90, "starter": 9.90}

    active_subs = (await db.execute(
        select(Subscription).where(Subscription.statut == "active")
    )).scalars().all()

    mrr = sum(
        PLAN_PRICE_MONTHLY.get(s.plan, 0) / (12 if s.periodicite == "annual" else 1)
        for s in active_subs
    )

    # Churn : abonnements annulés dans les 30 derniers jours
    canceled_30d = (await db.execute(
        select(func.count(Subscription.sub_id)).where(
            and_(
                Subscription.statut == "canceled",
                Subscription.updated_at >= since_30d,
            )
        )
    )).scalar() or 0

    # Nouveaux abonnés ce mois
    new_subs_30d = (await db.execute(
        select(func.count(Subscription.sub_id)).where(
            Subscription.created_at >= since_30d
        )
    )).scalar() or 0

    # Abonnements actifs il y a 30j (approx)
    active_30d_ago = (await db.execute(
        select(func.count(Subscription.sub_id)).where(
            and_(
                Subscription.created_at < since_30d,
                Subscription.statut.in_(["active", "canceled"]),
            )
        )
    )).scalar() or 1

    churn_rate = round(canceled_30d / active_30d_ago * 100, 2)

    # Répartition par plan
    plan_breakdown = {}
    for s in active_subs:
        plan_breakdown[s.plan] = plan_breakdown.get(s.plan, 0) + 1

    return {
        "mrr": round(mrr, 2),
        "arr": round(mrr * 12, 2),
        "active_subscribers": len(active_subs),
        "new_subs_30d": new_subs_30d,
        "canceled_30d": canceled_30d,
        "churn_rate_pct": churn_rate,
        "plan_breakdown": plan_breakdown,
        "computed_at": now.isoformat(),
    }


# ─────────────────────────────────────────────
# Trigger scrape / invalidate cache
# ─────────────────────────────────────────────
@router.post("/trigger-scrape")
async def trigger_scrape(
    _=Depends(require_admin),
):
    """Déclenche manuellement un cycle de scraping PMU via RQ."""
    import redis as sync_redis
    from rq import Queue
    from api.config import get_settings
    settings = get_settings()
    r = sync_redis.from_url(settings.redis_url)
    q = Queue("scraper", connection=r, default_timeout=600)
    job = q.enqueue("scrapers.pmu.run_full_cycle")
    log.info("admin.trigger_scrape", job_id=job.id)
    return {"ok": True, "job_id": job.id, "queue": "scraper"}


@router.post("/invalidate-cache")
async def invalidate_cache(
    _=Depends(require_admin),
):
    """
    Supprime toutes les clés Redis des patterns :
    course_detail:*  programme:*  (et variantes préfixées)
    """
    from db.redis_client import get_redis
    redis = await get_redis()

    patterns = [
        "course_detail:*",
        "programme:*",
        "courses:*",
        "vb:*",
    ]
    total_deleted = 0
    for pattern in patterns:
        keys = []
        async for key in redis.scan_iter(match=pattern, count=200):
            keys.append(key)
        if keys:
            deleted = await redis.delete(*keys)
            total_deleted += deleted
            log.info("admin.invalidate_cache", pattern=pattern, deleted=deleted)

    return {"ok": True, "total_deleted": total_deleted, "patterns": patterns}


@router.get("/backtest")
async def run_backtest_endpoint(
    date_from: str = Query(..., description="YYYY-MM-DD inclus"),
    date_to: str = Query(..., description="YYYY-MM-DD inclus"),
    strategy: str = Query("value_bet", pattern="^(value_bet|portfolio)$"),
    kelly_fraction: float = Query(0.25, ge=0.05, le=1.0),
    ev_min: float = Query(0.0, ge=0.0),
    profil: str = Query("equilibre"),
    bankroll: float = Query(100.0, gt=0),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Backtest ROI sur les courses terminées d'une période. Gain RÉEL (paris réglés
    contre l'arrivée + rapports), jamais estimé.

    strategy : `value_bet` (gagnant simple, EV+Kelly) ou `portfolio` (moteur
    diversifié multi-scénarios : simples + combinés, chevaux variés).
    """
    from datetime import date as date_type
    from ml.backtest import run_backtest, value_bet_strategy, portfolio_strategy

    try:
        d_from = date_type.fromisoformat(date_from)
        d_to = date_type.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates invalides (YYYY-MM-DD)")

    ids_r = await db.execute(text("""
        SELECT course_id FROM courses
        WHERE statut = 'termine'
          AND date_heure::date BETWEEN :d_from AND :d_to
        ORDER BY date_heure
    """), {"d_from": d_from, "d_to": d_to})
    course_ids = [r[0] for r in ids_r.fetchall()]
    if not course_ids:
        return {"nb_courses": 0, "message": "Aucune course terminée sur la période"}

    if strategy == "portfolio":
        strat_fn, strat_kwargs = portfolio_strategy, {"profil": profil}
    else:
        strat_fn, strat_kwargs = value_bet_strategy, {"kelly_fraction": kelly_fraction, "ev_min": ev_min}

    result = await run_backtest(
        db, course_ids, strategy=strat_fn, bankroll=bankroll, strategy_kwargs=strat_kwargs,
    )
    out = result.as_dict()
    out["strategy"] = strategy
    return out


@router.get("/tune-strategy")
async def tune_strategy_endpoint(
    date_from: str = Query(..., description="YYYY-MM-DD inclus"),
    date_to: str = Query(..., description="YYYY-MM-DD inclus"),
    strategy: str = Query("value_bet", pattern="^(value_bet|portfolio)$"),
    bankroll: float = Query(100.0, gt=0),
    train_frac: float = Query(0.7, ge=0.3, le=0.9),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Optimise les paramètres de la stratégie sur le ROI backtesté, avec validation
    out-of-sample (split chronologique train/test). Signale le surapprentissage.
    """
    from datetime import date as date_type
    from ml.strategy_tuner import tune_strategy

    try:
        d_from = date_type.fromisoformat(date_from)
        d_to = date_type.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates invalides (YYYY-MM-DD)")

    ids_r = await db.execute(text("""
        SELECT course_id FROM courses
        WHERE statut = 'termine' AND date_heure::date BETWEEN :d_from AND :d_to
        ORDER BY date_heure
    """), {"d_from": d_from, "d_to": d_to})
    course_ids = [r[0] for r in ids_r.fetchall()]
    if not course_ids:
        return {"error": "Aucune course terminée sur la période"}

    return await tune_strategy(
        db, course_ids, strategy=strategy, bankroll=bankroll, train_frac=train_frac,
    )


@router.get("/causes-recurrentes")
async def causes_recurrentes(
    limite: int = Query(500, ge=10, le=5000, description="Nb de courses récentes analysées"),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Agrège les causes physiques (tags causaux) des courses récentes : quels schémas
    reviennent (favori qui faiblit, gagnant qui finit fort, train lent…) et combien
    sont liés à une surprise. Sert à voir ce que l'algo apprend.
    """
    from collections import Counter
    from db.models import RaceLearningLog

    rows = (await db.execute(
        select(RaceLearningLog)
        .order_by(desc(RaceLearningLog.analyzed_at))
        .limit(limite)
    )).scalars().all()

    total = len(rows)
    tag_counts = Counter()
    tag_surprise = Counter()
    for r in rows:
        fa = r.feature_autopsy or {}
        for t in fa.get("causal_tags", []):
            tag = t.get("tag") if isinstance(t, dict) else t
            if not tag:
                continue
            tag_counts[tag] += 1
            if r.was_surprise:
                tag_surprise[tag] += 1

    causes = [
        {
            "cause": tag,
            "occurrences": n,
            "frequence": round(n / total, 3) if total else 0.0,
            "part_surprises": round(tag_surprise[tag] / n, 3) if n else 0.0,
        }
        for tag, n in tag_counts.most_common()
    ]
    return {"courses_analysees": total, "causes": causes}


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion cotes Betfair Exchange (POST depuis GitHub Actions, hors VPS DE)
# ──────────────────────────────────────────────────────────────────────────────
def _norm_name(s: str) -> str:
    """Normalise un nom (cheval/hippodrome) : majuscules, sans accents ni ponctuation."""
    import unicodedata, re
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\([A-Z]{2,3}\)", "", s)          # retire suffixe pays "(FR)" "(IRE)"
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    return s


@router.post("/ingest-betfair")
async def ingest_betfair(payload: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Reçoit les marchés Betfair (cotes Exchange) et les mappe aux courses PMU.

    Auth : header X-Ingest-Token == settings.betfair_ingest_token.
    Mapping : hippodrome (venue ⊂ hippodrome_nom) + heure (±12 min) → course ;
    nom du cheval normalisé → participation. Écrit cote_betfair_exchange.
    Aucune donnée inventée : si pas de correspondance, on ignore (pas de fausse cote).
    """
    from api.config import get_settings
    from db.models import Participation, Cheval
    from sqlalchemy import update as sa_update
    from datetime import datetime, timezone, timedelta

    settings = get_settings()
    token = request.headers.get("X-Ingest-Token", "")
    if not settings.betfair_ingest_token or token != settings.betfair_ingest_token:
        raise HTTPException(status_code=401, detail="Token d'ingestion invalide")

    markets = payload.get("markets") or []
    matched_markets = 0
    matched_runners = 0

    for mk in markets:
        venue = _norm_name(mk.get("hippodrome") or "")
        start = mk.get("market_start_time")
        if not venue or not start:
            continue
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except Exception:
            continue
        lo = start_dt - timedelta(minutes=12)
        hi = start_dt + timedelta(minutes=12)

        # Course PMU : hippodrome contient le venue Betfair + heure proche
        crs = (await db.execute(
            select(Course).where(
                and_(Course.date_heure >= lo, Course.date_heure <= hi,
                     func.upper(func.translate(Course.hippodrome_nom, "ÉÈÊÀÂ-' ", "EEEAA   ")).like(f"%{venue}%"))
            )
        )).scalars().first()
        if not crs:
            continue

        # Partants de la course (nom normalisé → numero)
        rows = (await db.execute(
            select(Participation.participation_id, Cheval.nom)
            .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
            .where(Participation.course_id == crs.course_id)
        )).all()
        by_name = {_norm_name(nom): pid for pid, nom in rows}

        m_runner = 0
        for h in mk.get("horses", []):
            key = _norm_name(h.get("name") or "")
            pid = by_name.get(key)
            if not pid:
                continue
            # Cote retenue : back disponible, sinon dernier échangé (marché efficient)
            cote = h.get("back_price") or h.get("last_traded")
            if not cote or cote <= 1.0:
                continue
            await db.execute(
                sa_update(Participation)
                .where(Participation.participation_id == pid)
                .values(cote_betfair_exchange=float(cote))
            )
            m_runner += 1
        if m_runner:
            matched_markets += 1
            matched_runners += m_runner

    await db.commit()
    log.info("admin.ingest_betfair", markets=len(markets),
             matched_markets=matched_markets, matched_runners=matched_runners)
    return {
        "received_markets": len(markets),
        "matched_markets": matched_markets,
        "matched_runners": matched_runners,
    }
