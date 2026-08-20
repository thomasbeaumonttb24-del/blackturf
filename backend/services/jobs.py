"""
Tâches planifiées BlackTurf — APScheduler.
Registered at FastAPI startup. Lightweight triggers only;
heavy work (retrain) is enqueued to RQ.
"""
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = structlog.get_logger()
_scheduler: AsyncIOScheduler | None = None

_DRIFT_RETRAIN_TRIGGER_KEY = "ml:drift_retrain_trigger_cooldown"
_DRIFT_RETRAIN_TRIGGER_TTL_S = 6 * 3600


# Conservation d'un job ML RATÉ dans la FailedJobRegistry. Le défaut de RQ est un
# AN : les 35 `retrain_if_needed` tués par le OOM killer depuis juin 2026 y étaient
# encore, à gonfler le décompte d'une alerte dont la cause était traitée. 7 jours
# suffisent au diagnostic sans constituer un passif permanent.
ML_FAILURE_TTL_S = 7 * 24 * 3600


def _enqueue_drift_retrain_once(redis_client, queue):
    """Déduplique les demandes horaires de retrain tant que le drift reste critique."""
    claimed = redis_client.set(
        _DRIFT_RETRAIN_TRIGGER_KEY,
        "1",
        nx=True,
        ex=_DRIFT_RETRAIN_TRIGGER_TTL_S,
    )
    if not claimed:
        return None
    try:
        return queue.enqueue(
            "ml.pipeline.run_incremental_retraining_sync",
            result_ttl=86400,
            failure_ttl=ML_FAILURE_TTL_S,
        )
    except Exception:
        # L'enqueue n'a pas eu lieu : rendre immédiatement le droit de réessayer.
        redis_client.delete(_DRIFT_RETRAIN_TRIGGER_KEY)
        raise


# ─────────────────────────────────────────────
# Job functions
# ─────────────────────────────────────────────
async def job_morning_digest() -> None:
    """07:00 Paris — envoie le digest email aux abonnés."""
    log.info("jobs.morning_digest.start")
    try:
        from db.database import AsyncSessionLocal
        from services.alerts import send_morning_digest
        async with AsyncSessionLocal() as session:
            await send_morning_digest(session)
        log.info("jobs.morning_digest.done")
    except Exception as e:
        log.error("jobs.morning_digest.error", error=str(e))


async def job_weekly_best_value_bet() -> None:
    """Lundi 09:00 Paris — funnel conversion Free (décision produit 2026-08-16) :
    identifie le meilleur value bet RÉEL de la semaine passée et l'envoie par
    email/push aux comptes Free/Découverte. N'envoie rien si aucun value bet
    ★★★+ n'a gagné la semaine passée (honnêteté > relance à tout prix)."""
    log.info("jobs.weekly_best_value_bet.start")
    try:
        from db.database import AsyncSessionLocal
        from services.alerts import send_weekly_best_value_bet
        async with AsyncSessionLocal() as session:
            await send_weekly_best_value_bet(session)
        log.info("jobs.weekly_best_value_bet.done")
    except Exception as e:
        log.error("jobs.weekly_best_value_bet.error", error=str(e))


async def job_retrain_trigger() -> None:
    """02:00 UTC — enqueue ML retrain in RQ worker (heavy CPU, don't run in API process)."""
    log.info("jobs.retrain.trigger")
    try:
        import redis as sync_redis
        from rq import Queue
        from api.config import get_settings
        settings = get_settings()

        r = sync_redis.from_url(settings.redis_url)
        q = Queue("ml", connection=r, default_timeout=3600)
        job = q.enqueue("ml.pipeline.retrain_if_needed", result_ttl=86400,
                        failure_ttl=ML_FAILURE_TTL_S)
        log.info("jobs.retrain.enqueued", job_id=job.id)
    except Exception as e:
        log.error("jobs.retrain.error", error=str(e))


async def job_meta_learner_retrain() -> None:
    """
    03:00 UTC (après nightly retrain) — réentraîne le meta-learner contextuel.

    Le meta-learner apprend des biais systématiques (terrain/hippodrome/heure)
    sur les 6 derniers mois de race_learning_log. Nécessite ≥ 200 courses analysées.
    """
    log.info("jobs.meta_learner_retrain.start")
    try:
        from db.database import AsyncSessionLocal
        from ml.meta_learner import get_meta_learner
        async with AsyncSessionLocal() as session:
            ml = get_meta_learner()
            result = await ml.train(session)
            # train() renvoie status="ok" en cas de succès (pas "trained").
            if result.get("status") == "ok":
                ml.save()
                log.info(
                    "jobs.meta_learner_retrain.done",
                    n_samples=result.get("n_samples"),
                    auc=result.get("auc_roc"),
                )
            else:
                log.info(
                    "jobs.meta_learner_retrain.skipped",
                    reason=result.get("status"),
                    n_samples=result.get("n_samples", 0),
                )
    except Exception as e:
        log.error("jobs.meta_learner_retrain.error", error=str(e))


async def job_drift_check() -> None:
    """
    Toutes les heures (10h-22h) — vérifie l'état du drift detector.
    Si drift critique détecté → déclenche retraining incrémental.
    """
    log.info("jobs.drift_check.start")
    try:
        # Le conteneur `scheduler` n'a AUCUN hook de démarrage qui appelle
        # initialize_drift_detector() (seul api/main.py:lifespan le fait, et RQ
        # worker le fait par job — cf. pipeline.py run_post_course). `get_drift_detector()`
        # nu levait donc RuntimeError à CHAQUE run depuis toujours : ce job a échoué
        # TOUTES LES HEURES en silence (log.error, jamais remonté), et le retraining
        # incrémental sur dérive critique n'a donc jamais pu se déclencher par cette
        # voie. Fix : recharger l'état depuis la DB à chaque exécution — pas un init
        # une fois au boot du conteneur, qui resterait figé sur le snapshot de ce
        # boot alors que le worker RQ met l'état à jour en continu à chaque course
        # (même raisonnement que le commentaire de pipeline.py:402-408).
        from db.database import AsyncSessionLocal
        from ml.drift_detector import initialize_drift_detector
        async with AsyncSessionLocal() as dd_session:
            dd = await initialize_drift_detector(dd_session)
        report = dd.get_drift_report()
        severity = report.get("status", "healthy")

        if severity == "critical":
            log.warning("jobs.drift_check.critical", report=report)
            # Retraining incrémental HEAVY CPU/RAM → enqueue RQ worker, JAMAIS dans
            # le process API (asyncio.create_task saturait la mémoire de l'API et
            # risquait un OOM silencieux). Même pattern que job_retrain_trigger.
            import redis as sync_redis
            from rq import Queue
            from api.config import get_settings
            r = sync_redis.from_url(get_settings().redis_url)
            q = Queue("ml", connection=r, default_timeout=3600)
            job = _enqueue_drift_retrain_once(r, q)
            if job is None:
                log.info("jobs.drift_check.retrain_deduplicated")
            else:
                log.info("jobs.drift_check.retrain_enqueued", job_id=job.id)
        else:
            log.info("jobs.drift_check.ok", status=severity, brier_mean=report.get("brier_mean"))
    except Exception as e:
        log.error("jobs.drift_check.error", error=str(e))


async def job_resultats_poll() -> None:
    """Toutes les 3 minutes — poll résultats courses en cours."""
    try:
        from scraper.orchestrator import BlackTurfOrchestrator
        orch = BlackTurfOrchestrator()
        await orch.poll_resultats()
    except Exception as e:
        log.error("jobs.resultats_poll.error", error=str(e))


async def job_expire_stale_value_bets() -> None:
    """
    Filet de sécurité — toutes les 15 minutes : désactive les value bets dont la
    course est passée depuis longtemps.

    Bug constaté le 2026-08-17 : la page /value-bets affichait des paris datés de
    juin. `ValueBet.actif` n'est posé à True qu'à la création et n'est JAMAIS remis
    à False ailleurs dans le code — les endpoints (REST, WS, stats, assistant)
    filtrent en plus sur `Course.statut IN ('a_venir','en_cours')`, mais ce statut
    ne passe à 'termine' que si `save_resultat_to_db` reçoit un résultat PMU
    (db_writer.py). Le polling résultats (`poll_resultats`, orchestrator.py) ne
    regarde qu'une fenêtre glissante de 36h : une course sans résultat au-delà de
    36h (piste étrangère non couverte par le PMU comme "PALERMO ARG", panne de
    scraper, réunion annulée…) sort du périmètre pour toujours → son statut reste
    'a_venir' à vie et ses value bets restent "actifs" indéfiniment.

    Fenêtre de 6h : largement suffisant pour qu'une course PMU publie son arrivée ;
    passé ce délai le pari n'a plus d'objet, résultat connu ou pas.
    """
    try:
        from db.database import AsyncSessionLocal
        from db.models import ValueBet, Course
        from sqlalchemy import update, select
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        async with AsyncSessionLocal() as session:
            stale_ids = select(Course.course_id).where(Course.date_heure < cutoff)
            result = await session.execute(
                update(ValueBet)
                .where(ValueBet.actif == True, ValueBet.course_id.in_(stale_ids))
                .values(actif=False)
            )
            await session.commit()
            if result.rowcount:
                log.info("jobs.expire_stale_value_bets.done", n=result.rowcount)
    except Exception as e:
        log.error("jobs.expire_stale_value_bets.error", error=str(e))


async def job_notifications_retention() -> None:
    """1x/jour — hygiène du centre de notifications.

    `AlerteLog.lue` n'était posé à True que par un clic utilisateur : le compte admin
    accumulait 22 400 alertes in-app non lues (67 175 tous canaux confondus) et le
    badge navbar affichait « 9+ » à vie. Un value bet de la semaine dernière est de
    l'information MORTE — le garder « non lu » ne signale plus rien.

      1. auto-lecture des alertes de plus de BT_NOTIF_AUTOREAD_JOURS (défaut 7 j) :
         le badge redevient un signal utile ;
      2. purge des lignes in-app de plus de BT_NOTIF_PURGE_JOURS (défaut 90 j) :
         l'historique consultable reste large, la table ne gonfle pas indéfiniment.
         Les lignes email/push sont CONSERVÉES — ce sont des preuves d'envoi
         (audit RGPD / support), pas du contenu d'interface.
    """
    try:
        import os
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import delete, update
        from db.database import AsyncSessionLocal
        from db.models import AlerteLog

        autoread_jours = int(os.getenv("BT_NOTIF_AUTOREAD_JOURS", "7"))
        purge_jours = int(os.getenv("BT_NOTIF_PURGE_JOURS", "90"))
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            lues = await session.execute(
                update(AlerteLog)
                .where(
                    AlerteLog.lue == False,  # noqa: E712
                    AlerteLog.created_at < now - timedelta(days=autoread_jours),
                )
                .values(lue=True)
            )
            purgees = await session.execute(
                delete(AlerteLog).where(
                    AlerteLog.canal == "in-app",
                    AlerteLog.created_at < now - timedelta(days=purge_jours),
                )
            )
            await session.commit()
            log.info("jobs.notifications_retention.done",
                     auto_lues=lues.rowcount or 0, purgees=purgees.rowcount or 0,
                     autoread_jours=autoread_jours, purge_jours=purge_jours)
    except Exception as e:
        log.error("jobs.notifications_retention.error", error=str(e))


async def job_data_quality_check() -> None:
    """Toutes les heures — surveille la FRAÎCHEUR et la COUVERTURE des entrées.

    Une panne d'alimentation est silencieuse : conteneurs « healthy », site en
    ligne, endpoints à 200 — seules les cotes ne bougent plus. En production,
    quatre journées entières (12→15/08/2026) sans une seule course en base ne
    l'ont été qu'au bout de quatre jours, et la source `geny` est restée à 0 %
    de couverture pendant des semaines pendant que son daemon publiait son
    heartbeat sans faillir.

    Les anomalies partent dans `system_errors` (lu par le back-office) : on rend
    le trou VISIBLE, on ne corrige rien ici.
    """
    try:
        from db.database import AsyncSessionLocal
        from services.data_quality import verifier_et_alerter
        async with AsyncSessionLocal() as session:
            rapport = await verifier_et_alerter(session)
        log.info("jobs.data_quality_check.done",
                 statut=rapport["statut_global"],
                 n_anomalies=len(rapport["anomalies"]))
    except Exception as e:
        log.error("jobs.data_quality_check.error", error=str(e))


async def job_resolve_courses_sans_resultat() -> None:
    """1x/jour — clôture les courses passées restées sans résultat.

    Complément STRUCTUREL du filet de sécurité `job_expire_stale_value_bets` : le
    filet neutralise les value bets périmés mais laisse la course en 'a_venir' à
    vie. Ici on va chercher le verdict du PMU au-delà de la fenêtre 36h de
    `poll_resultats` : arrivée publiée en retard → 'termine', COURSE_ANNULEE →
    'annule', rien après quelques jours → 'sans_resultat' + entrée system_errors.
    Cf. services/course_resolution.py pour le détail de la cause racine.
    """
    try:
        from services.course_resolution import resolve_courses_sans_resultat
        cr = await resolve_courses_sans_resultat()
        log.info("jobs.resolve_courses_sans_resultat.done", **cr)
    except Exception as e:
        log.error("jobs.resolve_courses_sans_resultat.error", error=str(e))


async def job_vb_notify() -> None:
    """Toutes les 10 minutes — notifie nouveaux value bets non notifiés."""
    try:
        from db.database import AsyncSessionLocal
        from db.models import ValueBet, Participation, Cheval, Course, User
        from services.alerts import notify_value_bets
        from sqlalchemy import select, and_
        from datetime import datetime, timedelta, timezone

        async with AsyncSessionLocal() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=12)
            q = (
                select(ValueBet, Participation, Cheval, Course)
                .join(Participation, Participation.participation_id == ValueBet.participation_id)
                .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
                .join(Course, Course.course_id == ValueBet.course_id)
                .where(
                    and_(
                        ValueBet.actif == True,
                        ValueBet.notifie == False,
                        ValueBet.created_at >= cutoff,
                    )
                )
                .limit(20)
            )
            rows = (await session.execute(q)).all()
            if not rows:
                return

            # Get all paid users
            users_res = await session.execute(
                select(User.user_id).where(
                    User.plan.in_(["starter", "standard", "expert"]),
                    User.is_active == True,
                )
            )
            user_ids = [r[0] for r in users_res.fetchall()]
            if not user_ids:
                return

            vb_batch = []
            for vb, part, cheval, course in rows:
                vb_batch.append({
                    "vb_id": vb.vb_id,
                    "participation_id": vb.participation_id,
                    "nom_cheval": cheval.nom,
                    "hippodrome": course.hippodrome_nom,
                    "cote": part.cote_pmu,
                    "ev": vb.ev_max,
                    "niveau": vb.niveau,
                    "course_id": vb.course_id,
                    "heure_depart": course.date_heure.isoformat() if course.date_heure else None,
                })
                vb.notifie = True

            # Une seule notification récapitulative pour tout le lot. Aucun e-mail
            # unitaire : l'unique e-mail est le digest quotidien de 10h.
            await notify_value_bets(session, user_ids, vb_batch)

            await session.commit()
            log.info("jobs.vb_notify.done", nb_vbs=len(rows))
    except Exception as e:
        log.error("jobs.vb_notify.error", error=str(e))


# ─────────────────────────────────────────────
# Scheduler lifecycle
# ─────────────────────────────────────────────
def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def job_warm_caches() -> None:
    """Pre-chauffe les caches Redis des pages publiques lentes.

    `/stats/track-record` coute ~29 s a froid (mesure prod 2026-08-18, et non ~2 s
    comme le supposait la version precedente) : on appelle son rafraichissement EN
    DIRECT plutot que par HTTP. L'ancienne version tapait l'endpoint, qui lui
    renvoyait le cache encore chaud SANS rien reecrire -> le TTL n'etait jamais
    prolonge, le cache expirait 1 h apres le dernier calcul froid a une heure
    decorrelee de ce cron, et la page Palmares restait inutilisable (skeleton
    infini) jusqu'au passage suivant.

    Les autres pages sont rapides a froid (~0,4 s) : un simple GET suffit.
    `palmares-gagnants` est garde par require_admin et repondait 401 ici — il ne
    chauffait donc rien : on chauffe `palmares-public`, celui que la page utilise.
    """
    import httpx
    from api.routes.stats import refresh_track_record_cache

    try:
        reecrit = await refresh_track_record_cache()
        log.info("jobs.warm_cache.track_record", reecrit=reecrit)
    except Exception as e:  # noqa: BLE001
        log.warning("jobs.warm_cache.failed", url="track-record", err=str(e)[:120])

    urls = [
        "http://api:8000/api/v1/stats/palmares-public",
        "http://api:8000/api/v1/stats/profils",
    ]
    async with httpx.AsyncClient(timeout=60.0) as client:
        for u in urls:
            try:
                r = await client.get(u, headers={"Host": "blackturf.fr"})
                log.info("jobs.warm_cache", url=u, status=r.status_code)
            except Exception as e:  # noqa: BLE001
                log.warning("jobs.warm_cache.failed", url=u, err=str(e)[:120])


def start_scheduler() -> None:
    scheduler = get_scheduler()

    # Digest value bets unique — 10:00 Paris, après la majorité des détections
    # matinales et avant les premières courses françaises. Un seul e-mail/jour.
    scheduler.add_job(
        job_morning_digest,
        CronTrigger(hour=10, minute=0, timezone="Europe/Paris"),
        id="morning_digest",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Meilleur value bet de la semaine — lundi 09:00 Paris (funnel Free)
    scheduler.add_job(
        job_weekly_best_value_bet,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Europe/Paris"),
        id="weekly_best_value_bet",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Model retrain trigger — 02:00 UTC
    scheduler.add_job(
        job_retrain_trigger,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="retrain_trigger",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Results polling — every 3 minutes between 10:00 and 22:00 Paris
    scheduler.add_job(
        job_resultats_poll,
        CronTrigger(minute="*/3", hour="10-22", timezone="Europe/Paris"),
        id="resultats_poll",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Value bet notifications — every 10 minutes
    scheduler.add_job(
        job_vb_notify,
        CronTrigger(minute="*/10"),
        id="vb_notify",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Filet de sécurité value bets périmés — toutes les 15 minutes
    scheduler.add_job(
        job_expire_stale_value_bets,
        CronTrigger(minute="*/15"),
        id="expire_stale_value_bets",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Hygiène du centre de notifications — 04:45 UTC (avant la reprise de journée)
    scheduler.add_job(
        job_notifications_retention,
        CronTrigger(hour=4, minute=45, timezone="UTC"),
        id="notifications_retention",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Qualité des données d'entrée — toutes les heures à la minute 20 (décalé des
    # tâches de la minute 0 : lecture d'agrégats, inutile d'ajouter de la charge au
    # moment où le poll résultats et le warm cache travaillent).
    scheduler.add_job(
        job_data_quality_check,
        CronTrigger(minute=20),
        id="data_quality_check",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Clôture des courses sans résultat — 05:15 UTC, après la fin de toutes les
    # réunions de la veille et hors des heures de courses (requêtes PMU en trop
    # petit nombre, sans concurrence avec le poll live).
    scheduler.add_job(
        job_resolve_courses_sans_resultat,
        CronTrigger(hour=5, minute=15, timezone="UTC"),
        id="resolve_courses_sans_resultat",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Meta-learner retrain — 03:00 UTC (after nightly retrain finishes)
    scheduler.add_job(
        job_meta_learner_retrain,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="meta_learner_retrain",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Drift check — every hour during racing hours (10h-22h Paris)
    scheduler.add_job(
        job_drift_check,
        CronTrigger(minute=0, hour="10-22", timezone="Europe/Paris"),
        id="drift_check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Pre-chauffe caches pages publiques lentes — toutes les 30 min
    scheduler.add_job(
        job_warm_caches,
        CronTrigger(minute="*/30"),
        id="warm_caches",
        replace_existing=True,
        misfire_grace_time=120,
    )

    scheduler.start()
    log.info("jobs.scheduler.started", nb_jobs=len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("jobs.scheduler.stopped")
