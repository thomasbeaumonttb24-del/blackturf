"""
Orchestrateur de scraping BlackTurf.
Coordonne tous les scrapers selon les priorités du CDC.

Fréquences :
  PMU API           → toutes 3 min  (CRITIQUE)
  Zeturf cotes      → toutes 5 min  (HAUTE — value bets)
  Bookmakers        → toutes 5 min  (HAUTE — Winamax/Betclic/Unibet/Betfair)
  Pool PMU          → toutes 5 min  (HAUTE — smart money)
  Geny              → toutes 10 min (HAUTE)
  Letrot            → toutes 15 min (HAUTE)
  Pronostics presse → toutes 30 min (MOYENNE — Paris-Turf/CanalTurf)
  Turfoo            → toutes 30 min (MOYENNE)
  Météo             → toutes 30 min (MOYENNE)
  France Galop      → toutes 60 min (BASSE — pénétromètre + suspensions)
  Racing Post       → 1x/jour matin (BASSE — chevaux importés)
  Associations J×E  → 1x/semaine   (TRÈS BASSE — calcul interne)
"""
import asyncio
import argparse
import os
import threading
import time
import structlog
from datetime import datetime

from api.config import get_settings
from services.temps_courses import jour_courses
from db.database import AsyncSessionLocal
from scraper.base import make_stealth_browser
from scraper.sources.pmu import PmuScraper
from scraper.sources.geny import GenyScraper
from scraper.sources.letrot import LetrotScraper
from scraper.sources.turfoo import TurfooScraper
from scraper.sources.zeturf import ZeturfScraper
from scraper.sources.meteo import MeteoScraper
from scraper.sources.winamax import WinamaxScraper
from scraper.sources.betclic import BetclicScraper
from scraper.sources.unibet import UnibetScraper
from scraper.sources.france_galop import FranceGalopScraper
from scraper.sources.paris_turf import ParisTurfScraper
from scraper.sources.racing_post import RacingPostScraper
from scraper.db_writer import (
    save_course_to_db,
    save_resultat_to_db,
    save_historique_pmu,
    save_meteo_to_db,
    log_scrape_result,
    save_cote_bookmaker,
    save_pool_pmu,
    save_enjeux_course,
    save_suspension,
    save_penetrometre,
    save_temps_passage,
    save_pronostic_presse,
    save_genealogie,
    save_running_style,
    compute_and_save_jockey_entraineur_assoc,
    detect_jockey_change,
    compute_jours_depuis_derniere,
    resolve_bookmaker_course_id,
    resolve_presse_course_id,
    compute_and_save_acteur_stats,
)

log = structlog.get_logger()
settings = get_settings()


# ── Anti-gel du daemon ────────────────────────────────────────────────────────
# Le 2026-08-11 à 22:59 le daemon s'est figé dans run_bookmakers_cycle (page
# Playwright bloquée). Aucune exception n'a été levée : le try/except de
# run_daemon n'a rien vu, `restart: unless-stopped` ne relance qu'un process
# MORT, et le conteneur n'avait pas de healthcheck. Résultat : 4 j 16 h sans une
# seule course en base, sans la moindre alerte (0 ligne dans system_errors).
#
# Trois lignes de défense, de la plus douce à la plus brutale :
#   1. asyncio.wait_for  — annule un cycle bloqué sur un await annulable ;
#   2. watchdog THREAD   — tue le process quand l'annulation elle-même se bloque
#                          (cas Playwright) ou que la boucle asyncio est starvée ;
#   3. heartbeat fichier — lu par le healthcheck Docker, rend le gel VISIBLE.
CYCLE_TIMEOUT_S = int(os.getenv("BT_SCRAPER_CYCLE_TIMEOUT", "1200"))  # 20 min
# Marge avant le kill dur : laisse wait_for tenter l'annulation propre d'abord,
# sinon les deux mécanismes se déclencheraient au même instant (course).
WATCHDOG_GRACE_S = int(os.getenv("BT_SCRAPER_WATCHDOG_GRACE", "120"))
HEARTBEAT_PATH = os.getenv("BT_SCRAPER_HEARTBEAT", "/app/data/scraper_heartbeat")

# Durée de conservation d'un job post-course RATÉ dans la FailedJobRegistry de RQ.
# Le défaut de RQ est UN AN : la file de production en avait accumulé 527 depuis
# juin 2026, dont les causes (libgomp manquant, dtypes XGBoost) étaient corrigées
# depuis longtemps — mais leur seul décompte continuait de nourrir l'alerte
# qualité. 7 jours : assez pour diagnostiquer, trop court pour devenir un passif.
POST_COURSE_FAILURE_TTL_S = 7 * 24 * 3600

# Monotonic du début du cycle en cours ; None = aucun cycle en vol.
_cycle_started_at: float | None = None


def _write_heartbeat() -> None:
    """Marque « un cycle vient d'aboutir ». Best-effort : jamais fatal."""
    try:
        parent = os.path.dirname(HEARTBEAT_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(HEARTBEAT_PATH, "w") as fh:
            fh.write(str(time.time()))
    except Exception as e:  # un heartbeat raté ne doit pas tuer le scraping
        log.warning("orchestrator.heartbeat_failed", error=str(e)[:160])


def _start_cycle_watchdog() -> None:
    """Tue le process si un cycle dépasse CYCLE_TIMEOUT_S + WATCHDOG_GRACE_S.

    Un THREAD, pas une task asyncio : si la boucle d'événements est bloquée, une
    task ne s'exécuterait jamais — c'est exactement le mode de panne du 11/08.
    `os._exit` court-circuite atexit/finally À DESSEIN : on veut sortir même si
    c'est `await browser.close()` qui est lui-même bloqué. Docker relance
    derrière un process propre (restart: unless-stopped).
    """
    deadline = CYCLE_TIMEOUT_S + WATCHDOG_GRACE_S

    def _loop() -> None:
        while True:
            time.sleep(30)
            started = _cycle_started_at
            if started is None:
                continue
            elapsed = time.monotonic() - started
            if elapsed > deadline:
                log.error("orchestrator.watchdog_kill",
                          elapsed_s=int(elapsed), deadline_s=deadline)
                os._exit(1)

    threading.Thread(target=_loop, name="cycle-watchdog", daemon=True).start()
    log.info("orchestrator.watchdog_started",
             timeout_s=CYCLE_TIMEOUT_S, deadline_s=deadline)


async def _detect_smart_money(session, course_id: str) -> None:
    """
    Détecte les mouvements de 'smart money' sur un pool PMU.
    Si le pool a augmenté de >20% en 15 min sur un cheval : flag SPI.
    """
    from sqlalchemy import text
    result = await session.execute(text("""
        SELECT pool_total_centimes, scraped_at
        FROM pool_pmu_historique
        WHERE course_id = :course_id
        ORDER BY scraped_at DESC
        LIMIT 5
    """), {"course_id": course_id})
    rows = result.fetchall()
    if len(rows) < 2:
        return

    latest = rows[0].pool_total_centimes or 0
    prev = rows[-1].pool_total_centimes or 0
    if prev > 0 and (latest - prev) / prev > 0.20:
        log.info("smart_money.detected", course_id=course_id,
                 variation_pct=round((latest - prev) / prev * 100, 1))


# Fenêtre de relevé des enjeux par cheval, autour de l'heure de départ.
# Avant T-4 h la masse est quasi nulle et ne bouge pas ; après le départ le PMU
# fige les enjeux (on garde 15 min pour capter la photo finale, qui est celle qui
# fixe les rapports).
ENJEUX_AVANT_MIN = 4 * 60
ENJEUX_APRES_MIN = 15


def _fenetre_enjeux(date_heure, *, maintenant=None) -> bool:
    """Vrai si la course est dans la fenêtre où ses enjeux évoluent.

    `date_heure` vient du PMU : epoch ms (int ou str) ou ISO. Format inattendu →
    True : mieux vaut un relevé de trop qu'un trou dans la série.
    """
    from datetime import datetime as _dt, timezone as _tz
    now = maintenant or _dt.now(_tz.utc)
    depart = None
    try:
        if isinstance(date_heure, (int, float)):
            depart = _dt.fromtimestamp(date_heure / 1000, tz=_tz.utc)
        elif isinstance(date_heure, str) and date_heure.isdigit() and len(date_heure) > 10:
            depart = _dt.fromtimestamp(int(date_heure) / 1000, tz=_tz.utc)
        elif isinstance(date_heure, _dt):
            depart = date_heure
        elif date_heure:
            depart = _dt.fromisoformat(str(date_heure))
    except (ValueError, OSError, OverflowError):
        depart = None
    if depart is None:
        return True
    if depart.tzinfo is None:
        depart = depart.replace(tzinfo=_tz.utc)
    minutes = (depart - now).total_seconds() / 60.0
    return -ENJEUX_APRES_MIN <= minutes <= ENJEUX_AVANT_MIN


def _is_deadlock(exc: Exception) -> bool:
    """Vrai si l'exception est un deadlock PostgreSQL (transitoire, à rejouer)."""
    s = (str(getattr(exc, "orig", "")) + " " + str(exc)).lower()
    return "deadlock detected" in s or "deadlockdetected" in s


class BlackTurfOrchestrator:
    """Orchestre tous les scrapers avec retry et monitoring."""

    # Backoff adaptatif par source : après N échecs consécutifs, l'intervalle
    # effectif est multiplié par BACKOFF_BASE**N (plafonné à BACKOFF_MAX_MULT).
    # Une source bannie/down se met donc en retrait au lieu d'être martelée à
    # pleine cadence (ce qui accélère les bans).
    BACKOFF_BASE: int = 2
    BACKOFF_MAX_MULT: int = 8  # ex : pmu 3 min → jusqu'à 24 min en cas d'échecs

    def __init__(self):
        self._last_scrape: dict[str, float] = {}
        # Nb d'échecs consécutifs par source (drive le backoff exponentiel).
        self._consecutive_errors: dict[str, int] = {}
        # Sources ayant échoué pendant le run_once courant (reset à chaque cycle).
        self._failed_this_cycle: set[str] = set()
        base_intervals = {
            "pmu":           3 * 60,    # 3 min  — CRITIQUE
            "resultats":     3 * 60,    # 3 min  — poll arrivées (courses finies)
            "predictions":   8 * 60,    # 8 min  — (re)calcul prédictions/value bets du jour
            "zeturf":        5 * 60,    # 5 min  — VB
            "bookmakers":    5 * 60,    # 5 min  — Winamax/Betclic/Unibet/Betfair
            "pool_pmu":      5 * 60,    # 5 min  — smart money
            "geny":         10 * 60,    # 10 min
            "letrot":       15 * 60,    # 15 min
            "paris_turf":   30 * 60,    # 30 min — pronostics presse
            "turfoo":       30 * 60,    # 30 min
            "meteo":        30 * 60,    # 30 min
            "france_galop": 60 * 60,    # 60 min — pénétromètre + suspensions
            "racing_post":  24 * 3600,  # 1x/jour — chevaux importés
            "associations":  7 * 86400, # 1x/semaine — calcul interne J×E
        }

        # ── Mode starter (démarrage prudent, sans proxy) ─────────────────────
        # SCRAPER_INTERVAL_MULTIPLIER : ralentit toutes les sources (2.0 = ×2 →
        #   moitié moins de requêtes = moins de risque de ban au démarrage).
        # SCRAPER_DISABLED_SOURCES   : CSV des sources à NE PAS scraper
        #   (ex. "racing_post,france_galop" pour les sites les plus protégés).
        #
        # Sources mises en sommeil le 18/08/2026 après vérification une par une
        # depuis le conteneur — elles produisaient TOUTES 0 cote sur 7 jours :
        #   geny     : geny.com répond « Accès refusé » y compris avec le
        #              navigateur furtif (HTTP 200 dont le corps est une page
        #              d'erreur 403). Seul un solve_cloudflare via scrapling y
        #              accède, et scrapling n'est pas dans cette image.
        #   betclic  : HTTP 403 « Accès refusé - Betclic », navigateur furtif inclus.
        #   winamax  : la page /courses-hippiques répond 200 mais ne contient plus
        #              aucun lien de course — la rubrique a disparu de cette URL.
        #   unibet   : unibet.fr/turf redirige vers zeturf.fr ; la source est déjà
        #              couverte par le daemon zeturf (cote_unibet, 73 % de
        #              couverture). Le scraper retourne [] depuis 2026-06.
        # Aucune donnée perdue : elles n'en fournissaient plus. Les réactiver
        # demande de traiter le blocage (proxy résidentiel ou solve_cloudflare),
        # pas de corriger un sélecteur.
        try:
            mult = float(os.environ.get("SCRAPER_INTERVAL_MULTIPLIER", "1.0"))
        except ValueError:
            mult = 1.0
        mult = max(1.0, mult)  # jamais plus agressif que le défaut
        self._intervals = {k: int(v * mult) for k, v in base_intervals.items()}

        disabled = os.environ.get("SCRAPER_DISABLED_SOURCES", "")
        self._disabled = {s.strip().lower() for s in disabled.split(",") if s.strip()}
        if self._disabled:
            log.info("orchestrator.sources_disabled", sources=sorted(self._disabled))
        if mult > 1.0:
            log.info("orchestrator.starter_mode", interval_multiplier=mult)

        self._courses_today: list = []

    def _backoff_mult(self, source: str) -> int:
        """Multiplicateur d'intervalle selon le nb d'échecs consécutifs (plafonné)."""
        streak = self._consecutive_errors.get(source, 0)
        if streak <= 0:
            return 1
        return min(self.BACKOFF_BASE ** streak, self.BACKOFF_MAX_MULT)

    def _should_run(self, source: str) -> bool:
        if source in self._disabled:
            return False
        last = self._last_scrape.get(source, 0)
        interval = self._intervals.get(source, 300) * self._backoff_mult(source)
        return (time.time() - last) >= interval

    def _mark_done(self, source: str) -> None:
        """Met à jour le timestamp + l'état de backoff selon l'issue du cycle.

        Lit ``_failed_this_cycle`` (alimenté par ``_log_error``) : échec →
        incrémente la série d'erreurs (backoff plus long) ; succès → reset.
        """
        self._last_scrape[source] = time.time()
        if source in self._failed_this_cycle:
            self._consecutive_errors[source] = self._consecutive_errors.get(source, 0) + 1
            log.warning(
                "orchestrator.source_backoff",
                source=source,
                consecutive_errors=self._consecutive_errors[source],
                next_interval_mult=self._backoff_mult(source),
            )
        else:
            if self._consecutive_errors.get(source, 0) > 0:
                log.info("orchestrator.source_recovered", source=source)
            self._consecutive_errors[source] = 0

    async def _log_error(self, source: str, exc: Exception) -> None:
        """Enregistre l'échec d'un cycle : marque la source (backoff) + trace
        une ligne ``erreur`` dans ``scrape_log`` (visible côté /admin).

        Centralise le logging d'erreur — avant, la plupart des cycles ne
        traçaient que les succès, rendant les bans invisibles dans /scrape-status.
        """
        self._failed_this_cycle.add(source)
        try:
            async with AsyncSessionLocal() as session:
                await log_scrape_result(session, source, "erreur", erreur=str(exc)[:500])
                await session.commit()
        except Exception as log_exc:  # ne jamais laisser le logging casser le cycle
            log.error("orchestrator.log_error_failed", source=source, err=str(log_exc)[:120])

    async def _log_ok(self, source: str, *, nb_courses: int = 0, duree_ms: int = 0) -> None:
        """Trace une ligne ``ok`` dans scrape_log → la source repasse au vert dans /admin
        dès qu'un cycle réussit (sinon, sans log de succès, l'UI reste figée sur l'erreur)."""
        try:
            async with AsyncSessionLocal() as session:
                await log_scrape_result(session, source, "ok",
                                        nb_courses=nb_courses, duree_ms=duree_ms)
                await session.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("orchestrator.log_ok_failed", source=source, err=str(e)[:120])

    async def _commit_unit(self, work, *, retries: int = 4) -> bool:
        """Exécute ``work(session)`` dans une transaction ISOLÉE puis commit, avec retry
        sur DEADLOCK (PostgreSQL tue une des 2 transactions concurrentes → on rejoue après
        un court backoff). De PETITES transactions par unité (course) = fenêtre de lock
        minimale → on n'a plus le deadlock chronique de resultats/pool_pmu (1 grosse txn sur
        toutes les courses, en concurrence avec le poller par-course + le cycle PMU)."""
        for attempt in range(retries):
            try:
                async with AsyncSessionLocal() as session:
                    await work(session)
                    await session.commit()
                return True
            except Exception as e:  # noqa: BLE001
                if _is_deadlock(e) and attempt < retries - 1:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise
        return False

    async def run_pmu_cycle(self) -> None:
        """Cycle PMU : récupère programme + cotes live + résultats."""
        t0 = time.time()
        log.info("orchestrator.pmu_start")

        pmu = PmuScraper(proxy=settings.brightdata_proxy if hasattr(settings, "brightdata_proxy") else None)
        try:
            courses = await pmu.get_programme_today()
            self._courses_today = courses

            nb_partants_total = 0
            scratched_courses: set[str] = set()   # courses où un cheval vient d'être déclaré non-partant
            for course in courses:
                r_id = course.reunion_id
                c_num = int(course.course_id.split("C")[-1])

                # Enrichir les partants (endpoint /participants — programme seul
                # ne les contient pas). Attache avant la sauvegarde.
                try:
                    partants = await pmu.enrich_partants(r_id, c_num)
                    if partants:
                        course.partants = partants
                        course.nb_partants = len(partants)
                except Exception as e:
                    log.warning("orchestrator.enrich_partants_failed",
                                course_id=course.course_id, err=str(e))

                # Session + commit PAR COURSE : isole une course fautive et
                # commit toutes les bonnes (sinon 1 erreur avorte tout le cycle).
                try:
                    async with AsyncSessionLocal() as session:
                        scratched_cid = await save_course_to_db(session, course)
                        if scratched_cid:
                            scratched_courses.add(scratched_cid)
                        if course.date_heure:
                            # préfixe date du course_id (ddmmyyyy) → garantit que le
                            # course_id du résultat == celui de la course stockée
                            cid_prefix = course.course_id[:8] if course.course_id[:8].isdigit() else course.date_heure
                            resultat = await pmu.get_rapports_definitifs(r_id, c_num, cid_prefix)
                            if resultat and resultat.ordre_arrivee:
                                await save_resultat_to_db(session, resultat)
                        await session.commit()
                    nb_partants_total += len(course.partants)

                    # Historique détaillé des partants (courses passées) →
                    # alimente features ML + confrontations directes (robuste PMU).
                    try:
                        histo = await pmu.get_historique_chevaux(r_id, c_num)
                        async with AsyncSessionLocal() as hs:
                            for h in histo:
                                await save_historique_pmu(hs, h["cheval_nom"], h["courses"])
                            await hs.commit()
                    except Exception as e:
                        log.warning("orchestrator.historique_failed",
                                    course_id=course.course_id, err=str(e)[:120])
                except Exception as e:
                    log.error("orchestrator.course_save_failed",
                              course_id=course.course_id, err=str(e)[:200])

            # ── NON-PARTANTS : régénérer le prono des courses touchées ──
            # Quand un cheval est déclaré non-partant, on recalcule immédiatement le
            # pronostic sur le champ restant (compute_all_features_for_course exclut
            # déjà non_partant=false → probas renormalisées). On appelle predict_course
            # DIRECTEMENT : le gel T-10 n'est imposé que par la requête du cycle
            # prédictions, pas ici → le prono est refait MÊME dans les 10 dernières
            # minutes, uniquement dans ce cas (exception au gel demandée).
            if scratched_courses:
                from ml.pipeline import predict_course
                for cid in scratched_courses:
                    try:
                        await predict_course(cid)
                        log.info("orchestrator.repredict_after_scratch", course_id=cid)
                    except Exception as e:
                        log.error("orchestrator.repredict_scratch_failed",
                                  course_id=cid, err=str(e)[:200])

            duree = int((time.time() - t0) * 1000)
            async with AsyncSessionLocal() as session:
                await log_scrape_result(
                    session, "pmu", "ok",
                    nb_courses=len(courses),
                    nb_partants=nb_partants_total,
                    duree_ms=duree,
                )
                await session.commit()

        except Exception as e:
            log.error("orchestrator.pmu_error", error=str(e))
            await self._log_error("pmu", e)
        finally:
            await pmu.close()

    async def run_geny_cycle(self, browser_context) -> None:
        """Cycle Geny : pronostics + cotes Geny."""
        t0 = time.time()
        log.info("orchestrator.geny_start")

        page = await browser_context.new_page()
        try:
            geny = GenyScraper(page)
            data = await geny.get_partants_du_jour()
            n_cotes = 0

            # Enrichir les cotes Geny en DB
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select, update
                from db.models import Participation, Course, Cheval

                for course_data in data:
                    for cheval_data in course_data.get("chevaux", []):
                        nom = cheval_data.get("nom", "").strip()
                        cote_str = cheval_data.get("cote_geny", "")
                        rang_geny = cheval_data.get("rang_pronostic_geny")
                        if not nom or not cote_str:
                            continue
                        try:
                            cote = float(str(cote_str).replace(",", "."))
                        except (ValueError, TypeError):
                            continue

                        # Mise à jour cote_geny (+ rang pronostic Geny) dans participations.
                        # Wiring 2026-06-17 : rang_pronostic_geny est une feature ML qui
                        # n'était JAMAIS alimentée (donnée extraite puis jetée). Le scraper
                        # httpx+bs4 la fournit désormais → on la persiste ici.
                        vals = {"cote_geny": cote}
                        if isinstance(rang_geny, int) and rang_geny > 0:
                            vals["rang_pronostic_geny"] = rang_geny
                        stmt = (
                            update(Participation)
                            .where(
                                Participation.cheval_id.in_(
                                    select(Cheval.cheval_id).where(Cheval.nom == nom)
                                )
                            )
                            .values(**vals)
                        )
                        await session.execute(stmt)
                        n_cotes += 1

                await session.commit()
                duree = int((time.time() - t0) * 1000)
                # Compteurs RÉELS + statut honnête : le cycle se journalisait « ok »
                # même quand Geny renvoyait sa page d'erreur en HTTP 200 (0 course
                # extraite). La source est ainsi restée muette des semaines sans
                # qu'aucune alerte ne parte.
                await log_scrape_result(
                    session, "geny",
                    "ok" if n_cotes else "erreur",
                    nb_courses=len(data),
                    nb_partants=n_cotes,
                    erreur=(None if n_cotes else
                            "aucune cote extraite (source bloquée ou structure changée)"),
                    duree_ms=duree,
                )
                await session.commit()
            if not n_cotes:
                # Alimente le backoff : inutile de marteler une source qui bloque.
                self._failed_this_cycle.add("geny")

        except Exception as e:
            log.error("orchestrator.geny_error", error=str(e))
            await self._log_error("geny", e)
        finally:
            await page.close()

    async def run_meteo_cycle(self) -> None:
        """Cycle météo pour tous les hippodromes du jour."""
        log.info("orchestrator.meteo_start")

        meteo_scraper = MeteoScraper()
        try:
            # Récupère les hippodromes des courses du jour
            hippodromes = list({c.hippodrome for c in self._courses_today})

            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                from db.models import Course as DBCourse

                for hippodrome in hippodromes:
                    meteo = await meteo_scraper.get_meteo(hippodrome)
                    if not meteo:
                        continue

                    # Récupérer les course_id de cet hippodrome aujourd'hui
                    from datetime import date
                    result = await session.execute(
                        select(DBCourse.course_id)
                        .where(
                            DBCourse.hippodrome_nom == hippodrome,
                            DBCourse.statut == "a_venir",
                        )
                    )
                    course_ids = [r[0] for r in result.fetchall()]

                    for course_id in course_ids:
                        await save_meteo_to_db(session, course_id, meteo)

                await session.commit()

        except Exception as e:
            log.error("orchestrator.meteo_error", error=str(e))
            await self._log_error("meteo", e)
        finally:
            await meteo_scraper.close()

    async def run_zeturf_cycle(self, browser_context) -> None:
        """Cycle Zeturf : cotes alternatives pour détection VB. Toutes les 5 min."""
        t0 = time.time()
        page = await browser_context.new_page()
        try:
            from scraper.sources.zeturf import ZeturfScraper
            scraper = ZeturfScraper(page)
            cotes_map = await scraper.get_cotes_du_jour()  # {course_id: {num: cote}}

            async with AsyncSessionLocal() as session:
                from sqlalchemy import update as sa_update
                from db.models import Participation, Cheval
                from sqlalchemy import select as sa_select

                for course_id, partants_cotes in cotes_map.items():
                    for numero, cote in partants_cotes.items():
                        stmt = (
                            sa_update(Participation)
                            .where(
                                Participation.course_id == course_id,
                                Participation.numero == int(numero),
                            )
                            .values(cote_bzh=float(cote), updated_at=datetime.now())
                        )
                        await session.execute(stmt)

                        # Aussi dans CoteHistorique
                        from db.models import CoteHistorique
                        pid_r = await session.execute(
                            sa_select(Participation.participation_id)
                            .where(Participation.course_id == course_id,
                                   Participation.numero == int(numero))
                        )
                        pid_row = pid_r.fetchone()
                        if pid_row:
                            session.add(CoteHistorique(
                                time=datetime.now(),
                                participation_id=pid_row[0],
                                source="zeturf",
                                cote=float(cote),
                            ))

                await session.commit()
                await log_scrape_result(
                    session, "zeturf", "ok",
                    nb_courses=len(cotes_map),
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()
        except Exception as e:
            log.error("orchestrator.zeturf_error", error=str(e))
            await self._log_error("zeturf", e)
        finally:
            await page.close()

    async def run_letrot_cycle(self, browser_context) -> None:
        """Cycle Letrot : fiches chevaux trot (meilleur temps, record hippodrome). Toutes les 15 min."""
        t0 = time.time()
        page = await browser_context.new_page()
        try:
            from scraper.sources.letrot import LetrotScraper
            scraper = LetrotScraper(page)

            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as sa_select
                from db.models import Cheval, Course, Participation, PerformanceCarriere

                # Chevaux trot d'aujourd'hui dont on n'a pas le meilleur temps
                result = await session.execute(sa_select(
                    Cheval.nom, Cheval.cheval_id,
                ).join(Participation, Participation.cheval_id == Cheval.cheval_id
                ).join(Course, Course.course_id == Participation.course_id
                ).where(
                    Course.discipline.in_(["Attelé", "Monté"]),
                    Course.statut == "a_venir",
                ))
                chevaux = result.fetchall()[:25]  # max 25/cycle

                for nom, cheval_id in chevaux:
                    fiche = await scraper.get_fiche_cheval(nom)
                    if not fiche:
                        continue
                    update_vals = {}
                    if fiche.get("meilleur_temps"):
                        update_vals["meilleur_temps_all"] = fiche["meilleur_temps"]
                    if fiche.get("record_hippodrome"):
                        update_vals["record_hippodrome_actuel"] = fiche["record_hippodrome"]
                    if update_vals:
                        from sqlalchemy import update as sa_update
                        await session.execute(
                            sa_update(PerformanceCarriere)
                            .where(PerformanceCarriere.cheval_id == cheval_id)
                            .values(**update_vals)
                        )

                await session.commit()
                await log_scrape_result(
                    session, "letrot", "ok",
                    nb_partants=len(chevaux),
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()
        except Exception as e:
            log.error("orchestrator.letrot_error", error=str(e))
            await self._log_error("letrot", e)
        finally:
            await page.close()

    async def run_turfoo_cycle(self, browser_context) -> None:
        """Cycle Turfoo : stats jockeys + entraîneurs. Toutes les 30 min."""
        t0 = time.time()
        page = await browser_context.new_page()
        try:
            from scraper.sources.turfoo import TurfooScraper
            scraper = TurfooScraper(page)

            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as sa_select
                from db.models import Jockey, Entraineur, StatsJockey, StatsEntraineur, gen_uuid
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                from datetime import datetime as dt

                saison = dt.now().year

                # Le ROI scrape n'ECRASE le ROI calcule que s'il vaut vraiment
                # quelque chose. Turfoo ne le publie pas (et 403 depuis le VPS) :
                # `stats.get("roi", 0.0)` ecrivait donc 0.0 par-dessus le ROI
                # calcule sur nos propres reglements, remettant la feature a plat.
                def _maj_roi(stats: dict, colonnes: dict) -> dict:
                    roi = stats.get("roi")
                    if isinstance(roi, (int, float)) and roi:
                        colonnes["roi_global"] = float(roi)
                    return colonnes

                # Jockeys du jour
                result = await session.execute(
                    sa_select(Jockey.jockey_id, Jockey.nom).distinct()
                )
                jockeys = result.fetchall()[:30]

                for jockey_id, nom in jockeys:
                    stats = await scraper.get_stats_jockey(nom)
                    if not stats:
                        continue
                    stmt = pg_insert(StatsJockey).values(
                        stat_id=gen_uuid(),
                        jockey_id=jockey_id,
                        saison=saison,
                        victoires_saison=stats.get("victoires_saison", 0),
                        taux_victoire_global=stats.get("taux_victoire", 0.0),
                        taux_place_global=stats.get("taux_place", 0.0),
                        taux_par_distance=stats.get("stats_par_distance"),
                        taux_par_hippodrome=stats.get("stats_par_hippodrome"),
                        taux_par_terrain=stats.get("stats_par_terrain"),
                        **_maj_roi(stats, {}),
                    ).on_conflict_do_update(
                        constraint="stats_jockeys_jockey_id_saison_key",
                        set_=_maj_roi(stats, {
                            "victoires_saison": stats.get("victoires_saison", 0),
                            "taux_victoire_global": stats.get("taux_victoire", 0.0),
                            "updated_at": datetime.now(),
                        }),
                    )
                    await session.execute(stmt)

                # Entraîneurs du jour
                result = await session.execute(
                    sa_select(Entraineur.entraineur_id, Entraineur.nom).distinct()
                )
                entraineurs = result.fetchall()[:20]

                for entraineur_id, nom in entraineurs:
                    stats = await scraper.get_stats_entraineur(nom)
                    if not stats:
                        continue
                    stmt = pg_insert(StatsEntraineur).values(
                        stat_id=gen_uuid(),
                        entraineur_id=entraineur_id,
                        saison=saison,
                        victoires_saison=stats.get("victoires_saison", 0),
                        taux_victoire_global=stats.get("taux_victoire", 0.0),
                        taux_place_global=stats.get("taux_place", 0.0),
                        taux_par_distance=stats.get("stats_par_distance"),
                        taux_par_hippodrome=stats.get("stats_par_hippodrome"),
                        **_maj_roi(stats, {}),
                    ).on_conflict_do_update(
                        constraint="stats_entraineurs_entraineur_id_saison_key",
                        set_=_maj_roi(stats, {
                            "victoires_saison": stats.get("victoires_saison", 0),
                            "taux_victoire_global": stats.get("taux_victoire", 0.0),
                            "updated_at": datetime.now(),
                        }),
                    )
                    await session.execute(stmt)

                await session.commit()
                await log_scrape_result(
                    session, "turfoo", "ok",
                    nb_partants=len(jockeys) + len(entraineurs),
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()
        except Exception as e:
            log.error("orchestrator.turfoo_error", error=str(e))
            await self._log_error("turfoo", e)
        finally:
            await page.close()

    async def run_bookmakers_cycle(self, browser_context) -> None:
        """
        Cycle bookmakers alternatifs : Winamax, Betclic, Unibet, Betfair Exchange.
        Toutes les 5 min — même fréquence que Zeturf pour VB detection étendue.
        """
        t0 = time.time()
        log.info("orchestrator.bookmakers_start")
        nb_total = 0

        scrapers = [
            ("winamax", WinamaxScraper),
            ("betclic", BetclicScraper),
            ("unibet", UnibetScraper),
        ]

        for source_name, ScraperClass in scrapers:
            # Gating PAR BOOKMAKER : `_should_run` ne filtre que le groupe
            # « bookmakers », si bien qu'un bookmaker mis dans
            # SCRAPER_DISABLED_SOURCES continuait d'être ouvert, chargé et
            # attendu à chaque cycle — pour rien, et en polluant scrape_log.
            if source_name in self._disabled:
                log.info("orchestrator.bookmaker_disabled", source=source_name)
                continue
            page = await browser_context.new_page()
            nb_source = 0
            try:
                scraper = ScraperClass(page)

                if source_name == "betclic":
                    data = await scraper.get_cotes_du_jour()
                    cotes_list = data.get("actuelles", []) + data.get("ouvertures", [])
                else:
                    cotes_list = await scraper.get_cotes_du_jour()

                async with AsyncSessionLocal() as session:
                    for cote_scrape in cotes_list:
                        # Résoudre le pseudo course_id en course_id PMU réel
                        parts = cote_scrape.course_id.split("_")
                        hippodrome_hint = parts[1] if len(parts) > 1 else ""
                        time_hint = parts[2] if len(parts) > 2 else ""

                        real_course_id = await resolve_bookmaker_course_id(
                            session, hippodrome_hint, time_hint
                        )
                        if not real_course_id:
                            continue

                        # Trouver la participation correspondante (par nom ou numéro)
                        from sqlalchemy import select as sa_select
                        from db.models import Participation, Cheval
                        stmt = sa_select(Participation.participation_id).join(
                            Cheval, Participation.cheval_id == Cheval.cheval_id
                        ).where(
                            Participation.course_id == real_course_id,
                            Cheval.nom == cote_scrape.nom,
                        )
                        result = await session.execute(stmt)
                        pid_row = result.fetchone()
                        if not pid_row:
                            continue

                        await save_cote_bookmaker(
                            session, cote_scrape, pid_row[0], real_course_id
                        )
                        nb_total += 1
                        nb_source += 1

                    await session.commit()
                    # Compteurs RÉELS : ils n'étaient jamais transmis, si bien que
                    # scrape_log enregistrait 0 partant même pour un scrape réussi.
                    # Un bookmaker bloqué (Betclic 403, Winamax sans contenu
                    # hippique) apparaissait donc « ok » indéfiniment, et la panne
                    # restait invisible côté back-office. `nb_extrait` distingue en
                    # plus « rien récupéré du site » de « récupéré mais non
                    # rattaché à une participation connue ».
                    await log_scrape_result(
                        session, source_name,
                        "ok" if nb_source else "erreur",
                        nb_partants=nb_source,
                        erreur=(None if nb_source else
                                f"aucune cote enregistrée ({len(cotes_list)} extraite(s) "
                                "du site, 0 rattachée à une participation)"),
                        duree_ms=int((time.time() - t0) * 1000),
                    )
                    await session.commit()

            except Exception as e:
                log.error(f"orchestrator.{source_name}_error", error=str(e))
                await self._log_error(source_name, e)
            finally:
                await page.close()

        log.info("orchestrator.bookmakers_done", nb_cotes=nb_total)

    async def run_pool_pmu_cycle(self) -> None:
        """
        Cycle pool PMU : récupère le volume total misé pour chaque course du jour.
        Indicateur de 'smart money' (argent professionnel).
        """
        log.info("orchestrator.pool_pmu_start")
        pmu = PmuScraper()
        t0 = time.time()
        try:
            # Une transaction PAR COURSE + retry deadlock (cf. poll_resultats) : pool_pmu
            # écrit pool_pmu_historique pendant que d'autres cycles touchent les mêmes
            # courses → la grosse txn globale deadlockait. Petites txns isolées = robuste.
            ok_n = 0
            enjeux_n = 0
            for course in self._courses_today:
                try:
                    pool_data = await pmu.get_pool_data(course.reunion_id, course.course_id)

                    # Enjeux PAR CHEVAL : uniquement dans la fenêtre où ils bougent.
                    # Une course à J+6 h a une masse figée à quelques centaines
                    # d'euros ; relever toutes les 5 min toute la journée écrirait
                    # des relevés identiques (filtrés en écriture, mais payés en
                    # requêtes PMU). Cf. _fenetre_enjeux.
                    vue = None
                    if _fenetre_enjeux(course.date_heure):
                        vue = await pmu.get_enjeux_par_cheval(
                            course.reunion_id, course.course_id,
                            nb_partants=getattr(course, "nb_partants", None) or None,
                        )

                    if pool_data or vue:
                        async def _w(session, _pd=pool_data, _cid=course.course_id, _vue=vue):
                            nonlocal enjeux_n
                            if _pd:
                                await save_pool_pmu(session, _pd)
                                await _detect_smart_money(session, _cid)  # smart money indicator
                            if _vue and await save_enjeux_course(session, _cid, _vue):
                                enjeux_n += 1
                        if await self._commit_unit(_w):
                            ok_n += 1
                except Exception as e:
                    log.warning("orchestrator.pool_pmu_course_failed",
                                course_id=course.course_id, err=str(e)[:160])
            log.info("orchestrator.pool_pmu_done", nb_courses=ok_n, nb_releves_enjeux=enjeux_n)
            await self._log_ok("pool_pmu", nb_courses=ok_n, duree_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            log.error("orchestrator.pool_pmu_error", error=str(e))
            await self._log_error("pool_pmu", e)
        finally:
            await pmu.close()

    async def run_france_galop_cycle(self, browser_context) -> None:
        """
        Cycle France Galop : pénétromètre + suspensions + généalogie des chevaux du jour.
        Toutes les 60 min.
        """
        t0 = time.time()
        log.info("orchestrator.france_galop_start")
        page = await browser_context.new_page()
        try:
            fg = FranceGalopScraper(page)

            async with AsyncSessionLocal() as session:
                # 1. Pénétromètre pour les réunions du jour
                penetros = await fg.get_penetrometre_du_jour()
                for pen in penetros:
                    if pen.reunion_id:
                        await save_penetrometre(session, pen)

                # 2. Suspensions officielles
                suspensions = await fg.get_suspensions()
                for susp in suspensions:
                    await save_suspension(session, susp)

                # 3. Généalogie des chevaux sans généalogie
                from sqlalchemy import select as sa_select
                from db.models import Cheval
                stmt = sa_select(Cheval.nom).where(
                    Cheval.pere.is_(None),
                    Cheval.pays_naissance == "FR",
                )
                result = await session.execute(stmt)
                chevaux_sans_pedigree = [r[0] for r in result.fetchall()[:20]]  # max 20/cycle

                for nom in chevaux_sans_pedigree:
                    gen = await fg.get_genealogie(nom)
                    if gen:
                        await save_genealogie(session, gen)

                # 4. Running style pour les chevaux du jour sans style défini
                stmt = sa_select(Cheval.nom).where(Cheval.running_style.is_(None))
                result = await session.execute(stmt)
                chevaux_sans_style = [r[0] for r in result.fetchall()[:15]]

                for nom in chevaux_sans_style:
                    rs = await fg.get_running_style(nom)
                    if rs:
                        await save_running_style(session, rs)

                await session.commit()
                duree = int((time.time() - t0) * 1000)
                await log_scrape_result(
                    session, "france_galop", "ok",
                    nb_courses=len(penetros),
                    nb_partants=len(suspensions),
                    duree_ms=duree,
                )
                await session.commit()

        except Exception as e:
            log.error("orchestrator.france_galop_error", error=str(e))
            await self._log_error("france_galop", e)
        finally:
            await page.close()

    async def run_paris_turf_cycle(self, browser_context) -> None:
        """
        Cycle Paris-Turf + CanalTurf : pronostics journalistes.
        Toutes les 30 min.
        """
        t0 = time.time()
        log.info("orchestrator.paris_turf_start")
        page = await browser_context.new_page()
        try:
            scraper = ParisTurfScraper(page)
            all_pronos = []

            pt_pronos = await scraper.get_pronostics_paris_turf()
            ct_pronos = await scraper.get_pronostics_canalturf()
            eq_pronos = await scraper.get_pronostics_equidia()
            all_pronos = pt_pronos + ct_pronos + eq_pronos

            import re as _re
            async with AsyncSessionLocal() as session:
                nb_saved = 0
                for prono in all_pronos:
                    # Résolution course_id : priorité au suffixe R{r}C{c} (EXACT,
                    # encodé par les scrapers presse 2026-06-17), repli sur
                    # l'hippodrome. Avant, l'heure vide → 0 match → presse perdue.
                    real_course_id = None
                    m = _re.search(r"_R(\d+)C(\d+)$", prono.course_id)
                    if m:
                        real_course_id = await resolve_presse_course_id(
                            session, int(m.group(1)), int(m.group(2))
                        )
                    if not real_course_id:
                        parts = prono.course_id.split("_")
                        hippodrome_hint = parts[1] if len(parts) > 1 else ""
                        real_course_id = await resolve_bookmaker_course_id(
                            session, hippodrome_hint, ""
                        )
                    if real_course_id:
                        await save_pronostic_presse(session, prono, real_course_id)
                        nb_saved += 1

                await session.commit()
                log.info("orchestrator.presse_saved", scraped=len(all_pronos), saved=nb_saved)
                await log_scrape_result(
                    session, "paris_turf", "ok",
                    nb_courses=nb_saved,
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()

        except Exception as e:
            log.error("orchestrator.paris_turf_error", error=str(e))
            await self._log_error("paris_turf", e)
        finally:
            await page.close()

    async def run_racing_post_cycle(self, browser_context) -> None:
        """
        Cycle Racing Post : généalogie et historique des chevaux importés.
        1x/jour au matin.
        """
        t0 = time.time()
        log.info("orchestrator.racing_post_start")
        page = await browser_context.new_page()
        try:
            scraper = RacingPostScraper(page)

            async with AsyncSessionLocal() as session:
                # Chevaux sans généalogie et d'origine étrangère (non FR)
                from sqlalchemy import select as sa_select
                from db.models import Cheval
                stmt = sa_select(Cheval.cheval_id, Cheval.nom, Cheval.racing_post_url).where(
                    Cheval.pere.is_(None),
                    Cheval.pays_naissance != "FR",
                )
                result = await session.execute(stmt)
                chevaux = result.fetchall()[:30]  # max 30/jour

                for cheval_id, nom, rp_url in chevaux:
                    gen = await scraper.get_genealogie(nom)
                    if gen:
                        await save_genealogie(session, gen)

                    # Sauvegarder l'URL Racing Post sur le cheval — par PK (évite les homonymes)
                    fiche = await scraper.get_fiche_cheval(nom, rp_url)
                    if fiche and fiche.get("racing_post_url"):
                        from sqlalchemy import update as sa_update
                        from db.models import Cheval as ChevalModel
                        await session.execute(
                            sa_update(ChevalModel)
                            .where(ChevalModel.cheval_id == cheval_id)
                            .values(racing_post_url=fiche["racing_post_url"])
                        )

                await session.commit()
                await log_scrape_result(
                    session, "racing_post", "ok",
                    nb_partants=len(chevaux),
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()

        except Exception as e:
            log.error("orchestrator.racing_post_error", error=str(e))
            await self._log_error("racing_post", e)
        finally:
            await page.close()

    async def run_associations_cycle(self) -> None:
        """
        Calcule et sauvegarde les associations jockey × entraîneur.
        1x/semaine — pas de scraping, calcul interne.
        """
        log.info("orchestrator.associations_start")
        from datetime import datetime as dt
        saison = dt.now().year
        try:
            async with AsyncSessionLocal() as session:
                nb_paires = await compute_and_save_jockey_entraineur_assoc(session, saison)
                await session.commit()
                # Stats globales jockey/entraîneur calculées depuis nos résultats
                # (Turfoo 403 → tables à 0 sinon → features qualité acteur mortes).
                nb_jockeys, nb_entraineurs = await compute_and_save_acteur_stats(session)
                await session.commit()
                # VOLUME RÉELLEMENT PRODUIT, et non les compteurs d'un scraper.
                # `associations` est un CALCUL INTERNE : il ne visite ni course ni
                # partant, donc `nb_courses`/`nb_partants` restaient à 0 quoi qu'il
                # arrive. Un audit y a lu « 13 exécutions, 13 stériles, statut ok »
                # et conclu à une panne, alors que la table portait 11 749 lignes
                # fraîches — et surtout, une VRAIE panne aurait laissé la trace
                # EXACTEMENT identique. On journalise donc ce qui a été écrit.
                produit = nb_paires + nb_jockeys + nb_entraineurs
                await log_scrape_result(
                    session, "associations",
                    "ok" if produit else "empty",
                    nb_partants=produit,
                )
                await session.commit()
                log.info("orchestrator.associations_done", nb_paires=nb_paires,
                         nb_jockeys=nb_jockeys, nb_entraineurs=nb_entraineurs)
        except Exception as e:
            log.error("orchestrator.associations_error", error=str(e))
            await self._log_error("associations", e)

    async def run_enrichissement_participations(self) -> None:
        """
        Post-traitement après cycle PMU :
        - Calcule jours_depuis_derniere pour chaque partant
        - Détecte les changements de jockey
        Lance après chaque cycle PMU (toutes les 3 min).
        """
        try:
            from sqlalchemy import text as sa_text
            async with AsyncSessionLocal() as session:
                # Journée PARISIENNE : en UTC, l'enrichissement des partants du
                # jour ne démarrait qu'à 02 h heure française (cf. temps_courses).
                today = jour_courses()

                # Query SQL directe pour éviter le problème de cast SQLAlchemy
                result = await session.execute(sa_text("""
                    SELECT p.participation_id, p.course_id, p.cheval_id, p.jockey_id
                    FROM participations p
                    JOIN courses c ON p.course_id = c.course_id
                    WHERE DATE(c.date_heure) = :today
                      AND p.jours_depuis_derniere IS NULL
                      AND p.non_partant = false
                    LIMIT 100
                """), {"today": today})
                rows = result.fetchall()

                for pid, cid, cheval_id, jockey_id in rows:
                    await compute_jours_depuis_derniere(session, cid, cheval_id, pid)
                    if jockey_id:
                        await detect_jockey_change(session, cid, cheval_id, jockey_id, pid)

                await session.commit()
        except Exception as e:
            log.error("orchestrator.enrichissement_error", error=str(e))

    async def run_once(self) -> None:
        """Exécute un cycle complet de scraping."""
        # Repart d'une ardoise propre : seules les sources qui échouent dans
        # CE run_once seront mises en backoff par les _mark_done() suivants.
        self._failed_this_cycle = set()
        playwright, browser, context = await make_stealth_browser(
            proxy=getattr(settings, "brightdata_proxy", None)
        )
        try:
            # ── CRITIQUE (toutes les 3 min) ──────────────────────────────
            await self.run_pmu_cycle()
            self._mark_done("pmu")

            # Enrichissement post-PMU (jours_depuis_derniere, changement_jockey)
            await self.run_enrichissement_participations()

            # ── RÉSULTATS : poll des arrivées des courses finies ─────────
            if self._should_run("resultats"):
                await self.poll_resultats()
                self._mark_done("resultats")

            # ── PRÉDICTIONS : (re)calcul algo pour les courses du jour ───
            if self._should_run("predictions"):
                await self.run_predictions_cycle()
                self._mark_done("predictions")

            # ── HAUTE (toutes les 5 min) ─────────────────────────────────
            if self._should_run("zeturf"):
                await self.run_zeturf_cycle(context)
                self._mark_done("zeturf")

            if self._should_run("bookmakers"):
                await self.run_bookmakers_cycle(context)
                self._mark_done("bookmakers")

            if self._should_run("pool_pmu"):
                await self.run_pool_pmu_cycle()
                self._mark_done("pool_pmu")

            # ── HAUTE (toutes les 10-15 min) ─────────────────────────────
            if self._should_run("geny"):
                await self.run_geny_cycle(context)
                self._mark_done("geny")

            if self._should_run("letrot"):
                await self.run_letrot_cycle(context)
                self._mark_done("letrot")

            # ── MOYENNE (toutes les 30 min) ──────────────────────────────
            if self._should_run("turfoo"):
                await self.run_turfoo_cycle(context)
                self._mark_done("turfoo")

            if self._should_run("paris_turf"):
                await self.run_paris_turf_cycle(context)
                self._mark_done("paris_turf")

            if self._should_run("meteo"):
                await self.run_meteo_cycle()
                self._mark_done("meteo")

            # ── BASSE (toutes les 60 min) ────────────────────────────────
            if self._should_run("france_galop"):
                await self.run_france_galop_cycle(context)
                self._mark_done("france_galop")

            # ── TRÈS BASSE (1x/jour) ─────────────────────────────────────
            if self._should_run("racing_post"):
                await self.run_racing_post_cycle(context)
                self._mark_done("racing_post")

            # ── HEBDOMADAIRE ─────────────────────────────────────────────
            if self._should_run("associations"):
                await self.run_associations_cycle()
                self._mark_done("associations")

        finally:
            await browser.close()
            await playwright.stop()

    async def run_daemon(self, interval_minutes: int = 5) -> None:
        """Daemon continu — boucle infinie, chaque cycle BORNÉ dans le temps.

        Un cycle complet mesuré en prod dure 2,5 à 6 min ; le timeout à 20 min
        laisse donc ~3× de marge. Au-delà, le cycle est considéré gelé : au pire
        on perd 20 min de données au lieu des 4 jours du 11/08.
        """
        global _cycle_started_at
        log.info("orchestrator.daemon_start", interval_min=interval_minutes)
        _start_cycle_watchdog()
        _write_heartbeat()  # le conteneur vient de démarrer : il est vivant
        while True:
            _cycle_started_at = time.monotonic()
            try:
                await asyncio.wait_for(self.run_once(), timeout=CYCLE_TIMEOUT_S)
                _write_heartbeat()
            except asyncio.TimeoutError:
                # L'annulation a abouti : inutile de tuer le process, le cycle
                # suivant repart sur un navigateur neuf. Si elle N'aboutit PAS,
                # on ne passe jamais ici et c'est le watchdog thread qui tranche.
                log.error("orchestrator.cycle_timeout", timeout_s=CYCLE_TIMEOUT_S)
            except Exception as e:
                log.error("orchestrator.daemon_error", error=str(e))
            finally:
                _cycle_started_at = None
            await asyncio.sleep(interval_minutes * 60)

    async def run_predictions_cycle(self) -> None:
        """(Re)calcule prédictions + value bets + recommandations pour les courses
        du jour qui ont des partants. Idempotent (upsert). Tourne automatiquement
        afin que l'utilisateur n'ait rien à lancer manuellement."""
        from ml.pipeline import predict_course
        from sqlalchemy import text

        # Cleanup : un value bet n'a de sens que sur une course à venir / en cours.
        # Dès qu'une course est terminée ou annulée, ses VB doivent être désactivés
        # (sinon ils s'accumulent en `actif=true` avec des EV obsolètes). Idempotent.
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("""
                UPDATE value_bets vb SET actif = false
                FROM courses c
                WHERE vb.course_id = c.course_id
                  AND vb.actif = true
                  AND c.statut NOT IN ('a_venir', 'en_cours')
            """))
            await session.commit()
            if res.rowcount:
                log.info("orchestrator.vb_deactivated", n=res.rowcount)

        async with AsyncSessionLocal() as session:
            # GEL DU PRONOSTIC À T-10 MIN : on ne (re)calcule une course que si elle
            # est encore à plus de 10 min du départ, OU si elle n'a pas encore de
            # pronostic (premier calcul toujours autorisé). Dès qu'on entre dans la
            # fenêtre des 10 dernières minutes, le dernier prono (proba + cote_figee +
            # value bets) reste FIGÉ — il ne flip-flope plus avec les cotes live. Les
            # cotes affichées (participations.cote_pmu / cotes-live) continuent, elles,
            # d'évoluer normalement (scrapées par les autres cycles).
            r = await session.execute(text("""
                SELECT c.course_id
                FROM courses c
                WHERE c.statut = 'a_venir'
                  AND c.date_heure::date = current_date
                  AND EXISTS (
                      SELECT 1 FROM participations p
                      WHERE p.course_id = c.course_id AND p.non_partant = false
                  )
                  AND (
                      c.date_heure > now() + interval '5 minutes'
                      OR NOT EXISTS (
                          SELECT 1 FROM predictions pr
                          JOIN participations pp
                            ON pp.participation_id = pr.participation_id
                          WHERE pp.course_id = c.course_id
                      )
                  )
                ORDER BY c.date_heure
            """))
            course_ids = [row[0] for row in r.fetchall()]

        ok = 0
        for cid in course_ids:
            try:
                if await predict_course(cid):
                    ok += 1
            except Exception as e:
                log.error("orchestrator.predict_error", course_id=cid, error=str(e)[:200])
        log.info("orchestrator.predictions_cycle", total=len(course_ids), ok=ok)

        # ── Garde-fou observabilité : alerte si la couche value-bet repart en vrille
        # (régression de calibration). Bornes larges = ne crient qu'en cas d'anomalie
        # franche, pas sur du bruit. Aide à détecter un retour du biais longshot.
        VB_COUNT_ALERT = 120     # > ~2 VB/course en moyenne = suspect
        VB_EV_ALERT = 2.0        # EV > +200% = quasi toujours une erreur de calibration
        try:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(text("""
                    SELECT count(*) AS n,
                           COALESCE(max(ev_max), 0) AS ev_max,
                           COALESCE(count(*) FILTER (WHERE ev_max > :ev), 0) AS n_hot
                    FROM value_bets WHERE actif = true
                """), {"ev": VB_EV_ALERT})).one()
                n, ev_max, n_hot = int(row[0]), float(row[1]), int(row[2])
                if n > VB_COUNT_ALERT or ev_max > VB_EV_ALERT:
                    log.warning("orchestrator.vb_sanity_alert",
                                n_actifs=n, ev_max=round(ev_max, 3), n_ev_aberrants=n_hot,
                                seuil_count=VB_COUNT_ALERT, seuil_ev=VB_EV_ALERT)
                else:
                    log.info("orchestrator.vb_sanity_ok", n_actifs=n, ev_max=round(ev_max, 3))
        except Exception as e:
            log.error("orchestrator.vb_sanity_failed", error=str(e)[:160])

    async def poll_resultats(self) -> None:
        """Polling résultats toutes les 3 minutes pour courses en cours."""
        from services.course_resolution import STATUT_ANNULE, statut_interne_depuis_pmu
        pmu = PmuScraper()
        t0 = time.time()
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select, and_
                from db.models import Course as DBCourse
                from datetime import datetime, timedelta

                now = datetime.now()
                win = now - timedelta(hours=36)
                # Courses à (re)poller dans une fenêtre 36h :
                #  - 'a_venir' déjà passées → récupérer l'arrivée ;
                #  - 'termine' MAIS rapports PMU encore absents, OU runs profil non
                #    réglés ('pending'/'partial'). Le PMU publie l'arrivée PUIS les
                #    RAPPORTS 5-10 min plus tard ; une course passée 'termine' sur la
                #    seule arrivée ne re-fetchait JAMAIS ses rapports (ancien filtre
                #    statut='a_venir' uniquement) → gains figés "en attente". On
                #    re-poll jusqu'à rapports publiés + tous les runs réglés, puis la
                #    course sort d'elle-même du périmètre (set borné par la fenêtre).
                from sqlalchemy import text as _text
                courses = (await session.execute(_text("""
                    SELECT c.course_id AS course_id, c.reunion_id AS reunion_id,
                           c.date_heure AS date_heure, c.statut AS statut,
                           (c.date_heure < now() - interval '30 minutes') AS depart_ancien
                    FROM courses c
                    LEFT JOIN resultats r ON r.course_id = c.course_id
                    WHERE c.date_heure < :now AND c.date_heure > :win
                      AND (
                        c.statut = 'a_venir'
                        OR (c.statut = 'termine' AND (
                              r.course_id IS NULL
                              OR r.rapports IS NULL
                              OR r.rapports::text IN ('{}', 'null')
                              OR EXISTS (SELECT 1 FROM profil_run_log p
                                         WHERE p.course_id = c.course_id
                                           AND p.statut IN ('pending', 'partial'))
                        ))
                      )
                    ORDER BY c.date_heure
                """), {"now": now, "win": win})).all()

            # Sauvegarde PAR COURSE en transaction ISOLÉE + retry deadlock. La fenêtre 36h
            # repolle des courses que le cycle PMU + le poller live touchent aussi → une
            # grosse transaction globale deadlockait en boucle (resultats KO depuis des
            # semaines). Chaque course = sa propre petite txn, indépendante et rejouable.
            ok_n = 0
            annule_n = 0
            for course in courses:
                try:
                    r_id = course.reunion_id
                    c_num = int(course.course_id.split("C")[-1])
                    cid_prefix = course.course_id[:8] if course.course_id[:8].isdigit() else course.date_heure
                    resultat = await pmu.get_rapports_definitifs(r_id, c_num, cid_prefix)
                    if resultat and resultat.ordre_arrivee:
                        async def _w(session, _r=resultat):
                            await save_resultat_to_db(session, _r)
                        if await self._commit_unit(_w):
                            ok_n += 1
                            log.info("orchestrator.resultat_polled", course_id=course.course_id)
                            # Déclencher le pipeline post-course via RQ.
                            # `retry` : un échec de post_course_sync est le plus
                            # souvent TRANSITOIRE (base momentanément indisponible,
                            # worker tué par le OOM killer) ; sans réessai, la
                            # course perd définitivement son apprentissage.
                            # `failure_ttl` : sans lui, RQ garde les jobs ratés un
                            # AN dans la FailedJobRegistry — 527 entrées empilées
                            # depuis juin en production, dont le décompte polluait
                            # chaque alerte qualité bien après correction des causes.
                            from rq import Queue, Retry
                            import redis
                            rq = Queue(connection=redis.from_url(settings.redis_url))
                            rq.enqueue(
                                "ml.pipeline.post_course_sync", course.course_id,
                                retry=Retry(max=2, interval=[120, 600]),
                                failure_ttl=POST_COURSE_FAILURE_TTL_S,
                            )
                        continue

                    # Pas d'arrivée : course ANNULÉE ? Le PMU ne publiera JAMAIS
                    # d'ordreArrivee pour elle — sans ce test la course tourne en
                    # boucle jusqu'à sortir de la fenêtre 36h, puis reste 'a_venir'
                    # à vie (159 cas en prod au 2026-08-17, 100 % COURSE_ANNULEE).
                    # Sonde seulement passé 30 min après l'heure de départ : entre la
                    # fin de course et la publication de l'arrivée l'absence
                    # d'ordreArrivee est NORMALE, inutile de payer une requête de plus.
                    if course.statut == "a_venir" and course.depart_ancien:
                        statut_pmu = await pmu.get_statut_course(r_id, c_num, cid_prefix)
                        if statut_interne_depuis_pmu(statut_pmu) == STATUT_ANNULE:
                            async def _wa(session, _cid=course.course_id):
                                await session.execute(_text(
                                    "UPDATE courses SET statut = :s, updated_at = now() "
                                    "WHERE course_id = :c"),
                                    {"s": STATUT_ANNULE, "c": _cid})
                            if await self._commit_unit(_wa):
                                annule_n += 1
                                log.info("orchestrator.course_annulee",
                                         course_id=course.course_id, statut_pmu=statut_pmu)
                except Exception as e:  # une course fautive n'arrête pas le poll
                    log.warning("orchestrator.resultat_course_failed",
                                course_id=course.course_id, err=str(e)[:160])

            await self._log_ok("resultats", nb_courses=ok_n, duree_ms=int((time.time() - t0) * 1000))
            if annule_n:
                log.info("orchestrator.resultats_annulees", n=annule_n)
        except Exception as e:
            log.error("orchestrator.resultats_error", error=str(e))
            await self._log_error("resultats", e)
        finally:
            await pmu.close()


async def main_today():
    """CLI : scrape du jour."""
    orch = BlackTurfOrchestrator()
    await orch.run_once()
    print(f"Scrape terminé : {len(orch._courses_today)} courses")


async def main_daemon(interval: int = 5):
    """CLI : mode daemon."""
    orch = BlackTurfOrchestrator()
    await orch.run_daemon(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BlackTurf Scraper")
    parser.add_argument("--today", action="store_true", help="Scrape du jour")
    parser.add_argument("--daemon", action="store_true", help="Mode daemon continu")
    parser.add_argument("--interval", type=int, default=5, help="Intervalle daemon (min)")
    args = parser.parse_args()

    if args.daemon:
        asyncio.run(main_daemon(args.interval))
    else:
        asyncio.run(main_today())
