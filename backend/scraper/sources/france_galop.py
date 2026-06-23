"""
Scraper France Galop — données officielles courses plat/obstacle.
URLs cibles :
  - https://www.france-galop.com/fr/course-du-jour  (programme + pénétromètre)
  - https://www.france-galop.com/fr/cheval/{nom}    (fiche cheval : généalogie, style)
  - https://www.france-galop.com/fr/suspensions      (suspensions officielles)
  - https://www.france-galop.com/fr/resultat/{id}   (temps de passage post-course)

Récupère :
  - Coefficient pénétromètre par réunion (échelle 0-9)
  - Généalogie cheval (père, mère, père de mère, prix de vente)
  - Style de course (running style) depuis positions en course
  - Suspensions jockeys et entraîneurs
  - Temps de passage (splits) post-course
  - Poids réel à la pesée
"""
import re
import structlog
from datetime import date
from typing import Optional

from scraper.base import BaseScraper, human_delay
from scraper.base import (
    PenetrometreScrape, GeneralogieScrape, RunningStyleScrape,
    SuspensionScrape, TempsPassageScrape,
)

log = structlog.get_logger()

BASE = "https://www.france-galop.com/fr"
SUSPENSIONS_URL = f"{BASE}/suspensions"
# URL corrigée 2026-06-17 : /programme-des-courses renvoyait 404.
# /fr/courses/aujourdhui (server-rendered léger). Variantes: /demain /hier.
# NB: France-Galop = galop/plat-obstacle uniquement (pas de trot).
PROGRAMME_URL = f"{BASE}/courses/aujourdhui"


class FranceGalopScraper(BaseScraper):
    """Scrape les données officielles France Galop."""

    SOURCE = "france_galop"

    # ──────────────────────────────────────────────────
    # Pénétromètre
    # ──────────────────────────────────────────────────

    async def get_penetrometre_du_jour(self) -> list[PenetrometreScrape]:
        """
        Récupère les coefficients de pénétromètre pour toutes les réunions du jour.
        France Galop publie le coefficient dans le bulletin de réunion.
        """
        results: list[PenetrometreScrape] = []
        today = date.today().isoformat()

        ok = await self.safe_goto(PROGRAMME_URL)
        if not ok:
            return results

        await human_delay(1.5, 2.5)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                // France Galop affiche le bulletin de réunion avec le pénétromètre
                // Structure : sections par réunion avec les infos terrain
                document.querySelectorAll(
                    '[class*="reunion"], [class*="meeting"], .programme-reunion'
                ).forEach(section => {
                    const hippoEl = section.querySelector(
                        '[class*="hippodrome"], [class*="venue"], h2, h3'
                    );
                    const reunionEl = section.querySelector('[class*="reunion-num"], [data-reunion]');

                    // Chercher le pénétromètre : affiché sous "Terrain : Bon (3.5)"
                    const terrainEl = section.querySelector(
                        '[class*="terrain"], [class*="ground"], [class*="going"]'
                    );
                    const penEl = section.querySelector(
                        '[class*="penetrometre"], [class*="coefficient"], [class*="coef"]'
                    );

                    const terrainText = (terrainEl || penEl) ?
                        (terrainEl || penEl).textContent.trim() : '';

                    if (terrainText) {
                        results.push({
                            reunion_id: reunionEl ? reunionEl.getAttribute('data-reunion') || '' : '',
                            hippodrome: hippoEl ? hippoEl.textContent.trim() : '',
                            terrain_text: terrainText,
                        });
                    }
                });
                return results;
            }
        """, default=[])

        for item in (data or []):
            coef, desc = _parse_penetrometre(item.get("terrain_text", ""))
            if coef is not None:
                results.append(PenetrometreScrape(
                    reunion_id=item.get("reunion_id", ""),
                    hippodrome=item.get("hippodrome", ""),
                    date=today,
                    coefficient=coef,
                    description=desc,
                ))

        self.log.info("france_galop.penetrometre", nb=len(results))
        return results

    # ──────────────────────────────────────────────────
    # Généalogie cheval
    # ──────────────────────────────────────────────────

    async def get_genealogie(self, nom_cheval: str) -> Optional[GeneralogieScrape]:
        """
        Récupère la généalogie d'un cheval depuis sa fiche France Galop.
        """
        # Normaliser le nom pour l'URL
        nom_url = nom_cheval.lower().replace(" ", "-").replace("'", "")
        url = f"{BASE}/cheval/{nom_url}"

        ok = await self.safe_goto(url)
        if not ok:
            # Essayer recherche
            url = f"{BASE}/recherche-cheval?q={nom_cheval.replace(' ', '+')}"
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

                // France Galop fiche cheval structure
                const genealogie = document.querySelector(
                    '[class*="genealogie"], [class*="pedigree"], .fiche-cheval-genealogie'
                );

                return {
                    code_sire: getText('[class*="code-sire"], [data-sire]') ||
                               document.querySelector('[class*="sire"]')?.getAttribute('data-value'),
                    pere: getText('[class*="pere"]:not([class*="mere"]), .pedigree-sire, [data-role="pere"]'),
                    mere: getText('[class*="mere"]:not([class*="pere"]), .pedigree-dam, [data-role="mere"]'),
                    pere_de_mere: getText('[class*="pere-de-mere"], .pedigree-broodmare-sire, [data-role="broodmare"]'),
                    mere_de_mere: getText('[class*="mere-de-mere"], [data-role="granddam"]'),
                    eleveur: getText('[class*="eleveur"], [class*="breeder"]'),
                    pays_naissance: getText('[class*="pays-naissance"], [class*="country-birth"]'),
                    date_naissance: getText('[class*="date-naissance"], [class*="foaling-date"]'),
                    prix_vente_text: getText('[class*="prix-vente"], [class*="sale-price"], [class*="yearling-price"]'),
                };
            }
        """, default={})

        if not data:
            return None

        prix_vente = _parse_prix_vente(data.get("prix_vente_text"))

        return GeneralogieScrape(
            cheval_nom=nom_cheval,
            code_sire=data.get("code_sire"),
            pere=data.get("pere"),
            mere=data.get("mere"),
            pere_de_mere=data.get("pere_de_mere"),
            mere_de_mere=data.get("mere_de_mere"),
            eleveur=data.get("eleveur"),
            pays_naissance=data.get("pays_naissance"),
            prix_vente_yearling=prix_vente,
            date_naissance=data.get("date_naissance"),
            source=self.SOURCE,
        )

    # ──────────────────────────────────────────────────
    # Running style (style de course)
    # ──────────────────────────────────────────────────

    async def get_running_style(self, nom_cheval: str) -> Optional[RunningStyleScrape]:
        """
        Analyse le style de course depuis l'historique France Galop.
        Style calculé depuis les positions en course (mène / suit / ferme).
        """
        nom_url = nom_cheval.lower().replace(" ", "-").replace("'", "")
        url = f"{BASE}/cheval/{nom_url}/historique"

        ok = await self.safe_goto(url)
        if not ok:
            return None

        await human_delay(1.0, 2.0)

        data = await self.safe_evaluate("""
            () => {
                const rows = [];
                // Historique des courses — France Galop affiche position à différents points
                document.querySelectorAll(
                    '[class*="historique"] tr, [class*="result-row"], .race-history tr'
                ).forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length < 5) return;

                    // Colonne "Position en course" (souvent 4e ou 5e colonne)
                    // France Galop montre parfois "2-1-1" (pos 400m-800m-final)
                    const posText = cols[4] ? cols[4].textContent.trim() : '';
                    const finalPos = cols[cols.length - 2] ?
                        parseInt(cols[cols.length - 2].textContent.trim()) : null;

                    rows.push({
                        pos_course: posText,
                        pos_finale: finalPos,
                    });
                });
                return rows;
            }
        """, default=[])

        if not data:
            return None

        style, taux = _calculate_running_style(data)
        return RunningStyleScrape(
            cheval_nom=nom_cheval,
            running_style=style,
            taux_en_tete=taux,
            nb_courses_analyses=len(data),
            source=self.SOURCE,
        )

    # ──────────────────────────────────────────────────
    # Suspensions officielles
    # ──────────────────────────────────────────────────

    async def get_suspensions(self) -> list[SuspensionScrape]:
        """
        Récupère les suspensions actuelles de jockeys et entraîneurs.
        France Galop publie sur : france-galop.com/fr/suspensions
        """
        results: list[SuspensionScrape] = []

        ok = await self.safe_goto(SUSPENSIONS_URL)
        if not ok:
            return results

        await human_delay(1.0, 2.0)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll(
                    'table tr, [class*="suspension"] li, [class*="suspension-item"]'
                ).forEach(row => {
                    const cols = row.querySelectorAll('td, [class*="col"]');
                    if (cols.length < 3) return;

                    results.push({
                        nom: cols[0] ? cols[0].textContent.trim() : '',
                        type_pro: cols[1] ? cols[1].textContent.trim().toLowerCase() : 'jockey',
                        date_debut: cols[2] ? cols[2].textContent.trim() : '',
                        date_fin: cols[3] ? cols[3].textContent.trim() : '',
                        nb_jours: cols[4] ? cols[4].textContent.trim() : '',
                        motif: cols[5] ? cols[5].textContent.trim() : '',
                    });
                });
                return results;
            }
        """, default=[])

        for item in (data or []):
            nom = item.get("nom", "").strip()
            if not nom:
                continue

            type_pro = "jockey"
            raw_type = item.get("type_pro", "")
            if "entra" in raw_type:
                type_pro = "entraineur"
            elif "driver" in raw_type:
                type_pro = "driver"

            nb_jours = None
            try:
                nb_jours = int(item.get("nb_jours", "").replace("j", "").strip())
            except Exception:
                pass

            results.append(SuspensionScrape(
                nom=nom,
                type_pro=type_pro,
                source=self.SOURCE,
                date_debut=item.get("date_debut", ""),
                date_fin=item.get("date_fin") or None,
                nb_jours=nb_jours,
                motif=item.get("motif") or None,
            ))

        self.log.info("france_galop.suspensions", nb=len(results))
        return results

    # ──────────────────────────────────────────────────
    # Temps de passage (splits) post-course
    # ──────────────────────────────────────────────────

    async def get_temps_passage(self, course_id: str, url_resultat: str) -> list[TempsPassageScrape]:
        """
        Récupère les temps de passage depuis la page résultat France Galop.
        Disponible après la course.
        """
        results: list[TempsPassageScrape] = []

        ok = await self.safe_goto(url_resultat)
        if not ok:
            return results

        await human_delay(1.0, 2.0)

        data = await self.safe_evaluate("""
            () => {
                const runners = [];
                document.querySelectorAll(
                    '[class*="temps-passage"] tr, [class*="splits"] tr, .timing-table tr'
                ).forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length < 3) return;
                    runners.push({
                        numero: cols[0] ? parseInt(cols[0].textContent.trim()) || 0 : 0,
                        nom: cols[1] ? cols[1].textContent.trim().toUpperCase() : '',
                        t400: cols[2] ? cols[2].textContent.trim() : null,
                        t800: cols[3] ? cols[3].textContent.trim() : null,
                        t1000: cols[4] ? cols[4].textContent.trim() : null,
                        t1600: cols[5] ? cols[5].textContent.trim() : null,
                        tdernier400: cols[cols.length - 1] ? cols[cols.length - 1].textContent.trim() : null,
                    });
                });
                return runners;
            }
        """, default=[])

        for item in (data or []):
            if not item.get("nom"):
                continue
            results.append(TempsPassageScrape(
                course_id=course_id,
                numero=item.get("numero", 0),
                nom=item["nom"],
                passage_400m=item.get("t400") or None,
                passage_800m=item.get("t800") or None,
                passage_1000m=item.get("t1000") or None,
                passage_1600m=item.get("t1600") or None,
                passage_dernier_400m=item.get("tdernier400") or None,
            ))

        return results

    # ──────────────────────────────────────────────────
    # Poids réels post-pesée
    # ──────────────────────────────────────────────────

    async def get_poids_pesee(self, url_programme: str) -> list[dict]:
        """
        Récupère les poids réels après la pesée officielle.
        Retourne [{"numero": 3, "nom": "X", "poids_reel": 58.5}, ...]
        """
        ok = await self.safe_goto(url_programme)
        if not ok:
            return []

        await human_delay(0.8, 1.5)

        data = await self.safe_evaluate("""
            () => {
                const results = [];
                document.querySelectorAll(
                    '[class*="pesee"] tr, [class*="weigh-in"] tr, .partants-table tr'
                ).forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length < 4) return;
                    const poidsEl = row.querySelector('[class*="poids-pesee"], [class*="actual-weight"]');
                    results.push({
                        numero: parseInt(cols[0]?.textContent?.trim()) || 0,
                        nom: (cols[1]?.textContent?.trim() || '').toUpperCase(),
                        poids_reel: poidsEl ? parseFloat(poidsEl.textContent.trim().replace(',', '.')) : null,
                    });
                });
                return results;
            }
        """, default=[])

        return [r for r in (data or []) if r.get("nom") and r.get("poids_reel")]


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────

def _parse_penetrometre(text: str) -> tuple[Optional[float], str]:
    """
    Parse le texte terrain de France Galop.
    Exemples : "Bon (3.5)", "Souple 4.2", "Très souple (7.1)", "Lourd 8.0"
    Retourne (coefficient, description).
    """
    if not text:
        return None, ""

    # Chercher un nombre décimal dans le texte
    match = re.search(r"(\d+[,.]?\d*)", text)
    coef = None
    if match:
        try:
            coef = float(match.group(1).replace(",", "."))
        except ValueError:
            pass

    # Description = texte avant le coefficient
    desc = re.sub(r"[\(\)\d,. ]+", "", text).strip()
    if not desc:
        # Déduire la description depuis le coefficient
        if coef is not None:
            if coef < 3.0:
                desc = "Bon ferme"
            elif coef < 4.5:
                desc = "Bon"
            elif coef < 6.5:
                desc = "Souple"
            elif coef < 7.5:
                desc = "Très souple"
            else:
                desc = "Lourd"

    return coef, desc


def _parse_prix_vente(text: Optional[str]) -> Optional[int]:
    """Parse '45 000 €' ou '45000' en entier."""
    if not text:
        return None
    text = text.replace(" ", "").replace("€", "").replace("EUR", "").replace(",", "")
    try:
        return int(float(text))
    except ValueError:
        return None


def _calculate_running_style(rows: list[dict]) -> tuple[str, float]:
    """
    Calcule le running style depuis l'historique.
    Retourne (style, taux_en_tete).
    """
    if not rows:
        return "irregulier", 0.0

    en_tete = 0
    suit_tete = 0
    ferme = 0
    total = 0

    for row in rows:
        pos_text = str(row.get("pos_course", ""))
        pos_finale = row.get("pos_finale")

        if not pos_text and not pos_finale:
            continue

        total += 1
        # Analyser la position en course si disponible (ex: "1-2-3")
        if "-" in pos_text:
            parts = pos_text.split("-")
            try:
                first_pos = int(parts[0])
                if first_pos == 1:
                    en_tete += 1
                elif first_pos <= 3:
                    suit_tete += 1
                else:
                    ferme += 1
            except ValueError:
                pass

    if total == 0:
        return "irregulier", 0.0

    taux_en_tete = en_tete / total
    taux_suit = suit_tete / total
    taux_ferme = ferme / total

    if taux_en_tete >= 0.35:
        return "mene", round(taux_en_tete, 2)
    elif taux_en_tete + taux_suit >= 0.50:
        return "suit_tete", round(taux_en_tete, 2)
    elif taux_ferme >= 0.40:
        return "ferme", round(taux_en_tete, 2)
    else:
        return "placier", round(taux_en_tete, 2)
