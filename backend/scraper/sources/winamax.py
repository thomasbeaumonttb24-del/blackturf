"""
Scraper Winamax — cotes hippisme.
URL cible : https://www.winamax.fr/paris-sportifs/courses-hippiques

Récupère :
  - Cotes par partant (numéro, nom, cote)
  - Rapprochées des courses PMU par hippodrome + heure
"""
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay, CoteBookmakerScrape

log = structlog.get_logger()

BASE_URL = "https://www.winamax.fr/paris-sportifs/courses-hippiques"


class WinamaxScraper(BaseScraper):
    """Scrape les cotes Winamax pour les courses du jour."""

    SOURCE = "winamax"

    async def get_cotes_du_jour(self) -> list[CoteBookmakerScrape]:
        """
        Récupère toutes les cotes Winamax disponibles pour aujourd'hui.
        Retourne une liste de CoteBookmakerScrape.
        Note : course_id est au format Winamax interne ; le rapprochement
        avec les course_id PMU se fait dans le db_writer via hippodrome + heure.
        """
        results: list[CoteBookmakerScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(BASE_URL)
        if not ok:
            self.log.warning("winamax.goto_failed")
            return results

        await human_delay(1.5, 3.0)

        # Attendre que les courses soient chargées
        try:
            await self.page.wait_for_selector(
                "[data-testid='race-card'], .event-card, .hippisme-race",
                timeout=10000,
            )
        except Exception:
            self.log.warning("winamax.no_race_cards_found")

        # Extraire via JavaScript (Winamax est une SPA React)
        races = await self.safe_evaluate("""
            () => {
                const results = [];
                // Chercher les cartes de course dans le DOM React
                const raceCards = document.querySelectorAll(
                    '[class*="RaceCard"], [class*="race-card"], [data-sport="horse-racing"] .event'
                );
                raceCards.forEach(card => {
                    const timeEl = card.querySelector('[class*="time"], [class*="Time"]');
                    const hippoEl = card.querySelector('[class*="venue"], [class*="Venue"], [class*="location"]');
                    const runners = card.querySelectorAll('[class*="runner"], [class*="Runner"], [class*="horse"]');

                    const raceInfo = {
                        time: timeEl ? timeEl.textContent.trim() : '',
                        hippodrome: hippoEl ? hippoEl.textContent.trim() : '',
                        runners: []
                    };

                    runners.forEach(runner => {
                        const numEl = runner.querySelector('[class*="number"], [class*="num"]');
                        const nameEl = runner.querySelector('[class*="name"], [class*="horse-name"]');
                        const coteEl = runner.querySelector('[class*="odds"], [class*="cote"], button[class*="bet"]');

                        if (nameEl) {
                            raceInfo.runners.push({
                                numero: numEl ? parseInt(numEl.textContent.trim()) || 0 : 0,
                                nom: nameEl.textContent.trim().toUpperCase(),
                                cote_text: coteEl ? coteEl.textContent.trim() : ''
                            });
                        }
                    });

                    if (raceInfo.runners.length > 0) {
                        results.push(raceInfo);
                    }
                });
                return results;
            }
        """, default=[])

        # Parser les cotes extraites
        for race in (races or []):
            hippodrome = race.get("hippodrome", "")
            time_str = race.get("time", "")

            # Construire un course_id approximatif (sera résolu dans db_writer)
            pseudo_course_id = f"WINA_{hippodrome[:8].upper().replace(' ', '_')}_{time_str.replace(':', '')}"

            for runner in race.get("runners", []):
                cote = _parse_cote(runner.get("cote_text", ""))
                if cote and runner.get("nom"):
                    results.append(CoteBookmakerScrape(
                        course_id=pseudo_course_id,
                        numero=runner.get("numero", 0),
                        nom=runner["nom"],
                        source=self.SOURCE,
                        cote=cote,
                        est_cote_ouverture=False,
                    ))

        self.log.info("winamax.cotes_scraped", nb=len(results), today=today)
        return results

    async def get_cotes_course(self, url: str) -> list[dict]:
        """
        Scrape les cotes d'une course spécifique depuis son URL Winamax.
        Retourne [{"numero": 3, "nom": "CHEVAL X", "cote": 4.5}, ...]
        """
        ok = await self.safe_goto(url)
        if not ok:
            return []

        await human_delay(1.0, 2.0)

        runners = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('[class*="runner"], [class*="Runner"]').forEach(el => {
                    const numEl = el.querySelector('[class*="number"]');
                    const nameEl = el.querySelector('[class*="name"]');
                    const oddsEl = el.querySelector('[class*="odds"], button');
                    results.push({
                        numero: numEl ? parseInt(numEl.textContent) || 0 : 0,
                        nom: nameEl ? nameEl.textContent.trim().toUpperCase() : '',
                        cote_text: oddsEl ? oddsEl.textContent.trim() : ''
                    });
                });
                return results;
            }
        """, default=[])

        result = []
        for r in (runners or []):
            cote = _parse_cote(r.get("cote_text", ""))
            if cote and r.get("nom"):
                result.append({"numero": r["numero"], "nom": r["nom"], "cote": cote})
        return result


def _parse_cote(text: str) -> Optional[float]:
    """Parse '4,50' ou '4.50' ou '9/2' en float."""
    if not text:
        return None
    text = text.strip().replace(" ", "")
    try:
        # Format décimal
        return float(text.replace(",", "."))
    except ValueError:
        pass
    # Format fractionnel (ex: 9/2 → 5.5)
    if "/" in text:
        try:
            num, denom = text.split("/")
            return round(int(num) / int(denom) + 1, 2)
        except Exception:
            pass
    return None
