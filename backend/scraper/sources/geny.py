"""
Source Geny.com — Pronostics experts, cotes Geny, stats jockey/entraîneur.

get_partants_du_jour() : réécrit 2026-06-17 en httpx + BeautifulSoup (PLUS de
Playwright). La page index https://www.geny.com/reunions-courses-pmu et les
pages course https://www.geny.com/partants-pmu/{slug}_c{id} sont entièrement
server-rendered (HTTP 200, pas de Cloudflare). Testé sur le HTML live.

Particularité encodage : Geny renvoie un charset déclaré utf-8 alors que les
octets sont en latin-1 → on force r.encoding = "latin-1".

Les autres méthodes (cotes/fiche cheval/jockey) restent en Playwright.
Fréquence : toutes 10 minutes.
"""
import re
import time
import random
import unicodedata
import structlog
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseScraper, human_delay

log = structlog.get_logger(source="geny")

BASE = "https://www.geny.com"

# Index server-rendered listant toutes les courses PMU du jour.
INDEX_URL = f"{BASE}/reunions-courses-pmu"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Nb max de pages course fetchées par cycle + délai poli entre requêtes.
MAX_COURSES_PER_CYCLE = 40
_DELAY_MIN, _DELAY_MAX = 0.4, 0.9

# /partants-pmu/2026-06-17-agen-le-passage-pmu-prix-de-toulouse_c1660470
_COURSE_RE = re.compile(
    r"/partants-pmu/(\d{4}-\d{2}-\d{2})-(.+?)-pmu-(.+?)_c(\d+)$"
)


def _clean_text(s: Optional[str]) -> str:
    """Supprime les glyphes de la police d'icônes Geny (PUA) + espaces."""
    if not s:
        return ""
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Co")
    return re.sub(r"\s+", " ", s).strip()


def _parse_cote(s: Optional[str]) -> Optional[float]:
    """'47,9' -> 47.9 ; '-' / 'NP' / vide -> None."""
    s = _clean_text(s).replace(",", ".")
    if not s or s in ("-", "NP"):
        return None
    m = re.match(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _fetch(client: httpx.Client, url: str) -> Optional[BeautifulSoup]:
    try:
        r = client.get(url, timeout=30.0)
    except Exception as e:  # noqa: BLE001
        log.warning("geny.http_error", url=url, error=str(e))
        return None
    if r.status_code != 200:
        log.warning("geny.http_status", url=url, status=r.status_code)
        return None
    # Geny déclare utf-8 mais sert du latin-1.
    r.encoding = "latin-1"
    text = r.text
    if "Just a moment" in text or "cf-browser-verification" in text:
        log.warning("geny.cloudflare_block", url=url)
        return None
    return BeautifulSoup(text, "html.parser")


def _parse_index(soup: BeautifulSoup) -> list[dict]:
    """Extrait la liste des courses du jour depuis l'index."""
    seen: set[str] = set()
    courses: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        if "/partants-pmu/" not in href:
            continue
        if href in seen:
            continue
        m = _COURSE_RE.search(href)
        if not m:
            continue
        seen.add(href)
        date, hippo, prix, cid = m.groups()
        courses.append({
            "course_id": int(cid),
            "date": date,
            "hippodrome": hippo.replace("-", " ").title(),
            "prix": prix.replace("-", " ").title(),
            "url": href if href.startswith("http") else f"{BASE}{href}",
        })
    return courses


def _parse_course(soup: BeautifulSoup) -> list[dict]:
    """Extrait les chevaux d'une page course (#tableau_partants).

    Colonnes utiles : N° (1ère cellule), Cheval (1ère cellule alphanumérique),
    Cotes références (avant-dernière cellule), Dernières cotes (dernière).
    Le layout varie (trot 11 col / galop 15 col), mais les deux cotes sont
    TOUJOURS les deux dernières <td> → robuste.
    """
    table = soup.find("table", id="tableau_partants")
    if table is None:
        return []

    chevaux: list[dict] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:  # header (th) ou ligne séparatrice
            continue
        num_raw = _clean_text(tds[0].get_text())
        m = re.match(r"\d+", num_raw)
        if not m:
            continue
        numero = int(m.group())

        # Nom = 1ère cellule (après le n°) contenant du texte alphabétique.
        nom = ""
        for td in tds[1:]:
            link = td.find("a")
            txt = _clean_text(link.get_text() if link else td.get_text())
            if txt and re.search(r"[A-Za-zÀ-ÿ]", txt):
                nom = txt
                break
        if not nom:
            continue

        cote_ref = _parse_cote(tds[-2].get_text())
        cote_last = _parse_cote(tds[-1].get_text())
        chevaux.append({
            "numero": numero,
            "nom": nom,
            "cote_geny": cote_last if cote_last is not None else cote_ref,
            "_ref": cote_ref,
        })

    # Rang pronostic Geny dérivé de l'ordre des cotes de référence
    # (favori = rang 1). Pas de synthèse explicite server-rendered.
    ranked = sorted(
        (c for c in chevaux if c["_ref"] is not None),
        key=lambda c: c["_ref"],
    )
    for i, c in enumerate(ranked):
        c["rang_pronostic_geny"] = i + 1
    for c in chevaux:
        c.setdefault("rang_pronostic_geny", None)
        c.pop("_ref", None)
    return chevaux


def _scrape_partants_sync(proxy: Optional[str] = None) -> list[dict]:
    """Travail bloquant httpx+bs4 (exécuté dans un thread).

    proxy : depuis settings.brightdata_proxy. INDISPENSABLE en prod — l'IP
    datacenter du VPS (Hetzner) reçoit un 403 de Geny (anti-bot IP). Une IP
    résidentielle (proxy) ou locale passe en 200. Sans proxy → 403 → liste vide
    (dégrade proprement, aucune fausse donnée).
    """
    out: list[dict] = []
    client_kwargs = {"headers": _HEADERS, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy
    with httpx.Client(**client_kwargs) as client:
        idx = _fetch(client, INDEX_URL)
        if idx is None:
            return []
        courses = _parse_index(idx)
        log.info("geny.index_courses", count=len(courses))

        for i, course in enumerate(courses[:MAX_COURSES_PER_CYCLE]):
            soup = _fetch(client, course["url"])
            if soup is None:
                continue
            chevaux = _parse_course(soup)
            if not chevaux:
                continue
            out.append({
                "course_id": course["course_id"],
                "date": course["date"],
                "hippodrome": course["hippodrome"],
                "prix": course["prix"],
                "url": course["url"],
                "chevaux": chevaux,
            })
            # Délai poli entre requêtes pour ne pas se faire bannir.
            if i < len(courses) - 1:
                time.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))
    return out


class GenyScraper(BaseScraper):

    async def get_partants_du_jour(self) -> list[dict]:
        """Partants + cotes Geny + rangs pronostic (httpx+bs4, pas de Playwright).

        Retourne une list[dict] : chaque course a `chevaux` = liste de
        {numero, nom, cote_geny, rang_pronostic_geny} + hints
        {course_id, date, hippodrome, prix, url}.
        `self.page` reste inutilisé ici (gardé pour compat constructeur).
        """
        import asyncio
        try:
            from api.config import get_settings
            proxy = getattr(get_settings(), "brightdata_proxy", None)
        except Exception:
            proxy = None

        data = await asyncio.to_thread(_scrape_partants_sync, proxy)
        nb_chevaux = sum(len(c.get("chevaux", [])) for c in data)
        log.info("geny.courses_found", count=len(data), chevaux=nb_chevaux)
        return data

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
