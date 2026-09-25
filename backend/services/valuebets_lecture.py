"""Lecture des paris de valeur pour l'affichage — une seule forme de ligne.

GET /value-bets et le flux WebSocket /ws/value-bets servent la même liste : le
flux REMPLACE la réponse REST dans le navigateur dès qu'il a parlé. Jusqu'au
2026-09-25 chacun construisait ses lignes à la main, et aucun des deux n'envoyait
ce que la page affiche : discipline (le filtre par discipline ne retenait donc
jamais rien), confiance, meilleure cote, nombre d'opérateurs, mouvement de cote.
Ce module construit la requête et la ligne ; `services.valuebets_visibilite`
reste seul juge de ce qui est visible.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import desc, select

from db.models import Cheval, Course, Entraineur, Jockey, Participation, Prediction, ValueBet

# Opérateurs retenus pour la meilleure cote et le compte des sources. `cote_geny`
# en est exclue, comme sur la fiche course : elle porte trop souvent sur un autre
# cheval (cf. `services.data_quality.SOURCES_COTES_NON_FIABLES`).
_COTES = (
    ("pmu", "cote_pmu"), ("winamax", "cote_winamax"), ("betclic", "cote_betclic"),
    ("unibet", "cote_unibet"), ("bet365", "cote_bet365"), ("ladbrokes", "cote_ladbrokes"),
    ("betfair", "cote_betfair_exchange"),
)


def requete(filtres: list, limit: int = 100):
    """Paris visibles, du meilleur au moins bon. Jointures externes : une ligne sans
    prédiction, jockey ou entraîneur reste servie, avec des champs vides."""
    return (
        select(ValueBet, Participation, Cheval, Course, Prediction, Jockey.nom, Entraineur.nom)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .outerjoin(Prediction, Prediction.prediction_id == ValueBet.prediction_id)
        .outerjoin(Jockey, Jockey.jockey_id == Participation.jockey_id)
        .outerjoin(Entraineur, Entraineur.entraineur_id == Participation.entraineur_id)
        .where(*filtres)
        .order_by(desc(ValueBet.ev_max))
        .limit(limit)
    )


def _r(x: Optional[float], n: int) -> Optional[float]:
    return round(float(x), n) if x is not None else None


def ligne(vb: ValueBet, part: Participation, cheval: Cheval, course: Course,
          pred: Optional[Prediction], jockey: Optional[str], entraineur: Optional[str]) -> dict[str, Any]:
    cotes = {src: getattr(part, col) for src, col in _COTES}
    valides = {src: c for src, c in cotes.items() if c and c > 1.0}
    meilleure = max(valides.items(), key=lambda kv: kv[1]) if valides else None

    # Mouvement PMU natif : en base, positif = la cote MONTE (cheval délaissé). À
    # l'affichage, même convention que la fiche course : positif = la cote BAISSE.
    mouvement = round(-float(part.mouvement_cote_pct) * 100, 1) if part.mouvement_cote_pct is not None else None

    proba = float(pred.proba_top1) if pred and pred.proba_top1 else None
    return {
        "vb_id": vb.vb_id,
        "course_id": vb.course_id,
        "participation_id": vb.participation_id,
        # Cheval
        "nom_cheval": cheval.nom,
        "numero": part.numero,
        "casaque_image_url": part.casaque_image_url,
        "jockey": jockey,
        "entraineur": entraineur,
        "musique": part.musique,
        # Course
        "hippodrome_nom": course.hippodrome_nom,
        "hippodrome": course.hippodrome_nom,
        "date_heure": course.date_heure,
        "code": f"R{course.numero_reunion}C{course.numero}" if course.numero_reunion and course.numero else None,
        "nom_course": course.nom,
        "discipline": course.discipline,
        "distance": course.distance,
        "nb_partants": course.nb_partants,
        "est_quinte": bool(course.est_quinte),
        "statut_course": course.statut,
        # Pari
        "ev_max": round(vb.ev_max, 4),
        "ev_pmu": _r(vb.ev_pmu, 4),
        "niveau": vb.niveau,
        "meilleure_source": vb.meilleure_source,
        "actif": vb.actif,
        "detecte_a": vb.detecte_a,
        "spi_detected": vb.spi_detected,
        "spi_score": _r(vb.spi_score, 3) if vb.spi_score else None,
        # Modèle
        "proba_top1": _r(proba, 4),
        "proba_top1_low": _r(pred.proba_top1_low, 4) if pred else None,
        "proba_top1_high": _r(pred.proba_top1_high, 4) if pred else None,
        "proba_top3": _r(pred.proba_top3, 4) if pred else None,
        "rang_predit": pred.rang_predit if pred else None,
        "confiance": _r(pred.confidence_score, 1) if pred else None,
        "cote_juste": round(1 / proba, 2) if proba else None,
        # Marché
        "cote_pmu": part.cote_pmu,
        "cote_reference": part.cote_reference,
        "cote_betfair_exchange": part.cote_betfair_exchange,
        "cote_max": meilleure[1] if meilleure else None,
        "cote_max_source": meilleure[0] if meilleure else None,
        "nb_sources": len(valides),
        "mouvement_cote_pct": mouvement,
    }
