"""
Source Geny.com — Pronostics experts, cotes Geny, stats jockey/entraîneur.
Site JS dynamique → Playwright obligatoire.
Fréquence : toutes 10 minutes.
"""
import structlog
from typing import Optional
from scraper.base import BaseScraper, human_delay

log = structlog.get_logger(source="geny")

BASE = "https://www.geny.com"


class GenyScraper(BaseScraper):

    async def get_partants_du_jour(self) -> list[dict]:
        """Récupère les partants + cotes Geny + rangs pronostic."""
        url = f"{BASE}/partants-pronostics"
        if not await self.safe_goto(url, timeout=30000):
            return []

        await human_delay(2, 4)

        try:
            await self.page.wait_for_selector(
                ".course, .race, [class*='course'], [data-course-id]",
                timeout=12000,
            )
        except Exception:
            log.warning("geny.selector_timeout")

        data = await self.safe_evaluate("""
            () => {
                const courses = [];
                const blocks = document.querySelectorAll(
                    '[data-course-id], .race-block, .course-block, .programme-course'
                );
                blocks.forEach(el => {
                    const id = el.dataset.courseId || el.dataset.raceId || '';
                    const title = el.querySelector('.course-title, .race-title, h2, h3')?.textContent?.trim() || '';
                    const chevaux = [];
                    el.querySelectorAll('.participant, .horse-row, [class*="partant"], tr[data-horse-id]').forEach((p, idx) => {
                        const numEl = p.querySelector('.num, .numero, [class*="number"], td:first-child');
                        const nomEl = p.querySelector('.name, .horse-name, [class*="nom"], td:nth-child(2)');
                        const coteEl = p.querySelector('.cote, .odds, [class*="cote"]');
                        const jockeyEl = p.querySelector('.jockey, [class*="jockey"]');
                        const pronoEl = p.querySelector('.prono, [class*="pronostic"], .rank');
                        chevaux.push({
                            numero: numEl?.textContent?.trim(),
                            nom: nomEl?.textContent?.trim(),
                            cote_geny: coteEl?.textContent?.trim()?.replace(',', '.'),
                            jockey: jockeyEl?.textContent?.trim(),
                            rang_pronostic_geny: pronoEl?.textContent?.trim(),
                        });
                    });
                    if (title || chevaux.length > 0) {
                        courses.push({ id, title, chevaux });
                    }
                });
                return courses;
            }
        """, default=[])

        log.info("geny.courses_found", count=len(data) if data else 0)
        return data or []

    async def get_cotes_course(self, course_url: str) -> dict[str, float]:
        """Récupère les cotes Geny pour une course spécifique."""
        if not await self.safe_goto(f"{BASE}{course_url}", timeout=20000):
            return {}

        await human_delay(1.5, 3)

        data = await self.safe_evaluate("""
            () => {
                const cotes = {};
                document.querySelectorAll('[data-horse-num], .partant-row').forEach(el => {
                    const num = el.dataset.horseNum || el.querySelector('.numero')?.textContent?.trim();
                    const cote = el.querySelector('.cote-geny, .cote, .odds')?.textContent?.trim();
                    if (num && cote) {
                        cotes[num] = parseFloat(cote.replace(',', '.'));
                    }
                });
                return cotes;
            }
        """, default={})

        return data or {}

    async def get_fiche_cheval(self, cheval_nom: str) -> dict:
        """Récupère l'historique et les stats d'un cheval."""
        url = f"{BASE}/chevaux/{cheval_nom.lower().replace(' ', '-')}"
        if not await self.safe_goto(url, timeout=20000):
            return {}

        await human_delay(2, 3)

        data = await self.safe_evaluate("""
            () => ({
                nom: document.querySelector('h1, .horse-name, .cheval-nom')?.textContent?.trim(),
                age: document.querySelector('.age, [class*="age"]')?.textContent?.trim(),
                sexe: document.querySelector('.sexe, [class*="sexe"]')?.textContent?.trim(),
                gains: document.querySelector('.gains-total, [class*="gains"]')?.textContent?.trim(),
                entraineur: document.querySelector('.entraineur, [class*="trainer"]')?.textContent?.trim(),
                proprietaire: document.querySelector('.proprietaire')?.textContent?.trim(),
                pere: document.querySelector('.pere, [class*="father"]')?.textContent?.trim(),
                mere: document.querySelector('.mere, [class*="mother"]')?.textContent?.trim(),
                historique: Array.from(
                    document.querySelectorAll('.course-history tr:not(:first-child), .past-race')
                ).slice(0, 20).map(r => ({
                    date: r.querySelector('.date, td:nth-child(1)')?.textContent?.trim(),
                    hippodrome: r.querySelector('.hippo, .track, td:nth-child(2)')?.textContent?.trim(),
                    distance: r.querySelector('.distance, td:nth-child(3)')?.textContent?.trim(),
                    terrain: r.querySelector('.terrain, td:nth-child(4)')?.textContent?.trim(),
                    position: r.querySelector('.pos, .position, td:nth-child(5)')?.textContent?.trim(),
                    cote: r.querySelector('.cote, .odds, td:nth-child(6)')?.textContent?.trim(),
                }))
            })
        """, default={})

        return data or {}

    async def get_stats_jockey(self, jockey_nom: str) -> dict:
        """Stats du jockey depuis Geny."""
        url = f"{BASE}/jockeys/{jockey_nom.lower().replace(' ', '-')}"
        if not await self.safe_goto(url, timeout=20000):
            return {}

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => ({
                nom: document.querySelector('h1')?.textContent?.trim(),
                victoires: document.querySelector('.victoires, .wins')?.textContent?.trim(),
                taux_victoire: document.querySelector('.taux-victoire')?.textContent?.trim(),
                taux_place: document.querySelector('.taux-place')?.textContent?.trim(),
            })
        """, default={})

        return data or {}
