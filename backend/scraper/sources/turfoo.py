"""
Source Turfoo.fr — Stats jockey/entraîneur par hippodrome et distance.
Fréquence : toutes 30 minutes.
"""
import structlog
from scraper.base import BaseScraper, human_delay

log = structlog.get_logger(source="turfoo")

BASE = "https://www.turfoo.fr"


class TurfooScraper(BaseScraper):

    async def get_stats_jockey(self, jockey_nom: str, saison: int | None = None) -> dict:
        """Stats complètes d'un jockey."""
        slug = jockey_nom.lower().replace(" ", "-").replace("'", "")
        url = f"{BASE}/jockeys/{slug}"
        if not await self.safe_goto(url, timeout=20000):
            return {}

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => {
                const getNum = (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    return parseFloat(el.textContent.replace('%','').replace(',','.').trim()) || null;
                };
                return {
                    victoires_saison: getNum('.victoires-saison, .wins'),
                    courses_saison: getNum('.courses-saison, .rides'),
                    taux_victoire_global: getNum('.taux-victoire, .win-rate'),
                    taux_place_global: getNum('.taux-place, .place-rate'),
                    roi_global: getNum('.roi, .return'),
                    montes_30j: getNum('.montes-30j, .recent-rides'),
                    stats_par_distance: (() => {
                        const stats = {};
                        document.querySelectorAll('.stats-distance tr:not(:first-child)').forEach(r => {
                            const dist = r.querySelector('td:first-child')?.textContent?.trim();
                            const taux = r.querySelector('td:nth-child(3)')?.textContent?.trim();
                            if (dist && taux) stats[dist] = parseFloat(taux.replace('%','')) || 0;
                        });
                        return stats;
                    })(),
                    stats_par_hippodrome: (() => {
                        const stats = {};
                        document.querySelectorAll('.stats-hippodrome tr:not(:first-child)').forEach(r => {
                            const hippo = r.querySelector('td:first-child')?.textContent?.trim();
                            const taux = r.querySelector('td:nth-child(3)')?.textContent?.trim();
                            if (hippo && taux) stats[hippo] = parseFloat(taux.replace('%','')) || 0;
                        });
                        return stats;
                    })(),
                    stats_par_terrain: (() => {
                        const stats = {};
                        document.querySelectorAll('.stats-terrain tr:not(:first-child)').forEach(r => {
                            const terrain = r.querySelector('td:first-child')?.textContent?.trim();
                            const taux = r.querySelector('td:nth-child(3)')?.textContent?.trim();
                            if (terrain && taux) stats[terrain] = parseFloat(taux.replace('%','')) || 0;
                        });
                        return stats;
                    })(),
                };
            }
        """, default={})

        return data or {}

    async def get_stats_entraineur(self, entraineur_nom: str) -> dict:
        """Stats complètes d'un entraîneur."""
        slug = entraineur_nom.lower().replace(" ", "-").replace("'", "")
        url = f"{BASE}/entraineurs/{slug}"
        if not await self.safe_goto(url, timeout=20000):
            return {}

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => {
                const getNum = (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    return parseFloat(el.textContent.replace('%','').replace(',','.').trim()) || null;
                };
                return {
                    victoires_saison: getNum('.victoires-saison'),
                    courses_saison: getNum('.courses-saison'),
                    taux_victoire_global: getNum('.taux-victoire'),
                    taux_place_global: getNum('.taux-place'),
                    roi_global: getNum('.roi'),
                    stats_par_distance: (() => {
                        const stats = {};
                        document.querySelectorAll('.stats-distance tr:not(:first-child)').forEach(r => {
                            const dist = r.querySelector('td:first-child')?.textContent?.trim();
                            const taux = r.querySelector('td:nth-child(3)')?.textContent?.trim();
                            if (dist && taux) stats[dist] = parseFloat(taux.replace('%','')) || 0;
                        });
                        return stats;
                    })(),
                    stats_par_hippodrome: (() => {
                        const stats = {};
                        document.querySelectorAll('.stats-hippodrome tr:not(:first-child)').forEach(r => {
                            const hippo = r.querySelector('td:first-child')?.textContent?.trim();
                            const taux = r.querySelector('td:nth-child(3)')?.textContent?.trim();
                            if (hippo && taux) stats[hippo] = parseFloat(taux.replace('%','')) || 0;
                        });
                        return stats;
                    })(),
                };
            }
        """, default={})

        return data or {}
