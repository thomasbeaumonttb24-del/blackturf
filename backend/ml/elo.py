"""
Calcul ELO hippique — BlackTurf.
4 scores ELO distincts : global, plat, trot, obstacle.

Algorithme :
- ELO initial : 1500
- Duels 2-à-2 pour chaque paire (i, j) dans la course, tous de même poids
- Disqualifiés / tombés / arrêtés : battus par tous les classés
- Facteur K variable selon prestige de la course, majoré pour les chevaux
  peu notés (K provisoire), inédits amorcés à la moyenne du champ
"""
import uuid
import math
import structlog
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from db.models import Cheval, EloHistorique

log = structlog.get_logger()

ELO_INITIAL = 1500.0
ELO_MIN = 800.0
ELO_MAX = 2800.0
ELO_K_BASE = 32
ELO_K_GROUP1 = 64
ELO_K_LISTED = 48
ELO_K_RECLAIM = 24

DISCIPLINE_ELO_FIELD = {
    "Plat": "elo_score_plat",
    "Attelé": "elo_score_trot",
    "Monté": "elo_score_trot",
    "Haies": "elo_score_obstacle",
    "Steeple": "elo_score_obstacle",
    "Cross": "elo_score_obstacle",
}


def get_k_factor(niveau_course: Optional[str], dotation: Optional[int]) -> int:
    """Facteur K selon prestige de la course."""
    niveau = (niveau_course or "").lower()
    dot = dotation or 0

    if "group1" in niveau or "grade1" in niveau or dot > 50_000_000:
        return ELO_K_GROUP1
    elif "group2" in niveau or "group3" in niveau or dot > 10_000_000:
        return 48
    elif "listed" in niveau or dot > 5_000_000:
        return ELO_K_LISTED
    elif "reclam" in niveau or dot < 1_000_000:
        return ELO_K_RECLAIM
    return ELO_K_BASE


def expected_prob(elo_a: float, elo_b: float) -> float:
    """Probabilité que A batte B."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400))


def calculer_delta_elo(elo_a: float, elo_b: float, score_a: float, k: int = ELO_K_BASE) -> float:
    """Delta ELO pour A (score_a=1 victoire, 0.5 nul, 0 défaite)."""
    return k * (score_a - expected_prob(elo_a, elo_b))


def classement_elo(classement: list[dict]) -> list[dict]:
    """Partants qui comptent dans les duels, avec leur position de duel.

    Un cheval classé garde sa place. Un cheval PARTI mais non classé sur incident
    (disqualifié, tombé, arrêté…) est rangé DERRIÈRE tous les classés, à égalité
    entre eux : il a perdu contre chaque cheval qui a fini la course.

    Avant, les incidents étaient simplement retirés des duels : une disqualification
    ne coûtait AUCUN point. Un trotteur fautif cinq fois de suite gardait l'ELO de
    ses rares bonnes sorties et pouvait être présenté « au-dessus du lot ».
    Les non-partants, eux, n'ont pas couru : ils restent hors du calcul.
    """
    classes, fautifs = [], []
    for r in classement:
        if r.get("cheval_id") is None:
            continue
        pos = r.get("position")
        try:
            pos = int(pos) if pos is not None else None
        except (TypeError, ValueError):
            pos = None
        incident = str(r.get("incident") or "").upper()
        if pos is not None and 1 <= pos < 90:
            classes.append({**r, "position": pos})
        elif "NON_PARTANT" in incident or "NON PARTANT" in incident:
            continue
        elif incident or r.get("disqualifie") or (pos is not None and pos >= 90):
            fautifs.append(r)
    derniere = max((r["position"] for r in classes), default=0) + 1
    return classes + [{**r, "position": derniere} for r in fautifs]


# ── Cheval peu noté : K PROVISOIRE ─────────────────────────────────────────
# Un ELO sans historique est une supposition. Avec le même K qu'un cheval à 40
# courses, un bon cheval mettait des dizaines de sorties à rejoindre sa vraie
# valeur — et tant qu'il n'y était pas, il faussait aussi les duels de ses
# adversaires. Le K est multiplié par PROVISOIRE_K_MAX au premier passage, puis
# décroît linéairement jusqu'à 1 après PROVISOIRE_NB_COURSES courses notées.
PROVISOIRE_K_MAX = 2.5
PROVISOIRE_NB_COURSES = 8
# Nombre minimal de partants DÉJÀ notés pour amorcer un inédit à leur moyenne.
AMORCE_MIN_NOTES = 3


def champ_elo(discipline: Optional[str]) -> str:
    """Colonne ELO d'une discipline, quelle que soit sa graphie (« Attelé »,
    « TROT_ATTELE », « attele », « Steeple »…). Défaut : plat."""
    brut = DISCIPLINE_ELO_FIELD.get(discipline or "")
    if brut:
        return brut
    d = (discipline or "").lower()
    if "trot" in d or "attel" in d or "mont" in d:
        return "elo_score_trot"
    if "haie" in d or "steeple" in d or "obstacle" in d or "cross" in d:
        return "elo_score_obstacle"
    return "elo_score_plat"


def multiplicateur_provisoire(nb_courses_notees: int) -> float:
    """K × [PROVISOIRE_K_MAX → 1] selon l'expérience du cheval dans la discipline."""
    reste = max(0.0, 1.0 - max(0, nb_courses_notees) / PROVISOIRE_NB_COURSES)
    return 1.0 + (PROVISOIRE_K_MAX - 1.0) * reste


def amorcer_inedits(ratings: dict, nb_notees: dict) -> dict:
    """Rating de départ des chevaux JAMAIS notés : la moyenne des partants notés.

    Les conditions de course (catégorie, gains, allocation) réunissent des chevaux
    de niveau voisin : le champ est le meilleur a priori disponible. Démarrer tout
    le monde à 1500 plaçait un débutant de Groupe au niveau d'un réclamer, et
    faisait gagner/perdre des points à ses adversaires sur une valeur fictive.
    Faute d'au moins AMORCE_MIN_NOTES chevaux notés, on garde le rating courant.
    """
    notes = [r for cid, r in ratings.items() if nb_notees.get(cid, 0) > 0]
    if len(notes) < AMORCE_MIN_NOTES:
        return dict(ratings)
    moyenne = sum(notes) / len(notes)
    return {cid: (moyenne if nb_notees.get(cid, 0) == 0 and r == ELO_INITIAL else r)
            for cid, r in ratings.items()}


def calculer_deltas_course(valides: list[dict], ratings: dict, nb_notees: dict,
                           k: float) -> dict:
    """Deltas ELO d'une course (fonction pure, testable sans base).

    valides : [{cheval_id, position}] — cf. `classement_elo` (incidents derniers,
    à égalité). Chaque paire de partants est un duel : le mieux classé gagne,
    même position = nul. Tous les duels PÈSENT PAREIL : l'ancien poids décroissant
    avec l'écart de places faisait compter trois fois moins « battre le dernier »
    que « battre le 2ᵉ », alors que c'est l'information la plus sûre de la course.

    K est divisé par (n-1) pour que le gain total d'une course reste de l'ordre de
    K quel que soit le nombre de partants, puis modulé par l'expérience de chaque
    cheval (`multiplicateur_provisoire`). Les probabilités attendues sont calculées
    sur les ratings AVANT course : le résultat ne dépend pas de l'ordre des duels.
    """
    n = len(valides)
    deltas = {r["cheval_id"]: 0.0 for r in valides}
    if n < 2:
        return deltas
    k_eff = k / (n - 1)
    ordre = sorted(valides, key=lambda r: r["position"])
    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = ordre[i]["cheval_id"], ordre[j]["cheval_id"]
            p_i = expected_prob(ratings[ci], ratings[cj])
            score_i = 0.5 if ordre[i]["position"] == ordre[j]["position"] else 1.0
            deltas[ci] += score_i - p_i
            deltas[cj] += (1.0 - score_i) - (1.0 - p_i)
    return {cid: k_eff * multiplicateur_provisoire(nb_notees.get(cid, 0)) * d
            for cid, d in deltas.items()}


def resoudre_course(valides: list[dict], disc_bruts: dict, glob_bruts: dict,
                    nb_disc: dict, nb_total: dict, k: float) -> dict:
    """Nouveaux ratings de tous les partants d'une course — fonction PURE.

    Partagée par la mise à jour en direct (`update_elo_after_race`) et le recalcul
    complet (`scripts/elo_recalcul.py`) : les deux produisent exactement les mêmes
    chiffres. `valides` sort de `classement_elo`. Retourne, par cheval :
    disc_avant (après amorçage éventuel), disc_apres, glob_apres, delta_disc.
    """
    disc_avant = amorcer_inedits(disc_bruts, nb_disc)
    glob_avant = amorcer_inedits(glob_bruts, nb_total)
    deltas_disc = calculer_deltas_course(valides, disc_avant, nb_disc, k)
    # Global : même course, ratings globaux, demi-K (plus stable, multi-discipline).
    deltas_glob = calculer_deltas_course(valides, glob_avant, nb_total, k * 0.5)
    out = {}
    for cid in disc_bruts:
        # Clamp pour empêcher la divergence (saturation de expected_prob à 0/1)
        d = round(min(ELO_MAX, max(ELO_MIN, disc_avant[cid] + deltas_disc.get(cid, 0.0))), 2)
        g = round(min(ELO_MAX, max(ELO_MIN, glob_avant[cid] + deltas_glob.get(cid, 0.0))), 2)
        out[cid] = {"disc_avant": disc_avant[cid], "disc_apres": d, "glob_apres": g,
                    "delta_disc": round(d - disc_avant[cid], 2)}
    return out


async def update_elo_after_race(
    session: AsyncSession,
    course_id: str,
    discipline: str,
    niveau_course: Optional[str],
    dotation: Optional[int],
    classement: list[dict],
    date_course: Optional[date] = None,
) -> dict[str, float]:
    """
    Met à jour les ELO de tous les partants après une course.

    classement : [{cheval_id, position, incident}, ...]
    Retourne {cheval_id: nouveau_elo}.
    Les incidents (disqualifié, tombé…) comptent comme battus par tous les
    classés — cf. `classement_elo`. Calcul : `calculer_deltas_course`.
    date_course : date de la course (défaut : lue dans `courses`). Elle date les
    lignes d'`elo_historique`, que les features filtrent en point-in-time — la
    date du CALCUL les rendait fausses à chaque rejeu ou rattrapage.
    """
    # ── IDEMPOTENCE (anti-inflation) ─────────────────────────────────────────
    # L'ELO est INCRÉMENTAL (on lit le rating courant, on ajoute le delta, on
    # réécrit). Le pipeline post-course peut tourner plusieurs fois sur la même
    # course (re-settlement, sync, catch-up). Sans garde, chaque passage RÉ-applique
    # le delta → double-comptage → les ratings divergent jusqu'au plafond (bug
    # observé : 5,9M lignes elo_historique pour 152k vrais résultats, ~39×). On
    # n'applique l'ELO qu'UNE SEULE FOIS par course.
    already = await session.execute(
        select(func.count()).select_from(EloHistorique).where(
            EloHistorique.course_id == course_id
        )
    )
    if (already.scalar() or 0) > 0:
        log.info("elo.skip_already_applied", course_id=course_id)
        return {}

    k = get_k_factor(niveau_course, dotation)
    elo_field = champ_elo(discipline)

    if date_course is None:
        from db.models import Course
        dh = await session.scalar(select(Course.date_heure).where(Course.course_id == course_id))
        date_course = dh.date() if hasattr(dh, "date") else (dh or date.today())

    classement = classement_elo(classement)
    cheval_ids = [r["cheval_id"] for r in classement]
    result = await session.execute(
        select(Cheval).where(Cheval.cheval_id.in_(cheval_ids))
    )
    chevaux = {c.cheval_id: c for c in result.scalars().all()}

    # Expérience de chaque cheval : courses déjà notées dans CETTE colonne ELO
    # (pour le K provisoire et l'amorçage) et toutes colonnes (pour le global).
    nb_disc: dict[str, int] = {}
    nb_total: dict[str, int] = {}
    if chevaux:
        rows = await session.execute(
            select(EloHistorique.cheval_id, EloHistorique.discipline, func.count())
            .where(EloHistorique.cheval_id.in_(list(chevaux)))
            .group_by(EloHistorique.cheval_id, EloHistorique.discipline)
        )
        for cid, disc, nb in rows.all():
            nb_total[cid] = nb_total.get(cid, 0) + nb
            if champ_elo(disc) == elo_field:
                nb_disc[cid] = nb_disc.get(cid, 0) + nb

    disc_bruts = {cid: getattr(c, elo_field, None) or ELO_INITIAL for cid, c in chevaux.items()}
    glob_bruts = {cid: c.elo_score_global or ELO_INITIAL for cid, c in chevaux.items()}
    valides = [r for r in classement if r["cheval_id"] in chevaux]
    resultats = resoudre_course(valides, disc_bruts, glob_bruts, nb_disc, nb_total, k)

    # Sauvegarder les nouveaux ELO
    nouveaux_elos = {}

    for cid, res in resultats.items():
        cheval = chevaux.get(cid)
        if not cheval:
            continue
        data = {"disc_avant": res["disc_avant"]}
        nouveau_disc = res["disc_apres"]
        nouveau_global = res["glob_apres"]
        delta_disc = res["delta_disc"]

        # Update cheval
        setattr(cheval, elo_field, nouveau_disc)
        cheval.elo_score_global = nouveau_global

        # Historique ELO
        hist = EloHistorique(
            elo_id=str(uuid.uuid4()),
            cheval_id=cid,
            course_id=course_id,
            date_course=date_course,
            discipline=discipline,
            elo_avant=data["disc_avant"],
            elo_apres=nouveau_disc,
            delta_elo=delta_disc,
        )
        session.add(hist)
        nouveaux_elos[cid] = nouveau_disc

        log.debug(
            "elo.updated",
            cheval_id=cid,
            avant=data["disc_avant"],
            apres=nouveau_disc,
            delta=delta_disc,
        )

    await session.flush()
    log.info("elo.race_updated", course_id=course_id, nb_chevaux=len(nouveaux_elos))
    return nouveaux_elos
