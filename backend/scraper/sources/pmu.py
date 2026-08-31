"""
Source PMU — API JSON non documentée mais stable.
Source CRITIQUE — polling toutes 3 minutes.

Endpoints :
  /programme/today                                  → programme + partants basiques
  /reunion/{id}/course/{id}/participants            → détails partants + cotes live
  /reunion/{id}/course/{id}/rapports-definitifs     → résultats officiels post-course
"""
import json
import re
import asyncio
import httpx
import structlog
from datetime import datetime, date, timezone
from typing import Optional

from services.temps_courses import jour_courses
from scraper.base import CourseScrape, PartantScrape, ResultatScrape, PoolPMUScrape, BaseScraper, human_delay, get_circuit_breaker

log = structlog.get_logger(source="pmu")

BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"


def make_course_id(date_ddmmyyyy: str, reunion_id, course_num) -> str:
    """Identifiant de course DATÉ : {ddmmyyyy}R{reunion}C{course}.

    Le préfixe date est indispensable : sans lui, "R1C1" est réutilisé chaque jour
    et la course du jour ÉCRASE celle de la veille (collision de clé primaire →
    corruption de l'historique). Préfixe = chiffres uniquement, donc
    `course_id.split("C")[-1]` continue de donner le numéro de course.
    """
    return f"{date_ddmmyyyy}R{reunion_id}C{course_num}"


def _fmt_date_pmu(course_date=None) -> str:
    """Normalise une date vers le format d'URL PMU `ddmmyyyy`.

    Accepte : None (= aujourd'hui), str ddmmyyyy (préfixe de course_id) ou ISO,
    epoch ms (heureDepart PMU), date/datetime. Tolérant : sert juste à bâtir l'URL.
    """
    if course_date is None:
        return jour_courses().strftime("%d%m%Y")
    if isinstance(course_date, str):
        return (course_date if (len(course_date) == 8 and course_date.isdigit())
                else jour_courses().strftime("%d%m%Y"))
    if isinstance(course_date, bool):  # garde-fou : bool est un int en Python
        return jour_courses().strftime("%d%m%Y")
    if isinstance(course_date, (int, float)):
        return datetime.fromtimestamp(course_date / 1000).strftime("%d%m%Y")
    return course_date.strftime("%d%m%Y")


def _epoch_ms_to_dt(value) -> "datetime | None":
    """Epoch millisecondes PMU → datetime UTC. None si absent ou aberrant.

    Le PMU date ses rapports en ms depuis l'époque. On rejette les valeurs hors
    d'une plage plausible (2000→2100) plutôt que de fabriquer une date en 1970 à
    partir d'un champ vide : une date fausse serait pire que pas de date, elle
    ferait passer une cote périmée pour fraîche.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if not (946_684_800_000 <= ms <= 4_102_444_800_000):   # 2000-01-01 → 2100-01-01
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _first_poids(p: dict):
    """Poids porté en kg depuis le PMU (poidsConditionMonte/poidsJockey/handicapPoids).
    handicapPoids est en décigrammes (560 = 56,0 kg). On normalise : toute valeur
    > 120 est en décigrammes → /10 ; sinon déjà en kg. None si absent."""
    for key in ("poidsConditionMonte", "poidsJockey", "handicapPoids"):
        v = p.get(key)
        if not v:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        return round(v / 10.0, 1) if v > 120 else round(v, 1)
    return None


def _commentaire_texte(v):
    """Normalise un champ commentaire PMU (dict {texte:…} ou str) → str|None."""
    if isinstance(v, dict):
        t = v.get("texte") or v.get("commentaire") or v.get("text")
        return t.strip() if isinstance(t, str) and t.strip() else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _extract_commentaire(course_obj: dict, moi: dict | None):
    """Déroulé / trip note d'une course passée. Cherche d'abord au niveau du partant
    (commentaire spécifique au cheval, le plus utile), puis au niveau course. None si
    le PMU ne publie rien (défensif : pas de champ inventé)."""
    for src, keys in (
        (moi or {}, ("commentaireApresCourse", "commentaire", "deroulement")),
        (course_obj or {}, ("commentaireApresCourse", "commentaire")),
    ):
        for k in keys:
            t = _commentaire_texte(src.get(k))
            if t:
                return t
    return None

# ── Écart à l'arrivée : du libellé PMU aux longueurs ────────────────────────────
#
# `distanceAvecPrecedent` n'est PAS un nombre, c'est un objet
# `{"knownValue": "UN_NEZ", "rawValue": "Nez"}`. Le writer testait
# `isinstance(ecart, (int, float))` : la valeur était donc écartée à CHAQUE ligne,
# et `historique_courses.ecart_longueurs` valait NULL sur les 330 145 lignes de la
# table. Quatre features en dépendent (`ecart_moyen_recent`, `proximite_vainqueur`,
# `nb_defaites_courtes`, `defaite_courte_derniere`) : toutes constantes, donc
# apprises comme du bruit.
#
# Barème en longueurs, aligné sur l'usage des chronos français (1 longueur ≈ 2,4 m).
# Table établie sur les valeurs RÉELLEMENT observées : 802 courses passées relevées
# le 2026-08-31, 33 libellés distincts, tous couverts ci-dessous.
_ECART_MOTS = {
    "DEAD_HEAT": 0.0, "DEAD_HEAT_ALT": 0.0,
    "UN_NEZ": 0.05, "COURTE_TETE": 0.10, "UNE_TETE": 0.15, "TETE": 0.15,
    "COURTE_ENCOLURE": 0.20, "UNE_ENCOLURE": 0.30, "ENCOLURE": 0.30,
    "DEMI_LONGUEUR": 0.50, "TROIS_QUARTS_DE_LONGUEUR": 0.75,
    # « Loin » / « Distancé » : le PMU ne chiffre pas. 25 longueurs est au-delà de
    # tout écart utile et sous le plafond de 30 appliqué par la feature — la valeur
    # ne prétend donc pas à une précision qu'elle n'a pas, elle dit « très loin ».
    "LOIN": 25.0, "DISTANCE": 25.0,
}
_ECART_UNITES = {
    "UNE": 1, "DEUX": 2, "TROIS": 3, "QUATRE": 4, "CINQ": 5, "SIX": 6, "SEPT": 7,
    "HUIT": 8, "NEUF": 9, "DIX": 10, "ONZE": 11, "DOUZE": 12, "TREIZE": 13,
    "QUATORZE": 14, "QUINZE": 15, "SEIZE": 16, "DIX_SEPT": 17, "DIX_HUIT": 18,
    "DIX_NEUF": 19, "VINGT": 20, "VINGT_CINQ": 25, "TRENTE": 30,
}
_ECART_FRACTIONS = {
    "": 0.0, "_ET_DEMIE": 0.5, "_ET_DEMI": 0.5, "_ET_QUART": 0.25,
    "_TROIS_QUARTS": 0.75,
}


def _ecart_texte_en_longueurs(brut: str | None):
    """Repli sur `rawValue` : « 1 L 1/2 », « 3/4 L », « Courte tête », « Nez »…

    Indispensable, et pas théorique : 30 des 802 écarts relevés portent
    `knownValue = "INCONNU"` alors que `rawValue` dit précisément « Courte tête »,
    « Tête » ou « Courte encolure ». Sans ce repli, ces marges seraient perdues.
    """
    if not isinstance(brut, str):
        return None
    t = " ".join(brut.strip().lower().split())
    mots = {
        "dead-heat": 0.0, "dead heat": 0.0,
        "nez": 0.05, "courte tête": 0.10, "courte tete": 0.10,
        "tête": 0.15, "tete": 0.15,
        "courte encolure": 0.20, "encolure": 0.30,
        "loin": 25.0, "distancé": 25.0, "distance": 25.0,
    }
    if t in mots:
        return mots[t]
    # Formes chiffrées : « 2 L », « 1 L 1/2 », « 3/4 L », « 1/2 L ».
    m = re.match(r"^(?:(\d+)\s*l)?\s*(?:(\d)\s*/\s*(\d))?\s*(?:l)?$", t)
    if not m or not (m.group(1) or m.group(2)):
        return None
    total = float(m.group(1) or 0)
    if m.group(2) and m.group(3) and float(m.group(3)) != 0:
        total += float(m.group(2)) / float(m.group(3))
    return total


def _ecart_en_longueurs(valeur):
    """Marge SUR LE CHEVAL PRÉCÉDENT, en longueurs. None si indéchiffrable."""
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return float(valeur)
    if not isinstance(valeur, dict):
        return None
    connu = valeur.get("knownValue")
    if isinstance(connu, str):
        cle = connu.strip().upper()
        if cle in _ECART_MOTS:
            return _ECART_MOTS[cle]
        for suffixe, fraction in sorted(_ECART_FRACTIONS.items(), key=lambda kv: -len(kv[0])):
            if suffixe and not cle.endswith(suffixe):
                continue
            racine = cle[:len(cle) - len(suffixe)] if suffixe else cle
            for terminaison in ("_LONGUEURS", "_LONGUEUR"):
                if racine.endswith(terminaison):
                    unite = _ECART_UNITES.get(racine[:-len(terminaison)])
                    if unite is not None:
                        return float(unite) + fraction
            break
    return _ecart_texte_en_longueurs(valeur.get("rawValue"))


def _ecart_au_vainqueur(course_obj: dict, moi: dict | None):
    """Longueurs CUMULÉES entre le vainqueur et `moi`.

    Le PMU publie la marge sur le cheval PRÉCÉDENT ; la feature, elle, lit
    « 0 = vainqueur » et calcule une proximité au vainqueur. Reporter la marge
    brute aurait donc sous-estimé tout le champ — un 6ᵉ battu d'un nez sur le 5ᵉ
    serait passé pour un cheval collé au gagnant.

    La liste `participants` d'une course passée est TRONQUÉE au cheval concerné
    (vérifié : 6 lignes pour une course de 11 partants, `moi` en 6ᵉ position),
    ce qui suffit exactement : la chaîne des places 2..moi est complète.

    Renvoie None si un maillon de la chaîne est illisible — une somme partielle
    serait un chiffre faux, ce qui est pire que pas de chiffre.
    """
    place_moi = (moi or {}).get("place")
    if not isinstance(place_moi, dict):
        return None
    try:
        rang_moi = int(place_moi.get("place"))
    except (TypeError, ValueError):
        return None
    if rang_moi <= 1:
        return 0.0

    marges: dict[int, float] = {}
    for pp in (course_obj.get("participants") or []):
        pl = pp.get("place")
        if not isinstance(pl, dict):
            continue
        try:
            rang = int(pl.get("place"))
        except (TypeError, ValueError):
            continue
        if rang <= 1 or rang > rang_moi:
            continue
        marge = _ecart_en_longueurs(pp.get("distanceAvecPrecedent"))
        if marge is None:
            return None
        marges[rang] = marge

    if len(marges) != rang_moi - 1:
        return None          # chaîne incomplète : on ne devine pas
    return round(sum(marges.values()), 2)


# Allocation : plafond de VRAISEMBLANCE, pas de normalisation d'unité.
#
# La course la mieux dotée au monde tourne autour de 20 M€. Le plafond retenu —
# 50 M€ LU EN CENTIMES, soit 5 000 000 000 — est volontairement le plus GÉNÉREUX
# des deux lectures possibles, parce que la colonne d'historique porte les DEUX
# unités selon la ligne. Un seuil posé à 50 000 000 « euros » écartait 1 455 lignes
# dont 1 192 entre 50 M et 238 M, qui valent 500 k€ à 2,4 M€ une fois lues en
# centimes : des grands prix parfaitement réels. Ne reste impossible que ce qui
# l'est DANS LES DEUX UNITÉS — 16 lignes en base, jusqu'à 109 000 000 000, soit
# 1,09 milliard d'euros pour un prix de province.
#
# ATTENTION AUX UNITÉS, elles diffèrent et ce n'est pas corrigé ici :
#   `courses.allocation`            = CENTIMES (`montantTotalOffert` × 100)
#   `historique_courses.allocation` = EUROS pour les lignes externes, CENTIMES pour
#                                     celles rattachées à une course interne
# Vérifié en base : sur les 186 770 lignes rattachées, le rapport
# `historique.allocation / courses.allocation` vaut exactement 1.000 —
# `ml/features.py` a donc raison de ne diviser par 100 que ces lignes-là
# (`h.course_id IS NOT NULL`). Normaliser la colonne en masse changerait
# `class_drop_ratio` AU SERVICE alors que le modèle actif a été entraîné sur les
# unités mélangées : ce serait un écart train/serve, pas une correction.
ALLOCATION_PLAFOND = 5_000_000_000


def _allocation_vraisemblable(valeur, plafond: int = ALLOCATION_PLAFOND):
    """Montant, ou None s'il est impossible quelle que soit l'unité lue.

    On ne RAMÈNE PAS au plafond : un montant faux ramené à 50 M€ resterait faux et
    passerait alors pour une donnée. Absent, il est traité comme absent.
    """
    if not isinstance(valeur, (int, float)) or isinstance(valeur, bool):
        return None
    if valeur < 0 or valeur > plafond:
        log.warning("pmu.allocation_invraisemblable", valeur=valeur, plafond=plafond)
        return None
    return valeur


DISCIPLINE_MAP = {
    "PLAT": "Plat",
    "TROT_ATTELE": "Attelé",
    "TROT_MONTE": "Monté",
    "HAIES": "Haies",
    "STEEPLE_CHASE": "Steeple",
    "CROSS_COUNTRY": "Cross",
    "PLAT_INTERNATIONAL": "Plat",
}

TERRAIN_MAP = {
    1: "Très bon",
    2: "Bon",
    3: "Bon souple",
    4: "Souple",
    5: "Très souple",
    6: "Lourd",
    7: "Très lourd",
    8: "Collant",
    9: "Bourbeux",
}


class PmuScraper(BaseScraper):
    """
    PMU est la source CRITIQUE. On utilise httpx pour l'API JSON
    (plus rapide que Playwright pour des APIs pures).
    Playwright utilisé en fallback si l'API répond du HTML.
    """

    SOURCE_NAME = "pmu"

    def __init__(self, page=None, proxy: Optional[str] = None):
        super().__init__(page, proxy)
        self._client: Optional[httpx.AsyncClient] = None
        self._cb = get_circuit_breaker("pmu")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                    "Referer": "https://www.pmu.fr/",
                    "Origin": "https://www.pmu.fr",
                },
                timeout=15.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def _fetch_json(self, url: str, max_retries: int = 3) -> Optional[dict | list]:
        """Fetch JSON avec retry exponentiel + circuit breaker."""
        if self._cb.is_open():
            log.warning("pmu.circuit_open", url=url)
            return None

        client = await self._get_client()
        for attempt in range(1, max_retries + 1):
            try:
                r = await client.get(url)
                r.raise_for_status()
                self._cb.record_success()
                # 204 / corps vide = « rien à dire sur cette course », pas une panne.
                # Le PMU répond 204 sur `masse-enjeu` d'une réunion qui ne publie pas
                # ses enjeux. Sans ce court-circuit, `r.json()` lève, le code retente
                # trois fois, journalise une erreur PAR COURSE — et surtout appelle
                # `record_failure` sur la source CRITIQUE : assez de 204 d'affilée et
                # le disjoncteur s'ouvre, bloquant les vrais appels PMU.
                if r.status_code == 204 or not r.content:
                    log.debug("pmu.sans_contenu", url=url, status=r.status_code)
                    return None
                return r.json()
            except Exception as e:
                self._cb.record_failure("pmu")
                if attempt < max_retries:
                    wait = 2.0 ** (attempt - 1)
                    log.warning("pmu.fetch_retry", url=url, attempt=attempt, wait_s=wait, error=str(e))
                    await asyncio.sleep(wait)
                else:
                    log.error("pmu_fetch_failed", url=url, attempts=max_retries, error=str(e))
                    return None
        return None

    async def get_programme_today(self, target_date=None) -> list[CourseScrape]:
        """Récupère toutes les courses d'une journée avec partants basiques.

        target_date : date|datetime|str(ddmmyyyy). Défaut = aujourd'hui. Permet le
        BACKFILL historique (programme + arrivées d'une date passée)."""
        if target_date is None:
            today_str = jour_courses().strftime("%d%m%Y")
        elif isinstance(target_date, str) and len(target_date) == 8 and target_date.isdigit():
            today_str = target_date
        else:
            today_str = target_date.strftime("%d%m%Y")
        url = f"{BASE}/programme/{today_str}?specialisation=INTERNET"
        log.info("pmu.programme_fetch", date=today_str)

        data = await self._fetch_json(url)
        if not data:
            return []

        courses: list[CourseScrape] = []
        reunions = data.get("programme", {}).get("reunions", [])
        log.info("pmu.reunions_found", count=len(reunions))

        for reunion in reunions:
            r_num = reunion.get("numOfficiel", 0)
            r_id = str(r_num)
            # N° de réunion PUBLIC = numExterne (affiché sur pmu.fr). Diffère parfois
            # de numOfficiel (ex. REIMS : officiel 10, externe 9). On garde r_id =
            # numOfficiel pour les URLs API PMU, mais on affiche numExterne.
            r_public = reunion.get("numExterne") or r_num
            hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "Inconnu")
            # Le pays est au niveau RÉUNION dans le payload PMU (pas imbriqué dans
            # hippodrome). Ne jamais retomber silencieusement sur "FR".
            pays = reunion.get("pays", {}).get("code")

            # Préfixe = date INTERROGÉE (today_str). On vient de demander
            # /programme/{today_str}, donc toutes ces réunions sont de ce jour.
            # (dateReunion = minuit Paris → en UTC il bascule la veille : à éviter.)
            for c_data in reunion.get("courses", []):
                c_num = c_data.get("numOrdre", 0)
                c_id = make_course_id(today_str, r_id, c_num)

                partants = self._parse_partants(c_data.get("participants", []))

                # Désignations jackpot — déduites des PARIS RÉELLEMENT proposés par le
                # PMU (champ `paris[].codePari`), pas du texte des conditions (qui ne
                # mentionne jamais Tiercé/Quarté/Quinté). Sans ça, est_quinte/quarte/
                # tierce restaient TOUJOURS False → la couverture jackpot ne se
                # déclenchait jamais.
                conditions = c_data.get("conditions", "")
                pari_codes = {
                    (p.get("codePari") or p.get("typePari") or "").upper()
                    for p in (c_data.get("paris") or [])
                }
                est_tierce = any("TIERCE" in c for c in pari_codes)
                est_quarte = any(("QUARTE" in c) or ("SUPER_QUATRE" in c) for c in pari_codes)
                est_quinte = any("QUINTE" in c for c in pari_codes)
                # 2sur4 (DEUX_SUR_QUATRE) — proposé seulement sur CERTAINES courses par
                # le PMU, indépendamment du nb de partants. On ne se fie donc PAS à une
                # heuristique « ≥8 partants » (fausse : ex. R6C7 a ≥8 partants mais PAS
                # de 2sur4) mais aux paris RÉELLEMENT offerts. Pas dans la liste → on ne
                # génèrera jamais de prono 2sur4 pour cette course.
                est_2sur4 = any(("DEUX_SUR_QUATRE" in c) or ("2SUR4" in c) for c in pari_codes)
                # Liste complète des paris offerts (triée, dédoublonnée) → le moteur
                # propose EXACTEMENT ce que la course accepte et passe à l'ordre quand
                # le champ réduit l'impose (E_COUPLE_ORDRE / E_TRIO_ORDRE).
                paris_disponibles = sorted(c for c in pari_codes if c)

                # Terrain — conditionPiste/libellePiste n'existent PLUS dans le payload
                # programme 2026 : le PMU publie `penetrometre` {valeurMesure, intitule}
                # au niveau course (plat/obstacle). C'est la seule source terrain
                # course-level réelle → intitule = libellé officiel (Bon/Souple/…).
                terrain_code = c_data.get("conditionPiste")
                terrain_libelle = TERRAIN_MAP.get(terrain_code) if terrain_code else None
                if not terrain_libelle:
                    terrain_libelle = c_data.get("libellePiste")
                pen = c_data.get("penetrometre") or {}
                if not terrain_libelle:
                    terrain_libelle = pen.get("intitule") or None
                pen_coef = None
                try:
                    _vm = str(pen.get("valeurMesure") or "").replace(",", ".").strip()
                    pen_coef = float(_vm) if _vm else None
                except (ValueError, TypeError):
                    pen_coef = None

                # Dotation en centimes
                dotation_raw = c_data.get("montantTotalOffert")
                dotation = _allocation_vraisemblable(
                    int(dotation_raw * 100) if dotation_raw else None)

                course = CourseScrape(
                    reunion_id=r_id,
                    course_id=c_id,
                    numero_reunion=int(r_public) if r_public else None,
                    hippodrome=hippodrome,
                    pays=pays,
                    date_heure=c_data.get("heureDepart", ""),
                    discipline=DISCIPLINE_MAP.get(c_data.get("specialite", ""), c_data.get("specialite", "")),
                    distance=c_data.get("distance", 0),
                    terrain=terrain_libelle,
                    terrain_code=terrain_code,
                    dotation=dotation,
                    nb_partants=len(partants),
                    partants=partants,
                    corde=c_data.get("corde"),
                    niveau_course=c_data.get("conditions"),
                    type_depart=c_data.get("typeDepart"),
                    est_quinte=est_quinte,
                    est_quarte=est_quarte,
                    est_tierce=est_tierce,
                    est_2sur4=est_2sur4,
                    paris_disponibles=paris_disponibles or None,
                    nom=re.sub(r"\s+", " ", c_data.get("libelle") or "").strip() or None,
                    conditions_texte=conditions or None,
                    penetrometre_coef=pen_coef,
                    categorie_particularite=c_data.get("categorieParticularite"),
                    montant_offert_1er=c_data.get("montantOffert1er"),
                    nombre_declares_partants=c_data.get("nombreDeclaresPartants"),
                    # Statut PMU BRUT (PROGRAMMEE / FIN_COURSE / ARRIVEE_DEFINITIVE_*
                    # / COURSE_ANNULEE). Ignoré jusqu'au 2026-08-17 → une course
                    # annulée n'avait aucun moyen de quitter 'a_venir' (le PMU ne
                    # publie jamais son ordreArrivee). Cf. services/course_resolution.
                    statut_pmu=(str(c_data.get("statut")).strip().upper()
                                if c_data.get("statut") else None),
                    source="pmu",
                )
                courses.append(course)

        log.info("pmu.courses_parsed", count=len(courses))
        return courses

    async def enrich_partants(self, reunion_id: str, course_num: int, course_date=None) -> list[PartantScrape]:
        """Récupère les données complètes des partants pour une course.

        course_date : date|str(ddmmyyyy). Défaut = aujourd'hui. Indispensable au
        BACKFILL : le programme d'une date passée renvoie participants=[] en inline,
        mais l'endpoint /participants dédié les contient."""
        if course_date is None:
            d = jour_courses().strftime("%d%m%Y")
        elif isinstance(course_date, str) and len(course_date) == 8 and course_date.isdigit():
            d = course_date
        else:
            d = course_date.strftime("%d%m%Y")
        url = f"{BASE}/programme/{d}/R{reunion_id}/C{course_num}/participants?specialisation=INTERNET"
        await human_delay(0.3, 0.8)

        data = await self._fetch_json(url)
        if not data:
            return []

        participants = data if isinstance(data, list) else data.get("participants", [])
        return self._parse_partants(participants)

    async def get_historique_chevaux(self, reunion_id: str, course_num: int) -> list[dict]:
        """
        Historique détaillé de chaque partant (courses passées) via l'endpoint
        PMU /performances-detaillees/pretty. Pour chaque cheval, ses dernières
        courses avec : date, hippodrome, discipline, distance, position d'arrivée,
        écart, réduction km, ET la liste des autres chevaux (→ confrontations).

        Retourne : [{"cheval_nom": str, "courses": [
            {date_ms, hippodrome, discipline, distance, allocation, nb_partants,
             position, ecart, reduction_km, jockey, adversaires:[noms]}, ...]}]
        """
        d = jour_courses().strftime("%d%m%Y")
        url = f"{BASE}/programme/{d}/R{reunion_id}/C{course_num}/performances-detaillees/pretty"
        await human_delay(0.3, 0.8)
        data = await self._fetch_json(url)
        if not data:
            return []

        out = []
        for part in data.get("participants", []):
            courses = []
            for c in part.get("coursesCourues", []) or []:
                pps = c.get("participants", []) or []
                # Le cheval concerné est marqué itsHim=True
                moi = next((pp for pp in pps if pp.get("itsHim")), None)
                place = (moi or {}).get("place") or {}
                rk = (moi or {}).get("reductionKilometrique")
                # Vitesse moyenne du vainqueur (m/s) = distance / temps. tempsDuPremier
                # est en CENTISECONDES (vérifié : 2400m PLAT → 15.2 m/s, 1000m → 17.3).
                # Figure de vitesse réelle, normalisée par les features (vs réf distance/discipline).
                tdp = c.get("tempsDuPremier")
                dist_c = c.get("distance")
                vitesse_ms = (round(dist_c / (tdp / 100.0), 2)
                              if isinstance(tdp, (int, float)) and tdp > 0
                              and isinstance(dist_c, (int, float)) and dist_c > 0
                              else None)
                _oeil = (moi or {}).get("oeillere")
                courses.append({
                    "date_ms": c.get("date"),
                    "hippodrome": c.get("hippodrome"),
                    "discipline": c.get("discipline"),
                    "distance": c.get("distance"),
                    "allocation": _allocation_vraisemblable(c.get("allocation")),
                    "nb_partants": c.get("nbParticipants"),
                    "position": place.get("place") if isinstance(place, dict) else None,
                    # Longueurs CUMULÉES depuis le vainqueur (pas la marge sur le
                    # cheval précédent) : c'est ce que lit la feature. Cf.
                    # `_ecart_au_vainqueur` pour le pourquoi et les garde-fous.
                    "ecart": _ecart_au_vainqueur(c, moi),
                    "reduction_km": round(rk / 1000.0, 2) if isinstance(rk, (int, float)) and rk else None,
                    "vitesse_ms": vitesse_ms,
                    # ── Données API jusque-là inexploitées ──────────────────────
                    "terrain": c.get("etatTerrain"),                 # bon/souple/lourd… (galop)
                    "corde": (moi or {}).get("corde"),               # n° de corde (plat)
                    "poids": (moi or {}).get("poidsJockey"),         # kg portés
                    "oeilleres": (_oeil not in (None, "SANS_OEILLERES")) if _oeil is not None else None,
                    "jockey": (moi or {}).get("nomJockey"),
                    "adversaires": [pp.get("nomCheval") for pp in pps
                                    if not pp.get("itsHim") and pp.get("nomCheval")],
                    # Commentaire / déroulé de la course passée (trip notes). Le PMU
                    # peut le publier au niveau course (commentaireApresCourse) ou du
                    # partant. Défensif : on prend le 1er disponible, sinon None.
                    "commentaire": _extract_commentaire(c, moi),
                })
            if courses:
                out.append({"cheval_nom": part.get("nomCheval"), "courses": courses})
        return out

    async def get_rapports_definitifs(
        self, reunion_id: str, course_num: int, course_date=None
    ) -> Optional[ResultatScrape]:
        """Récupère les résultats officiels après la course.

        - ordre d'arrivée : endpoint /participants (champ ordreArrivee, fiable)
        - rapports (dividendes) : endpoint /rapports-definitifs (LISTE de typePari)
        course_date : date de la course (date|datetime|str ddmmyyyy). Défaut = aujourd'hui.
        """
        d = _fmt_date_pmu(course_date)

        c_id = make_course_id(d, reunion_id, course_num)
        base_rc = f"{BASE}/programme/{d}/R{reunion_id}/C{course_num}"

        # 1) Ordre d'arrivée via /participants
        parts = await self._fetch_json(f"{base_rc}/participants?specialisation=INTERNET")
        if not parts:
            return None
        participants = parts if isinstance(parts, list) else parts.get("participants", [])

        ordre = []
        for p in participants:
            pos = p.get("ordreArrivee")
            if pos and pos > 0:  # uniquement les chevaux classés
                temps_ms = p.get("tempsObtenu")
                rk = p.get("reductionKilometrique")
                ordre.append({
                    "numero": p.get("numPmu"),
                    "nom": p.get("nom"),
                    "position": int(pos),
                    "temps": round(temps_ms / 1000, 2) if temps_ms else None,
                    "reduction_km": round(rk / 1000, 2) if rk else None,
                    "incident": p.get("incident"),
                })
        if not ordre:
            return None  # course pas encore arrivée
        ordre.sort(key=lambda x: x["position"])

        # Disqualifiés / distancés : partants SANS place à l'arrivée mais avec un
        # `incident` PMU (DAI au trot, tombé/distancé/arrêté au galop/obstacle…). On les
        # ajoute EN FIN de classement (position=None → ignorés par le règlement des paris,
        # cf. settle_pari qui saute les positions nulles) pour les afficher dans le tableau.
        for p in participants:
            if (p.get("ordreArrivee") or 0) > 0:
                continue
            statut = (p.get("statut") or "").upper()
            incident = p.get("incident")
            # NON_PARTANT n'est PAS une disqualification (cheval retiré avant le départ).
            if statut == "PARTANT" and incident and incident.upper() != "NON_PARTANT":
                ordre.append({
                    "numero": p.get("numPmu"),
                    "nom": p.get("nom"),
                    "position": None,
                    "temps": None,
                    "reduction_km": None,
                    "incident": incident,
                    "disqualifie": True,
                })

        # 2) Rapports (dividendes) via /rapports-definitifs (liste de typePari)
        # On capture TOUT le détail PUBLIÉ : chaque type a une liste de rapports avec
        # une `combinaison` (cheval pour le Simple Placé, combo pour 2sur4/Couplé…) et
        # le dividende "pour 1€ misé". On garde :
        #   - rapports        : {type: 1er rapport}  (rétro-compatibilité / agrégat)
        #   - rapports_detail : {type: [{combinaison, rapport}, …]}  (détail réel complet)
        # Aucune valeur inventée : seulement ce que le PMU publie.
        rapports = {}
        rapports_detail = {}
        try:
            rd = await self._fetch_json(f"{base_rc}/rapports-definitifs?specialisation=INTERNET")
            if isinstance(rd, list):
                for item in rd:
                    type_pari = (item.get("typePari") or "").lower()
                    raps = item.get("rapports") or []
                    if not type_pari or not raps:
                        continue
                    detail = []
                    for rp in raps:
                        div = rp.get("dividendePourUnEuro") or rp.get("dividende")
                        if not div:
                            continue
                        detail.append({
                            "combinaison": str(rp.get("combinaison") or "").strip() or None,
                            "rapport": round(div / 100, 2),
                            # libellé PMU (« e-Multi en 4/5/6/7 ») = discriminateur de la
                            # formule jouée : Multi/Mini Multi publient UNE entrée par « en N »
                            # (même combinaison, rapports décroissants). Sans lui on ne sait
                            # pas distinguer en 4/5/6/7 → on paierait toujours le 1er (en 4).
                            "libelle": str(rp.get("libelle") or "").strip() or None,
                        })
                    if not detail:
                        continue
                    rapports_detail[type_pari] = detail
                    rapports[type_pari] = detail[0]["rapport"]  # agrégat (1er) pour compat
        except Exception as e:
            log.warning("pmu.rapports_dividendes_skip", course_id=c_id, error=str(e)[:120])

        # 3) Commentaire narratif post-course + durée (objet course C1)
        commentaire = None
        duree_course = None
        try:
            c_obj = await self._fetch_json(f"{base_rc}?specialisation=INTERNET")
            if isinstance(c_obj, dict):
                cac = c_obj.get("commentaireApresCourse")
                if isinstance(cac, dict):
                    commentaire = cac.get("texte")
                elif isinstance(cac, str):
                    commentaire = cac
                dc = c_obj.get("dureeCourse")
                duree_course = int(dc) if isinstance(dc, (int, float)) else None
        except Exception as e:
            log.warning("pmu.course_commentaire_skip", course_id=c_id, error=str(e)[:120])

        return ResultatScrape(
            course_id=c_id,
            ordre_arrivee=ordre,
            rapports=rapports,
            rapports_detail=rapports_detail or None,
            temps_gagnant=str(ordre[0]["temps"]) if ordre and ordre[0].get("temps") is not None else None,
            incidents=None,
            commentaire=commentaire,
            duree_course=duree_course,
            source="pmu",
        )

    async def get_statut_course(
        self, reunion_id: str, course_num: int, course_date=None
    ) -> Optional[str]:
        """Statut PMU BRUT d'une course (PROGRAMMEE / FIN_COURSE /
        ARRIVEE_DEFINITIVE_COMPLETE / COURSE_ANNULEE …), None si indisponible.

        Indispensable pour clôturer les courses ANNULÉES : le PMU ne publie jamais
        d'ordreArrivee pour elles, donc `get_rapports_definitifs` renvoie None à vie
        et la course restait 'a_venir' indéfiniment (159 cas en prod au 2026-08-17,
        100 % COURSE_ANNULEE). Cf. services/course_resolution.py.
        """
        d = _fmt_date_pmu(course_date)
        url = f"{BASE}/programme/{d}/R{reunion_id}/C{course_num}?specialisation=INTERNET"
        data = await self._fetch_json(url)
        if not isinstance(data, dict):
            return None
        course = data.get("course") if isinstance(data.get("course"), dict) else data
        statut = course.get("statut")
        return str(statut).strip().upper() if statut else None

    async def get_cotes_live(self, reunion_id: str, course_num: int) -> dict[int, float]:
        """
        Récupère les cotes en temps réel.
        Retourne {numero_partant: cote}.
        """
        d = jour_courses().strftime("%d%m%Y")
        url = f"{BASE}/programme/{d}/R{reunion_id}/C{course_num}/participants?specialisation=INTERNET"
        data = await self._fetch_json(url)
        if not data:
            return {}

        participants = data if isinstance(data, list) else data.get("participants", [])
        cotes = {}
        for p in participants:
            num = p.get("numPmu")
            rapport = p.get("dernierRapportDirect", {})
            cote = rapport.get("rapport") if rapport else None
            if num and cote:
                cotes[num] = float(cote)
        return cotes

    async def get_pool_data(self, reunion_id: str, course_id: str):
        """
        Récupère le volume du pool PMU pour une course.
        Endpoint : /reunion/{id}/course/{num}/rapports-simples
        Retourne PoolPMUScrape ou None.
        """
        from scraper.base import PoolPMUScrape
        c_num = int(course_id.split("C")[-1]) if "C" in str(course_id) else 1
        d = jour_courses().strftime("%d%m%Y")
        # Endpoint masse-enjeu : liste de {typePari, totalEnjeu (centimes)}.
        url = f"{BASE}/programme/{d}/R{reunion_id}/C{c_num}/masse-enjeu"
        data = await self._fetch_json(url)
        if not data:
            return None

        try:
            items = data if isinstance(data, list) else data.get("rapports", [])
            pool_total = None
            pool_gagnant = None
            pool_place = None
            gagnant_evolution = None
            for it in items:
                type_pari = (it.get("typePari") or "").upper()
                fond = it.get("totalEnjeu")  # centimes
                if not fond:
                    continue
                pool_total = (pool_total or 0) + fond
                if "SIMPLE_GAGNANT" in type_pari:
                    pool_gagnant = fond
                    gagnant_evolution = it.get("evolution")  # taux croissance (smart money)
                elif "SIMPLE_PLACE" in type_pari:
                    pool_place = fond

            if pool_total is None:
                return None

            return PoolPMUScrape(
                course_id=course_id,
                pool_total=pool_total,
                pool_gagnant=pool_gagnant,
                pool_place=pool_place,
                gagnant_evolution=float(gagnant_evolution) if isinstance(gagnant_evolution, (int, float)) else None,
            )
        except Exception as e:
            log.warning("pmu.pool_data_error", course_id=course_id, error=str(e))
            return None

    async def get_enjeux_par_cheval(self, reunion_id: str, course_id: str,
                                    nb_partants: int | None = None) -> Optional[dict]:
        """
        Enjeux PMU PAR CHEVAL (simple gagnant + simple placé) via `combinaisons`.

        `get_pool_data` ne dit que combien est misé SUR LA COURSE ; ici on sait
        sur QUI. Retourne la vue de `services.pmu_enjeux.parser_enjeux`, ou None
        si le PMU ne publie pas encore d'enjeux pour cette course.
        """
        from services.pmu_enjeux import parser_enjeux

        c_num = int(course_id.split("C")[-1]) if "C" in str(course_id) else 1
        d = jour_courses().strftime("%d%m%Y")
        base = f"{BASE}/programme/{d}/R{reunion_id}/C{c_num}"

        combinaisons = await self._fetch_json(f"{base}/combinaisons")
        if not combinaisons:
            return None
        masse = await self._fetch_json(f"{base}/masse-enjeu")

        vue = parser_enjeux(combinaisons, masse, nb_partants=nb_partants)
        return vue if vue.get("simples") else None

    def _parse_partants(self, raw: list) -> list[PartantScrape]:
        partants = []
        for i, p in enumerate(raw):
            # Cote (dernier rapport direct E_SIMPLE_GAGNANT)
            cote = (p.get("dernierRapportDirect") or {}).get("rapport")

            # Gains carrière (centimes) — gainsParticipant.gainsCarriere
            gp = p.get("gainsParticipant") or {}
            gains = gp.get("gainsCarriere")

            # Jockey/driver + entraîneur (chaînes directes côté API PMU)
            jockey = p.get("driver") or p.get("jockey") or ""
            if isinstance(jockey, dict):
                jockey = jockey.get("nom", "")
            entraineur = p.get("entraineur")
            if isinstance(entraineur, dict):
                entraineur = entraineur.get("nom")

            # Réduction kilométrique : PMU la donne en millièmes de seconde/km
            rk_raw = p.get("reductionKilometrique")
            reduction_km = round(rk_raw / 1000.0, 2) if isinstance(rk_raw, (int, float)) and rk_raw else None

            # ── Mouvement de cote NATIF PMU (référence = ouverture, direct = actuel) ──
            rd = p.get("dernierRapportDirect") or {}
            rr = p.get("dernierRapportReference") or {}
            cote_ref = rr.get("rapport")
            mouvement_pct = None
            if cote and cote_ref and cote_ref > 0:
                mouvement_pct = round((float(cote) - float(cote_ref)) / float(cote_ref), 4)
            tendance = rd.get("indicateurTendance")  # "+" / "-" / "="
            tendance_force = rd.get("nombreIndicateurTendance")
            est_favori = rd.get("favoris")
            # Heure de publication RÉELLE de la cote par le PMU (epoch ms). Le
            # scrape peut avoir lieu bien après, et le PMU republie la même cote
            # tant que rien ne bouge : sans cette date on ne peut ni dater
            # honnêtement une cote figée, ni détecter un flux de cotes gelé.
            cote_dt = _epoch_ms_to_dt(rd.get("dateRapport"))

            # robe / race : PMU peut renvoyer un dict {code, libelleCourt, libelleLong}
            def _libelle(v):
                if isinstance(v, dict):
                    return v.get("libelleLong") or v.get("libelleCourt") or v.get("code")
                return v
            robe_val = _libelle(p.get("robe"))
            race_val = _libelle(p.get("race"))

            # ── Non-partant (cheval retiré avant la course) ──
            # Le PMU expose le statut du partant : "PARTANT" tant qu'il court,
            # "NON_PARTANT" dès qu'il est déclaré forfait. On le capte pour le
            # retirer du tableau + du pronostic (et régénérer le prono restant).
            statut_pmu = str(p.get("statut") or "").upper()
            non_partant = statut_pmu in ("NON_PARTANT", "NONPARTANT", "ABSENT")

            partant = PartantScrape(
                numero=p.get("numPmu", i + 1),
                nom=p.get("nom", ""),
                cote_pmu=float(cote) if cote else None,
                jockey=jockey if isinstance(jockey, str) else "",
                entraineur=entraineur,
                proprietaire=p.get("proprietaire"),
                age=p.get("age"),
                sexe=p.get("sexe"),
                # Poids porté (kg). Selon le type de course le PMU renseigne soit
                # poidsConditionMonte/poidsJockey, soit handicapPoids (en décigrammes,
                # ex. 560 = 56,0 kg → /10). On retombe sur le 1er disponible.
                poids=_first_poids(p),
                decharge=p.get("handicapPoids"),
                musique=p.get("musique"),
                nb_victoires=p.get("nombreVictoires"),
                nb_places=p.get("nombrePlaces"),
                nb_courses=p.get("nombreCourses"),
                gain_carriere=gains,
                # Équipement (champs top-level côté API PMU)
                deferre=p.get("deferre"),
                oeilleres=p.get("oeilleres"),
                # Généalogie
                pere=p.get("nomPere"),
                mere=p.get("nomMere"),
                eleveur=p.get("eleveur") or None,
                reduction_km=reduction_km,
                rang_pronostic_pmu=p.get("ordreArriveePronostic"),
                # ── Enrichissements PMU ──
                cote_reference=float(cote_ref) if cote_ref else None,
                cote_pmu_datetime=cote_dt,
                mouvement_cote_pct=mouvement_pct,
                tendance_cote=tendance,
                tendance_force=float(tendance_force) if isinstance(tendance_force, (int, float)) else None,
                est_favori=bool(est_favori) if est_favori is not None else None,
                avis_entraineur=p.get("avisEntraineur"),
                nb_places_second=p.get("nombrePlacesSecond"),
                nb_places_troisieme=p.get("nombrePlacesTroisieme"),
                handicap_distance=p.get("handicapDistance"),
                # Valeur handicap (#10) — champ PMU réel = `handicapValeur` (vérifié live
                # 2026-06-18 : présent sur les participants, ≠ valeurHandicap).
                valeur_handicap=p.get("handicapValeur"),
                indicateur_inedit=p.get("indicateurInedit"),
                jument_pleine=p.get("jumentPleine"),
                race=race_val,
                robe=robe_val,
                non_partant=non_partant,
                source="pmu",
            )
            partants.append(partant)
        return partants
