"""
Utilitaires partagés pour tous les scrapers BlackTurf.
Anti-détection, délais, browser stealth, retry, circuit breaker.
"""
import asyncio
import random
import time
import functools
import structlog
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from datetime import datetime
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

log = structlog.get_logger()


# ─────────────────────────────────────────────
# Retry decorator
# ─────────────────────────────────────────────
def retry_async(max_attempts: int = 3, backoff_base: float = 2.0, exceptions=(Exception,)):
    """
    Décorateur retry pour coroutines async.
    Attente exponentielle : 2s, 4s, 8s entre tentatives.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        wait = backoff_base ** (attempt - 1)
                        log.warning(
                            "scraper.retry",
                            func=func.__name__,
                            attempt=attempt,
                            wait_s=wait,
                            error=str(e),
                        )
                        await asyncio.sleep(wait)
                    else:
                        log.error(
                            "scraper.max_retries_exceeded",
                            func=func.__name__,
                            attempts=max_attempts,
                            error=str(e),
                        )
            raise last_exc
        return wrapper
    return decorator


# ─────────────────────────────────────────────
# Circuit breaker
# ─────────────────────────────────────────────
@dataclass
class CircuitBreaker:
    """
    Circuit breaker par source.
    État OPEN après failures_threshold échecs consécutifs → skip pendant cooldown_s secondes.
    """
    failures_threshold: int = 5
    cooldown_s: float = 1800.0  # 30 min

    _failures: int = field(default=0, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)
    _state: str = field(default="closed", init=False, repr=False)  # closed / open / half_open

    def is_open(self) -> bool:
        if self._state == "open":
            if time.time() - self._opened_at >= self.cooldown_s:
                self._state = "half_open"
                return False
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self, source: str = "") -> None:
        self._failures += 1
        if self._failures >= self.failures_threshold:
            self._state = "open"
            self._opened_at = time.time()
            log.warning(
                "circuit_breaker.opened",
                source=source,
                failures=self._failures,
                cooldown_s=self.cooldown_s,
            )

    @property
    def state(self) -> str:
        if self.is_open():
            return "open"
        return self._state


# Global registry des circuit breakers par source
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(source: str) -> CircuitBreaker:
    if source not in _circuit_breakers:
        _circuit_breakers[source] = CircuitBreaker()
    return _circuit_breakers[source]


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


# ─────────────────────────────────────────────
# Data models (partagés entre scrapers)
# ─────────────────────────────────────────────
@dataclass
class PartantScrape:
    numero: int
    nom: str
    cote_pmu: Optional[float] = None
    cote_geny: Optional[float] = None
    cote_bzh: Optional[float] = None
    jockey: Optional[str] = None
    entraineur: Optional[str] = None
    proprietaire: Optional[str] = None
    age: Optional[int] = None
    sexe: Optional[str] = None
    poids: Optional[float] = None
    decharge: Optional[float] = None
    musique: Optional[str] = None
    nb_victoires: Optional[int] = None
    nb_places: Optional[int] = None
    gain_carriere: Optional[int] = None  # en centimes
    deferre: Optional[str] = None
    oeilleres: Optional[str] = None
    plaques: Optional[str] = None
    muserolle: Optional[bool] = None
    langue_attachee: Optional[bool] = None
    visiere: Optional[bool] = None
    blinkers: Optional[bool] = None
    valeur_indice: Optional[int] = None
    retard_gains: Optional[int] = None
    rang_pronostic_pmu: Optional[int] = None
    # Généalogie + carrière + dynamique (API PMU participants)
    pere: Optional[str] = None
    mere: Optional[str] = None
    eleveur: Optional[str] = None
    nb_courses: Optional[int] = None
    reduction_km: Optional[float] = None  # secondes/km
    # ── Données PMU enrichies (participants) ─────────────────────────────────
    cote_reference: Optional[float] = None      # dernierRapportReference (cote d'ouverture)
    mouvement_cote_pct: Optional[float] = None  # (direct - reference)/reference
    tendance_cote: Optional[str] = None         # "+" / "-" / "=" (indicateurTendance)
    tendance_force: Optional[float] = None       # nombreIndicateurTendance (ampleur)
    est_favori: Optional[bool] = None           # dernierRapportDirect.favoris
    avis_entraineur: Optional[str] = None        # POSITIF / NEUTRE / NEGATIF
    nb_places_second: Optional[int] = None
    nb_places_troisieme: Optional[int] = None
    handicap_distance: Optional[int] = None      # distance de handicap (mètres)
    indicateur_inedit: Optional[bool] = None     # cheval n'ayant jamais couru
    jument_pleine: Optional[bool] = None
    race: Optional[str] = None                   # race/breed
    robe: Optional[str] = None                   # robe (couleur)
    source: str = "pmu"
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class CourseScrape:
    reunion_id: str
    course_id: str
    hippodrome: str
    date_heure: str
    discipline: str
    distance: int
    terrain: Optional[str] = None
    terrain_code: Optional[int] = None
    dotation: Optional[int] = None  # en centimes
    nb_partants: int = 0
    partants: list = None
    corde: Optional[str] = None
    niveau_course: Optional[str] = None
    type_depart: Optional[str] = None
    est_quinte: bool = False
    est_quarte: bool = False
    est_tierce: bool = False
    nom: Optional[str] = None
    # ── Enrichissements PMU (course) ─────────────────────────────────────────
    conditions_texte: Optional[str] = None        # conditions complètes (texte long)
    categorie_particularite: Optional[str] = None  # EUROPEENNE / NATIONALE / ...
    montant_offert_1er: Optional[int] = None       # dotation au gagnant (euros)
    nombre_declares_partants: Optional[int] = None # déclarés (vs réels = scratchings)
    source: str = "pmu"
    scraped_at: str = ""

    def __post_init__(self):
        if self.partants is None:
            self.partants = []
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class ResultatScrape:
    course_id: str
    ordre_arrivee: list  # [{"numero": 1, "nom": "...", "position": 1, "temps": "..."}]
    rapports: dict  # {"gagnant": 4.5, "place": 2.1, "couple": 12.3, ...}
    temps_gagnant: Optional[str] = None
    incidents: Optional[str] = None
    commentaire: Optional[str] = None      # commentaireApresCourse.texte (narratif PMU/GENY)
    duree_course: Optional[int] = None     # dureeCourse (ms)
    source: str = "pmu"
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


# ─────────────────────────────────────────────
# Browser stealth factory
# ─────────────────────────────────────────────
async def make_stealth_browser(proxy: Optional[str] = None):
    """Crée un browser Playwright anti-détection."""
    playwright = await async_playwright().start()

    launch_args = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--no-first-run",
            "--disable-infobars",
            "--disable-setuid-sandbox",
        ],
    }
    if proxy:
        launch_args["proxy"] = {"server": proxy}

    browser = await playwright.chromium.launch(**launch_args)

    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=random.choice(USER_AGENTS),
        locale="fr-FR",
        timezone_id="Europe/Paris",
        extra_http_headers={
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        },
    )

    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR','fr','en-US','en'] });
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        Object.defineProperty(navigator, 'permissions', {
            get: () => ({ query: async () => ({ state: 'granted' }) })
        });
    """)

    return playwright, browser, context


async def human_delay(min_s: float = 1.0, max_s: float = 3.5) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


@dataclass
class CoteBookmakerScrape:
    """Cote d'un bookmaker alternatif (Winamax, Betclic, Unibet, Betfair Exchange)."""
    course_id: str
    numero: int
    nom: str
    source: str          # winamax / betclic / unibet / betfair
    cote: float
    est_cote_ouverture: bool = False   # True si cote d'ouverture J-1
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class PoolPMUScrape:
    """Volume du pool PMU pour une course (smart-money indicator)."""
    course_id: str
    pool_total: int          # montant total misé en centimes
    pool_gagnant: Optional[int] = None
    pool_place: Optional[int] = None
    nb_parieurs: Optional[int] = None
    gagnant_evolution: Optional[float] = None  # taux de croissance du pool gagnant (smart money)
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class SuspensionScrape:
    """Suspension officielle d'un jockey ou entraîneur (France Galop / LeTrot)."""
    nom: str
    type_pro: str        # jockey / entraineur / driver
    source: str          # france_galop / letrot
    date_debut: str
    date_fin: Optional[str] = None
    nb_jours: Optional[int] = None
    motif: Optional[str] = None
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class PenetrometreScrape:
    """Coefficient de sol mesuré au pénétromètre (échelle 0–9 France Galop)."""
    reunion_id: str
    hippodrome: str
    date: str
    coefficient: float       # ex: 4.2 → souple, 6.8 → très souple
    description: str         # Bon / Souple / Lourd / Très souple
    heure_mesure: Optional[str] = None
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class TempsPassageScrape:
    """Splits chronométriques d'une course (temps de passage)."""
    course_id: str
    numero: int
    nom: str
    passage_400m: Optional[str] = None
    passage_800m: Optional[str] = None
    passage_1000m: Optional[str] = None
    passage_1600m: Optional[str] = None
    passage_dernier_400m: Optional[str] = None
    vitesse_max_kmh: Optional[float] = None
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class PronosticPresseScrape:
    """Pronostic d'un journaliste / expert (Paris-Turf, CanalTurf, Geny)."""
    course_id: str
    source: str              # paris_turf / canalturf / geny_expert
    journaliste: Optional[str] = None
    selection: list = None   # [{"numero": 3, "nom": "CHEVAL X", "rang": 1}, ...]
    commentaire: Optional[str] = None
    scraped_at: str = ""

    def __post_init__(self):
        if self.selection is None:
            self.selection = []
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class GeneralogieScrape:
    """Généalogie complète d'un cheval (France Galop / Racing Post)."""
    cheval_nom: str
    code_sire: Optional[str] = None
    pere: Optional[str] = None
    mere: Optional[str] = None
    pere_de_mere: Optional[str] = None
    mere_de_mere: Optional[str] = None
    eleveur: Optional[str] = None
    pays_naissance: Optional[str] = None
    prix_vente_yearling: Optional[int] = None   # euros
    date_naissance: Optional[str] = None
    source: str = "france_galop"
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class RunningStyleScrape:
    """Style de course d'un cheval calculé depuis son historique."""
    cheval_nom: str
    running_style: str       # mene / suit_tete / placier / ferme / irregulier
    taux_en_tete: float = 0.0
    taux_top3_500m: float = 0.0
    nb_courses_analyses: int = 0
    source: str = "france_galop"
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


@dataclass
class AssociationJockeyEntraineurScrape:
    """Stats de la paire jockey × entraîneur."""
    jockey_nom: str
    entraineur_nom: str
    saison: int
    nb_courses: int = 0
    nb_victoires: int = 0
    nb_places: int = 0
    taux_victoire: float = 0.0
    taux_place: float = 0.0
    roi: float = 0.0
    source: str = "calcul_interne"
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


class BaseScraper:
    """Classe de base pour tous les scrapers BlackTurf."""

    SOURCE_NAME: str = "unknown"   # override dans les sous-classes

    def __init__(self, page: Page, proxy: Optional[str] = None):
        self.page = page
        self.proxy = proxy
        self.log = structlog.get_logger(scraper=self.__class__.__name__)
        self._cb = get_circuit_breaker(self.SOURCE_NAME)

    async def safe_goto(self, url: str, timeout: int = 20000, max_retries: int = 3) -> bool:
        """
        Navigation avec retry exponentiel (2s, 4s, 8s).
        Vérifie le circuit breaker avant chaque tentative.
        """
        if self._cb.is_open():
            self.log.warning("circuit_breaker.skip", source=self.SOURCE_NAME, url=url)
            return False

        for attempt in range(1, max_retries + 1):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                await human_delay(0.8, 2.0)
                self._cb.record_success()
                return True
            except Exception as e:
                self._cb.record_failure(self.SOURCE_NAME)
                if attempt < max_retries:
                    wait = 2.0 ** (attempt - 1)
                    self.log.warning("goto_retry", url=url, attempt=attempt, wait_s=wait, error=str(e))
                    await asyncio.sleep(wait)
                else:
                    self.log.error("goto_failed", url=url, attempts=max_retries, error=str(e))
                    return False
        return False

    async def safe_evaluate(self, script: str, default=None):
        try:
            return await self.page.evaluate(script)
        except Exception as e:
            self.log.warning("evaluate_failed", error=str(e))
            return default

    async def close(self) -> None:
        """Ferme la page si elle existe."""
        try:
            if self.page and not self.page.is_closed():
                await self.page.close()
        except Exception:
            pass
