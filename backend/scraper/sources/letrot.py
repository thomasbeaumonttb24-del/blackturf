"""
Source Letrot.com — Référence officielle trot (SECF).
Données : records, meilleurs temps, historique complet trot.
Fréquence : toutes 15 minutes.
"""
import structlog
from typing import Optional
from scraper.base import BaseScraper, human_delay

log = structlog.get_logger(source="letrot")

BASE = "https://www.letrot.com"


class LetrotScraper(BaseScraper):

    async def get_fiche_cheval(self, nom: str) -> dict:
        """Fiche complète cheval trot : records, palmarès, historique."""
        url = f"{BASE}/stats/fiche-cheval?cheval={nom.replace(' ', '+')}"
        if not await self.safe_goto(url, timeout=25000):
            return {}

        await human_delay(2, 3.5)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('.search-result, .horse-result, tr.cheval, .fiche-cheval').forEach(el => {
                    results.push({
                        id: el.dataset.id || el.querySelector('a')?.href?.split('/').pop(),
                        nom: el.querySelector('.nom, .name, td:first-child')?.textContent?.trim(),
                        age: el.querySelector('.age, td:nth-child(2)')?.textContent?.trim(),
                        gains: el.querySelector('.gains, td:nth-child(3)')?.textContent?.trim(),
                    });
                });
                // Si on est sur la page de fiche directement
                const fiche = {
                    nom: document.querySelector('h1, .horse-name')?.textContent?.trim(),
                    age: document.querySelector('.age')?.textContent?.trim(),
                    sexe: document.querySelector('.sexe')?.textContent?.trim(),
                    gains_carriere: document.querySelector('.gains-carriere')?.textContent?.trim(),
                    meilleur_temps: document.querySelector('.meilleur-temps, .record')?.textContent?.trim(),
                    historique: Array.from(
                        document.querySelectorAll('table.performances tr:not(:first-child)')
                    ).slice(0, 30).map(r => ({
                        date: r.querySelector('td:nth-child(1)')?.textContent?.trim(),
                        hippodrome: r.querySelector('td:nth-child(2)')?.textContent?.trim(),
                        distance: r.querySelector('td:nth-child(3)')?.textContent?.trim(),
                        terrain: r.querySelector('td:nth-child(4)')?.textContent?.trim(),
                        position: r.querySelector('td:nth-child(5)')?.textContent?.trim(),
                        temps: r.querySelector('td:nth-child(6)')?.textContent?.trim(),
                        cote: r.querySelector('td:nth-child(7)')?.textContent?.trim(),
                        allocation: r.querySelector('td:nth-child(8)')?.textContent?.trim(),
                    }))
                };
                return { search_results: results, fiche };
            }
        """, default={})

        return data or {}

    async def get_programme_trot(self) -> list[dict]:
        """Programme du jour pour le trot."""
        url = f"{BASE}/programme"
        if not await self.safe_goto(url, timeout=20000):
            return []

        await human_delay(2, 3)

        data = await self.safe_evaluate("""
            () => Array.from(
                document.querySelectorAll('.course, .reunion, [class*="programme"]')
            ).map(el => ({
                id: el.dataset.courseId || '',
                hippodrome: el.querySelector('.hippodrome, .hippo')?.textContent?.trim(),
                heure: el.querySelector('.heure, .time')?.textContent?.trim(),
                distance: el.querySelector('.distance')?.textContent?.trim(),
                nb_partants: el.querySelector('.nb-partants')?.textContent?.trim(),
            }))
        """, default=[])

        return data or []

    async def get_record_hippodrome(self, hippodrome: str, distance: int) -> Optional[str]:
        """Record de l'hippodrome sur une distance donnée."""
        url = f"{BASE}/stats/records?hippo={hippodrome.replace(' ', '+')}&dist={distance}"
        if not await self.safe_goto(url, timeout=15000):
            return None

        await human_delay(1, 2)

        record = await self.safe_evaluate("""
            () => document.querySelector('.record-temps, .best-time')?.textContent?.trim()
        """)

        return record
