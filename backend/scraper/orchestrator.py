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
import time
import structlog
from datetime import datetime

from api.config import get_settings
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
from scraper.sources.betfair import BetfairScraper
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
)

log = structlog.get_logger()
settings = get_settings()


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


class BlackTurfOrchestrator:
    """Orchestre tous les scrapers avec retry et monitoring."""

    def __init__(self):
        self._last_scrape: dict[str, float] = {}
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

    def _should_run(self, source: str) -> bool:
        if source in self._disabled:
            return False
        last = self._last_scrape.get(source, 0)
        interval = self._intervals.get(source, 300)
        return (time.time() - last) >= interval

    def _mark_done(self, source: str) -> None:
        self._last_scrape[source] = time.time()

    async def run_pmu_cycle(self) -> None:
        """Cycle PMU : récupère programme + cotes live + résultats."""
        t0 = time.time()
        log.info("orchestrator.pmu_start")

        pmu = PmuScraper(proxy=settings.brightdata_proxy if hasattr(settings, "brightdata_proxy") else None)
        try:
            courses = await pmu.get_programme_today()
            self._courses_today = courses

            nb_partants_total = 0
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
                        await save_course_to_db(session, course)
                        if course.date_heure:
                            resultat = await pmu.get_rapports_definitifs(r_id, c_num, course.date_heure)
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
            async with AsyncSessionLocal() as session:
                await log_scrape_result(session, "pmu", "erreur", erreur=str(e))
                await session.commit()
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

            # Enrichir les cotes Geny en DB
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select, update
                from db.models import Participation, Course, Cheval

                for course_data in data:
                    for cheval_data in course_data.get("chevaux", []):
                        nom = cheval_data.get("nom", "").strip()
                        cote_str = cheval_data.get("cote_geny", "")
                        if not nom or not cote_str:
                            continue
                        try:
                            cote = float(str(cote_str).replace(",", "."))
                        except ValueError:
                            continue

                        # Mise à jour cote_geny dans participations
                        stmt = (
                            update(Participation)
                            .where(
                                Participation.cheval_id.in_(
                                    select(Cheval.cheval_id).where(Cheval.nom == nom)
                                )
                            )
                            .values(cote_geny=cote)
                        )
                        await session.execute(stmt)

                await session.commit()
                duree = int((time.time() - t0) * 1000)
                await log_scrape_result(session, "geny", "ok", duree_ms=duree)
                await session.commit()

        except Exception as e:
            log.error("orchestrator.geny_error", error=str(e))
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
                from db.models import Jockey, Entraineur, StatsJockey, StatsEntraineur
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                from datetime import datetime as dt

                saison = dt.now().year

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
                        roi_global=stats.get("roi", 0.0),
                        taux_par_distance=stats.get("stats_par_distance"),
                        taux_par_hippodrome=stats.get("stats_par_hippodrome"),
                        taux_par_terrain=stats.get("stats_par_terrain"),
                    ).on_conflict_do_update(
                        constraint="stats_jockeys_jockey_id_saison_key",
                        set_={
                            "victoires_saison": stats.get("victoires_saison", 0),
                            "taux_victoire_global": stats.get("taux_victoire", 0.0),
                            "roi_global": stats.get("roi", 0.0),
                            "updated_at": datetime.now(),
                        },
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
                        roi_global=stats.get("roi", 0.0),
                        taux_par_distance=stats.get("stats_par_distance"),
                        taux_par_hippodrome=stats.get("stats_par_hippodrome"),
                    ).on_conflict_do_update(
                        constraint="stats_entraineurs_entraineur_id_saison_key",
                        set_={
                            "victoires_saison": stats.get("victoires_saison", 0),
                            "taux_victoire_global": stats.get("taux_victoire", 0.0),
                            "roi_global": stats.get("roi", 0.0),
                            "updated_at": datetime.now(),
                        },
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
            ("betfair", BetfairScraper),
        ]

        for source_name, ScraperClass in scrapers:
            page = await browser_context.new_page()
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

                    await session.commit()
                    await log_scrape_result(
                        session, source_name, "ok",
                        duree_ms=int((time.time() - t0) * 1000),
                    )
                    await session.commit()

            except Exception as e:
                log.error(f"orchestrator.{source_name}_error", error=str(e))
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
        try:
            async with AsyncSessionLocal() as session:
                for course in self._courses_today:
                    pool_data = await pmu.get_pool_data(course.reunion_id, course.course_id)
                    if pool_data:
                        await save_pool_pmu(session, pool_data)

                        # Calculer l'évolution du pool (smart money indicator)
                        await _detect_smart_money(session, course.course_id)

                await session.commit()
        except Exception as e:
            log.error("orchestrator.pool_pmu_error", error=str(e))
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
            async with AsyncSessionLocal() as session:
                await log_scrape_result(session, "france_galop", "erreur", erreur=str(e))
                await session.commit()
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
            all_pronos = pt_pronos + ct_pronos

            async with AsyncSessionLocal() as session:
                for prono in all_pronos:
                    # Résoudre le pseudo_id en course_id PMU réel
                    parts = prono.course_id.split("_")
                    hippodrome_hint = parts[1] if len(parts) > 1 else ""
                    real_course_id = await resolve_bookmaker_course_id(
                        session, hippodrome_hint, ""
                    )
                    if real_course_id:
                        await save_pronostic_presse(session, prono, real_course_id)

                await session.commit()
                await log_scrape_result(
                    session, "paris_turf", "ok",
                    nb_courses=len(all_pronos),
                    duree_ms=int((time.time() - t0) * 1000),
                )
                await session.commit()

        except Exception as e:
            log.error("orchestrator.paris_turf_error", error=str(e))
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
                stmt = sa_select(Cheval.nom, Cheval.racing_post_url).where(
                    Cheval.pere.is_(None),
                    Cheval.pays_naissance != "FR",
                )
                result = await session.execute(stmt)
                chevaux = result.fetchall()[:30]  # max 30/jour

                for nom, rp_url in chevaux:
                    gen = await scraper.get_genealogie(nom)
                    if gen:
                        await save_genealogie(session, gen)

                    # Sauvegarder l'URL Racing Post sur le cheval
                    fiche = await scraper.get_fiche_cheval(nom, rp_url)
                    if fiche and fiche.get("racing_post_url"):
                        from sqlalchemy import update as sa_update
                        from db.models import Cheval as ChevalModel
                        await session.execute(
                            sa_update(ChevalModel)
                            .where(ChevalModel.nom == nom)
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
                await compute_and_save_jockey_entraineur_assoc(session, saison)
                await session.commit()
                await log_scrape_result(session, "associations", "ok")
                await session.commit()
        except Exception as e:
            log.error("orchestrator.associations_error", error=str(e))

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
                from datetime import date as dt_date
                today = dt_date.today()

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
        """Daemon continu — boucle infinie."""
        log.info("orchestrator.daemon_start", interval_min=interval_minutes)
        while True:
            try:
                await self.run_once()
            except Exception as e:
                log.error("orchestrator.daemon_error", error=str(e))
            await asyncio.sleep(interval_minutes * 60)

    async def run_predictions_cycle(self) -> None:
        """(Re)calcule prédictions + value bets + recommandations pour les courses
        du jour qui ont des partants. Idempotent (upsert). Tourne automatiquement
        afin que l'utilisateur n'ait rien à lancer manuellement."""
        from ml.pipeline import predict_course
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            r = await session.execute(text("""
                SELECT c.course_id
                FROM courses c
                WHERE c.statut = 'a_venir'
                  AND c.date_heure::date = current_date
                  AND EXISTS (
                      SELECT 1 FROM participations p
                      WHERE p.course_id = c.course_id AND p.non_partant = false
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

    async def poll_resultats(self) -> None:
        """Polling résultats toutes les 3 minutes pour courses en cours."""
        pmu = PmuScraper()
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select, and_
                from db.models import Course as DBCourse
                from datetime import datetime, timedelta

                now = datetime.now()
                # Courses qui auraient dû finir (fenêtre 36h pour rattraper hier)
                result = await session.execute(
                    select(DBCourse)
                    .where(
                        and_(
                            DBCourse.statut == "a_venir",
                            DBCourse.date_heure < now,
                            DBCourse.date_heure > now - timedelta(hours=36),
                        )
                    )
                )
                courses = result.scalars().all()

                for course in courses:
                    r_id = course.reunion_id
                    c_num = int(course.course_id.split("C")[-1])
                    resultat = await pmu.get_rapports_definitifs(r_id, c_num, course.date_heure)
                    if resultat and resultat.ordre_arrivee:
                        await save_resultat_to_db(session, resultat)
                        log.info("orchestrator.resultat_polled", course_id=course.course_id)

                        # Déclencher le pipeline post-course via RQ
                        from rq import Queue
                        import redis
                        rq = Queue(connection=redis.from_url(settings.redis_url))
                        rq.enqueue("ml.pipeline.post_course_sync", course.course_id)

                await session.commit()
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
