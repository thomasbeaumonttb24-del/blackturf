"""
Source PMU — API JSON non documentée mais stable.
Source CRITIQUE — polling toutes 3 minutes.

Endpoints :
  /programme/today                                  → programme + partants basiques
  /reunion/{id}/course/{id}/participants            → détails partants + cotes live
  /reunion/{id}/course/{id}/rapports-definitifs     → résultats officiels post-course
"""
import json
import re
import httpx
import structlog
from datetime import datetime, date
from typing import Optional

from scraper.base import CourseScrape, PartantScrape, ResultatScrape, PoolPMUScrape, BaseScraper, human_delay, get_circuit_breaker

log = structlog.get_logger(source="pmu")

BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"

DISCIPLINE_MAP = {
    "PLAT": "Plat",
    "TROT_ATTELE": "Attelé",
    "TROT_MONTE": "Monté",
    "HAIES": "Haies",
    "STEEPLE_CHASE": "Steeple",
    "CROSS_COUNTRY": "Cross",
    "PLAT_INTERNATIONAL": "Plat",
}

TERRAIN_MAP = {
    1: "Très bon",
    2: "Bon",
    3: "Bon souple",
    4: "Souple",
    5: "Très souple",
    6: "Lourd",
    7: "Très lourd",
    8: "Collant",
    9: "Bourbeux",
}


class PmuScraper(BaseScraper):
    """
    PMU est la source CRITIQUE. On utilise httpx pour l'API JSON
    (plus rapide que Playwright pour des APIs pures).
    Playwright utilisé en fallback si l'API répond du HTML.
    """

    SOURCE_NAME = "pmu"

    def __init__(self, page=None, proxy: Optional[str] = None):
        super().__init__(page, proxy)
        self._client: Optional[httpx.AsyncClient] = None
        self._cb = get_circuit_breaker("pmu")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                    "Referer": "https://www.pmu.fr/",
                    "Origin": "https://www.pmu.fr",
                },
                timeout=15.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def _fetch_json(self, url: str, max_retries: int = 3) -> Optional[dict | list]:
        """Fetch JSON avec retry exponentiel + circuit breaker."""
        if self._cb.is_open():
            log.warning("pmu.circuit_open", url=url)
            return None

        client = await self._get_client()
        for attempt in range(1, max_retries + 1):
            try:
                r = await client.get(url)
                r.raise_for_status()
                self._cb.record_success()
                return r.json()
            except Exception as e:
                self._cb.record_failure("pmu")
                if attempt < max_retries:
                    wait = 2.0 ** (attempt - 1)
                    log.warning("pmu.fetch_retry", url=url, attempt=attempt, wait_s=wait, error=str(e))
                    await asyncio.sleep(wait)
                else:
                    log.error("pmu_fetch_failed", url=url, attempts=max_retries, error=str(e))
                    return None
        return None

    async def get_programme_today(self) -> list[CourseScrape]:
        """Récupère toutes les courses du jour avec partants basiques."""
        today_str = date.today().strftime("%d%m%Y")
        url = f"{BASE}/programme/{today_str}?specialisation=INTERNET"
        log.info("pmu.programme_today", date=today_str)

        data = await self._fetch_json(url)
        if not data:
            return []

        courses: list[CourseScrape] = []
        reunions = data.get("programme", {}).get("reunions", [])
        log.info("pmu.reunions_found", count=len(reunions))

        for reunion in reunions:
            r_num = reunion.get("numOfficiel", 0)
            r_id = str(r_num)
            hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "Inconnu")
            pays = reunion.get("hippodrome", {}).get("pays", {}).get("code", "FR")

            for c_data in reunion.get("courses", []):
                c_num = c_data.get("numOrdre", 0)
                c_id = f"R{r_id}C{c_num}"

                partants = self._parse_partants(c_data.get("participants", []))

                # Désignations
                conditions = c_data.get("conditions", "")
                est_quinte = "QUINTE" in conditions.upper()
                est_quarte = "QUARTE" in conditions.upper()
                est_tierce = "TIERCE" in conditions.upper()

                # Terrain
                terrain_code = c_data.get("conditionPiste")
                terrain_libelle = TERRAIN_MAP.get(terrain_code) if terrain_code else None
                if not terrain_libelle:
                    terrain_libelle = c_data.get("libellePiste")

                # Dotation en centimes
                dotation_raw = c_data.get("montantTotalOffert")
                dotation = int(dotation_raw * 100) if dotation_raw else None

                course = CourseScrape(
                    reunion_id=r_id,
                    course_id=c_id,
                    hippodrome=hippodrome,
                    date_heure=c_data.get("heureDepart", ""),
                    discipline=DISCIPLINE_MAP.get(c_data.get("specialite", ""), c_data.get("specialite", "")),
                    distance=c_data.get("distance", 0),
                    terrain=terrain_libelle,
                    terrain_code=terrain_code,
                    dotation=dotation,
                    nb_partants=len(partants),
                    partants=partants,
                    corde=c_data.get("corde"),
                    niveau_course=c_data.get("conditions"),
                    type_depart=c_data.get("typeDepart"),
                    est_quinte=est_quinte,
                    est_quarte=est_quarte,
                    est_tierce=est_tierce,
                    nom=c_data.get("libelle"),
                    source="pmu",
                )
                courses.append(course)

        log.info("pmu.courses_parsed", count=len(courses))
        return courses

    async def enrich_partants(self, reunion_id: str, course_num: int) -> list[PartantScrape]:
        """Récupère les données complètes des partants pour une course."""
        url = (
            f"{BASE}/reunion/{reunion_id}/course/{course_num}"
            f"/participants?specialisation=INTERNET"
        )
        await human_delay(0.3, 0.8)

        data = await self._fetch_json(url)
        if not data:
            return []

        participants = data if isinstance(data, list) else data.get("participants", [])
        return self._parse_partants(participants)

    async def get_rapports_definitifs(self, reunion_id: str, course_num: int) -> Optional[ResultatScrape]:
        """Récupère les résultats officiels après la course."""
        url = (
            f"{BASE}/reunion/{reunion_id}/course/{course_num}"
            f"/rapports-definitifs?specialisation=INTERNET"
        )
        data = await self._fetch_json(url)
        if not data:
            return None

        try:
            c_id = f"R{reunion_id}C{course_num}"
            ordre = []
            for p in data.get("participants", []):
                if p.get("ordreArrivee"):
                    ordre.append({
                        "numero": p.get("numPmu"),
                        "nom": p.get("nom"),
                        "position": p.get("ordreArrivee"),
                        "temps": p.get("tempsOfficiel"),
                        "incident": p.get("incident"),
                        "gains": p.get("gainsRapportes"),
                    })
            ordre.sort(key=lambda x: (x.get("position") or 999))

            rapports = {}
            for r in data.get("rapports", []):
                type_r = r.get("typePari", "").lower()
                rapport = r.get("dividendes", [{}])[0].get("rapport")
                if rapport:
                    rapports[type_r] = rapport

            return ResultatScrape(
                course_id=c_id,
                ordre_arrivee=ordre,
                rapports=rapports,
                temps_gagnant=ordre[0].get("temps") if ordre else None,
                incidents=data.get("incidents"),
                source="pmu",
            )
        except Exception as e:
            log.error("pmu.rapports_parse_error", error=str(e))
            return None

    async def get_cotes_live(self, reunion_id: str, course_num: int) -> dict[int, float]:
        """
        Récupère les cotes en temps réel.
        Retourne {numero_partant: cote}.
        """
        url = (
            f"{BASE}/reunion/{reunion_id}/course/{course_num}"
            f"/participants?specialisation=INTERNET"
        )
        data = await self._fetch_json(url)
        if not data:
            return {}

        participants = data if isinstance(data, list) else data.get("participants", [])
        cotes = {}
        for p in participants:
            num = p.get("numPmu")
            rapport = p.get("dernierRapportDirect", {})
            cote = rapport.get("rapport") if rapport else None
            if num and cote:
                cotes[num] = float(cote)
        return cotes

    async def get_pool_data(self, reunion_id: str, course_id: str):
        """
        Récupère le volume du pool PMU pour une course.
        Endpoint : /reunion/{id}/course/{num}/rapports-simples
        Retourne PoolPMUScrape ou None.
        """
        from scraper.base import PoolPMUScrape
        c_num = int(course_id.split("C")[-1]) if "C" in str(course_id) else 1
        url = (
            f"{BASE}/reunion/{reunion_id}/course/{c_num}"
            f"/rapports-simples?specialisation=INTERNET"
        )
        data = await self._fetch_json(url)
        if not data:
            return None

        try:
            # PMU expose les fonds de pool dans les rapports simples
            pool_total = None
            pool_gagnant = None
            pool_place = None

            for rapport in data.get("rapports", data if isinstance(data, list) else []):
                type_pari = rapport.get("typePari", "").upper()
                fond = rapport.get("fondMise")  # en centimes
                if fond is None:
                    # Parfois sous forme d'entier en euros — convertir
                    fond_euros = rapport.get("montantMise") or rapport.get("masse")
                    fond = int(fond_euros * 100) if fond_euros else None

                if fond:
                    pool_total = (pool_total or 0) + fond
                    if "SIMPLE_GAGNANT" in type_pari or type_pari == "GAGNANT":
                        pool_gagnant = fond
                    elif "SIMPLE_PLACE" in type_pari or type_pari == "PLACE":
                        pool_place = fond

            if pool_total is None:
                return None

            return PoolPMUScrape(
                course_id=course_id,
                pool_total=pool_total,
                pool_gagnant=pool_gagnant,
                pool_place=pool_place,
            )
        except Exception as e:
            log.warning("pmu.pool_data_error", course_id=course_id, error=str(e))
            return None

    def _parse_partants(self, raw: list) -> list[PartantScrape]:
        partants = []
        for i, p in enumerate(raw):
            # Cote
            rapport_direct = p.get("dernierRapportDirect") or {}
            cote = rapport_direct.get("rapport")

            # Gains en centimes
            gains_raw = p.get("gainsCarriere")
            gains = int(gains_raw * 100) if gains_raw and isinstance(gains_raw, float) else gains_raw

            # Entraîneur
            entraineur_obj = p.get("entraineur", {})
            entraineur = entraineur_obj.get("nom") if isinstance(entraineur_obj, dict) else entraineur_obj

            # Driver ou Jockey
            jockey = p.get("driver") or p.get("jockey") or ""

            # Équipement
            equip = p.get("equipementsCourse", {}) or {}
            deferre = equip.get("deferre")
            oeilleres = equip.get("oeilleres")
            plaques = equip.get("plaques")

            partant = PartantScrape(
                numero=p.get("numPmu", i + 1),
                nom=p.get("nom", ""),
                cote_pmu=float(cote) if cote else None,
                jockey=jockey if isinstance(jockey, str) else jockey.get("nom", "") if isinstance(jockey, dict) else "",
                entraineur=entraineur,
                proprietaire=p.get("proprietaire"),
                age=p.get("age"),
                sexe=p.get("sexe"),
                poids=p.get("poidsJockey"),
                decharge=p.get("handicapPoids"),
                musique=p.get("musique"),
                nb_victoires=p.get("nbVictoires"),
                nb_places=p.get("nbPlaces"),
                gain_carriere=gains,
                deferre=deferre,
                oeilleres=oeilleres,
                plaques=plaques,
                muserolle=equip.get("muserolle"),
                langue_attachee=equip.get("langueAttachee"),
                visiere=equip.get("visiere"),
                blinkers=equip.get("blinkers"),
                valeur_indice=p.get("indiceSynthese"),
                retard_gains=p.get("retardAuxGains"),
                rang_pronostic_pmu=p.get("ordreArriveePronostic"),
                source="pmu",
            )
            partants.append(partant)
        return partants
