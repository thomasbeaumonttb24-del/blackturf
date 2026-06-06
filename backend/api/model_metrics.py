"""
Métriques modèle FIABLES — BlackTurf.

Les métadonnées brutes de ModelVersion (roi_simule, precision_top3) ne sont PAS
fiables (overfit train / valeurs seed à 0). Règle projet : NE JAMAIS afficher de
fausse donnée. Ce module recalcule les métriques réelles observées et masque les
valeurs aberrantes.

- precision_top3 RÉELLE : observée sur race_learning_log (gagnant dans le top-3 prédit)
- roi_simule : n'est exposé que s'il tombe dans une plage plausible

Pattern d'origine : assistant.py get_model_metrics (commit b9121ca).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ModelVersion, RaceLearningLog

# ROI simulé considéré crédible uniquement dans cette plage (fraction, pas %).
ROI_MIN_PLAUSIBLE = -0.5   # -50%
ROI_MAX_PLAUSIBLE = 1.0    # +100%
# Minimum de courses évaluées avant de publier une précision réelle.
MIN_RACES_FOR_PRECISION = 10


def plausible_roi(roi_simule: float | None) -> float | None:
    """Retourne le ROI (fraction) s'il est crédible, sinon None."""
    if roi_simule is None:
        return None
    roi = float(roi_simule)
    if ROI_MIN_PLAUSIBLE <= roi <= ROI_MAX_PLAUSIBLE:
        return roi
    return None


async def real_model_metrics(db: AsyncSession, mv: ModelVersion | None) -> dict:
    """
    Métriques fiables du modèle pour affichage.

    Retourne (toutes les valeurs peuvent être None si non fiables) :
      - precision_top3 : fraction (0..1) observée sur race_learning_log, None si < seuil
      - roi_simule     : fraction, None si hors plage plausible
      - nb_courses_evaluees : nombre de courses réellement évaluées
    """
    rll_total = (await db.execute(
        select(func.count(RaceLearningLog.log_id))
    )).scalar() or 0
    rll_top3 = (await db.execute(
        select(func.count(RaceLearningLog.log_id)).where(
            RaceLearningLog.gagnant_rang_predit <= 3
        )
    )).scalar() or 0

    if rll_total >= MIN_RACES_FOR_PRECISION:
        precision_top3 = round(rll_top3 / rll_total, 4)
    else:
        precision_top3 = None

    roi = plausible_roi(mv.roi_simule if mv else None)

    return {
        "precision_top3": precision_top3,
        "roi_simule": roi,
        "nb_courses_evaluees": rll_total,
    }
