"""
Scraper Unibet — cotes hippisme.
URL cible : https://www.unibet.fr/hippisme

Récupère :
  - Cotes actuelles par partant pour les courses du jour
"""
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay, CoteBookmakerScrape

log = structlog.get_logger()

BASE_URL = "https://www.unibet.fr/hippisme"


class UnibetScraper(BaseScraper):
    """Scrape les cotes Unibet pour les courses du jour."""

    SOURCE = "unibet"

    async def get_cotes_du_jour(self) -> list[CoteBookmakerScrape]:
        """
        Récupère toutes les cotes Unibet disponibles pour aujourd'hui.
        """
        results: list[CoteBookmakerScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(BASE_URL)
        if not ok:
            self.log.warning("unibet.goto_failed")
            return results

        await human_delay(2.0, 3.5)

        # Gérer le popup cookies
        try:
            await self.page.click(
                '[data-testid="accept-all-cookies"], #onetrust-accept-btn-handler, .btn-accept-cookies',
                timeout=3000,
            )
            await human_delay(0.5, 1.0)
        except Exception:
            pass

        # Unibet charge ses données via Kambi ou leur propre API
        # Tenter l'interception des données window._unibet ou Kambi
        races = await self.safe_evaluate("""
            () => {
                const results = [];

                // Kambi est le fournisseur de paris d'Unibet
                // Les données sont souvent dans window.offeringsData ou dans l'API Kambi
                try {
                    // Essayer les données Kambi
                    const kambiData = window.KambiWidget?.offeringsData
                        || window.__KAMBI_DATA__
                        || window.offeringsData;

                    if (kambiData?.betOffers) {
                        kambiData.betOffers.forEach(bo => {
                            if (bo.sport !== 'HORSE_RACING' && bo.sport !== 'TROT') return;
                            bo.outcomes?.forEach(o => {
                                results.push({
                                    event_id: bo.eventId,
                                    hippodrome: bo.eventName || '',
                                    time: bo.startTime || '',
                                    numero: o.runnerNumber || 0,
                                    nom: (o.runnerName || o.label || '').toUpperCase(),
                                    cote: o.odds / 1000,  // Kambi stocke les cotes × 1000
                                });
                            });
                        });
                    }
                } catch(e) {}

                // Fallback DOM
                if (results.length === 0) {
                    document.querySelectorAll(
                        '[class*="event"], [class*="meeting"], [class*="race"]'
                    ).forEach(card => {
                        const venue = card.querySelector('[class*="venue"], [class*="location"], [class*="name"]');
                        const timeEl = card.querySelector('[class*="time"], [class*="clock"]');

                        card.querySelectorAll(
                            '[class*="runner"], [class*="horse"], [class*="participant"]'
                        ).forEach(runner => {
                            const numEl = runner.querySelector('[class*="num"], [class*="number"], [class*="draw"]');
                            const nameEl = runner.querySelector('[class*="name"], [class*="horse"]');
                            const oddsEl = runner.querySelector('[class*="odds"], [class*="price"], button');

                            if (nameEl && oddsEl) {
                                results.push({
                                    hippodrome: venue ? venue.textContent.trim() : '',
                                    time: timeEl ? timeEl.textContent.trim() : '',
                                    numero: numEl ? parseInt(numEl.textContent.trim()) || 0 : 0,
                                    nom: nameEl.textContent.trim().toUpperCase(),
                                    cote: oddsEl.textContent.trim(),
                                });
                            }
                        });
                    });
                }
                return results;
            }
        """, default=[])

        # Grouper par course
        seen_courses: dict = {}
        for r in (races or []):
            hippodrome = r.get("hippodrome", "")
            time_str = str(r.get("time", ""))[:5].replace(":", "")
            pseudo_id = f"UNIBET_{hippodrome[:8].upper().replace(' ', '_')}_{time_str}"

            cote = _parse_cote(r.get("cote"))
            nom = r.get("nom", "").strip()
            if cote and nom:
                results.append(CoteBookmakerScrape(
                    course_id=pseudo_id,
                    numero=r.get("numero", 0),
                    nom=nom,
                    source=self.SOURCE,
                    cote=cote,
                    est_cote_ouverture=False,
                ))

        self.log.info("unibet.cotes_scraped", nb=len(results), today=today)
        return results


def _parse_cote(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v > 1.0 else None
    text = str(value).strip().replace(",", ".").replace(" ", "")
    try:
        v = float(text)
        return v if v > 1.0 else None
    except ValueError:
        return None
