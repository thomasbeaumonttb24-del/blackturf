"""
Admin routes — BlackTurf back-office.
Accès admin uniquement.
"""
import json
import secrets
import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, or_, case, text, delete, update

from api.model_metrics import plausible_roi, real_model_metrics
from api.routes.auth import require_admin
from db.database import get_db
from db.models import (
    User, Subscription, ModelVersion, ScrapeLog,
    Course, Prediction, ValueBet, AlerteLog,
    AdaptiveLearningState, DriftDetectorState, BankrollEntry,
    SubscriptionEvent,
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

    # Alertes en erreur = VRAIES erreurs runtime des dernières 24h : exceptions API non
    # gérées (system_errors) + scrapers échoués + échecs d'envoi d'alertes. Live.
    from services.error_monitor import error_count
    alertes_erreur = await error_count(db, hours=24)
    alertes_envoi_ko = (await db.execute(
        select(func.count(AlerteLog.alerte_id)).where(
            and_(AlerteLog.envoye == False, AlerteLog.erreur.is_not(None),
                 AlerteLog.created_at >= since_24h)
        )
    )).scalar() or 0
    alertes_erreur += int(alertes_envoi_ko)

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
# Erreurs runtime (monitoring live du back-office)
# ─────────────────────────────────────────────
@router.get("/errors")
async def list_errors(
    hours: int = Query(default=72, le=720),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Erreurs runtime récentes (exceptions API non gérées + scrapers échoués), la plus
    récente d'abord → identifier EN LIVE ce qui casse sur le site, pour correction."""
    from services.error_monitor import recent_errors, error_count
    items = await recent_errors(db, hours=hours, limit=limit)
    return {"count_24h": await error_count(db, hours=24), "errors": items}


@router.post("/errors/{error_id}/resolve")
async def resolve_error_endpoint(
    error_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Marque une erreur API comme résolue (la retire du compteur live)."""
    from services.error_monitor import resolve_error
    return {"ok": await resolve_error(db, error_id)}


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
    """Liste les utilisateurs : identité, plan, profil, Défi du mois en cours (solde en
    points, rang, paris), date création. Agrégats groupés (pas de N+1). Jamais le
    mot de passe."""
    from services import defi as _defi
    q = select(User)
    if plan:
        q = q.where(User.plan == plan)
    if search:
        like = f"%{search}%"
        q = q.where(or_(User.email.ilike(like), User.nom.ilike(like), User.prenom.ilike(like)))
    q = q.order_by(desc(User.created_at)).limit(limit).offset(offset)
    users = (await db.execute(q)).scalars().all()
    uids = [u.user_id for u in users]
    mois = _defi.mois_courant()
    defi_par_user = await _defi.resume_admin(db, uids, mois)

    # ── Statut d'abonnement RÉEL par user (dernière Subscription, pas juste "a un
    # customer_id Stripe") — un customer Stripe est créé dès le clic sur "S'abonner",
    # AVANT que le paiement soit rempli/validé : `stripe_client=True` seul ne prouve
    # rien. `abonnement_statut=None` avec `stripe_client=True` = checkout démarré et
    # jamais terminé (carte non renseignée, session Stripe abandonnée).
    sub_status: dict[str, str] = {}
    if uids:
        sub_rows = (await db.execute(
            select(Subscription.user_id, Subscription.statut)
            .where(Subscription.user_id.in_(uids))
            .order_by(Subscription.user_id, desc(Subscription.created_at))
        )).all()
        for uid, statut in sub_rows:
            sub_status.setdefault(uid, statut)

    result = []
    for u in users:
        d = defi_par_user.get(u.user_id)
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
            "abonnement_statut": sub_status.get(u.user_id),
            "created_at": u.created_at,
            "last_login": u.last_login_at,
            # Défi du mois en cours
            "defi_mois": mois,
            "defi_solde": d["solde"] if d else float(_defi.CAPITAL_MENSUEL),
            "defi_rang": d["rang"] if d else None,
            "nb_paris": d["nb_paris"] if d else 0,
            "nb_gagnes": d["nb_gagnes"] if d else 0,
            "defi_points_nets": d["points_nets"] if d else 0.0,
            "defi_points_mises": d["points_mises"] if d else 0,
            "defi_nb_en_attente": d["nb_en_attente"] if d else 0,
            "defi_dernier_pari_at": d["dernier_pari_at"] if d else None,
            "roi": d["roi"] if d else None,
        })
    return result


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Détail COMPLET d'un utilisateur pour le back-office : identité, abonnements,
    Défi du mois en cours (solde, rang, plan / perso) et HISTORIQUE intégral de ses
    paris du défi (tous les mois), avec la répartition par type de pari."""
    from db.models import DefiPari
    from services import defi as _defi
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    subs = (await db.execute(
        select(Subscription).where(Subscription.user_id == user_id).order_by(desc(Subscription.created_at))
    )).scalars().all()

    mois = _defi.mois_courant()
    resume = await _defi.resume_joueur(db, user_id, mois)
    resume.pop("paris")
    rang = (await _defi.resume_admin(db, [user_id], mois)).get(user_id, {}).get("rang")

    rows = (await db.execute(
        select(DefiPari, Course.hippodrome_nom, Course.numero_reunion, Course.numero,
               Course.date_heure)
        .outerjoin(Course, Course.course_id == DefiPari.course_id)
        .where(DefiPari.user_id == user_id)
        .order_by(desc(DefiPari.engage_at))
        .limit(500)
    )).all()
    bets = []
    for p, hippo, n_r, n_c, dh in rows:
        bets.append({
            "pari_id": p.pari_id,
            "mois": p.mois,
            "engage_at": p.engage_at,
            "type_pari": p.type_pari,
            "chevaux": list(p.chevaux),
            "points": p.points,
            "origine": p.origine,
            "statut": p.statut,
            "rapport": p.rapport,
            "points_retour": p.points_retour,
            "course_id": p.course_id,
            "course_code": f"R{n_r}C{n_c}" if n_r and n_c else None,
            "hippodrome": hippo,
            "course_date": dh,
        })
    nb_total = (await db.execute(
        select(func.count(DefiPari.pari_id)).where(DefiPari.user_id == user_id))).scalar() or 0

    # Répartition par type (tous les mois, paris réglés gagnés/perdus seulement).
    type_rows = (await db.execute(
        select(
            DefiPari.type_pari,
            func.count(DefiPari.pari_id),
            func.coalesce(func.sum(DefiPari.points), 0),
            func.coalesce(func.sum(func.coalesce(DefiPari.points_retour, 0) - DefiPari.points), 0.0),
            func.sum(case((DefiPari.statut == "gagne", 1), else_=0)),
        ).where(DefiPari.user_id == user_id, DefiPari.statut.in_(("gagne", "perd")))
        .group_by(DefiPari.type_pari)
        .order_by(desc(func.count(DefiPari.pari_id)))
    )).all()
    par_type = [
        {"type_pari": t, "nb": int(n), "points": int(m), "net": round(float(g), 1),
         "nb_gagnes": int(win or 0),
         "roi": round(float(g) / float(m) * 100, 1) if m else None}
        for t, n, m, g, win in type_rows
    ]

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
            "email_verified": user.email_verified,
            "auth_method": "google" if user.google_id else "email",
            "stripe_client": bool(user.stripe_customer_id),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login": user.last_login_at,
        },
        "defi": {"mois": mois, "rang": rang, **resume},
        "par_type": par_type,
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
        "nb_bets": nb_total,
        "bets": bets,
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
    if not new_plan or new_plan not in {"free", "standard", "expert", "starter"}:
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
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    # is_admin VOLONTAIREMENT EXCLU : pas d'escalade de privilège via l'API (un admin
    # ne peut pas se/ promouvoir admin). La promotion admin se fait en SQL contrôlé.
    allowed = {"plan", "is_active", "profil_risque"}
    # Garde anti auto-verrouillage : un admin ne peut pas se désactiver lui-même.
    if user_id == admin.user_id and body.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Auto-désactivation interdite")
    for k, v in body.items():
        if k in allowed:
            setattr(user, k, v)
    await db.commit()
    log.info("admin.update_user", admin_id=admin.user_id, user_id=user_id,
             changes={k: body[k] for k in body if k in allowed})
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Supprime définitivement un compte et ce qui n'appartient qu'à lui.

    Sert au ménage (inscriptions bidon jamais confirmées) et au droit à
    l'effacement. Trois refus, parce qu'ils coûtent plus cher que le ménage :

    - son propre compte : l'admin se fermerait la porte de la console ;
    - un autre compte admin : on ne retire pas un accès de supervision d'un clic
      dans un tableau — il faut d'abord lui ôter le rôle ;
    - un compte dont l'abonnement est encore vivant côté Stripe : la facturation
      continuerait sans personne en face. Résiliation d'abord.

    L'historique comptable (`subscription_events`) est CONSERVÉ, détaché du
    compte (`user_id` à NULL) : la ligne y porte déjà l'e-mail en clair, elle
    reste lisible sans l'utilisateur — c'est ce que dit le modèle, et ce
    qu'impose la conservation des pièces comptables. Le client Stripe, lui,
    survit chez Stripe : rien ici ne le touche.
    """
    from api.routes.stripe_routes import STATUTS_VIVANTS
    from db.models import Bankroll, DefiPari, DefiRecompense, Recommandation, Strategie

    user = (await db.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Auto-suppression interdite")
    if user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Compte admin : retirez-lui d'abord le rôle avant de le supprimer.")

    vivant = (await db.execute(
        select(Subscription).where(and_(
            Subscription.user_id == user_id,
            Subscription.statut.in_(STATUTS_VIVANTS),
        ))
    )).scalars().first()
    if vivant is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Abonnement encore actif ({vivant.statut}) : résiliez-le dans Stripe "
                   "avant de supprimer le compte, sinon la facturation continue.")

    email = user.email
    supprime: dict[str, int] = {}

    # L'ordre suit les clés étrangères : un enfant avant son parent, sinon la
    # base refuse la suppression et la transaction entière repart en arrière.
    supprime["paris"] = (await db.execute(
        delete(BankrollEntry).where(BankrollEntry.user_id == user_id))).rowcount or 0
    # Les paris du défi sont immuables en base (trigger 0055) : seule une
    # suppression de compte, déclarée pour cette transaction, peut les effacer.
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT set_config('blackturf.suppression_compte', 'on', true)"))
    supprime["defi_paris"] = (await db.execute(
        delete(DefiPari).where(DefiPari.user_id == user_id))).rowcount or 0
    supprime["defi_recompenses"] = (await db.execute(
        delete(DefiRecompense).where(DefiRecompense.user_id == user_id))).rowcount or 0
    # Un pari d'un AUTRE compte pourrait pointer une reco de celui-ci : on coupe
    # le lien plutôt que de faire échouer la suppression sur une contrainte.
    await db.execute(
        update(BankrollEntry)
        .where(BankrollEntry.reco_id.in_(
            select(Recommandation.reco_id).where(Recommandation.user_id == user_id)))
        .values(reco_id=None))
    supprime["recommandations"] = (await db.execute(
        delete(Recommandation).where(Recommandation.user_id == user_id))).rowcount or 0
    supprime["portefeuilles"] = (await db.execute(
        delete(Bankroll).where(Bankroll.user_id == user_id))).rowcount or 0
    supprime["strategies"] = (await db.execute(
        delete(Strategie).where(Strategie.user_id == user_id))).rowcount or 0
    supprime["alertes"] = (await db.execute(
        delete(AlerteLog).where(AlerteLog.user_id == user_id))).rowcount or 0
    supprime["evenements_abonnement_detaches"] = (await db.execute(
        update(SubscriptionEvent)
        .where(SubscriptionEvent.user_id == user_id)
        .values(user_id=None))).rowcount or 0
    supprime["abonnements"] = (await db.execute(
        delete(Subscription).where(Subscription.user_id == user_id))).rowcount or 0

    await db.delete(user)
    await db.commit()

    log.warning("admin.delete_user", admin_id=admin.user_id, user_id=user_id,
                email=email, supprime=supprime)
    return {"ok": True, "email": email, "supprime": supprime}


@router.get("/users-export")
async def export_users_csv(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Export CSV de TOUS les comptes + leur Défi du mois en cours."""
    import csv as _csv
    import io
    from fastapi.responses import StreamingResponse
    from services import defi as _defi

    users = (await db.execute(select(User).order_by(desc(User.created_at)).limit(5000))).scalars().all()
    uids = [u.user_id for u in users]
    mois = _defi.mois_courant()
    defi_par_user = await _defi.resume_admin(db, uids, mois)

    sub_status: dict[str, str] = {}
    if uids:
        for uid, statut in (await db.execute(
            select(Subscription.user_id, Subscription.statut)
            .where(Subscription.user_id.in_(uids))
            .order_by(Subscription.user_id, desc(Subscription.created_at))
        )).all():
            sub_status.setdefault(uid, statut)

    out = io.StringIO()
    w = _csv.writer(out)
    w.writerow(["Email", "Nom", "Prenom", "Plan", "Profil", "Auth", "Email verifie", "Actif",
                "Admin", "Inscrit le", "Derniere connexion", "Client Stripe", "Statut abonnement",
                f"Defi {mois} solde (pts)", "Rang", "Paris", "Gagnes", "ROI %"])
    for u in users:
        d = defi_par_user.get(u.user_id) or {}
        w.writerow([u.email, u.nom or "", u.prenom or "", u.plan, u.profil_risque,
                    "google" if u.google_id else "email", "oui" if u.email_verified else "non",
                    "oui" if u.is_active else "non", "oui" if u.is_admin else "non",
                    u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
                    u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "jamais",
                    "oui" if u.stripe_customer_id else "non",
                    sub_status.get(u.user_id) or ("checkout abandonne" if u.stripe_customer_id else ""),
                    d.get("solde", _defi.CAPITAL_MENSUEL), d.get("rang") or "",
                    d.get("nb_paris", 0), d.get("nb_gagnes", 0),
                    "" if d.get("roi") is None else d["roi"]])
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
        # Modèle ACTIF → ROI RÉEL observé (pronos réglés) = le seul honnête. Pour les
        # archivés, la sim de train est masquée si hors plage plausible (in-sample).
        if m.est_actif and active_real.get("roi_reel") is not None:
            return round(float(active_real["roi_reel"]), 4)
        roi = plausible_roi(m.roi_simule)
        return round(roi, 4) if roi is not None else None

    # Top-3 RÉEL observé (race_learning_log) pour le modèle ACTIF : les métadonnées de
    # train stockent souvent 0 (top-3 non calculé sur le holdout avant le fix). L'observé
    # n'est attribuable qu'au modèle actif (race_learning_log n'a pas de version_id) → pour
    # les versions archivées on renvoie la valeur stockée si >0, sinon null (affiché « — »,
    # jamais un « 0.0% » trompeur).
    active_mv = next((m for m in rows if m.est_actif), None)
    active_real = await real_model_metrics(db, active_mv) if active_mv else {}

    def _top3(m: ModelVersion) -> float | None:
        if m.est_actif and active_real.get("precision_top3") is not None:
            return round(float(active_real["precision_top3"]), 4)
        return round(m.precision_top3, 4) if (m.precision_top3 or 0) > 0 else None

    return [
        {
            "version_id": m.version_id,
            "version_num": m.version_num,
            "auc_roc": round(m.auc_roc, 4),
            "brier_score": round(m.brier_score, 4),
            "precision_top3": _top3(m),
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
        # Un retour arrière RETIRE le modèle abandonné : marqué `est_rollback`, il
        # cesse de servir de prédécesseur et de record au rapport du matin. Faute
        # de cette marque, v545 (fuite ELO, retirée le 25/09) a été présentée le
        # 26/09 comme le record que v546 n'atteignait pas.
        if m.est_actif and m.version_num > version_num:
            m.est_rollback = True
        if m.version_num == version_num:
            m.est_rollback = False
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

    L'état est RELU EN BASE à chaque appel. `get_adaptive_learning()` nu rendait
    le singleton du process API, chargé une seule fois au démarrage
    (`api/main.py`, lifespan) : c'est le worker RQ qui fait avancer cet état, à
    chaque course analysée. Une API restée en service plusieurs jours servait donc
    la température, le Brier lissé, les poids de features et le rapport de dérive
    du dernier redémarrage, pendant que la page de supervision les rafraîchissait
    toutes les 30 s — elle avait l'air en direct sans l'être.

    Le même défaut avait déjà été diagnostiqué et corrigé pour le contrôle horaire
    de dérive (cf. `services/jobs.job_drift_check`, « recharger l'état depuis la
    DB à chaque exécution — pas un init une fois au boot ») ; cet endpoint n'avait
    pas été traité.

    La relecture se fait sur des instances DÉTACHÉES, pas via
    `initialize_adaptive_learning()` : celui-ci recharge le singleton PARTAGÉ, donc
    celui que `predict_course` consulte pour la température et les poids. Rafraîchir
    l'inférence toutes les trente secondes parce qu'un admin regarde une page
    changerait les probabilités servies aux abonnés — un effet de bord qu'une vue
    de supervision n'a pas à provoquer. Lire est ici en lecture seule, au sens
    fort.

    Ce n'est pas un chemin chaud : un appel toutes les 30 s, deux lectures de
    ligne unique. Le repli sur le singleton en mémoire est conservé — une lecture
    impossible ne doit pas vider la page de supervision, seulement la faire
    vieillir comme avant.
    """
    from ml.adaptive_learning import AdaptiveLearning, TILT_MIN_RACES
    from ml.drift_detector import DriftDetector

    al = get_adaptive_learning()
    try:
        _al_lu = AdaptiveLearning()
        await _al_lu.load_state(db)
        # `load_state` laisse l'instance à ses valeurs par défaut quand la table est
        # vide. Un état neutre complet ne remplace jamais un état en mémoire qui,
        # lui, a vu passer des courses : c'est exactement la confusion « valeur par
        # défaut prise pour une mesure » que la page s'interdit.
        if _al_lu.n_races_processed > 0:
            al = _al_lu
    except Exception as e:
        await db.rollback()
        log.warning("admin.al_state.rechargement_impossible", err=str(e)[:160])

    try:
        dd = get_drift_detector()
    except RuntimeError:
        # Le singleton n'existe que si le démarrage l'a initialisé. Sur un process
        # où ça n'a pas eu lieu, une instance détachée vaut mieux qu'une 500.
        dd = DriftDetector()
    try:
        _dd_lu = DriftDetector()
        if await _dd_lu.load_state(db):
            dd = _dd_lu
    except Exception as e:
        await db.rollback()
        log.warning("admin.drift_state.rechargement_impossible", err=str(e)[:160])

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


@router.get("/learning-signals")
async def get_learning_signals(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Santé de l'apprentissage RÉELLE (admin) — preuve live que l'algo apprend :
      - poids appris PAR PROFIL × type de pari (profil_run_log réglés)
      - ROI réel par signal qualitatif (signal_performance)
      - edge hors-échantillon (edge_monitor : le filtre conviction bat-il le marché ?)
    100% mesuré, aucune valeur inventée. Rien d'appris encore → listes vides."""
    out: dict = {"profil_weights": None, "signaux": [], "edge": None}

    # 1. Poids par profil (pronos émis réglés)
    try:
        from ml.profil_learning import load_profil_weights
        out["profil_weights"] = await load_profil_weights(db)
    except Exception as e:
        log.warning("admin.learning_signals.profil_skip", err=str(e)[:120])

    # 2. ROI par signal (global) — top gagnants + top pièges
    try:
        from ml.signal_performance import load_signal_performance
        perf = await load_signal_performance(db)
        signals = (perf or {}).get("signals") or {}
        rows = [
            {"signal": k, "n": v.get("n"), "win_rate": v.get("win_rate"),
             "roi": v.get("roi"), "multiplier": v.get("multiplier")}
            for k, v in signals.items() if (v.get("n") or 0) >= 30
        ]
        rows.sort(key=lambda x: (x["roi"] if x["roi"] is not None else 0), reverse=True)
        out["signaux"] = rows
    except Exception as e:
        log.warning("admin.learning_signals.signal_skip", err=str(e)[:120])

    # 3. Edge monitor (dernière mesure hors-échantillon — data JSONB)
    try:
        r = (await db.execute(text("""
            SELECT (data->>'n_test')::int, (data->>'win_filt')::float, (data->>'win_base')::float,
                   (data->>'roi_cap')::float, (data->>'edge_ok')::bool, created_at,
                   (data->>'n_filt')::int, (data->>'enough_filt')::bool
            FROM edge_monitor ORDER BY created_at DESC LIMIT 1
        """))).first()
        if r:
            out["edge"] = {
                "n_test": r[0], "win_filtre": r[1], "win_baseline": r[2],
                "roi_plafonne": r[3], "edge_ok": r[4],
                "mesure_le": r[5].isoformat() if r[5] else None,
                # nb de paris filtrés + si l'échantillon est suffisant pour conclure
                "n_filt": r[6], "enough_filt": r[7],
            }
    except Exception as e:
        await db.rollback()
        log.warning("admin.learning_signals.edge_skip", err=str(e)[:120])

    return out


@router.get("/learning-convergence")
async def get_learning_convergence(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """CONVERGENCE de l'apprentissage — preuve VISUELLE que l'algo s'améliore :
      - par semaine : précision top-3 (monte = mieux) + erreur Brier (baisse = mieux)
      - edge hors-échantillon dans le temps (le filtre conviction bat-il le marché ?)
      - gain net CUMULÉ par profil (la courbe qui doit monter)
    100% mesuré sur résultats réels. Compréhensible : tout est expliqué côté front."""
    out: dict = {"par_semaine": [], "edge_histo": [], "profil_cumul": {}}

    # 1. Précision + Brier par semaine (race_learning_log)
    try:
        rows = (await db.execute(text("""
            SELECT to_char(date_trunc('week', analyzed_at), 'DD/MM') AS sem,
                   count(*) AS n,
                   round(avg(brier_score)::numeric, 3) AS brier,
                   round((count(*) FILTER (WHERE gagnant_rang_predit <= 3)::numeric
                          / NULLIF(count(*), 0)) * 100, 1) AS prec_top3,
                   round((count(*) FILTER (WHERE gagnant_rang_predit = 1)::numeric
                          / NULLIF(count(*), 0)) * 100, 1) AS prec_top1
            FROM race_learning_log rll
            WHERE analyzed_at > now() - interval '12 weeks'
              AND gagnant_rang_predit IS NOT NULL
              -- INTÉGRITÉ : que les courses dont le prono existait AVANT le départ
              -- (exclut les entrées backfillées qui fausseraient la précision « réelle »).
              AND EXISTS (
                  SELECT 1 FROM predictions pr
                  JOIN courses c ON c.course_id = pr.course_id
                  WHERE pr.course_id = rll.course_id
                    AND c.date_heure IS NOT NULL AND pr.created_at IS NOT NULL
                    AND pr.created_at < c.date_heure
              )
            GROUP BY date_trunc('week', analyzed_at)
            ORDER BY date_trunc('week', analyzed_at)
        """))).all()
        out["par_semaine"] = [
            {"semaine": r[0], "n": r[1], "brier": float(r[2]) if r[2] is not None else None,
             "precision_top3": float(r[3]) if r[3] is not None else None,
             "precision_top1": float(r[4]) if r[4] is not None else None}
            for r in rows
        ]
    except Exception as e:
        await db.rollback()
        log.warning("admin.convergence.week_skip", err=str(e)[:120])

    # 2. Edge hors-échantillon dans le temps (edge_monitor — tout dans data JSONB)
    try:
        rows = (await db.execute(text("""
            SELECT to_char(created_at, 'DD/MM') AS d,
                   (data->>'win_filt')::float, (data->>'win_base')::float,
                   (data->>'roi_cap')::float, (data->>'edge_ok')::bool
            FROM edge_monitor ORDER BY created_at DESC LIMIT 20
        """))).all()
        out["edge_histo"] = [
            {"date": r[0], "win_filtre": round(float(r[1]) * 100, 1) if r[1] is not None else None,
             "win_baseline": round(float(r[2]) * 100, 1) if r[2] is not None else None,
             "roi": round(float(r[3]), 1) if r[3] is not None else None, "edge_ok": r[4]}
            for r in reversed(rows)
        ]
    except Exception as e:
        await db.rollback()
        log.warning("admin.convergence.edge_skip", err=str(e)[:120])

    # 3. Gain net CUMULÉ par profil dans le temps (profil_run_log réglés)
    try:
        # On étale sur la DATE DE COURSE (date_heure), pas settled_at (= maintenant
        # pour les runs backfillés) → courbe d'évolution réelle sur l'historique.
        rows = (await db.execute(text("""
            SELECT r.profil,
                   date_trunc('day', c.date_heure) AS j,
                   to_char(date_trunc('day', c.date_heure), 'DD/MM') AS jour,
                   sum((r.resultat->>'net')::numeric) AS net_jour
            FROM profil_run_log r
            JOIN courses c ON c.course_id = r.course_id
            WHERE r.statut = 'settled' AND r.resultat IS NOT NULL AND c.date_heure IS NOT NULL
              -- INTÉGRITÉ (cf. palmarès / oos_weights) : que les pronos émis AVANT
              -- le départ et non-backfillés → courbe cohérente avec les poids honnêtes
              -- (sinon la courbe gonfle des runs reconstruits a posteriori).
              AND r.created_at < c.date_heure
              AND COALESCE(r.meta->>'backfill', '') <> 'true'
            GROUP BY r.profil, date_trunc('day', c.date_heure)
            ORDER BY r.profil, date_trunc('day', c.date_heure)
        """))).all()
        LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
        cumul: dict = {}
        running: dict = {}
        for profil, _j, jour, net in rows:
            running[profil] = running.get(profil, 0.0) + float(net or 0)
            cumul.setdefault(profil, []).append({"jour": jour, "cumul": round(running[profil], 2)})
        out["profil_cumul"] = {LBL.get(k, k): v for k, v in cumul.items()}
    except Exception as e:
        await db.rollback()
        log.warning("admin.convergence.profil_skip", err=str(e)[:120])

    # 4. DERNIÈRES VICTOIRES — et leur DÉNOMINATEUR.
    #
    # La liste ne retient que les courses où un plan a fini net positif. C'est vrai,
    # mesuré sur les rapports PMU, et ça reste une sélection par le résultat : sur
    # une console dont le ROI global est négatif, un mur de gains est une vitrine,
    # pas une supervision. La liste est conservée — elle sert à ouvrir une course et
    # à comprendre ce qui a marché — mais elle est désormais accompagnée du taux
    # dont elle est extraite : X courses gagnantes sur Y réglées, et le net total.
    #
    # Le comptage porte sur les COURSES distinctes, jamais sur les paris : le même
    # plan est ré-émis à chaque mouvement de cote, compter les lignes gonflerait le
    # dénominateur autant que le numérateur mais pas dans le même rapport.
    #
    # Fenêtre bornée à 90 jours : la requête d'origine balayait tout
    # `profil_run_log` réglé depuis l'origine, puis bouclait en Python — un coût qui
    # croissait sans fin sur un endpoint rafraîchi toutes les deux minutes.
    out["victoires"] = []
    out["victoires_resume"] = None
    try:
        rows = (await db.execute(text("""
            SELECT c.course_id, c.hippodrome_nom, c.date_heure, c.numero_reunion, c.numero,
                   r.profil, (r.resultat->>'net')::numeric AS net
            FROM profil_run_log r
            JOIN courses c ON c.course_id = r.course_id
            WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
              -- Mêmes gardes d'intégrité : conseils réellement émis avant le départ.
              AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure
              AND COALESCE(r.meta->>'backfill', '') <> 'true'
              AND c.date_heure >= now() - interval '90 days'
            ORDER BY c.date_heure DESC, net DESC
        """))).all()
        LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
        # Meilleur profil par course, gagnantes ET perdantes : c'est ce qui permet
        # de rendre le dénominateur, impossible à produire depuis la seule liste
        # filtrée sur `net > 0`.
        best: dict = {}
        for cid, hippo, dh, n_r, n_c, profil, net in rows:
            cur = best.get(cid)
            netf = float(net or 0)
            if cur is None or netf > cur["net"]:
                code = f"R{n_r}C{n_c}" if n_r and n_c else None
                if not code:
                    import re as _re
                    m = _re.search(r"(R\d+C\d+)", str(cid))
                    code = m.group(1) if m else None
                best[cid] = {"course_id": cid, "code": code, "hippodrome": hippo,
                             "date": dh.isoformat() if dh else None,
                             "profil": LBL.get(profil, profil), "net": round(netf, 2)}
        gagnantes = [v for v in best.values() if v["net"] > 0]
        out["victoires"] = sorted(
            gagnantes, key=lambda x: x["date"] or "", reverse=True)[:25]
        n_courses = len(best)
        out["victoires_resume"] = {
            "fenetre_jours": 90,
            "n_courses_reglees": n_courses,
            "n_courses_gagnantes": len(gagnantes),
            "taux_courses_gagnantes_pct": (
                round(len(gagnantes) * 100.0 / n_courses, 1) if n_courses else None),
            # Somme des MEILLEURS profils par course : ce n'est pas le net du
            # portefeuille (qui vit dans /supervision/rentabilite), c'est le net de
            # la population dont la liste ci-dessus est extraite. Nommé comme tel.
            "net_meilleur_profil": round(sum(v["net"] for v in best.values()), 2),
        }
    except Exception as e:
        await db.rollback()
        log.warning("admin.convergence.victoires_skip", err=str(e)[:120])

    return out


@router.get("/adaptive-learning/history")
async def get_adaptive_learning_history(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Historique d'apprentissage des dernières courses analysées.

    ``gagnant_rang_predit`` vaut 99 quand le gagnant réel ne figurait PAS dans le
    top-3 du modèle (sentinelle posée par ``post_race_analyzer``) : ce n'est pas
    une 99e place, et l'affichage doit le traduire, jamais le montrer tel quel.

    ``adaptive_updates`` n'a jamais été alimenté (0 ligne sur 3 692 en
    production) : la colonne « Δ température » qu'il servait à remplir est donc
    retirée plutôt que d'afficher un tiret permanent. ``nb_partants`` la
    remplace — un Brier de 0,30 dans un champ de 16 ne vaut pas le même dans un
    champ de 6.
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
            rll.nb_partants,
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
            "hors_top3": r[7] == 99,
            "signaux_manques": list((r[8] or {}).keys()),
            "nb_partants": r[9],
            "analyzed_at": r[10],
        }
        for r in rows
    ]


@router.get("/adaptive-learning/bias-matrix")
async def get_bias_matrix(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Matrice de biais par contexte (discipline × terrain × hippodrome).

    ``correction_factor`` est BINAIRE, pas continu : ``post_race_analyzer`` écrit
    -0,05 quand un contexte dépasse 55 % de surprises sur au moins 8 courses,
    0,0 sinon. Il n'est jamais positif — l'afficher comme un curseur à deux sens
    laisserait croire l'inverse.

    Il n'est par ailleurs LU à l'inférence que si ``nb_courses >= 8``
    (``get_bias_correction``) : ``correction_appliquee`` dit lequel des contextes
    listés pèse réellement sur un pronostic aujourd'hui.
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
            # Seuil de lecture à l'inférence (get_bias_correction) : sous 8
            # courses, la correction est stockée mais jamais appliquée.
            "correction_appliquee": bool(r[7]) and (r[4] or 0) >= 8,
            "seuil_courses": 8,
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

    # Prix mensuels RÉELS. Les valeurs précédentes (9,90 / 19,90) ne
    # correspondaient à aucun price Stripe : la production facture 12,00 € et
    # 19,00 €, le MRR affiché était donc faux d'environ 20 % (2026-08-20).
    PLAN_PRICE_MONTHLY = {k: v / 100 for k, v in PRIX_MENSUEL_CENTS.items()}

    # `essai_sans_carte` est volontairement exclu : un essai bloqué ne rapporte rien.
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
# Abonnements — suivi des essais et des mouvements
# ─────────────────────────────────────────────
# Prix mensuels réels, en CENTIMES, tels que Stripe les facture. Ne sert que de
# repli : le montant exact vient du journal, qui le tient du price Stripe. La
# table de `/admin/revenue` annonçait 9,90 € et 19,90 € alors que les prix en
# production sont 12,00 € et 19,00 € — le MRR était faux de ~20 %.
PRIX_MENSUEL_CENTS = {"standard": 1200, "expert": 1900, "starter": 1200, "pro": 1900}

# Doit rester aligné sur `stripe_routes.STATUTS_ACCES` / `STATUT_SANS_CARTE`.
# `past_due` en est sorti le 2026-08-27 : un paiement en échec ne donne plus accès
# au produit, il ne doit donc plus être compté comme un abonné servi (le MRR le
# comptait comme encaissé alors qu'il ne l'était pas).
STATUTS_ACCES_ADMIN = ("active", "cancel_at_period_end")
STATUT_SANS_CARTE_ADMIN = "essai_sans_carte"


@router.get("/abonnements")
async def abonnements(
    limite_mouvements: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Suivi complet des abonnements : qui est en essai, jusqu'à quand, avec ou
    sans carte, et le journal de tous les mouvements.

    `subscriptions` ne porte que l'état courant : il ne dit pas si un client a
    résilié AVANT la fin de son essai. C'est `subscription_events` (journal
    append-only, migration 0037) qui répond, et les deux sont renvoyés ensemble.
    """
    now = datetime.now(timezone.utc)
    depuis_30j = now - timedelta(days=30)

    vivants = ("active", "trialing", "past_due", "cancel_at_period_end",
               STATUT_SANS_CARTE_ADMIN)
    lignes = (await db.execute(
        select(Subscription, User)
        .join(User, User.user_id == Subscription.user_id)
        .where(Subscription.statut.in_(vivants))
        .order_by(desc(Subscription.created_at))
    )).all()

    # Dernier montant connu par abonnement : le journal tient le prix RÉEL lu sur
    # le price Stripe, plus fiable qu'une table codée en dur.
    montants: dict[str, int] = {}
    for sid, montant in (await db.execute(
        select(SubscriptionEvent.stripe_subscription_id,
               func.max(SubscriptionEvent.montant_cents))
        .where(SubscriptionEvent.montant_cents.isnot(None))
        .group_by(SubscriptionEvent.stripe_subscription_id)
    )).all():
        if sid:
            montants[sid] = montant

    abonnes = []
    mrr_cents = 0
    en_essai = essai_sans_carte = payants = fin_essai_3j = 0
    # Répartition par COMPTE (un compte peut porter deux lignes d'abonnement).
    ids_payants: dict[str, str] = {}
    ids_essai: dict[str, str] = {}
    for sub, user in lignes:
        essai_fin = sub.essai_fin
        if essai_fin is not None and essai_fin.tzinfo is None:
            essai_fin = essai_fin.replace(tzinfo=timezone.utc)
        en_cours_dessai = essai_fin is not None and essai_fin > now
        jours_restants = round((essai_fin - now).total_seconds() / 86400, 1) if en_cours_dessai else None
        sans_carte = sub.statut == STATUT_SANS_CARTE_ADMIN
        montant = montants.get(sub.stripe_subscription_id) or PRIX_MENSUEL_CENTS.get(sub.plan, 0)

        if sans_carte:
            essai_sans_carte += 1
            ids_essai.setdefault(user.user_id, sub.plan)
        elif en_cours_dessai:
            en_essai += 1
            ids_essai.setdefault(user.user_id, sub.plan)
        elif sub.statut in STATUTS_ACCES_ADMIN:
            payants += 1
            ids_payants.setdefault(user.user_id, sub.plan)
            # Un abonnement annuel ne rapporte pas douze fois son prix chaque mois.
            mrr_cents += montant / 12 if sub.periodicite == "annual" else montant
        if en_cours_dessai and jours_restants is not None and jours_restants <= 3:
            fin_essai_3j += 1

        abonnes.append({
            "user_id": user.user_id,
            "email": user.email,
            "plan": sub.plan,
            "plan_compte": user.plan,
            "periodicite": sub.periodicite,
            "statut": sub.statut,
            "carte_enregistree": not sans_carte,
            "acces_ouvert": sub.statut in STATUTS_ACCES_ADMIN,
            "en_essai": en_cours_dessai,
            "essai_fin": essai_fin,
            "jours_essai_restants": jours_restants,
            "periode_fin": sub.periode_fin,
            "montant_cents": montant,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "depuis": sub.created_at,
        })

    mouvements = (await db.execute(
        select(SubscriptionEvent)
        .order_by(desc(SubscriptionEvent.created_at))
        .limit(limite_mouvements)
    )).scalars().all()

    # Résiliations et essais perdus des 30 derniers jours : deux choses
    # différentes, que confondre fausserait le churn. Un essai qui meurt faute de
    # carte n'est pas un client qui part, c'est un prospect qui n'a jamais converti.
    async def _compte(type_: str) -> int:
        return (await db.execute(
            select(func.count(SubscriptionEvent.event_id)).where(
                and_(SubscriptionEvent.type == type_,
                     SubscriptionEvent.created_at >= depuis_30j)
            )
        )).scalar() or 0

    resiliations_30j = await _compte("resilie")
    essais_perdus_30j = await _compte("essai_termine_sans_carte")
    essais_ouverts_30j = await _compte("essai_ouvert") + await _compte("essai_sans_carte")
    resiliations_pendant_essai_30j = (await db.execute(
        select(func.count(SubscriptionEvent.event_id)).where(
            and_(SubscriptionEvent.type.in_(("resilie", "resiliation_demandee")),
                 SubscriptionEvent.pendant_essai.is_(True),
                 SubscriptionEvent.created_at >= depuis_30j)
        )
    )).scalar() or 0

    # ── Répartition de TOUS les comptes, chacun rangé dans UNE seule case ──
    # Ordre de priorité : payant > essai > offert > gratuit. « Offert » = un plan
    # payant accordé à la main (amis, tests) sans aucun abonnement Stripe vivant.
    # Le compte d'administration n'est compté nulle part : c'est un outil, pas un client.
    def _formule(plan: Optional[str]) -> str:
        return {"starter": "standard", "pro": "expert"}.get(plan or "", plan or "standard")

    ids_abonnes = {user.user_id for _, user in lignes}
    par_formule = {f: {"payants": 0, "essais": 0, "offerts": 0} for f in ("standard", "expert")}
    repartition = {"comptes": 0, "payants": 0, "essais": 0, "offerts": 0, "gratuits": 0}
    offerts = []
    for u in (await db.execute(
        select(User).where(User.is_admin.is_not(True)).order_by(desc(User.created_at))
    )).scalars().all():
        repartition["comptes"] += 1
        if u.user_id in ids_payants:
            case_, formule = "payants", _formule(ids_payants[u.user_id])
        elif u.user_id in ids_essai:
            case_, formule = "essais", _formule(ids_essai[u.user_id])
        elif u.plan in PRIX_MENSUEL_CENTS and u.user_id not in ids_abonnes:
            case_, formule = "offerts", _formule(u.plan)
            offerts.append({
                "user_id": u.user_id, "email": u.email, "plan": formule,
                "created_at": u.created_at, "last_login": u.last_login_at,
            })
        else:
            case_, formule = "gratuits", None
        repartition[case_] += 1
        if formule in par_formule:
            par_formule[formule][case_] += 1
    repartition["par_formule"] = par_formule

    return {
        "repartition": repartition,
        "offerts": offerts,
        "suivi": await _suivi_essais(db, now),
        "resume": {
            "en_essai_avec_carte": en_essai,
            "en_essai_sans_carte": essai_sans_carte,
            "abonnes_payants": payants,
            "fin_essai_sous_3j": fin_essai_3j,
            "mrr": round(mrr_cents / 100, 2),
            "arr": round(mrr_cents * 12 / 100, 2),
            "essais_ouverts_30j": essais_ouverts_30j,
            "essais_perdus_30j": essais_perdus_30j,
            "resiliations_30j": resiliations_30j,
            "resiliations_pendant_essai_30j": resiliations_pendant_essai_30j,
        },
        "abonnes": abonnes,
        "mouvements": [
            {
                "event_id": m.event_id,
                "type": m.type,
                "email": m.email,
                "plan": m.plan,
                "plan_precedent": m.plan_precedent,
                "montant_cents": m.montant_cents,
                "essai_fin": m.essai_fin,
                "pendant_essai": m.pendant_essai,
                "created_at": m.created_at,
            }
            for m in mouvements
        ],
        "computed_at": now.isoformat(),
    }


# ─────────────────────────────────────────────
# Revenus — l'argent RÉELLEMENT encaissé, mois par mois, et ce qui arrive
# ─────────────────────────────────────────────
# Demande de l'exploitant (2026-09-25) : le MRR dit ce que les abonnements
# DEVRAIENT rapporter ; il ne dit pas ce qui est entré en caisse ce mois-ci, ni
# quand tombe le prochain prélèvement de chaque abonné.
#
# Source unique : `subscription_events` de type `paiement_recu`, écrit à CHAQUE
# `invoice.payment_succeeded` avec `amount_paid` (cf. `stripe_routes`). C'est
# de l'argent constaté, pas une estimation. Les factures à 0 € (ouverture d'un
# essai) n'y sont jamais écrites.
#
# L'échéancier, lui, est une PRÉVISION : il se lit sur `subscriptions.periode_fin`
# (ou `essai_fin` pour un essai avec carte) et il est étiqueté comme tel.
FUSEAU_REVENUS = "Europe/Paris"


def _mois_de(d: datetime, tz) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(tz).strftime("%Y-%m")


def _ajoute_mois(d: datetime, n: int) -> datetime:
    """Même jour n mois plus tard, borné à la fin du mois (31 janv. → 28 févr.)."""
    import calendar
    m = d.month - 1 + n
    annee, mois = d.year + m // 12, m % 12 + 1
    jour = min(d.day, calendar.monthrange(annee, mois)[1])
    return d.replace(year=annee, month=mois, day=jour)


async def _montants_connus(db: AsyncSession) -> dict[str, int]:
    """Dernier montant connu par abonnement Stripe (le prix RÉEL du price)."""
    montants: dict[str, int] = {}
    for sid, montant in (await db.execute(
        select(SubscriptionEvent.stripe_subscription_id,
               func.max(SubscriptionEvent.montant_cents))
        .where(SubscriptionEvent.montant_cents.isnot(None))
        .group_by(SubscriptionEvent.stripe_subscription_id)
    )).all():
        if sid:
            montants[sid] = montant
    return montants


def _ligne_paiement(date, email, plan, montant, nature, *, frais=None, net=None, rembourse=0,
                    charge_id=None, recu_url=None, facture_id=None, motif=None, source="stripe"):
    return {
        "date": date, "email": email, "plan": plan, "montant_cents": int(montant),
        "rembourse_cents": int(rembourse or 0),
        "frais_cents": None if frais is None else int(frais),
        "net_cents": None if net is None else int(net),
        "nature": nature, "motif": motif, "charge_id": charge_id,
        "recu_url": recu_url, "facture_id": facture_id, "source": source,
    }


@router.get("/revenus")
async def revenus(
    mois: int = Query(12, ge=1, le=36),
    mois_prevision: int = Query(3, ge=1, le=12),
    actualiser: bool = Query(False, description="Ignore le cache et relit Stripe"),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Encaissements réels par mois, lus CHEZ STRIPE (débits réussis, frais,
    remboursements, virements), rapprochés du journal interne ; plus l'échéancier
    des prochains prélèvements de chaque abonné.

    Sans clé Stripe (tests, poste local) ou si Stripe ne répond pas, le calcul
    retombe sur le journal `paiement_recu` — et la réponse le DIT (`source`),
    pour que l'écran ne présente jamais un repli comme la vérité comptable.
    """
    import asyncio
    from zoneinfo import ZoneInfo
    from api.config import get_settings
    from services import revenus_stripe

    tz = ZoneInfo(FUSEAU_REVENUS)
    now = datetime.now(timezone.utc)
    local = now.astimezone(tz)
    debut_mois_courant = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    debut_fenetre = _ajoute_mois(debut_mois_courant, -(mois - 1))
    debut_fenetre_utc = debut_fenetre.astimezone(timezone.utc)
    cles_mois = [_ajoute_mois(debut_fenetre, i).strftime("%Y-%m") for i in range(mois)]

    def _formule(plan: Optional[str]) -> str:
        return {"starter": "standard", "pro": "expert"}.get(plan or "", plan or "standard")

    # ── Qui est qui : client Stripe / e-mail → compte et formule ──
    comptes = (await db.execute(
        select(User.user_id, User.email, User.stripe_customer_id, User.plan)
    )).all()
    plan_abo: dict[str, str] = {}
    for uid, plan in (await db.execute(
        select(Subscription.user_id, Subscription.plan).order_by(Subscription.created_at)
    )).all():
        plan_abo[uid] = plan  # le plus récent l'emporte
    par_client = {c: (uid, em) for uid, em, c, _p in comptes if c}
    plan_par_email = {
        (em or "").lower(): _formule(plan_abo.get(uid) or p) for uid, em, _c, p in comptes
    }
    PLAN_PAR_MONTANT = {v: _formule(k) for k, v in PRIX_MENSUEL_CENTS.items()}

    # ── Journal interne (sert au rapprochement, et de repli) ──
    journal = (await db.execute(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.type.in_(("paiement_recu", "paiement_echoue")))
        .order_by(SubscriptionEvent.created_at)
    )).scalars().all()

    # ── Source : Stripe d'abord ──
    source = {"type": "journal", "lu_le": None, "erreur": None}
    livre = None
    cle = get_settings().stripe_secret_key
    if cle:
        try:
            livre = await asyncio.to_thread(
                revenus_stripe.lire, cle, int(debut_fenetre_utc.timestamp()), actualiser,
            )
            source = {
                "type": "stripe",
                "lu_le": datetime.fromtimestamp(livre.lu_le, tz=timezone.utc).isoformat(),
                "erreur": None,
            }
        except Exception as e:  # noqa: BLE001 — Stripe injoignable : repli signalé
            log.error("admin.revenus.stripe_indisponible", error=str(e)[:300])
            source["erreur"] = "Stripe n'a pas répondu : chiffres issus du journal interne."
    else:
        source["erreur"] = "Clé Stripe absente : chiffres issus du journal interne."

    lignes_paiement: list[dict] = []
    remboursements: list[dict] = []
    virements: list[dict] = []
    ecarts = {"absents_du_journal": [], "absents_de_stripe": []}

    if livre is not None:
        premiers: set[str] = set()
        for e in livre.encaissements:  # ordre chronologique
            qui = e.client_id or (e.email or "").lower()
            premier = bool(qui) and qui not in premiers
            if qui:
                premiers.add(qui)
            uid_email = par_client.get(e.client_id or "")
            email = e.email or (uid_email[1] if uid_email else None)
            plan = plan_par_email.get((email or "").lower()) or PLAN_PAR_MONTANT.get(e.montant_cents) or "standard"
            lignes_paiement.append(_ligne_paiement(
                e.cree_le, email, plan, e.montant_cents, "nouveau" if premier else "renouvellement",
                frais=e.frais_cents, net=e.net_cents, rembourse=e.rembourse_cents,
                charge_id=e.charge_id, recu_url=e.recu_url, facture_id=e.facture_id,
                motif=e.description,
            ))
        remboursements = [
            {"date": r.cree_le, "montant_cents": r.montant_cents, "net_cents": r.net_cents,
             "charge_id": r.charge_id, "email": r.email}
            for r in livre.remboursements
        ]
        virements = [
            {"date": v.arrivee_le, "montant_cents": v.montant_cents, "statut": v.statut}
            for v in livre.virements
        ]

        # Rapprochement : chaque débit Stripe doit avoir son `paiement_recu`
        # (même e-mail, même montant, à 3 jours près), et réciproquement.
        restants = [ev for ev in journal if ev.type == "paiement_recu"]
        for lp in lignes_paiement:
            trouve = None
            for ev in restants:
                d = ev.created_at if ev.created_at.tzinfo else ev.created_at.replace(tzinfo=timezone.utc)
                if (int(ev.montant_cents or 0) == lp["montant_cents"]
                        and (ev.email or "").lower() == (lp["email"] or "").lower()
                        and abs((d - lp["date"]).total_seconds()) <= 3 * 86400):
                    trouve = ev
                    break
            if trouve is not None:
                restants.remove(trouve)
            elif lp["date"] >= debut_fenetre_utc:
                ecarts["absents_du_journal"].append(
                    {"date": lp["date"], "email": lp["email"], "montant_cents": lp["montant_cents"],
                     "charge_id": lp["charge_id"]})
        for ev in restants:
            d = ev.created_at if ev.created_at.tzinfo else ev.created_at.replace(tzinfo=timezone.utc)
            if d >= debut_fenetre_utc:
                ecarts["absents_de_stripe"].append(
                    {"date": d, "email": ev.email, "montant_cents": int(ev.montant_cents or 0)})
    else:
        vus: set[str] = set()
        for ev in journal:
            if ev.type != "paiement_recu":
                continue
            detail = ev.detail if isinstance(ev.detail, dict) else {}
            sid = ev.stripe_subscription_id
            premier = (detail.get("motif") == "subscription_create"
                       or bool(detail.get("premier_paiement_apres_essai"))
                       or (sid is not None and sid not in vus))
            if sid:
                vus.add(sid)
            d = ev.created_at if ev.created_at.tzinfo else ev.created_at.replace(tzinfo=timezone.utc)
            lignes_paiement.append(_ligne_paiement(
                d, ev.email, _formule(ev.plan), int(ev.montant_cents or 0),
                "nouveau" if premier else "renouvellement",
                motif=detail.get("motif"), facture_id=detail.get("facture"), source="journal",
            ))

    # ── Agrégation mensuelle (mois de Paris) ──
    buckets = {
        k: {
            "mois": k, "encaisse_cents": 0, "rembourse_cents": 0, "frais_cents": 0,
            "net_cents": 0, "verse_cents": 0, "nb_paiements": 0, "nb_remboursements": 0,
            "nouveaux_cents": 0, "renouvellements_cents": 0,
            "par_formule": {"standard": 0, "expert": 0},
            "echecs_cents": 0, "nb_echecs": 0, "frais_connus": livre is not None,
            "clients": set(), "paiements": [],
        }
        for k in cles_mois
    }
    for lp in lignes_paiement:
        b = buckets.get(_mois_de(lp["date"], tz))
        if b is None:
            continue
        m = lp["montant_cents"]
        b["encaisse_cents"] += m
        b["nb_paiements"] += 1
        b["frais_cents"] += lp["frais_cents"] or 0
        b["net_cents"] += lp["net_cents"] if lp["net_cents"] is not None else m
        f = lp["plan"] if lp["plan"] in b["par_formule"] else "standard"
        b["par_formule"][f] += m
        b["nouveaux_cents" if lp["nature"] == "nouveau" else "renouvellements_cents"] += m
        if lp["email"]:
            b["clients"].add(lp["email"].lower())
        b["paiements"].append(lp)
    for r in remboursements:
        b = buckets.get(_mois_de(r["date"], tz))
        if b is not None:
            b["rembourse_cents"] += r["montant_cents"]
            b["net_cents"] += r["net_cents"]
            b["nb_remboursements"] += 1
    for v in virements:
        b = buckets.get(_mois_de(v["date"], tz))
        if b is not None:
            b["verse_cents"] += v["montant_cents"]
    for ev in journal:
        if ev.type == "paiement_echoue":
            b = buckets.get(_mois_de(ev.created_at, tz))
            if b is not None:
                b["nb_echecs"] += 1
                b["echecs_cents"] += int(ev.montant_cents or 0)

    serie = []
    cumul = 0
    for k in cles_mois:
        b = buckets[k]
        ca = b["encaisse_cents"] - b["rembourse_cents"]
        cumul += ca
        b["paiements"].sort(key=lambda p: p["date"], reverse=True)
        serie.append({
            **{kk: vv for kk, vv in b.items() if kk != "clients"},
            # Chiffre d'affaires encaissé du mois = débits réussis − remboursements.
            "ca_cents": ca,
            "nb_clients": len(b["clients"]),
            "panier_moyen_cents": round(b["encaisse_cents"] / b["nb_paiements"]) if b["nb_paiements"] else None,
            "cumul_cents": cumul,
        })

    # ── Échéancier : prochain prélèvement de chaque abonnement vivant ──
    montants = await _montants_connus(db)
    # La prévision couvre des MOIS ENTIERS : le mois en cours puis `mois_prevision`
    # mois pleins. Une borne en jours (90 j) coupait le dernier mois en deux et le
    # graphique montrait une chute qui n'était qu'un artefact de fenêtre.
    horizon = _ajoute_mois(debut_mois_courant, mois_prevision + 1).astimezone(timezone.utc)
    lignes = (await db.execute(
        select(Subscription, User)
        .join(User, User.user_id == Subscription.user_id)
        .where(Subscription.statut.in_(("active", "trialing", "cancel_at_period_end", "past_due")))
    )).all()

    echeances = []
    prevu_par_mois: dict[str, int] = {}
    for sub, user in lignes:
        montant = montants.get(sub.stripe_subscription_id) or PRIX_MENSUEL_CENTS.get(sub.plan, 0)
        essai_fin = sub.essai_fin
        if essai_fin is not None and essai_fin.tzinfo is None:
            essai_fin = essai_fin.replace(tzinfo=timezone.utc)
        periode_fin = sub.periode_fin
        if periode_fin is not None and periode_fin.tzinfo is None:
            periode_fin = periode_fin.replace(tzinfo=timezone.utc)

        en_essai = essai_fin is not None and essai_fin > now
        prochaine = essai_fin if en_essai else periode_fin
        if sub.statut == "cancel_at_period_end":
            nature = "fin_acces"
        elif sub.statut == "past_due":
            nature = "impaye"
        elif en_essai:
            nature = "premier_prelevement"
        else:
            nature = "renouvellement"
        echeances.append({
            "user_id": user.user_id,
            "email": user.email,
            "plan": _formule(sub.plan),
            "periodicite": sub.periodicite,
            "statut": sub.statut,
            "nature": nature,
            "date": prochaine,
            "jours_restants": round((prochaine - now).total_seconds() / 86400, 1) if prochaine else None,
            "montant_cents": 0 if nature in ("fin_acces", "impaye") else montant,
            "stripe_subscription_id": sub.stripe_subscription_id,
        })

        # Projection : seules les échéances qui DÉBITERONT comptent.
        if nature in ("fin_acces", "impaye") or prochaine is None:
            continue
        pas = 12 if sub.periodicite == "annual" else 1
        d, i = prochaine, 0
        while d < horizon and i < 40:
            if d >= now:
                cle = _mois_de(d, tz)
                prevu_par_mois[cle] = prevu_par_mois.get(cle, 0) + montant
            i += 1
            d = _ajoute_mois(prochaine, pas * i)

    echeances.sort(key=lambda e: (e["date"] is None, e["date"] or now))
    mois_courant = cles_mois[-1]
    courant = serie[-1]
    precedent = serie[-2] if len(serie) > 1 else None
    prevision = [
        {"mois": k, "prevu_cents": v}
        for k, v in sorted(prevu_par_mois.items())
    ]
    reste_mois = prevu_par_mois.get(mois_courant, 0)
    total = sum(s_["ca_cents"] for s_ in serie)
    somme = lambda cle_: sum(s_[cle_] for s_ in serie)  # noqa: E731

    return {
        "fuseau": FUSEAU_REVENUS,
        "source": source,
        "mois": serie,
        "totaux": {
            # Toutes les sommes « encaissées » sont nettes des remboursements :
            # c'est le chiffre d'affaires réellement acquis.
            "periode_cents": total,
            "brut_cents": somme("encaisse_cents"),
            "rembourse_cents": somme("rembourse_cents"),
            "frais_cents": somme("frais_cents"),
            "net_cents": somme("net_cents"),
            "verse_cents": somme("verse_cents"),
            "mois_courant_cents": courant["ca_cents"],
            "mois_precedent_cents": precedent["ca_cents"] if precedent else None,
            "variation_pct": (
                round((courant["ca_cents"] - precedent["ca_cents"])
                      / precedent["ca_cents"] * 100, 1)
                if precedent and precedent["ca_cents"] else None
            ),
            "reste_a_encaisser_mois_cents": reste_mois,
            "atterrissage_mois_cents": courant["ca_cents"] + reste_mois,
            "moyenne_mensuelle_cents": round(total / len(serie)) if serie else 0,
            "nb_paiements": somme("nb_paiements"),
            "echecs_cents": somme("echecs_cents"),
        },
        "rapprochement": {
            "verifie": livre is not None,
            "absents_du_journal": ecarts["absents_du_journal"],
            "absents_de_stripe": ecarts["absents_de_stripe"],
        },
        "prevision": prevision,
        "echeancier": echeances,
        "computed_at": now.isoformat(),
    }


# ─────────────────────────────────────────────
# Suivi des essais : qui résilie, qui ne paie pas, qui abandonne
# ─────────────────────────────────────────────
# Demande de l'exploitant (2026-09-16) : les compteurs sur 30 jours ne disaient
# pas QUI avait résilié, QUI n'avait pas payé à la fin de son essai et était
# repassé en gratuit, ni QUI avait ouvert le paiement sans aller au bout.
#
# Chaque compte ayant eu au moins un abonnement Stripe reçoit UNE issue, lue sur
# son abonnement le plus récent et complétée par le journal (seul à savoir s'il
# a payé, combien de prélèvements ont échoué, quand la résiliation a été faite).
ISSUES_SUIVI = (
    "impaye",                  # prélèvement refusé (fin d'essai ou échéance) → accès coupé, relances en cours
    "impaye_perdu",            # 2 relances refusées → abonnement clos (cf. services.relances_paiement)
    "resiliation_programmee",  # résilié, garde l'accès jusqu'à l'échéance
    "en_essai",
    "converti",                # a payé, toujours abonné
    "resilie_pendant_essai",   # parti sans jamais payer
    "resilie_apres_paiement",  # client payant perdu
    "essai_perdu_sans_carte",
)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


async def _suivi_essais(db: AsyncSession, now: datetime) -> dict:
    comptes = {u.user_id: u for u in (await db.execute(
        select(User).where(User.is_admin.is_not(True))
    )).scalars().all()}

    subs_par_compte: dict[str, list[Subscription]] = {}
    for sub in (await db.execute(
        select(Subscription).order_by(Subscription.created_at)
    )).scalars().all():
        if sub.user_id in comptes:
            subs_par_compte.setdefault(sub.user_id, []).append(sub)

    evts_par_compte: dict[str, list[SubscriptionEvent]] = {}
    if subs_par_compte:
        for e in (await db.execute(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.user_id.in_(list(subs_par_compte)))
            .order_by(SubscriptionEvent.created_at)
        )).scalars().all():
            evts_par_compte.setdefault(e.user_id, []).append(e)

    lignes = []
    for uid, subs in subs_par_compte.items():
        u = comptes[uid]
        sub = subs[-1]
        sid = sub.stripe_subscription_id
        tous = evts_par_compte.get(uid, [])
        # Mouvements de CET abonnement (ou non rattachés à un abonnement précis).
        evts = [e for e in tous if e.stripe_subscription_id in (sid, None)]

        def _types(*types: str) -> list[SubscriptionEvent]:
            return [e for e in evts if e.type in types]

        paiements = _types("paiement_recu")
        echecs = _types("paiement_echoue")
        dernier_paiement = _aware(paiements[-1].created_at) if paiements else None
        # Série d'échecs EN COURS : ceux postérieurs au dernier paiement réussi.
        serie = [e for e in echecs
                 if dernier_paiement is None or _aware(e.created_at) > dernier_paiement]
        essai_refuse = any(e.type == "essai_refuse_carte_reutilisee" for e in evts)
        essai_fin = None if essai_refuse else _aware(sub.essai_fin)
        a_eu_essai = not essai_refuse and (
            essai_fin is not None
            or any(e.type in ("essai_ouvert", "essai_sans_carte") for e in evts)
        )
        essai_en_cours = essai_fin is not None and essai_fin > now
        a_paye = bool(paiements)
        resiliations = _types("resiliation_demandee")
        resiliation = resiliations[-1] if resiliations else None
        fin_evt = next((e for e in reversed(evts)
                        if e.type in ("resilie", "essai_termine_sans_carte")), None)
        date_fin = _aware(fin_evt.created_at) if fin_evt else _aware(sub.updated_at)

        statut = sub.statut
        reprises = _types("resiliation_annulee")
        if (statut == "active" and resiliation is not None
                and (not reprises or reprises[-1].created_at < resiliation.created_at)):
            # Avant le correctif du 2026-09-16, le webhook suivant la résiliation
            # réécrivait `active` : le journal, lui, a gardé la demande.
            statut = "cancel_at_period_end"
        perdus = _types("impaye_perdu")
        if statut in ("past_due", "unpaid", "incomplete"):
            issue = "impaye"
            date_issue = _aware(serie[0].created_at) if serie else _aware(sub.updated_at)
        elif statut in ("canceled", "incomplete_expired") and (serie or perdus):
            issue = "impaye_perdu"
            date_issue = _aware(perdus[-1].created_at) if perdus else date_fin
        elif statut == "cancel_at_period_end":
            issue = "resiliation_programmee"
            date_issue = _aware(resiliation.created_at) if resiliation else _aware(sub.updated_at)
        elif statut == STATUT_SANS_CARTE_ADMIN or (statut == "active" and essai_en_cours):
            issue = "en_essai"
            date_issue = _aware(sub.created_at)
        elif statut == "active":
            issue = "converti"
            date_issue = (_aware(paiements[0].created_at) if paiements
                          else essai_fin or _aware(sub.created_at))
        elif statut == "canceled" and fin_evt is not None and fin_evt.type == "essai_termine_sans_carte":
            issue, date_issue = "essai_perdu_sans_carte", date_fin
        elif statut == "canceled":
            issue = "resilie_apres_paiement" if a_paye else "resilie_pendant_essai"
            date_issue = date_fin
        else:
            continue  # statut inconnu : ne pas inventer de case

        # Fin (ou perte) d'accès : la date que l'exploitant veut lire.
        if issue == "resiliation_programmee":
            fin_acces = essai_fin if essai_en_cours else _aware(sub.periode_fin)
        elif issue in ("impaye", "impaye_perdu") and serie:
            fin_acces = _aware(serie[0].created_at)  # l'accès tombe au premier refus
        elif issue in ("impaye", "impaye_perdu", "resilie_pendant_essai",
                       "resilie_apres_paiement", "essai_perdu_sans_carte"):
            fin_acces = date_issue
        else:
            fin_acces = None

        prochaine_relance = None
        if statut == "past_due" and serie:
            ts = (serie[-1].detail or {}).get("prochaine_relance")
            if isinstance(ts, (int, float)):
                prochaine_relance = datetime.fromtimestamp(ts, tz=timezone.utc)

        if resiliation is None:
            resiliation_pendant_essai = False
        elif resiliation.pendant_essai is not None:
            resiliation_pendant_essai = bool(resiliation.pendant_essai)
        else:
            resiliation_pendant_essai = (essai_fin is not None
                                         and _aware(resiliation.created_at) < essai_fin)

        lignes.append({
            "user_id": uid,
            "email": u.email,
            "formule": sub.plan,
            "plan_compte": u.plan,
            "issue": issue,
            "statut": statut,
            "date_issue": date_issue,
            "debut": _aware(sub.created_at),
            "essai_fin": essai_fin,
            "a_eu_essai": a_eu_essai,
            "essai_refuse": essai_refuse,
            "fin_acces": fin_acces,
            "resiliation_le": _aware(resiliation.created_at) if resiliation else None,
            "resiliation_pendant_essai": resiliation_pendant_essai,
            "a_paye": a_paye,
            "impaye_regularise": bool(echecs) and not serie and a_paye,
            "montant_cents": (max((e.montant_cents for e in evts if e.montant_cents), default=None)
                              or PRIX_MENSUEL_CENTS.get(sub.plan)),
            "echecs_paiement": len(serie),
            "derniere_tentative": _aware(serie[-1].created_at) if serie else None,
            "prochaine_relance": prochaine_relance,
            "relances_faites": sum(1 for e in _types("relance_paiement")
                                   if dernier_paiement is None
                                   or _aware(e.created_at) > dernier_paiement),
            "relances_terminees": issue == "impaye_perdu" or statut == "unpaid",
            "inscrit_le": _aware(u.created_at),
            "derniere_connexion": _aware(u.last_login_at),
        })

    lignes.sort(key=lambda l: l["date_issue"] or now, reverse=True)
    par_issue = {i: sum(1 for l in lignes if l["issue"] == i) for i in ISSUES_SUIVI}

    # Essais arrivés au bout : ont-ils payé ? Seuls les comptes ayant réellement eu
    # une période gratuite comptent — un essai refusé (carte déjà vue) n'en est pas un.
    termines = [l for l in lignes if l["a_eu_essai"]
                and l["issue"] not in ("en_essai", "resiliation_programmee")]
    convertis = [l for l in termines if l["a_paye"] or l["issue"] == "converti"]

    # Paiement ouvert (le client Stripe naît au checkout) mais aucun abonnement :
    # la personne s'est arrêtée à l'écran de carte bancaire.
    abandons = [
        {"user_id": u.user_id, "email": u.email, "plan": u.plan,
         "inscrit_le": _aware(u.created_at), "derniere_connexion": _aware(u.last_login_at)}
        for u in sorted(comptes.values(), key=lambda x: _aware(x.created_at) or now, reverse=True)
        if u.stripe_customer_id and u.user_id not in subs_par_compte
    ]

    return {
        "resume": {
            **par_issue,
            "checkouts_abandonnes": len(abandons),
            "essais_ouverts": sum(1 for l in lignes if l["a_eu_essai"]),
            "essais_termines": len(termines),
            "essais_convertis": len(convertis),
            "taux_conversion_essai": (round(len(convertis) / len(termines) * 100, 1)
                                      if termines else None),
            "repasses_gratuits": sum(1 for l in lignes if l["plan_compte"] == "free"
                                     and l["issue"] != "en_essai"),
        },
        "comptes": lignes,
        "checkouts_abandonnes": abandons,
    }


# ─────────────────────────────────────────────
# Présence en ligne
# ─────────────────────────────────────────────
@router.get("/en-ligne")
async def en_ligne(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Qui a le site ouvert en ce moment (signal < 5 min), cf. services/presence.
    `disponible=False` si Redis ne répond pas : l'écran dit « inconnu », pas « 0 »."""
    from collections import Counter
    from services.presence import en_ligne as photo_presence

    photo = await photo_presence()
    if photo is None:
        return {"disponible": False, "fenetre_min": 5, "total": None, "connectes": None,
                "anonymes": None, "comptes": [], "pages": []}

    visiteurs = photo["visiteurs"]
    ids = [v["user_id"] for v in visiteurs if v["user_id"]]
    comptes_db = {}
    if ids:
        comptes_db = {u.user_id: u for u in (await db.execute(
            select(User).where(User.user_id.in_(ids))
        )).scalars().all()}

    comptes = []
    for v in visiteurs:
        u = comptes_db.get(v["user_id"]) if v["user_id"] else None
        if u is None:
            continue
        comptes.append({
            "user_id": u.user_id, "email": u.email, "plan": u.plan, "is_admin": u.is_admin,
            "chemin": v["chemin"], "vu_il_y_a_s": v["vu_il_y_a_s"],
        })
    comptes.sort(key=lambda c: c["vu_il_y_a_s"] if c["vu_il_y_a_s"] is not None else 10**6)

    pages = Counter(v["chemin"] for v in visiteurs if v["chemin"])
    return {
        "disponible": True,
        "fenetre_min": photo["fenetre_s"] // 60,
        "total": len(visiteurs),
        "connectes": len(comptes),
        "anonymes": len(visiteurs) - len(comptes),
        "comptes": comptes,
        "pages": [{"chemin": c, "n": n} for c, n in pages.most_common(6)],
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
    # compare_digest = comparaison à temps constant (anti timing-attack ; `!=` fuit la
    # longueur du préfixe commun). Refuse aussi si le token n'est pas configuré.
    if not settings.betfair_ingest_token or not secrets.compare_digest(
        token, settings.betfair_ingest_token
    ):
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


# ─────────────────────────────────────────────
# Qualité des données d'entrée (Point 13)
# ─────────────────────────────────────────────
@router.get("/data-quality")
async def data_quality(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Fraîcheur, couverture par source, cotes figées, concordance partants.

    Lecture seule. Répond à la question « les entrées du pronostic sont-elles
    encore alimentées ? », invisible autrement : conteneurs healthy, site en
    ligne, endpoints à 200 — et pourtant plus une cote qui bouge.
    """
    from services.data_quality import rapport_qualite
    return await rapport_qualite(db)


# ─────────────────────────────────────────────
# Supervision IA — chiffres par type de pari, rentabilité, trajectoire du modèle
# ─────────────────────────────────────────────
@router.get("/supervision/paris")
async def supervision_paris(
    days: Optional[int] = Query(default=90, ge=0, le=730),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Chiffres RÉELS par type de pari (Simple Gagnant, Couplé, Trio, Multi…).

    Mesuré sur les conseils réellement émis avant le départ et réglés sur les
    rapports PMU. ROI brut ET winsorisé à 50× la mise, IC 90 %, test de
    robustesse (ROI sans les 1/5/20 plus gros gains) : un segment n'est déclaré
    rentable qu'avec ≥150 gagnants ET un IC entièrement positif.
    `days=0` = tout l'historique.
    """
    from ml.bet_type_analytics import compute_bet_type_analytics
    return await compute_bet_type_analytics(db, days=days or None)


@router.get("/supervision/rentabilite")
async def supervision_rentabilite(
    days: Optional[int] = Query(default=90, ge=0, le=730),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Rentabilité jour par jour : net, ROI, capital cumulé, drawdown vécu.

    Mêmes gardes d'intégrité que `/supervision/paris` (conseil émis avant le
    départ, backfills exclus). En revanche les séries `net`/`cumul_net` portent
    les gains RÉELS : winsoriser une courbe de capital vécu la rendait fausse
    (le 19/07 affichait +280 € pour +4 306 € réellement encaissés). La lecture
    plafonnée reste disponible dans les champs `*_winsor`.
    """
    from ml.bet_type_analytics import compute_profitability_timeline
    return await compute_profitability_timeline(db, days=days or None)


@router.get("/supervision/algo-evolution")
async def supervision_algo_evolution(
    limit: int = Query(default=60, ge=5, le=300),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Trajectoire du modèle version par version (AUC, Brier, walk-forward)."""
    from ml.bet_type_analytics import compute_algo_evolution
    return await compute_algo_evolution(db, limit=limit)


@router.get("/supervision/outils-apprentissage")
async def supervision_outils_apprentissage(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Ce que le systeme apprend, quand il l'a appris, et ce que ca a change.

    Les dix-huit apprentissages nocturnes vivent tous derriere le retrain, dans un
    seul job RQ : quand le worker se fait OOM-killer, ils sautent EN SILENCE (vecu
    le 20/08/2026, quatre-vingt-treize secondes apres un deploiement annonce
    reussi). Cet endpoint expose leur etat PERSISTE — date du dernier succes,
    peremption au-dela de 48 h — plus le verdict de chaque correcteur : a-t-il
    prouve qu'il ameliorait quelque chose, ou est-il en place sans preuve ?

    Tout provient d'un etat reellement persiste. Un outil sans mesure suffisante
    rend `mesure_disponible = false` et dit pourquoi : aucune valeur neutre n'est
    deguisee en mesure.
    """
    from ml.supervision_apprentissage import etat_outils_apprentissage
    return await etat_outils_apprentissage(db)


@router.get("/supervision/suivi-precision")
async def supervision_suivi_precision(
    jours: int = 60,
    segment: str = "tout",
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Précision de ce qui a été servi à T-10, jour par jour, contre les arrivées.

    Classement (n°1 gagnant, AUC intra-course), justesse des cotes justes
    (log-vraisemblance du gagnant, calibration par tranche), placement, référence
    marché sur les mêmes courses, modèle technique en observation, valeurs détectées
    réglées au rapport PMU officiel. Calculé par l'étape nocturne `suivi_precision`
    et persisté : aucune valeur n'est estimée à la volée.
    """
    from ml.suivi_precision import lire_suivi
    segment = segment if segment in ("tout", "attele", "plat", "monte", "obstacle") else "tout"
    return await lire_suivi(db, jours=max(7, min(int(jours), 365)), segment=segment)


@router.get("/supervision/pulse")
async def supervision_pulse(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Battement de cœur : ce qui bouge aujourd'hui (courses, conseils réglés,
    apprentissage, fraîcheur des sources). Appelé toutes les 15 s par la page."""
    from ml.bet_type_analytics import compute_pulse
    return await compute_pulse(db)
