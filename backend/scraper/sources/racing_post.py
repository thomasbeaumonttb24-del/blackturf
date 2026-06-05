"""
Scraper Racing Post — données internationales chevaux importés.
URL cible : https://www.racingpost.com/horses/{slug}/form

Récupère :
  - Historique complet pour les chevaux importés (UK/Irlande → France)
  - URL Racing Post du cheval (pour référence future)
  - Prix de vente yearling (ventes de Tattersalls, Goffs, Arqana)
  - Généalogie (complément à France Galop pour les chevaux étrangers)
  - Forme internationale : positions, distances, terrains, niveaux (Group 1, Listed...)

Cas d'usage principal : cheval importé sans historique France Galop
→ on récupère son palmarès UK/Irlande pour alimenter les features ML.
"""
import re
import structlog
from typing import Optional

from scraper.base import BaseScraper, human_delay, GeneralogieScrape

log = structlog.get_logger()

BASE_URL = "https://www.racingpost.com"
SEARCH_URL = "https://www.racingpost.com/horses/horse_home.sd?horse_id="
HORSE_SEARCH = "https://www.racingpost.com/horses/{slug}/form"


class RacingPostScraper(BaseScraper):
    """Scrape l'historique international des chevaux depuis Racing Post."""

    SOURCE = "racing_post"

    async def search_horse(self, nom_cheval: str) -> Optional[str]:
        """
        Recherche un cheval sur Racing Post.
        Retourne l'URL de la fiche Racing Post, ou None si non trouvé.
        """
        search_url = f"{BASE_URL}/search?q={nom_cheval.replace(' ', '+')}&type=horse"
        ok = await self.safe_goto(search_url)
        if not ok:
            return None

        await human_delay(1.0, 2.0)

        horse_url = await self.safe_evaluate("""
            () => {
                // Premier résultat de recherche cheval
                const link = document.querySelector(
                    '[class*="horse-result"] a, [data-type="horse"] a, .search-result-horse a'
                );
                return link ? link.href : null;
            }
        """, default=None)

        return horse_url

    async def get_fiche_cheval(
        self, nom_cheval: str, racing_post_url: Optional[str] = None
    ) -> Optional[dict]:
        """
        Récupère la fiche complète d'un cheval depuis Racing Post.
        Retourne dict avec généalogie + historique de courses.

        Utilisé principalement pour les chevaux importés (pays_naissance ≠ FR).
        """
        url = racing_post_url
        if not url:
            url = await self.search_horse(nom_cheval)
            if not url:
                self.log.debug("racing_post.horse_not_found", nom=nom_cheval)
                return None

        ok = await self.safe_goto(url)
        if not ok:
            return None

        await human_delay(1.0, 2.0)

        data = await self.safe_evaluate("""
            () => {
                const getText = (sel) => {
                    const el = document.querySelector(sel);
                    return el ? el.textContent.trim() : null;
                };

                // Généalogie Racing Post
                const genealogie = {
                    pere: getText('[data-test-id="horse-details-sire"] a, [class*="sire"] a'),
                    mere: getText('[data-test-id="horse-details-dam"] a, [class*="dam"]:not([class*="sire"])'),
                    pere_de_mere: getText('[data-test-id="horse-details-damsire"] a, [class*="damsire"] a'),
                    eleveur: getText('[data-test-id="horse-details-breeder"], [class*="breeder"]'),
                    pays_naissance: getText('[data-test-id="horse-details-country"], [class*="country"]'),
                    age: getText('[data-test-id="horse-details-age"], [class*="horse-age"]'),
                    prix_vente: getText('[class*="sale-price"], [class*="yearling-price"]'),
                };

                // Historique des courses internationales
                const courses = [];
                document.querySelectorAll(
                    '[class*="race-result"] tr, [class*="form-table"] tbody tr, .rp-table tr'
                ).forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length < 6) return;
                    courses.push({
                        date: cols[0]?.textContent?.trim() || '',
                        hippodrome: cols[1]?.textContent?.trim() || '',
                        distance: cols[2]?.textContent?.trim() || '',
                        terrain: cols[3]?.textContent?.trim() || '',
                        niveau: cols[4]?.textContent?.trim() || '',
                        position: cols[5]?.textContent?.trim() || '',
                        cote: cols[6]?.textContent?.trim() || '',
                    });
                });

                return { genealogie, courses, url: window.location.href };
            }
        """, default=None)

        if not data:
            return None

        return {
            "nom": nom_cheval,
            "racing_post_url": data.get("url") or racing_post_url,
            "genealogie": data.get("genealogie", {}),
            "historique_international": data.get("courses", []),
        }

    async def get_genealogie(self, nom_cheval: str) -> Optional[GeneralogieScrape]:
        """
        Récupère uniquement la généalogie depuis Racing Post.
        Complément à FranceGalopScraper pour les chevaux étrangers.
        """
        fiche = await self.get_fiche_cheval(nom_cheval)
        if not fiche:
            return None

        g = fiche.get("genealogie", {})
        prix_vente = _parse_prix_vente(g.get("prix_vente"))

        return GeneralogieScrape(
            cheval_nom=nom_cheval,
            pere=g.get("pere"),
            mere=g.get("mere"),
            pere_de_mere=g.get("pere_de_mere"),
            eleveur=g.get("eleveur"),
            pays_naissance=g.get("pays_naissance"),
            prix_vente_yearling=prix_vente,
            source=self.SOURCE,
        )

    async def get_historique_international(
        self, nom_cheval: str, racing_post_url: Optional[str] = None
    ) -> list[dict]:
        """
        Récupère l'historique de courses internationales.
        Retourne liste de dicts avec date, hippodrome, distance, terrain, position, cote.
        """
        fiche = await self.get_fiche_cheval(nom_cheval, racing_post_url)
        if not fiche:
            return []
        return fiche.get("historique_international", [])


def _parse_prix_vente(text: Optional[str]) -> Optional[int]:
    """Parse '£45,000' ou '€120,000' en int."""
    if not text:
        return None
    text = re.sub(r"[£€$,\s]", "", text).strip()
    try:
        return int(float(text))
    except ValueError:
        return None
