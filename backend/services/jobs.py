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

    Le meta-learner apprend, PAR PARTANT, les biais contextuels résiduels de la
    chaîne de calibration, sur les 6 derniers mois de prédictions figées avant
    départ (`prediction_evaluation`). Il n'est conservé que s'il fait mieux que
    l'absence de correction sur un hold-out découpé par course.
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
            elif result.get("status") == "rejected_not_useful":
                # Le correcteur n'a pas battu l'absence de correction sur le
                # hold-out. Le rejet doit être DURABLE : sans effacer le pickle,
                # le prochain démarrage de l'API rechargerait le modèle précédent
                # et continuerait d'appliquer une correction que la mesure vient
                # de refuser.
                from ml.meta_learner import META_LEARNER_PATH
                try:
                    META_LEARNER_PATH.unlink(missing_ok=True)
                except OSError as err:
                    log.warning("jobs.meta_learner_retrain.purge_failed", error=str(err))
                log.warning(
                    "jobs.meta_learner_retrain.rejected",
                    logloss_meta=result.get("logloss_meta"),
                    logloss_sans_correction=result.get("logloss_sans_correction"),
                    gain_logloss=result.get("gain_logloss"),
                    n_samples=result.get("n_samples", 0),
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
            # MÊME interrupteur que le retrain post-course (25/08/2026). Ce contrôle
            # de dérive tourne TOUTES LES HEURES : sans cette garde, il restait la
            # seule voie capable de lancer un entraînement de ~20 min en pleine
            # après-midi de courses, sur le worker RQ UNIQUE qui règle aussi les
            # paris, calcule les prédictions et envoie les alertes. La dérive reste
            # journalisée en warning ; le nightly de 02:00 UTC, qui voit le même
            # dataset, la traitera hors course.
            if not get_settings().retrain_intraday_enabled:
                log.info("jobs.drift_check.retrain_intraday_disabled",
                         brier_mean=report.get("brier_mean"))
                return
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

    # IndexNow — deux passages : 08:30 (programme du jour complet, lendemain publié)
    # et 22:30 (toutes les arrivées et tous les rapports le sont). Google n'utilise pas
    # ce protocole ; il ne concerne que Bing, Yandex, Naver et Seznam.
    scheduler.add_job(
        job_indexnow_push,
        CronTrigger(hour="8,22", minute=30, timezone="Europe/Paris"),
        id="indexnow_push",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # PLUS AUCUNE PUBLICATION QUOTIDIENNE DANS LE FIL. Décision du 2026-09-06.
    #
    # `publication_matin` (09:15, « Quinté+ du jour ») et `publication_soir` (20:45,
    # « arrivée et rapports ») ne sont plus planifiés. Le fil ne reçoit désormais
    # qu'UNE publication par semaine, le dimanche : le bilan hebdomadaire, une tuile
    # de la mosaïque à la fois.
    #
    # Comment on l'a découvert, et pourquoi ce n'est pas un simple changement d'avis :
    # ces deux jobs existaient depuis toujours mais tournaient en SIMULATION, faute
    # d'interrupteur. En ouvrant `INSTAGRAM_PUBLICATION_ACTIVE` le 2026-09-06 pour la
    # story, on les a déverrouillés aussi — un interrupteur unique pour trois canaux —
    # et le post « Quinté+ du jour » est parti dans le fil le matin même, sans que
    # personne ne l'ait demandé. Les retirer d'ici est la seule façon d'empêcher qu'un
    # futur usage de cet interrupteur les réveille.
    #
    # Les fonctions `job_publication_matin` / `job_publication_soir` restent en place :
    # elles sont appelables à la main pour un cas ponctuel. Ce qui disparaît, c'est
    # leur déclenchement AUTOMATIQUE.
    # ─────────────────────────────────────────────────────────────────────────

    # Story de bilan — TOUTES LES DEMI-HEURES de 22 h à 10 h, Paris.
    #
    # Pas un horaire fixe, et ce n'est pas de la prudence : le moment où une journée
    # devient publiable varie de plusieurs heures. Les dernières courses se courent
    # jusqu'à 23 h 30, et le rattrapage nocturne règle encore au petit matin — le
    # 2026-09-06, les 165 derniers plans du 5 n'ont été réglés qu'à 04 h 19. Le job
    # repasse donc et publie la première journée qui remplit la condition ; l'unicité
    # (jour, canal) en base garantit qu'il n'y en aura qu'une.
    scheduler.add_job(
        job_publication_story,
        CronTrigger(hour="22,23,0-9", minute="0,30", timezone="Europe/Paris"),
        id="publication_story",
        replace_existing=True,
        # Pas de rattrapage tardif : si le conteneur était à l'arrêt, le passage
        # suivant est à trente minutes. Rejouer un passage manqué n'apporte rien et
        # publierait à une heure imprévisible.
        misfire_grace_time=600,
    )
    # Renouvellement des jetons d'integration — 04:20 Paris, tous les jours. Le job ne
    # renouvelle qu'a l'approche de l'echeance ; passer tous les jours sert a absorber
    # plusieurs echecs consecutifs avant que le jeton n'expire pour de bon.
    scheduler.add_job(
        job_renouveler_jetons,
        CronTrigger(hour=4, minute=20, timezone="Europe/Paris"),
        id="renouveler_jetons",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # Filet du rapport de retrain — 06:30 UTC, soit 1 h 30 après le cron de
    # l'hôte (05:00 UTC). Assez tard pour ne jamais doubler un cron qui a
    # simplement pris du retard, assez tôt pour que le rapport reste un rapport
    # du matin le jour où ce cron ne tire plus.
    scheduler.add_job(
        job_filet_rapport_retrain,
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="filet_rapport_retrain",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    log.info("jobs.scheduler.started", nb_jobs=len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("jobs.scheduler.stopped")


async def job_indexnow_push() -> None:
    """
    Signale à Bing, Yandex, Naver et Seznam les URLs du jour (IndexNow).

    Sans ce signalement, une fiche course n'est explorée qu'au prochain passage
    spontané d'un robot — soit, pour une course, souvent après qu'elle a été courue.
    Le contenu le plus périssable du site est aussi celui qui a le plus besoin d'être
    signalé tôt.

    **Google n'utilise pas IndexNow** : ce job n'accélère rien côté Google, qui passe
    par le sitemap et Search Console.

    Deux passages par jour : le matin, quand le programme du lendemain est publié et
    que celui du jour est complet ; le soir, quand toutes les arrivées et tous les
    rapports le sont. Signaler plus souvent des URLs inchangées est le meilleur moyen
    de se faire ignorer.
    """
    from sqlalchemy import select, func
    from db.database import AsyncSessionLocal
    from db.models import Course
    from services.temps_courses import jour_courses
    from services.indexnow import signaler, urls_du_jour

    jour = jour_courses()
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Course.course_id).where(func.date(Course.date_heure) == jour)
            )
            course_ids = [r[0] for r in res.all()]
    except Exception as e:  # noqa: BLE001
        # Best-effort : on signale au moins les pages fixes du jour.
        log.warning("jobs.indexnow.courses_indisponibles", err=str(e)[:160])
        course_ids = []

    envoyees = await signaler(urls_du_jour(course_ids, str(jour)))
    log.info("jobs.indexnow.push", jour=str(jour), nb_courses=len(course_ids), envoyees=envoyees)


async def job_publication_reseaux(moment: str) -> None:
    """
    Publie le visuel du jour sur Instagram — visuel du matin, ou arrivée du soir.

    Les légendes et les URLs d'image viennent du SITE (`/visuels/legendes.json`), et non
    d'une seconde rédaction côté backend : deux versions parallèles du même texte
    finissent par diverger, et c'est celle qui est publiée qui a tort.

    Rien ne part si `pret` est faux : le support du Quinté+ n'est pas encore désigné le
    matin, l'arrivée pas encore publiée le soir. Publier « pas encore disponible » sur un
    compte de marque est pire que ne rien publier.

    Tant que INSTAGRAM_PUBLICATION_ACTIVE vaut 0, le job va jusqu'au bout mais ne publie
    pas — il journalise ce qu'il aurait envoyé.
    """
    import httpx
    from services.instagram import publier_image, publication_active, quota_restant

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "http://frontend:3000/visuels/legendes.json",
                headers={"Host": "blackturf.fr"},
            )
            resp.raise_for_status()
            publications = resp.json().get("publications", [])
    except Exception as e:  # noqa: BLE001
        log.warning("jobs.reseaux.legendes_indisponibles", moment=moment, err=str(e)[:200])
        return

    cible = next((p for p in publications if p.get("cle") == moment), None)
    if not cible:
        log.warning("jobs.reseaux.publication_absente", moment=moment)
        return

    if not cible.get("pret"):
        log.info("jobs.reseaux.donnees_incompletes", moment=moment, detail="rien publié")
        return

    resultat = await publier_image(cible["image"], cible["legende"])
    log.info(
        "jobs.reseaux.publication",
        moment=moment,
        actif=publication_active(),
        publie=bool(resultat),
        media_id=resultat.media_id,
        raison=resultat.raison,
        quota_restant=await quota_restant() if publication_active() else None,
    )


async def job_publication_matin() -> None:
    await job_publication_reseaux("matin")


async def job_publication_soir() -> None:
    await job_publication_reseaux("soir")


# Canal de la story de bilan dans `publications_sociales`.
CANAL_STORY = "story_performance"


async def job_publication_story() -> None:
    """
    Publie la story de bilan de la dernière journée COURUE ET RÉGLÉE — une par jour.

    POURQUOI CE JOB REPASSE au lieu de tourner une fois le soir : le moment où une
    journée devient publiable n'a pas d'heure fixe. Les dernières courses du programme
    sont sud-américaines et se courent jusqu'à 23 h 30 ; surtout, les rapports Multi
    sont publiés en différé et le rattrapage nocturne règle encore au petit matin — le
    2026-09-06, les 165 derniers plans du 5 n'ont été réglés qu'à 04 h 19. Un job à
    23 h aurait publié un total faux, ou rien du tout.

    Il repasse donc toutes les demi-heures sur une fenêtre de nuit et publie la
    PREMIÈRE journée qui remplit la condition. `journee_complete` est lue sur l'API,
    pas recalculée ici : deux définitions de « la journée est finie » finiraient par
    diverger, et c'est celle qui décide de la publication qui aurait tort.

    L'IDEMPOTENCE EST EN BASE, pas dans ce code. `publications_sociales` porte une
    unicité (jour, canal) : deux passages, deux conteneurs, ou un redéploiement en
    pleine nuit ne peuvent pas produire deux stories du même jour.
    """
    import uuid as _uuid
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    import httpx
    from sqlalchemy import text as _text

    from api.config import get_settings
    from db.database import AsyncSessionLocal
    from services.instagram import publier_story, publication_active, quota_restant
    from services.temps_courses import jour_courses

    # L'image doit être servie par une URL PUBLIQUE en https : Meta va la chercher
    # lui-même, il ne reçoit aucun fichier. Un nom de service interne ne marcherait pas.
    base = (get_settings().frontend_url or "https://blackturf.fr").rstrip("/")
    # L'API, elle, se lit en interne. `Host` explicite : en production le middleware
    # TrustedHost refuse tout hôte inconnu (« Invalid host header »).
    API_INTERNE = "http://api:8000/api/v1/stats/meilleurs-plans-jour"

    # Aujourd'hui d'abord, la veille ensuite : au petit matin c'est la veille qui vient
    # de devenir publiable, mais en fin de soirée ce peut être le jour courant.
    candidats = [jour_courses().isoformat(), (jour_courses() - _td(days=1)).isoformat()]

    async with AsyncSessionLocal() as session:
        # ON NE REVIENT JAMAIS EN ARRIÈRE. Sans cette borne, le passage qui suit la
        # publication du jour J sautait J (déjà publié) et publiait J−1 : une story
        # d'avant-hier surgissant à 5 h du matin, puis une autre la nuit suivante.
        # Le défaut a été trouvé par le test d'idempotence, pas en production.
        dernier = (await session.execute(_text(
            "SELECT MAX(jour) FROM publications_sociales "
            "WHERE canal = :c AND publie_at IS NOT NULL"
        ), {"c": CANAL_STORY})).scalar()

        for jour in candidats:
            if dernier and jour <= dernier:
                continue  # ce jour-là, ou un plus récent, est déjà parti

            deja = (await session.execute(_text(
                "SELECT publie_at FROM publications_sociales "
                "WHERE jour = :j AND canal = :c"
            ), {"j": jour, "c": CANAL_STORY})).first()
            if deja and deja[0] is not None:
                continue  # déjà publiée : on ne repasse jamais dessus

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(API_INTERNE, params={"jour": jour},
                                         headers={"Host": "api.blackturf.fr"})
                    r.raise_for_status()
                    d = r.json()
            except Exception as e:  # noqa: BLE001
                log.warning("jobs.story.bilan_indisponible", jour=jour, err=str(e)[:160])
                continue

            if not d.get("journee_complete") or not int(d.get("nb_plans") or 0):
                log.info("jobs.story.pas_encore", jour=jour,
                         reste=d.get("reste_a_venir"), nb_plans=d.get("nb_plans"))
                continue

            url = f"{base}/visuels/story.jpg?jour={jour}"
            resultat = await publier_story(url)

            # La ligne est écrite QUE ÇA MARCHE OU NON : un échec sans trace se répète
            # en silence, et personne ne saurait qu'un jeton a expiré.
            await session.execute(_text("""
                INSERT INTO publications_sociales
                    (publication_id, jour, canal, media_id, publie_at,
                     derniere_tentative_at, nb_tentatives, derniere_raison)
                VALUES (:id, :j, :c, :m, :p, :maintenant, 1, :r)
                ON CONFLICT (jour, canal) DO UPDATE SET
                    media_id = COALESCE(EXCLUDED.media_id, publications_sociales.media_id),
                    publie_at = COALESCE(publications_sociales.publie_at, EXCLUDED.publie_at),
                    derniere_tentative_at = :maintenant,
                    nb_tentatives = publications_sociales.nb_tentatives + 1,
                    derniere_raison = EXCLUDED.derniere_raison
            """), {
                "id": str(_uuid.uuid4()), "j": jour, "c": CANAL_STORY,
                "maintenant": _dt.now(_tz.utc),
                "m": resultat.media_id,
                "p": _dt.now(_tz.utc) if resultat.publie else None,
                "r": (resultat.raison or "")[:300] or None,
            })
            await session.commit()

            log.info(
                "jobs.story.publication",
                jour=jour, actif=publication_active(), publie=bool(resultat),
                media_id=resultat.media_id, raison=resultat.raison, url=url,
                quota_restant=await quota_restant() if publication_active() else None,
            )
            # Une seule story par passage : deux d'un coup noieraient la plus récente.
            return

    log.info("jobs.story.rien_a_publier", candidats=candidats)


async def job_renouveler_jetons() -> None:
    """
    Prolonge le jeton Instagram avant son expiration.

    Un jeton longue durée Instagram vaut 60 jours. Sans ce job, la publication
    s'arrêterait sans prévenir deux mois après la mise en service, et personne ne s'en
    apercevrait avant des semaines. On passe tous les jours et on ne renouvelle qu'à
    l'approche de l'échéance : Instagram refuse un renouvellement trop précoce.
    """
    from db.database import AsyncSessionLocal
    from services.jetons import lire, renouveler_instagram, renouvellement_necessaire

    try:
        async with AsyncSessionLocal() as session:
            jeton = await lire(session)
            if jeton is None:
                log.info("jobs.jetons.aucun_jeton")
                return
            if not renouvellement_necessaire(jeton):
                log.info("jobs.jetons.pas_encore", expire_at=str(jeton.expire_at))
                return
            ok, raison = await renouveler_instagram(session)
            log.info("jobs.jetons.renouvellement", ok=ok, raison=raison)
    except Exception as e:  # noqa: BLE001
        log.warning("jobs.jetons.echec", err=str(e)[:200])


# Au-delà de ce délai sans rapport de retrain envoyé, le filet prend le relais.
# 26 h : une nuit complète de marge au cron de 05:00 UTC, sans jamais laisser
# passer deux matins de suite.
FILET_RAPPORT_APRES_H = 26


async def job_filet_rapport_retrain() -> None:
    """Envoie le rapport de retrain si le cron de l'HÔTE ne l'a pas fait.

    Le rapport du matin est le garde-fou du retrain. Mais il est lancé par un
    cron système, hors Docker : le 2026-08-19, ce cron n'a jamais tourné parce
    que le script n'était pas exécutable — des semaines sans aucun e-mail, et
    l'absence d'e-mail ne fait pas de bruit. Un garde-fou qui peut disparaître
    en silence n'en est pas un.

    Ce filet vit dans le scheduler, qui tourne 24 h/24 dans Docker et se relance
    tout seul. Il ne double JAMAIS le cron : il lit d'abord l'état persistant
    laissé par le dernier envoi et ne fait rien si un rapport est parti dans les
    dernières 26 h. Le rapport qu'il envoie est le même, en un peu plus pauvre —
    il n'a pas accès à `docker logs` — mais son verdict, lui, vient de la base
    et vaut exactement celui du cron.
    """
    import os
    from datetime import datetime, timedelta, timezone

    from db.database import AsyncSessionLocal

    try:
        from ml.learning_steps import dernier_run
        async with AsyncSessionLocal() as session:
            run = await dernier_run(session, "rapport_retrain")
        dernier = (run or {}).get("last_success_at")
        if dernier is not None:
            if dernier.tzinfo is None:
                dernier = dernier.replace(tzinfo=timezone.utc)
            limite = datetime.now(timezone.utc) - timedelta(hours=FILET_RAPPORT_APRES_H)
            if dernier > limite:
                log.info("jobs.filet_rapport.deja_envoye", dernier=str(dernier))
                return

        log.warning("jobs.filet_rapport.cron_muet", dernier=str(dernier))
        # `BT_RAPPORT_CANAL` distingue les deux canaux dans le journal : un
        # rapport « filet » deux matins de suite dit que le cron de l'hôte est
        # mort, ce que le rapport lui-même ne peut pas raconter.
        os.environ["BT_RAPPORT_CANAL"] = "filet"
        from scripts.check_retrain_nightly import main as rapport_retrain
        await rapport_retrain()
    except Exception as e:  # noqa: BLE001
        log.warning("jobs.filet_rapport.echec", err=str(e)[:200])
