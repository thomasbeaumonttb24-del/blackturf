"""
Calcul ELO hippique — BlackTurf.
4 scores ELO distincts : global, plat, trot, obstacle.

Algorithme :
- ELO initial : 1500
- Duels 2-à-2 pour chaque paire (i, j) dans la course
- Poids du duel décroit avec l'écart de position
- Facteur K variable selon prestige de la course
"""
import uuid
import math
import structlog
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

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


async def update_elo_after_race(
    session: AsyncSession,
    course_id: str,
    discipline: str,
    niveau_course: Optional[str],
    dotation: Optional[int],
    classement: list[dict],
) -> dict[str, float]:
    """
    Met à jour les ELO de tous les partants après une course.

    classement : [{cheval_id, position, incident}, ...]
    Retourne {cheval_id: nouveau_elo}.
    """
    k = get_k_factor(niveau_course, dotation)
    elo_field = DISCIPLINE_ELO_FIELD.get(discipline, "elo_score_plat")

    # Charger les ELO actuels
    cheval_ids = [r["cheval_id"] for r in classement if not r.get("incident")]
    result = await session.execute(
        select(Cheval).where(Cheval.cheval_id.in_(cheval_ids))
    )
    chevaux = {c.cheval_id: c for c in result.scalars().all()}

    # ELO actuels (global + discipline) — snapshot AVANT course.
    # On accumule les deltas séparément et on les applique en une fois après
    # la double boucle, pour que le résultat ne dépende pas de l'ordre
    # d'itération (calcul commutatif sur les ratings pré-course).
    elos = {}
    for cid in cheval_ids:
        cheval = chevaux.get(cid)
        if cheval:
            elo_disc = getattr(cheval, elo_field, None) or ELO_INITIAL
            elo_glob = cheval.elo_score_global or ELO_INITIAL
            elos[cid] = {
                "global_avant": elo_glob,
                "disc_avant": elo_disc,
                "delta_disc": 0.0,
                "delta_global": 0.0,
            }

    # Duels 2-à-2 entre partants valides
    valides = [r for r in classement if not r.get("incident") and r["cheval_id"] in elos]
    valides.sort(key=lambda x: x["position"] if x.get("position") is not None else 999)

    n_valides = len(valides)
    # Normaliser K par le nombre d'adversaires : un cheval dispute N-1 duels
    # par course et encaissait la SOMME des deltas → explosion (+200/+400 pts
    # en une course). k_eff borne le gain total ~ K, comme un ELO 1v1.
    k_eff = k / max(1, n_valides - 1)

    for i in range(n_valides):
        for j in range(i + 1, n_valides):
            ci = valides[i]["cheval_id"]
            cj = valides[j]["cheval_id"]

            # Probabilité attendue sur les ELO AVANT course (commutatif)
            elo_i = elos[ci]["disc_avant"]
            elo_j = elos[cj]["disc_avant"]
            p_i = expected_prob(elo_i, elo_j)
            p_j = 1.0 - p_i

            # Poids décroissant selon écart de position
            ecart = j - i
            poids = max(0.3, 1.0 - (ecart - 1) * 0.07)

            # Score réel : i est devant j (tri par position croissante),
            # sauf ex-aequo (même position : dead-heat/photo-finish) → nul 0.5
            pos_i = valides[i].get("position")
            pos_j = valides[j].get("position")
            if pos_i is not None and pos_j is not None and pos_i == pos_j:
                score_i = 0.5
            else:
                score_i = 1.0

            delta_i = k_eff * poids * (score_i - p_i)
            delta_j = k_eff * poids * ((1.0 - score_i) - p_j)

            elos[ci]["delta_disc"] += delta_i
            elos[cj]["delta_disc"] += delta_j
            elos[ci]["delta_global"] += delta_i * 0.5  # Global plus stable
            elos[cj]["delta_global"] += delta_j * 0.5

    # Sauvegarder les nouveaux ELO
    today = date.today()
    nouveaux_elos = {}

    for cid, data in elos.items():
        cheval = chevaux.get(cid)
        if not cheval:
            continue

        # Clamp pour empêcher la divergence (saturation de expected_prob à 0/1)
        nouveau_disc = round(min(ELO_MAX, max(ELO_MIN, data["disc_avant"] + data["delta_disc"])), 2)
        nouveau_global = round(min(ELO_MAX, max(ELO_MIN, data["global_avant"] + data["delta_global"])), 2)
        delta_disc = round(nouveau_disc - data["disc_avant"], 2)

        # Update cheval
        setattr(cheval, elo_field, nouveau_disc)
        cheval.elo_score_global = nouveau_global

        # Historique ELO
        hist = EloHistorique(
            elo_id=str(uuid.uuid4()),
            cheval_id=cid,
            course_id=course_id,
            date_course=today,
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
