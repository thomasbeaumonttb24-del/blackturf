"""
Scraper Betfair Exchange — cotes de marché (échange).
URL cible : https://www.betfair.com/exchange/plus/horse-racing

Les cotes Betfair Exchange sont les plus "efficientes" du marché :
ce sont des cotes déterminées par l'offre/demande entre parieurs,
sans marge bookmaker. Elles reflètent mieux la probabilité réelle.

Récupère :
  - Cotes d'échange (meilleur back price) par partant
  - Liquidité (volume misé = confidence dans la cote)
"""
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay, CoteBookmakerScrape

log = structlog.get_logger()

BASE_URL = "https://www.betfair.com/exchange/plus/horse-racing"
# Filtre pour les courses françaises
FRENCH_RACING_URL = "https://www.betfair.com/exchange/plus/horse-racing?countryCode=FR"


class BetfairScraper(BaseScraper):
    """Scrape les cotes d'échange Betfair pour les courses françaises."""

    SOURCE = "betfair"

    async def get_cotes_du_jour(self) -> list[CoteBookmakerScrape]:
        """
        Récupère les cotes d'échange Betfair pour les courses françaises du jour.
        """
        results: list[CoteBookmakerScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(FRENCH_RACING_URL)
        if not ok:
            # Fallback sans filtre pays
            ok = await self.safe_goto(BASE_URL)
            if not ok:
                self.log.warning("betfair.goto_failed")
                return results

        await human_delay(2.5, 4.0)

        # Gérer cookies / consent
        try:
            await self.page.click(
                '#onetrust-accept-btn-handler, [data-testid="cookie-accept"], .accept-cookies-btn',
                timeout=3000,
            )
            await human_delay(0.5, 1.0)
        except Exception:
            pass

        # Betfair Exchange charge les marchés via leur API interne
        # Les données sont dans window.BFExch ou dans des requêtes XHR vers l'API
        races = await self.safe_evaluate("""
            () => {
                const results = [];

                // Betfair expose parfois les données dans le DOM sous forme de JSON
                // Dans les attributs data-* ou via window.__INITIAL_STATE__
                try {
                    const state = window.__INITIAL_STATE__ || window.BFExch?.state;
                    if (state?.exchange?.markets) {
                        Object.values(state.exchange.markets).forEach(market => {
                            if (!market.runners) return;
                            const eventName = market.event?.name || market.marketName || '';
                            results.push({
                                market_id: market.marketId,
                                hippodrome: eventName,
                                time: market.event?.openDate || market.marketStartTime || '',
                                runners: market.runners.map(r => ({
                                    numero: r.runnerNumber || r.sortPriority || 0,
                                    nom: (r.runnerName || r.name || '').toUpperCase(),
                                    cote: r.ex?.availableToBack?.[0]?.price || null,
                                    volume: r.ex?.availableToBack?.[0]?.size || 0,
                                }))
                            });
                        });
                    }
                } catch(e) {}

                // Fallback DOM — Betfair affiche les cotes dans des tableaux
                if (results.length === 0) {
                    document.querySelectorAll(
                        '[class*="market-header"], .event-card, [class*="marketcard"]'
                    ).forEach(card => {
                        const titleEl = card.querySelector('[class*="market-title"], [class*="event-title"]');
                        const runners = [];

                        card.querySelectorAll(
                            '[class*="runner-info"], [class*="betContentArea"] tr, [class*="runner"]'
                        ).forEach(row => {
                            const nameEl = row.querySelector('[class*="runner-name"], [class*="name"]');
                            // Betfair affiche la cote dans un bouton de back bleu
                            const backEl = row.querySelector(
                                '[class*="back-cell"] button, [class*="lay-back"] .price, [title*="Back"]'
                            );
                            if (nameEl) {
                                runners.push({
                                    numero: 0,
                                    nom: nameEl.textContent.trim().toUpperCase(),
                                    cote: backEl ? backEl.textContent.trim() : null,
                                    volume: 0,
                                });
                            }
                        });

                        if (runners.length > 0) {
                            results.push({
                                hippodrome: titleEl ? titleEl.textContent.trim() : '',
                                time: '',
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
            time_str = str(race.get("time", ""))[:16].replace("T", "_").replace(":", "")
            pseudo_id = f"BF_{hippodrome[:8].upper().replace(' ', '_')}_{time_str[:8]}"

            for runner in race.get("runners", []):
                nom = runner.get("nom", "").strip()
                cote = _parse_cote(runner.get("cote"))
                if nom and cote:
                    results.append(CoteBookmakerScrape(
                        course_id=pseudo_id,
                        numero=runner.get("numero", 0),
                        nom=nom,
                        source=self.SOURCE,
                        cote=cote,
                        est_cote_ouverture=False,
                    ))

        self.log.info("betfair.cotes_scraped", nb=len(results), today=today)
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
