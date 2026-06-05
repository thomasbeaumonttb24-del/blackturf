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

    # ELO actuels (global + discipline)
    elos = {}
    for cid in cheval_ids:
        cheval = chevaux.get(cid)
        if cheval:
            elo_disc = getattr(cheval, elo_field, ELO_INITIAL)
            elos[cid] = {
                "global_avant": cheval.elo_score_global,
                "disc_avant": elo_disc,
                "global_apres": cheval.elo_score_global,
                "disc_apres": elo_disc,
            }

    # Duels 2-à-2 entre partants valides
    valides = [r for r in classement if not r.get("incident") and r["cheval_id"] in elos]
    valides.sort(key=lambda x: x.get("position") or 999)

    for i in range(len(valides)):
        for j in range(i + 1, len(valides)):
            ci = valides[i]["cheval_id"]
            cj = valides[j]["cheval_id"]
            if ci not in elos or cj not in elos:
                continue

            elo_i = elos[ci]["disc_apres"]
            elo_j = elos[cj]["disc_apres"]

            # Probabilité attendue
            p_i = expected_prob(elo_i, elo_j)
            p_j = 1.0 - p_i

            # Poids décroissant selon écart de position
            ecart = j - i
            poids = max(0.3, 1.0 - (ecart - 1) * 0.07)

            # i a battu j (position i < position j)
            delta_i = k * poids * (1.0 - p_i)
            delta_j = k * poids * (0.0 - p_j)

            elos[ci]["disc_apres"] += delta_i
            elos[cj]["disc_apres"] += delta_j
            elos[ci]["global_apres"] += delta_i * 0.5  # Global plus stable
            elos[cj]["global_apres"] += delta_j * 0.5

    # Sauvegarder les nouveaux ELO
    today = date.today()
    nouveaux_elos = {}

    for cid, data in elos.items():
        cheval = chevaux.get(cid)
        if not cheval:
            continue

        nouveau_disc = round(data["disc_apres"], 2)
        nouveau_global = round(data["global_apres"], 2)
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
