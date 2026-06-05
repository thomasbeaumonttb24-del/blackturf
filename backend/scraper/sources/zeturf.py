"""
Source Zeturf.fr — Cotes opérateur privé. Crucial pour détection value bets.
Fréquence : toutes 5 minutes (haute priorité).
"""
import structlog
from scraper.base import BaseScraper, human_delay

log = structlog.get_logger(source="zeturf")

BASE = "https://www.zeturf.fr"


class ZeturfScraper(BaseScraper):

    async def get_cotes_du_jour(self) -> dict[str, dict[int, float]]:
        """
        Récupère les cotes Zeturf pour toutes les courses du jour.
        Retourne {course_id: {numero: cote}}.
        """
        url = f"{BASE}/pmu/programme"
        if not await self.safe_goto(url, timeout=20000):
            return {}

        await human_delay(2, 3.5)

        data = await self.safe_evaluate("""
            () => {
                const courses = {};
                document.querySelectorAll('[data-race-id], .race, .course-block').forEach(el => {
                    const id = el.dataset.raceId || el.dataset.courseId || '';
                    const cotes = {};
                    el.querySelectorAll('[data-horse-num], .participant').forEach(p => {
                        const num = parseInt(p.dataset.horseNum || p.querySelector('.numero')?.textContent);
                        const coteEl = p.querySelector('.odds, .cote');
                        const cote = parseFloat(coteEl?.textContent?.replace(',', '.'));
                        if (num && !isNaN(cote)) cotes[num] = cote;
                    });
                    if (id && Object.keys(cotes).length > 0) courses[id] = cotes;
                });
                return courses;
            }
        """, default={})

        return data or {}

    async def get_cotes_course(self, course_id: str) -> dict[int, float]:
        """Cotes Zeturf pour une course spécifique."""
        url = f"{BASE}/pmu/{course_id}"
        if not await self.safe_goto(url, timeout=15000):
            return {}

        await human_delay(1, 2)

        data = await self.safe_evaluate("""
            () => {
                const cotes = {};
                document.querySelectorAll('[data-horse-num], .participant-row').forEach(p => {
                    const num = parseInt(p.dataset.horseNum || p.querySelector('.num')?.textContent);
                    const cote = parseFloat(
                        (p.querySelector('.odds, .cote')?.textContent || '').replace(',', '.')
                    );
                    if (num && !isNaN(cote)) cotes[num] = cote;
                });
                return cotes;
            }
        """, default={})

        return data or {}
