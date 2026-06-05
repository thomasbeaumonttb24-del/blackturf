"""
Scraper Paris-Turf — pronostics journalistes + cotes de presse.
URLs cibles :
  - https://www.paris-turf.com/pronostics       (pronostics du jour)
  - https://www.canalturf.com/pronostics         (CanalTurf — 2e source)

Récupère :
  - Sélections des experts (numéros de chevaux par course)
  - Journaliste responsable du pronostic
  - Commentaire éventuel

Feature ML : "consensus presse" → si ≥ 3 experts sélectionnent le même cheval = signal fort.
"""
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay, PronosticPresseScrape

log = structlog.get_logger()

PARIS_TURF_URL = "https://www.paris-turf.com/pronostics"
CANAL_TURF_URL = "https://www.canalturf.com/pronostics-courses"


class ParisTurfScraper(BaseScraper):
    """Scrape les pronostics presse (Paris-Turf + CanalTurf)."""

    async def get_pronostics_paris_turf(self) -> list[PronosticPresseScrape]:
        """
        Récupère les pronostics Paris-Turf pour les courses du jour.
        """
        results: list[PronosticPresseScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(PARIS_TURF_URL)
        if not ok:
            self.log.warning("paris_turf.goto_failed")
            return results

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll(
                    '[class*="pronostic-course"], [class*="pronostic_course"], .prono-block, [class*="race-prono"]'
                ).forEach(block => {
                    const courseEl = block.querySelector(
                        '[class*="course-name"], [class*="race-name"], h2, h3, .course-title'
                    );
                    const journalisteEl = block.querySelector(
                        '[class*="journaliste"], [class*="expert"], [class*="author"], .byline'
                    );
                    const commentEl = block.querySelector(
                        '[class*="commentaire"], [class*="comment"], p.text, .description'
                    );

                    // Sélection : numéros des chevaux retenus
                    const selection = [];
                    block.querySelectorAll(
                        '[class*="cheval"], [class*="runner"], [class*="selection"] li, .horse-pick'
                    ).forEach((item, idx) => {
                        const numEl = item.querySelector('[class*="num"], [class*="number"]');
                        const nameEl = item.querySelector('[class*="name"], [class*="horse-name"]');
                        selection.push({
                            rang: idx + 1,
                            numero: numEl ? parseInt(numEl.textContent.trim()) || 0 : 0,
                            nom: nameEl ? nameEl.textContent.trim().toUpperCase() : '',
                        });
                    });

                    // Parfois la sélection est affichée comme "1-4-7-3"
                    if (selection.length === 0) {
                        const selText = block.querySelector(
                            '[class*="selection-numbers"], [class*="numeros"]'
                        );
                        if (selText) {
                            selText.textContent.trim().split(/[-,\s]+/).forEach((n, idx) => {
                                const num = parseInt(n.trim());
                                if (!isNaN(num) && num > 0) {
                                    selection.push({ rang: idx + 1, numero: num, nom: '' });
                                }
                            });
                        }
                    }

                    if (selection.length > 0) {
                        results.push({
                            course_label: courseEl ? courseEl.textContent.trim() : '',
                            journaliste: journalisteEl ? journalisteEl.textContent.trim() : '',
                            commentaire: commentEl ? commentEl.textContent.trim().substring(0, 500) : '',
                            selection,
                        });
                    }
                });
                return results;
            }
        """, default=[])

        for item in (data or []):
            pseudo_id = f"PT_{item.get('course_label', '')[:12].upper().replace(' ', '_')}"
            results.append(PronosticPresseScrape(
                course_id=pseudo_id,
                source="paris_turf",
                journaliste=item.get("journaliste") or None,
                selection=item.get("selection", []),
                commentaire=item.get("commentaire") or None,
            ))

        self.log.info("paris_turf.pronostics", nb=len(results), today=today)
        return results

    async def get_pronostics_canalturf(self) -> list[PronosticPresseScrape]:
        """
        Récupère les pronostics CanalTurf.
        Structure similaire à Paris-Turf.
        """
        results: list[PronosticPresseScrape] = []

        ok = await self.safe_goto(CANAL_TURF_URL)
        if not ok:
            self.log.warning("canalturf.goto_failed")
            return results

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll(
                    '.pronostic-item, [class*="prono-item"], [class*="course-block"]'
                ).forEach(block => {
                    const courseEl = block.querySelector('h2, h3, .title, [class*="course"]');
                    const selection = [];

                    // CanalTurf affiche souvent les sélections sous forme de tableau
                    block.querySelectorAll('tr, [class*="row"]').forEach((row, idx) => {
                        const num = row.querySelector(
                            '[class*="numero"], td:first-child, [class*="num"]'
                        );
                        const name = row.querySelector(
                            '[class*="cheval"], td:nth-child(2), [class*="horse"]'
                        );
                        if (num && name) {
                            selection.push({
                                rang: idx + 1,
                                numero: parseInt(num.textContent.trim()) || 0,
                                nom: name.textContent.trim().toUpperCase(),
                            });
                        }
                    });

                    if (selection.length > 0) {
                        results.push({
                            course_label: courseEl ? courseEl.textContent.trim() : '',
                            selection,
                        });
                    }
                });
                return results;
            }
        """, default=[])

        for item in (data or []):
            pseudo_id = f"CT_{item.get('course_label', '')[:12].upper().replace(' ', '_')}"
            results.append(PronosticPresseScrape(
                course_id=pseudo_id,
                source="canalturf",
                selection=item.get("selection", []),
            ))

        self.log.info("canalturf.pronostics", nb=len(results))
        return results
