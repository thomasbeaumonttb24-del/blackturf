"""Carte « type de pari × contexte de course » apprise sur les vrais rapports PMU.

Pourquoi un apprentissage à part de `profil_learning` : celui-ci n'apprend que des
paris que les plans ont JOUÉS. Un type retiré d'un contexte n'y est plus jamais joué,
donc plus jamais mesuré — il ne peut pas revenir. Ici on règle, pour CHAQUE course
terminée, des paris CANONIQUES construits sur le classement de l'IA figé avant le
départ (gagnant/placé des rangs 1-3, couplés r1-r2 / r1-r3 / r2-r3, 2sur4, Trio
r1-r2-r3, Multi sur le top N) aux rapports PMU réellement payés. Chaque type est donc
mesuré dans chaque contexte, qu'un plan l'ait joué ou non.

Contexte = hiérarchie de cases, de la plus large à la plus fine :
    *  →  discipline  →  + taille du champ  →  + handicap  →  + terrain
Une case fine emprunte à sa parente tant qu'elle a peu de paris (shrink
bayésien, `SHRINK_K` paris d'a priori). Le facteur appliqué au plan est le
rendement du type DANS CE CONTEXTE rapporté à son rendement GLOBAL : il ne dit pas
« ce pari gagne », il dit « ce pari marche mieux / moins bien ici qu'ailleurs ».

Mesure préalable (29/09, 5 601 courses) : 0 case significative sur 367 à elle seule —
d'où le shrink fort et des facteurs bornés. Le gate dur ne coupe qu'un type dont le
rendement shrinké dans la case est catastrophique (≤ `ROI_COUPE`).
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger()

SHRINK_K = 150          # paris d'a priori empruntés à la case parente
WINSOR = 29.0           # retour plafonné à ×30 la mise (un jackpot ne fait pas une case)
FACTEUR_MIN, FACTEUR_MAX = 0.5, 1.5
ROI_COUPE = -0.55       # rendement shrinké ≤ −55 % dans la case → type coupé (poids 0)
N_MIN_COUPE = 200       # … seulement si la case (ou sa parente directe) a ce nombre de paris
MIN_COURSES = 1500      # sous ce volume, pas de carte (aucun facteur, comportement d'avant)

# Types canoniques mesurés → noms de types du moteur de plans auxquels ils s'appliquent.
TYPES_MOTEUR = {
    "Simple Gagnant": ("Simple Gagnant",),
    "Simple Placé": ("Simple Placé",),
    "Couplé Gagnant": ("Couplé Gagnant", "Couplé Ordre"),
    "Couplé Placé": ("Couplé Placé",),
    "2sur4": ("2sur4",),
    "Trio": ("Trio", "Trio Ordre", "Tiercé Désordre"),
    "Multi en 4": ("Multi en 4", "Mini Multi en 4"),
    "Multi en 5": ("Multi en 5", "Mini Multi en 5"),
    "Multi en 6": ("Multi en 6", "Mini Multi en 6"),
    "Multi en 7": ("Multi en 7", "Mini Multi en 7"),
}


# ─────────────────────────────────────────────────────────────
# Contexte d'une course (fonctions PURES)
# ─────────────────────────────────────────────────────────────
def discipline(d) -> str:
    d = (d or "").lower()
    if "attel" in d:
        return "attele"
    if "mont" in d:
        return "monte"
    if "obst" in d or "haie" in d or "steep" in d or "cross" in d:
        return "obstacle"
    if "plat" in d:
        return "plat"
    return "autre"


def champ(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    return "c8" if n <= 8 else "c11" if n <= 11 else "c14" if n <= 14 else "c15+"


def terrain(t) -> str:
    t = (t or "").lower()
    if not t:
        return "t?"
    if "psf" in t:
        return "psf"
    if "très souple" in t or "tres souple" in t or "lourd" in t or "collant" in t:
        return "lourd"
    if "souple" in t:
        return "souple"
    return "sec"


def chemin_contexte(course_info: Optional[dict]) -> list[str]:
    """Clés de la case la plus large à la plus fine pour cette course."""
    ci = course_info or {}
    d = discipline(ci.get("discipline"))
    c = champ(ci.get("nb_partants_courants") or ci.get("nb_partants"))
    h = "h" if "HANDICAP" in str(ci.get("categorie_particularite") or "").upper() else "nh"
    t = terrain(ci.get("terrain_officiel"))
    return ["*", d, f"{d}|{c}", f"{d}|{c}|{h}", f"{d}|{c}|{h}|{t}"]


# ─────────────────────────────────────────────────────────────
# Paris canoniques d'une course (fonction PURE)
# ─────────────────────────────────────────────────────────────
def _rapports(rd: dict, cle: str) -> list[tuple[frozenset, float, str]]:
    out = []
    for e in (rd or {}).get(cle) or []:
        try:
            nums = frozenset(int(x) for x in str(e["combinaison"]).split("-"))
            out.append((nums, float(e["rapport"]), str(e.get("libelle") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def paris_canoniques(rangs: dict[int, int], arrivee: list[int], rd: dict) -> list[tuple[str, float]]:
    """[(type canonique, retour net pour 1 €)] d'une course terminée.

    `rangs` : {rang IA: numéro}, `arrivee` : numéros dans l'ordre d'arrivée,
    `rd` : rapports_detail PMU. Un type non offert (clé absente) ou gagnant sans
    rapport publié est ignoré — on ne règle jamais un pari sans le vrai rapport."""
    out: list[tuple[str, float]] = []
    if len(arrivee) < 3 or not rangs:
        return out
    top3, top4 = set(arrivee[:3]), set(arrivee[:4])

    sg = {n: v for s, v, _ in _rapports(rd, "e_simple_gagnant") for n in s}
    sp = {n: v for s, v, _ in _rapports(rd, "e_simple_place") for n in s}
    for r in (1, 2, 3):
        num = rangs.get(r)
        if num is None:
            continue
        if sg and not (num == arrivee[0] and num not in sg):
            out.append(("Simple Gagnant", sg.get(num, 0.0) - 1))
        if sp and not (num in top3 and num not in sp):
            out.append(("Simple Placé", sp.get(num, 0.0) - 1))

    def combo(t, cle, rs, gagne):
        if any(r not in rangs for r in rs):
            return
        liste = _rapports(rd, cle)
        if not liste:
            return
        nums = frozenset(rangs[r] for r in rs)
        if gagne(nums):
            v = next((v for s, v, _ in liste if s == nums), None)
            if v is not None:
                out.append((t, v - 1))
        else:
            out.append((t, -1.0))

    for rs in ((1, 2), (1, 3), (2, 3)):
        combo("Couplé Gagnant", "e_couple_gagnant", rs, lambda s: s == set(arrivee[:2]))
        combo("Couplé Placé", "e_couple_place", rs, lambda s: s <= top3)
        combo("2sur4", "e_deux_sur_quatre", rs, lambda s: len(arrivee) >= 4 and s <= top4)
    combo("Trio", "e_trio", (1, 2, 3), lambda s: s == top3)

    multi = _rapports(rd, "e_multi")
    if multi and len(arrivee) >= 4:
        for n in (4, 5, 6, 7):
            if any(r not in rangs for r in range(1, n + 1)):
                continue
            nums = {rangs[r] for r in range(1, n + 1)}
            if top4 <= nums:
                v = next((v for _, v, lib in multi if lib.endswith(f"en {n}")), None)
                if v is not None:
                    out.append((f"Multi en {n}", v - 1))
            else:
                out.append((f"Multi en {n}", -1.0))
    return out


# ─────────────────────────────────────────────────────────────
# Apprentissage (fonction PURE sur des courses déjà chargées)
# ─────────────────────────────────────────────────────────────
def apprendre_carte(courses: list[dict]) -> dict:
    """`courses` : [{"course_info": {...}, "rangs": {...}, "arrivee": [...], "rd": {...}}].

    Renvoie {"n_courses", "cases": {cle: {type: {"n", "roi", "roi_s"}}}} où `roi` est
    le rendement brut winsorisé de la case et `roi_s` le rendement shrinké vers la
    case parente (lui seul sert aux décisions)."""
    agg: dict[str, dict[str, list[float]]] = {}
    n_courses = 0
    for c in courses:
        paris = paris_canoniques(c["rangs"], c["arrivee"], c["rd"])
        if not paris:
            continue
        n_courses += 1
        for cle in chemin_contexte(c["course_info"]):
            case = agg.setdefault(cle, {})
            for t, ret in paris:
                s = case.setdefault(t, [0, 0.0])
                s[0] += 1
                s[1] += min(ret, WINSOR)

    cases: dict[str, dict] = {}
    # Parent d'une clé = la même sans son dernier segment ; « * » pour la discipline.
    for cle in sorted(agg, key=lambda k: (k != "*", k.count("|"), k)):
        parent = None if cle == "*" else ("*" if "|" not in cle else cle.rsplit("|", 1)[0])
        cases[cle] = {}
        for t, (n, somme) in agg[cle].items():
            roi = somme / n
            prior = (cases.get(parent) or {}).get(t, {}).get("roi_s") if parent else None
            roi_s = roi if prior is None else (n * roi + SHRINK_K * prior) / (n + SHRINK_K)
            cases[cle][t] = {"n": n, "roi": round(roi, 4), "roi_s": round(roi_s, 4)}
    return {"n_courses": n_courses, "cases": cases}


def facteurs_contexte(carte: Optional[dict], course_info: Optional[dict]) -> dict[str, float]:
    """{type moteur: facteur} pour CETTE course. Vide si pas de carte (neutre).

    facteur = (1 + roi_s de la case la plus fine connue) / (1 + roi_s global), borné.
    0.0 (gate dur) si le rendement shrinké de la case est ≤ ROI_COUPE avec un
    échantillon suffisant dans la case ou sa parente directe."""
    if not carte or (carte.get("n_courses") or 0) < MIN_COURSES:
        return {}
    cases = carte.get("cases") or {}
    glob = cases.get("*") or {}
    chemin = chemin_contexte(course_info)
    out: dict[str, float] = {}
    for t, g in glob.items():
        fin, parent_n = None, 0
        for i, cle in enumerate(chemin[1:], start=1):
            e = (cases.get(cle) or {}).get(t)
            if e is None:
                break
            parent_n = ((cases.get(chemin[i - 1]) or {}).get(t) or {}).get("n", 0)
            fin = e
        if fin is None:
            continue
        roi_s, roi_g = float(fin["roi_s"]), float(g["roi_s"])
        if roi_s <= ROI_COUPE and max(int(fin["n"]), int(parent_n)) >= N_MIN_COUPE:
            f = 0.0
        else:
            f = max(FACTEUR_MIN, min(FACTEUR_MAX, (1 + roi_s) / max(1 + roi_g, 0.05)))
        for tm in TYPES_MOTEUR.get(t, (t,)):
            out[tm] = round(f, 3)
    return out


def appliquer_facteurs(poids: Optional[dict], facteurs: dict[str, float]) -> dict:
    """Multiplie les poids appris par les facteurs de contexte. Un poids déjà à 0
    (gate existant) reste à 0 ; un facteur 0 coupe le type."""
    out = dict(poids or {})
    for t, f in facteurs.items():
        out[t] = round(float(out.get(t, 1.0)) * f, 3)
    return out


# ─────────────────────────────────────────────────────────────
# Base de données
# ─────────────────────────────────────────────────────────────
async def ensure_table(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS contexte_paris_state (
            id INTEGER PRIMARY KEY,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""))


async def charger_courses(session, debut=None, fin=None) -> list[dict]:
    """Courses terminées avec prédictions FIGÉES avant le départ (anti-fuite :
    created_at < départ, cote_figee non nulle) et rapports détaillés."""
    rows = (await session.execute(text("""
        SELECT c.course_id, c.discipline, c.nb_partants, c.categorie_particularite,
               c.terrain_officiel, r.classement, r.rapports_detail,
               array_agg(pa.numero ORDER BY pr.rang_predit) AS nums
        FROM courses c
        JOIN resultats r ON r.course_id = c.course_id
        JOIN predictions pr ON pr.course_id = c.course_id
        JOIN participations pa ON pa.participation_id = pr.participation_id
        WHERE c.statut = 'termine' AND r.rapports_detail IS NOT NULL
          AND pr.created_at < c.date_heure AND pr.cote_figee IS NOT NULL
          AND COALESCE(pa.non_partant, false) = false
          AND (CAST(:d AS timestamptz) IS NULL OR c.date_heure >= CAST(:d AS timestamptz))
          AND (CAST(:f AS timestamptz) IS NULL OR c.date_heure < CAST(:f AS timestamptz))
        GROUP BY c.course_id, r.classement, r.rapports_detail
    """), {"d": debut, "f": fin})).fetchall()
    out = []
    for cid, disc, nb, cat, terr, classement, rd, nums in rows:
        cl = classement if isinstance(classement, list) else json.loads(classement or "[]")
        rd = rd if isinstance(rd, dict) else json.loads(rd or "{}")
        arrivee = []
        for e in sorted((e for e in cl if str(e.get("position", "")).isdigit()),
                        key=lambda e: int(e["position"])):
            arrivee.append(int(e["numero"]))
        if len(arrivee) < 3 or len(nums or []) < 4:
            continue
        out.append({
            "course_info": {"discipline": disc, "nb_partants": nb,
                            "categorie_particularite": cat, "terrain_officiel": terr},
            "rangs": {i + 1: int(n) for i, n in enumerate(nums)},
            "arrivee": arrivee, "rd": rd,
        })
    return out


async def calculer_et_sauver(session, fin=None) -> dict:
    """Job nocturne : réapprend la carte sur tout l'historique réglé et la persiste."""
    await ensure_table(session)
    carte = apprendre_carte(await charger_courses(session, fin=fin))
    if carte["n_courses"] < MIN_COURSES:
        log.warning("contexte_paris.echantillon_insuffisant", n=carte["n_courses"])
        return carte
    await session.execute(text("""
        INSERT INTO contexte_paris_state (id, data, updated_at)
        VALUES (1, CAST(:d AS jsonb), now())
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
    """), {"d": json.dumps(carte)})
    await session.commit()
    log.info("contexte_paris.carte_calculee", n_courses=carte["n_courses"],
             n_cases=len(carte["cases"]))
    return carte


# Cache mémoire lu par le moteur de plans (synchrone), rempli par
# `ml.reglages_appris.rafraichir` (au plus toutes les 5 min, par processus).
_CACHE: dict = {}


def carte_en_cache() -> Optional[dict]:
    return _CACHE or None


async def charger(session) -> None:
    """Chargeur pour `ml.reglages_appris` : remplace le cache par la carte en base."""
    carte = await charger_carte(session)
    _CACHE.clear()
    if carte:
        _CACHE.update(carte)


async def charger_carte(session) -> Optional[dict]:
    try:
        await ensure_table(session)
        r = (await session.execute(text(
            "SELECT data FROM contexte_paris_state WHERE id = 1"))).first()
        if not r:
            return None
        return r[0] if isinstance(r[0], dict) else json.loads(r[0])
    except Exception as e:  # noqa: BLE001 — sans carte, plan d'avant (neutre)
        log.warning("contexte_paris.chargement_echec", err=str(e)[:140])
        return None
