"""
Scraper Betclic — cotes hippisme + cotes d'ouverture.
URL cible : https://www.betclic.fr/hippisme-s5

Récupère :
  - Cotes actuelles par partant
  - Cotes d'ouverture (J-1) — signal de steam move si écart > 20%
"""
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay, CoteBookmakerScrape

log = structlog.get_logger()

# URL corrigée 2026-06-17 : /hippisme-s5 renvoie désormais 403 (durcissement
# anti-bot). /turf répond 200. ⚠ SPA Angular : les cotes sont chargées en JS →
# le parsing DOM actuel ne verra rien sans rendu navigateur complet OU sans taper
# l'API XHR sous-jacente. Source à valider en headless sur le VPS avant de fiabiliser.
BASE_URL = "https://www.betclic.fr/turf"
API_EVENTS_URL = "https://www.betclic.fr/api/sport/hippisme"


class BetclicScraper(BaseScraper):
    """Scrape les cotes Betclic pour les courses du jour."""

    SOURCE = "betclic"

    async def get_cotes_du_jour(self) -> dict[str, list[CoteBookmakerScrape]]:
        """
        Récupère cotes actuelles + cotes d'ouverture Betclic.
        Retourne dict : {"actuelles": [...], "ouvertures": [...]}
        """
        actuelles: list[CoteBookmakerScrape] = []
        ouvertures: list[CoteBookmakerScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(BASE_URL)
        if not ok:
            self.log.warning("betclic.goto_failed")
            return {"actuelles": actuelles, "ouvertures": ouvertures}

        await human_delay(2.0, 3.5)

        # Accepter cookies si présents
        try:
            await self.page.click(
                '[data-testid="cookie-accept"], button[id*="accept"], .cookies-btn-accept',
                timeout=3000,
            )
            await human_delay(0.5, 1.0)
        except Exception:
            pass

        # Attendre chargement des événements hippisme
        try:
            await self.page.wait_for_selector(
                '[class*="event"], [class*="race"], [data-sport="horseracing"]',
                timeout=12000,
            )
        except Exception:
            self.log.warning("betclic.no_events_found")

        # Intercepter les données depuis l'API interne Betclic (chargée en XHR)
        races = await self.safe_evaluate("""
            () => {
                const results = [];
                // Betclic expose ses données via des attributs data ou window.__NEXT_DATA__
                try {
                    const nextData = window.__NEXT_DATA__ || window.__data;
                    if (nextData) {
                        const str = JSON.stringify(nextData);
                        // Chercher les events hippisme dans les données Next.js
                        const events = (nextData.props?.pageProps?.events ||
                                       nextData.props?.pageProps?.data?.events || []);
                        events.forEach(event => {
                            if (!event.competitors) return;
                            results.push({
                                id: event.id,
                                hippodrome: event.competition?.name || event.venue || '',
                                time: event.startDateTimeUTC || event.date || '',
                                runners: event.competitors.map(c => ({
                                    numero: c.drawNumber || c.number || 0,
                                    nom: (c.name || '').toUpperCase(),
                                    cote: c.odds?.[0]?.price || c.odds?.win || null,
                                    cote_ouverture: c.odds?.[0]?.openingPrice || null,
                                }))
                            });
                        });
                    }
                } catch(e) {}

                // Fallback : DOM scraping
                if (results.length === 0) {
                    document.querySelectorAll('[class*="EventCard"], [class*="event-card"]').forEach(card => {
                        const hippoEl = card.querySelector('[class*="competition"], [class*="venue"]');
                        const timeEl = card.querySelector('[class*="time"], [class*="date"]');
                        const runners = [];

                        card.querySelectorAll('[class*="competitor"], [class*="runner"]').forEach(r => {
                            const numEl = r.querySelector('[class*="number"]');
                            const nameEl = r.querySelector('[class*="name"]');
                            const oddsEl = r.querySelector('[class*="odds"], [class*="price"]');
                            if (nameEl) {
                                runners.push({
                                    numero: numEl ? parseInt(numEl.textContent) || 0 : 0,
                                    nom: nameEl.textContent.trim().toUpperCase(),
                                    cote: oddsEl ? oddsEl.textContent.trim() : null,
                                    cote_ouverture: null,
                                });
                            }
                        });

                        if (runners.length > 0) {
                            results.push({
                                hippodrome: hippoEl ? hippoEl.textContent.trim() : '',
                                time: timeEl ? timeEl.textContent.trim() : '',
                                runners,
                            });
                        }
                    });
                }
                return results;
            }
        """, default=[])

        for race in (races or []):
            hippodrome = race.get("hippodrome", "")
            time_str = str(race.get("time", ""))[:5].replace("T", "").replace("-", "")
            pseudo_course_id = f"BETCLIC_{hippodrome[:8].upper().replace(' ', '_')}_{time_str}"

            for runner in race.get("runners", []):
                nom = runner.get("nom", "").strip()
                if not nom:
                    continue

                cote_act = _parse_cote(runner.get("cote"))
                cote_ouv = _parse_cote(runner.get("cote_ouverture"))
                numero = runner.get("numero", 0)

                if cote_act:
                    actuelles.append(CoteBookmakerScrape(
                        course_id=pseudo_course_id,
                        numero=numero,
                        nom=nom,
                        source=self.SOURCE,
                        cote=cote_act,
                        est_cote_ouverture=False,
                    ))
                if cote_ouv:
                    ouvertures.append(CoteBookmakerScrape(
                        course_id=pseudo_course_id,
                        numero=numero,
                        nom=nom,
                        source=self.SOURCE,
                        cote=cote_ouv,
                        est_cote_ouverture=True,
                    ))

        self.log.info(
            "betclic.cotes_scraped",
            nb_actuelles=len(actuelles),
            nb_ouvertures=len(ouvertures),
            today=today,
        )
        return {"actuelles": actuelles, "ouvertures": ouvertures}


def _parse_cote(value) -> Optional[float]:
    """Parse cote depuis float, int ou string."""
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
