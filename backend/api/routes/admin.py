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
            "abonnement_statut": sub_status.get(u.user_id),
            "created_at": u.created_at,
            "last_login": u.last_login_at,
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
    """Détail COMPLET d'un utilisateur pour le back-office : identité, portefeuille,
    abonnements et HISTORIQUE de jeu intégral (chaque pari joué/enregistré avec
    course, chevaux, cote, mise, résultat, gain), + agrégats (misé/gagné/net/ROI/
    win-rate, répartition par type de pari). Données réelles, paris réglés d'abord."""
    from db.models import Bankroll
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    # Règle les paris en attente de CE user (courses terminées) → gains à jour.
    try:
        from api.routes.bankroll import settle_pending_bets
        await settle_pending_bets(db, user_id)
    except Exception as e:
        log.warning("admin.user_detail.settle_skip", err=str(e)[:120])

    # Subscriptions
    subs = (await db.execute(
        select(Subscription).where(Subscription.user_id == user_id).order_by(desc(Subscription.created_at))
    )).scalars().all()

    # ── Historique complet des paris (join course pour contexte) ──
    rows = (await db.execute(
        select(
            BankrollEntry, Course.hippodrome_nom, Course.numero_reunion,
            Course.numero, Course.date_heure, Course.statut,
        )
        .outerjoin(Course, Course.course_id == BankrollEntry.course_id)
        .where(BankrollEntry.user_id == user_id)
        .order_by(desc(BankrollEntry.date))
        .limit(500)
    )).all()

    bets = []
    for e, hippo, n_r, n_c, dh, c_statut in rows:
        code = f"R{n_r}C{n_c}" if n_r and n_c else None
        bets.append({
            "entry_id": e.entry_id,
            "date": e.date,
            "type_pari": e.type_pari,
            "chevaux": e.chevaux,
            "mise": e.mise,
            "cote": e.cote,
            "resultat": e.resultat,
            "gain_perte": e.gain_perte,
            "suivi_reco_ia": e.suivi_reco_ia,
            "notes": e.notes,
            "course_id": e.course_id,
            "course_code": code,
            "hippodrome": hippo,
            "course_date": dh,
            "course_statut": c_statut,
        })

    # ── Agrégats portefeuille (toutes les entrées, pas seulement les 500) ──
    agg = (await db.execute(
        select(
            func.count(BankrollEntry.entry_id),
            func.coalesce(func.sum(BankrollEntry.mise), 0.0),
            func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
            func.sum(case((BankrollEntry.resultat == "gagne", 1), else_=0)),
            func.sum(case((BankrollEntry.resultat == "perd", 1), else_=0)),
            func.sum(case((BankrollEntry.resultat.is_(None), 1), else_=0)),
            func.sum(case((BankrollEntry.suivi_reco_ia == True, 1), else_=0)),
        ).where(BankrollEntry.user_id == user_id)
    )).one()
    nb_total, mise_tot, net_tot, nb_gagnes, nb_perdus, nb_attente, nb_ia = agg
    nb_total = int(nb_total or 0)
    mise_tot = float(mise_tot or 0.0)
    net_tot = float(net_tot or 0.0)
    nb_gagnes = int(nb_gagnes or 0)
    nb_perdus = int(nb_perdus or 0)
    nb_attente = int(nb_attente or 0)
    nb_regles = nb_gagnes + nb_perdus

    # Capital initial = Σ portefeuilles actifs (fallback bankroll_initiale)
    cap0 = (await db.execute(
        select(func.coalesce(func.sum(Bankroll.montant_initial), 0.0))
        .where(Bankroll.user_id == user_id, Bankroll.est_supprime == False)
    )).scalar() or (user.bankroll_initiale or 0.0)
    cap0 = float(cap0)

    # ── Répartition par type de pari ──
    type_rows = (await db.execute(
        select(
            BankrollEntry.type_pari,
            func.count(BankrollEntry.entry_id),
            func.coalesce(func.sum(BankrollEntry.mise), 0.0),
            func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
            func.sum(case((BankrollEntry.resultat == "gagne", 1), else_=0)),
        ).where(BankrollEntry.user_id == user_id).group_by(BankrollEntry.type_pari)
        .order_by(desc(func.count(BankrollEntry.entry_id)))
    )).all()
    par_type = [
        {"type_pari": t or "—", "nb": int(n), "mise": round(float(m), 2),
         "net": round(float(g), 2), "nb_gagnes": int(win or 0),
         "roi": round(float(g) / float(m) * 100, 1) if m and m > 0 else None}
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
            "bankroll_initiale": user.bankroll_initiale,
            "email_verified": user.email_verified,
            "auth_method": "google" if user.google_id else "email",
            "stripe_client": bool(user.stripe_customer_id),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login": user.last_login_at,
        },
        "portefeuille": {
            "capital_initial": round(cap0, 2),
            "solde_actuel": round(cap0 + net_tot, 2),
            "mise_totale": round(mise_tot, 2),
            "gain_net": round(net_tot, 2),
            "roi": round(net_tot / mise_tot * 100, 1) if mise_tot > 0 else None,
            "nb_paris": nb_total,
            "nb_gagnes": nb_gagnes,
            "nb_perdus": nb_perdus,
            "nb_attente": nb_attente,
            "nb_regles": nb_regles,
            "win_rate": round(nb_gagnes / nb_regles * 100, 1) if nb_regles > 0 else None,
            "nb_predictions_used": int(nb_ia or 0),
        },
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
    from db.models import Bankroll, Recommandation, Strategie

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
                "Capital", "Solde", "Mise totale", "Gain net", "ROI %", "Paris", "Gagnes"])
    for u in users:
        a = agg.get(u.user_id, {})
        mise = a.get("mise", 0.0); net = a.get("net", 0.0)
        cap = a.get("cap", 0.0) or (u.bankroll_initiale or 0.0)
        roi = round(net / mise * 100, 1) if mise > 0 else ""
        w.writerow([u.email, u.nom or "", u.prenom or "", u.plan, u.profil_risque,
                    "google" if u.google_id else "email", "oui" if u.email_verified else "non",
                    "oui" if u.is_active else "non", "oui" if u.is_admin else "non",
                    u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
                    u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "jamais",
                    "oui" if u.stripe_customer_id else "non",
                    sub_status.get(u.user_id) or ("checkout abandonne" if u.stripe_customer_id else ""),
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

    # 4. DERNIÈRES VICTOIRES : courses récentes où un plan profil a été NET positif,
    #    avec le meilleur profil + son gain net (rapports PMU réels). Concret, parlant.
    out["victoires"] = []
    try:
        rows = (await db.execute(text("""
            SELECT c.course_id, c.hippodrome_nom, c.date_heure, c.numero_reunion, c.numero,
                   r.profil, (r.resultat->>'net')::numeric AS net
            FROM profil_run_log r
            JOIN courses c ON c.course_id = r.course_id
            WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
              AND (r.resultat->>'net')::numeric > 0
              -- Mêmes gardes d'intégrité : victoires réelles émises avant départ only.
              AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure
              AND COALESCE(r.meta->>'backfill', '') <> 'true'
            ORDER BY c.date_heure DESC, net DESC
        """))).all()
        LBL = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
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
        out["victoires"] = sorted(best.values(), key=lambda x: x["date"] or "", reverse=True)[:25]
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
STATUTS_ACCES_ADMIN = ("active", "past_due", "cancel_at_period_end")
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
        elif en_cours_dessai:
            en_essai += 1
        elif sub.statut in STATUTS_ACCES_ADMIN:
            payants += 1
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

    return {
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


@router.get("/supervision/pulse")
async def supervision_pulse(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Battement de cœur : ce qui bouge aujourd'hui (courses, conseils réglés,
    apprentissage, fraîcheur des sources). Appelé toutes les 15 s par la page."""
    from ml.bet_type_analytics import compute_pulse
    return await compute_pulse(db)
