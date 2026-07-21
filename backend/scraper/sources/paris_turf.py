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
import re
import asyncio
import structlog
from datetime import date
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseScraper, human_delay, PronosticPresseScrape, random_user_agent

log = structlog.get_logger()

# URLs corrigées 2026-06-17 (anciennes en 404).
# Paris-Turf : programme server-rendered riche (variantes /demain /hier).
# CanalTurf : vieux site PHP (pas de SPA, facile à scraper) — page .php directe.
PARIS_TURF_URL = "https://www.paris-turf.com/programme-courses/aujourdhui"
CANAL_TURF_URL = "https://www.canalturf.com/courses_liste_pronostics.php"
# Equidia (3e source, 2026-07-03) : API JSON publique — pas de HTML à parser.
EQUIDIA_API = "https://api.equidia.fr/api/public"


class ParisTurfScraper(BaseScraper):
    """Scrape les pronostics presse (Paris-Turf + CanalTurf)."""

    async def get_pronostics_paris_turf(self) -> list[PronosticPresseScrape]:
        """
        Récupère les pronostics Paris-Turf en httpx + BeautifulSoup (PAS Playwright).

        Paris-Turf est une SPA Next.js : le DOM des composants (MUI) ne contient
        AUCUNE classe exploitable, MAIS la page est server-rendered et embarque
        l'intégralité de l'état dans un <script id="__NEXT_DATA__"> (JSON). Le
        pronostic du journaliste s'y trouve sous :
            props.pageProps.initialState.currentPageState.webTips
        avec :
          - author        → journaliste (ex. "Bruno Jolivet")
          - text          → commentaire narratif
          - meetingName   → hippodrome (ex. "Agen")
          - tips.{A,C,O,…} → catégories de sélection. Chaque catégorie a un
            saddleList ("4,6,2,3,7" = numéros ordonnés) et un nameList aligné.
            Ordre de lecture A (base) → C (chances rég.) → O (outsiders) → … = rang.

        Architecture du scrape :
          1) Page programme du jour (PARIS_TURF_URL) → liste server-rendered des
             liens /course/{hippo}-{prix}-idc-{hash} (un par course).
          2) Page détail de chaque course → __NEXT_DATA__ → webTips → sélection.

        Pseudo course_id : "PT_{HIPPODROME[:12]}" (convention conservée).

        Note encodage : le serveur déclare charset utf-8 mais émet en réalité des
        octets cp1252 (é=0xE9). On décode donc en cp1252 (errors=replace pour le
        rare octet 0x81 non défini) afin d'obtenir des accents corrects.
        """
        results: list[PronosticPresseScrape] = []
        today = date.today().isoformat()

        headers = {
            "User-Agent": random_user_agent(),
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=30.0, follow_redirects=True
            ) as client:
                # 1) Page programme → liens vers les pages détail des courses
                resp = await client.get(PARIS_TURF_URL)
                if resp.status_code != 200:
                    self.log.warning(
                        "paris_turf.listing_http_error", status=resp.status_code
                    )
                    return results
                courses = _pt_parse_listing(_pt_decode(resp.content))
                if not courses:
                    self.log.warning("paris_turf.listing_empty")
                    return results

                # 2) Page détail de chaque course → webTips → sélection ordonnée
                for course in courses:
                    try:
                        dresp = await client.get(course["url"])
                        if dresp.status_code != 200:
                            continue
                        detail = _pt_parse_detail(_pt_decode(dresp.content))
                        if not detail or not detail.get("selection"):
                            continue

                        hippo_src = detail.get("hippodrome") or course.get("hippo_hint") or ""
                        hippo = hippo_src[:12].upper().replace(" ", "_")
                        # Encode R/C (réunion/course) → résolution course_id EXACTE
                        # (PT_{hippo} seul = non résolvable, presse perdue).
                        reunion = detail.get("reunion")
                        course_num = detail.get("course")
                        if reunion and course_num:
                            pseudo_id = f"PT_{hippo}_R{reunion}C{course_num}"
                        else:
                            pseudo_id = f"PT_{hippo}"
                        results.append(PronosticPresseScrape(
                            course_id=pseudo_id,
                            source="paris_turf",
                            journaliste=detail.get("journaliste") or None,
                            selection=detail["selection"],
                            commentaire=detail.get("commentaire") or None,
                        ))
                    except Exception as e:
                        self.log.warning(
                            "paris_turf.detail_error", url=course.get("url"), error=str(e)
                        )
                    # politesse : petit délai entre pages détail
                    await human_delay(0.2, 0.5)

        except Exception as e:
            self.log.error("paris_turf.fetch_error", error=str(e))
            return results

        self.log.info("paris_turf.pronostics", nb=len(results), today=today)
        return results

    async def get_pronostics_canalturf(self) -> list[PronosticPresseScrape]:
        """
        Récupère les pronostics CanalTurf en httpx + BeautifulSoup (PAS Playwright).

        CanalTurf est un vieux site PHP server-rendered : tout le contenu est dans
        le HTML brut. Architecture :
          1) La page « liste des pronostics » (CANAL_TURF_URL) liste toutes les
             courses du jour, regroupées par réunion (panels Bootstrap). Chaque
             course = un <a.list-group-item> pointant vers sa page détail.
          2) La page détail de chaque course contient la sélection du journaliste
             sous forme de 3 tableaux (BASE / CHANCES REGULIERES / OUTSIDERS),
             chaque ligne = <td>numero</td><td>NOM</td>. L'ordre de lecture
             (BASE d'abord) donne le rang du pronostic. Le journaliste figure dans
             un <h3>La sélection de {Nom}</h3> et un commentaire narratif précède.

        Pseudo course_id : "CT_{HIPPODROME}" (convention conservée) — résolu plus
        tard par resolve_bookmaker_course_id (split('_')[1] → hint hippodrome).
        """
        results: list[PronosticPresseScrape] = []

        headers = {
            "User-Agent": random_user_agent(),
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=30.0, follow_redirects=True
            ) as client:
                # 1) Page liste → toutes les courses (url détail + hippodrome)
                resp = await client.get(CANAL_TURF_URL)
                if resp.status_code != 200:
                    self.log.warning(
                        "canalturf.listing_http_error", status=resp.status_code
                    )
                    return results
                listing_html = resp.content.decode("utf-8", errors="replace")
                courses = _ct_parse_listing(listing_html)
                if not courses:
                    self.log.warning("canalturf.listing_empty")
                    return results

                # 2) Page détail de chaque course → sélection ordonnée + journaliste
                for course in courses:
                    try:
                        dresp = await client.get(course["url"])
                        if dresp.status_code != 200:
                            continue
                        detail_html = dresp.content.decode("utf-8", errors="replace")
                        selection, journaliste, commentaire = _ct_parse_detail(detail_html)
                        if not selection:
                            continue

                        hippo = (course.get("hippodrome") or "")[:12].upper().replace(" ", "_")
                        # Encode réunion/course dans le pseudo-id → résolution
                        # course_id EXACTE (CT_{hippo} seul = ambigu, N courses →
                        # 0 prono sauvé). Format CT_{HIPPO}_R{r}C{c} (course_id PMU
                        # = {ddmmyyyy}R{r}C{c}, R/C unique par jour).
                        reunion = course.get("reunion")
                        course_num = course.get("course")
                        if reunion and course_num:
                            pseudo_id = f"CT_{hippo}_R{reunion}C{course_num}"
                        else:
                            pseudo_id = f"CT_{hippo}"
                        results.append(PronosticPresseScrape(
                            course_id=pseudo_id,
                            source="canalturf",
                            journaliste=journaliste or None,
                            selection=selection,
                            commentaire=commentaire or None,
                        ))
                    except Exception as e:
                        self.log.warning(
                            "canalturf.detail_error", url=course.get("url"), error=str(e)
                        )
                    # politesse : petit délai entre pages détail
                    await human_delay(0.2, 0.5)

        except Exception as e:
            self.log.error("canalturf.fetch_error", error=str(e))
            return results

        self.log.info("canalturf.pronostics", nb=len(results))
        return results

    async def get_pronostics_equidia(self) -> list[PronosticPresseScrape]:
        """
        Récupère les pronostics Equidia via l'API JSON publique (httpx, pas de
        Playwright ni d'anti-bot — même API que le site www.equidia.fr).

          1) GET {EQUIDIA_API}/dailyreunions/{YYYY-MM-DD} → réunions du jour,
             chacune avec num_reunion (= n° PMU) et courses_by_day[].num_course_pmu.
          2) GET {EQUIDIA_API}/courses/{date}/R{r}/C{c}/pronostic → pronostic du
             journaliste : creator (nom), chapeau (commentaire), et sélection
             ordonnée en 3 listes de numéros : bases → belles_chances → outsiders.
             pronostic_analyses[] donne le nom du cheval par numéro.

        Pseudo course_id : "EQ_{HIPPO}_R{r}C{c}" (même convention que CanalTurf →
        résolution EXACTE par suffixe R{r}C{c} dans l'orchestrateur).
        """
        results: list[PronosticPresseScrape] = []
        today = date.today().isoformat()
        headers = {
            "User-Agent": random_user_agent(),
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
        try:
            async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(f"{EQUIDIA_API}/dailyreunions/{today}")
                if resp.status_code != 200:
                    self.log.warning("equidia.listing_http_error", status=resp.status_code)
                    return results
                reunions = resp.json() or []

                for reunion in reunions:
                    rn = reunion.get("num_reunion")
                    hippo = (reunion.get("lib_reunion") or "")[:12].upper().replace(" ", "_")
                    if not rn:
                        continue
                    for c in reunion.get("courses_by_day") or []:
                        cn = c.get("num_course_pmu")
                        if not cn:
                            continue
                        try:
                            presp = await client.get(
                                f"{EQUIDIA_API}/courses/{today}/R{rn}/C{cn}/pronostic"
                            )
                            if presp.status_code != 200:
                                continue
                            p = presp.json() or {}
                            if p.get("status") not in (None, "published"):
                                continue
                            # Sélection ordonnée : bases → belles chances → outsiders.
                            nums = list(p.get("bases") or []) + \
                                   list(p.get("belles_chances") or []) + \
                                   list(p.get("outsiders") or [])
                            if not nums:
                                continue
                            noms: dict[int, str] = {}
                            for a in p.get("pronostic_analyses") or []:
                                num = (a.get("partant") or {}).get("num_partant")
                                nom = (a.get("cheval") or {}).get("nom_cheval")
                                if num and nom:
                                    noms[int(num)] = nom
                            selection = [
                                {"rang": i + 1, "numero": int(n), "nom": noms.get(int(n), "")}
                                for i, n in enumerate(nums[:8])
                            ]
                            cr = p.get("creator") or {}
                            journaliste = " ".join(
                                x for x in (cr.get("firstname"), cr.get("lastname")) if x
                            ).strip().title() or None
                            commentaire = (p.get("chapeau") or "").strip() or None
                            results.append(PronosticPresseScrape(
                                course_id=f"EQ_{hippo}_R{rn}C{cn}",
                                source="equidia",
                                journaliste=journaliste,
                                selection=selection,
                                commentaire=commentaire,
                            ))
                        except Exception as e:
                            self.log.warning("equidia.course_error", r=rn, c=cn, error=str(e))
                        await human_delay(0.15, 0.4)
        except Exception as e:
            self.log.error("equidia.fetch_error", error=str(e))
            return results

        self.log.info("equidia.pronostics", nb=len(results))
        return results


# ─────────────────────────────────────────────
# Helpers de parsing CanalTurf (httpx + BeautifulSoup)
# Hors-classe (purs, testables sans navigateur ni instance scraper).
# ─────────────────────────────────────────────
def _ct_text(el) -> str:
    """Texte normalisé d'un nœud bs4 (vide si None)."""
    return el.get_text(" ", strip=True) if el else ""


def _ct_parse_listing(html: str) -> list[dict]:
    """
    Parse la page liste des pronostics CanalTurf.

    Structure réelle (Bootstrap 3) :
      div.panel.panel-bordered                ← une réunion
        h2.panel-title  "17:00 Réunion 1 - AGEN LE PASSAGE"
        a.list-group-item href="…/409248_prix-de-bordeaux.html"   ← une course
          span.badge  → n° de course dans la réunion
          (col-xs-1) → nb de partants

    Retourne : [{"hippodrome", "reunion", "course", "url"}].
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for panel in soup.select(".panel.panel-bordered"):
        head_txt = _ct_text(panel.select_one(".panel-title"))
        # ex. "17:00 Réunion 1 - AGEN LE PASSAGE"
        m = re.search(r"R[ée]union\s+(\d+)\s*[-–]\s*(.+)$", head_txt, re.I)
        reunion = int(m.group(1)) if m else None
        hippo = m.group(2).strip() if m else head_txt
        for a in panel.select("a.list-group-item"):
            href = a.get("href") or ""
            if not href:
                continue
            badge_txt = _ct_text(a.select_one(".badge"))
            course_num = int(badge_txt) if badge_txt.isdigit() else None
            out.append({
                "hippodrome": hippo,
                "reunion": reunion,
                "course": course_num,
                "url": href,
            })
    return out


def _ct_parse_detail(html: str) -> tuple[list[dict], Optional[str], Optional[str]]:
    """
    Parse une page détail de course CanalTurf.

    Structure réelle :
      <p>…commentaire narratif…</p>
      <h3>La sélection de {Journaliste}</h3>
      <table.table-striped><thead>BASE</thead> <tr><td>4</td><td>NOM</td></tr>…
      <table.table-striped><thead>CHANCES REGULIERES</thead> …
      <table.table-striped><thead>OUTSIDERS</thead> …

    L'ordre de lecture (BASE puis CHANCES puis OUTSIDERS) donne le rang.

    Retourne : (selection, journaliste, commentaire)
      selection = [{"numero": int, "nom": str, "rang": int}, …]
    """
    soup = BeautifulSoup(html, "html.parser")
    journaliste: Optional[str] = None
    commentaire: Optional[str] = None
    selection: list[dict] = []

    # Journaliste : <h3>La sélection de {Nom}</h3>
    sel_h3 = None
    for h3 in soup.find_all("h3"):
        t = _ct_text(h3)
        m = re.search(r"s[ée]lection de\s+(.+)$", t, re.I)
        if m:
            journaliste = m.group(1).strip()
            sel_h3 = h3
            break

    # Commentaire : paragraphe narratif précédant le h3 « La sélection de … ».
    # Certaines courses (étrangères, quinté) n'ont pas de commentaire : on ne garde
    # alors aucun texte plutôt qu'un encart publicitaire. On remonte les <p> et on
    # prend le 1er assez long qui ne ressemble pas à une pub/lien partenaire.
    _AD_MARKERS = ("jusqu'", "clients pmu", "jouez sur", "offre", "remboursé",
                   "e-quinté", "pariez", ">>", "cotes")
    if sel_h3 is not None:
        prev = sel_h3
        for _ in range(6):
            prev = prev.find_previous("p")
            if prev is None:
                break
            t = _ct_text(prev)
            if len(t) <= 40:
                continue
            low = t.lower()
            if any(mk in low for mk in _AD_MARKERS):
                continue
            commentaire = t[:500]
            break

    # Sélection : tables BASE / CHANCES REGULIERES / OUTSIDERS, ordre DOM = rang.
    rang = 0
    seen: set[int] = set()
    for table in soup.select("table.table-striped"):
        thead = table.find("thead")
        if thead is None:
            continue
        cat = _ct_text(thead).upper()
        if not any(k in cat for k in ("BASE", "CHANCE", "REGUL", "OUTSIDER")):
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            num_txt = _ct_text(tds[0])
            nom = _ct_text(tds[1]).upper()
            if not num_txt.isdigit() or not nom:
                continue
            num = int(num_txt)
            if num in seen:
                continue
            seen.add(num)
            rang += 1
            selection.append({"numero": num, "nom": nom, "rang": rang})

    return selection, journaliste, commentaire


# ─────────────────────────────────────────────
# Helpers de parsing Paris-Turf (httpx + BeautifulSoup)
# Hors-classe (purs, testables sans navigateur ni instance scraper).
# Paris-Turf = SPA Next.js : tout l'état est dans <script id="__NEXT_DATA__">.
# ─────────────────────────────────────────────
import json as _json  # noqa: E402  (import local pour ne pas toucher l'en-tête)

_PT_BASE = "https://www.paris-turf.com"
# Ordre des catégories de tips Paris-Turf : Base, Chances régulières, Outsiders…
# Détermine le rang de la sélection (les autres catégories suivent, ordre alpha).
_PT_TIP_ORDER = ["A", "C", "O", "S", "G"]


def _pt_decode(raw: bytes) -> str:
    """
    Décode le HTML Paris-Turf.

    Historiquement le serveur annonçait charset=utf-8 mais émettait du cp1252
    (é = 0xE9 seul). Depuis 2026-07 des pages sont réellement en utf-8 → le
    décodage cp1252 forcé produisait du mojibake (« CÃ©dric » en base). Un
    contenu accentué réellement cp1252 ne passe PAS un décodage utf-8 strict :
    on tente donc utf-8 strict d'abord, repli cp1252 sinon.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _pt_next_data(html: str) -> Optional[dict]:
    """Extrait et parse le blob JSON <script id="__NEXT_DATA__">."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return None
    try:
        return _json.loads(tag.string)
    except Exception:
        return None


def _pt_parse_listing(html: str) -> list[dict]:
    """
    Parse la page programme du jour → liens vers les pages détail des courses.

    Les liens sont de la forme /course/{hippo}-{prix-slug}-idc-{hash}. Ils
    apparaissent en double dans le HTML (plusieurs ancres par carte course) :
    on déduplique. Le 1er segment du slug est un indice d'hippodrome (fallback
    si le détail ne fournit pas meetingName).

    Retourne : [{"url", "hippo_hint"}].
    """
    out: list[dict] = []
    seen: set[str] = set()
    for href in re.findall(r'href="(/course/[^"]+-idc-[0-9a-f]+)"', html):
        if href in seen:
            continue
        seen.add(href)
        slug = href[len("/course/"):]
        hippo_hint = slug.split("-")[0]
        out.append({"url": _PT_BASE + href, "hippo_hint": hippo_hint})
    return out


def _pt_parse_detail(html: str) -> Optional[dict]:
    """
    Parse une page détail de course Paris-Turf → pronostic du journaliste.

    Source : __NEXT_DATA__ → props.pageProps.initialState.currentPageState.webTips
      - author      → journaliste
      - text        → commentaire narratif
      - meetingName → hippodrome
      - tips.{cat}.saddleList → numéros ordonnés ("4,6,2,3,7")
      - tips.{cat}.nameList   → noms alignés ("Pantocrator,Kivala Renardier,…")

    Concatène les catégories dans l'ordre A (base) → C → O → … = rang du
    pronostic. Déduplique les numéros (un cheval ne figure qu'une fois).

    Retourne : {"hippodrome", "selection", "journaliste", "commentaire"} ou None
      selection = [{"numero": int, "nom": str, "rang": int}, …]
    """
    data = _pt_next_data(html)
    if not data:
        return None
    try:
        pp = data["props"]["pageProps"]
        wt = pp["initialState"]["currentPageState"].get("webTips")
    except Exception:
        return None
    if not wt or not isinstance(wt, dict):
        return None

    tips = wt.get("tips") or {}
    if not tips or not isinstance(tips, dict):
        return None

    hippodrome = wt.get("meetingName") or ""
    if not hippodrome:
        try:
            hippodrome = (pp.get("race") or {}).get("name") or ""
        except Exception:
            hippodrome = ""
    journaliste = (wt.get("author") or "").strip() or None
    commentaire = (wt.get("text") or "").strip() or None
    if commentaire:
        commentaire = commentaire[:500]
    # Numéros réunion/course (webTips) → permettent une résolution course_id
    # EXACTE par R/C (course_id PMU = {ddmmyyyy}R{r}C{c}).
    reunion = wt.get("meetingNumber")
    course_num = wt.get("raceNumber")

    cats = sorted(
        tips.keys(),
        key=lambda k: (_PT_TIP_ORDER.index(k) if k in _PT_TIP_ORDER else 99, k),
    )
    selection: list[dict] = []
    seen: set[int] = set()
    rang = 0
    for cat in cats:
        t = tips.get(cat) or {}
        saddle = (t.get("saddleList") or "")
        names = (t.get("nameList") or "").split(",")
        nums = [x.strip() for x in saddle.split(",") if x.strip()]
        for i, num_txt in enumerate(nums):
            if not num_txt.isdigit():
                continue
            num = int(num_txt)
            if num in seen:
                continue
            seen.add(num)
            nom = names[i].strip().upper() if i < len(names) else ""
            rang += 1
            selection.append({"numero": num, "nom": nom, "rang": rang})

    if not selection:
        return None
    return {
        "hippodrome": hippodrome,
        "selection": selection,
        "journaliste": journaliste,
        "commentaire": commentaire,
        "reunion": reunion,
        "course": course_num,
    }
