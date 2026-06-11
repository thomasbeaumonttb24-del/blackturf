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
# Même plage exprimée en POURCENTAGE (pour le ROI backtest renvoyé en %).
ROI_PCT_MIN_PLAUSIBLE = -50.0
ROI_PCT_MAX_PLAUSIBLE = 100.0
# AUC crédible uniquement dans [0.5, 1.0]. < 0.5 = pire que le hasard ⇒ modèle
# cassé / sous-entraîné (ex. valeur 0.06) : on n'affiche RIEN ("—") plutôt qu'un
# chiffre qui décrédibilise. > 1.0 = impossible.
AUC_MIN_PLAUSIBLE = 0.5
AUC_MAX_PLAUSIBLE = 1.0
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


def plausible_roi_pct(roi_pct: float | None) -> float | None:
    """Retourne le ROI (en %) s'il est crédible, sinon None.

    Un backtest flat sur un petit échantillon biaisé longshot peut sortir des ROI
    aberrants (+307%). On ne publie que la plage plausible, sinon None → "—".
    """
    if roi_pct is None:
        return None
    r = float(roi_pct)
    if ROI_PCT_MIN_PLAUSIBLE <= r <= ROI_PCT_MAX_PLAUSIBLE:
        return r
    return None


def plausible_auc(auc: float | None) -> float | None:
    """Retourne l'AUC si crédible (∈ [0.5, 1.0]), sinon None."""
    if auc is None:
        return None
    a = float(auc)
    if AUC_MIN_PLAUSIBLE <= a <= AUC_MAX_PLAUSIBLE:
        return a
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

    # AUC crédible (ou None). Sert aussi de garde-fou : si le modèle actif n'est
    # pas crédible (AUC hors [0.5,1]), sa précision observée n'est pas représentative
    # ⇒ on ne la publie pas (None → "—"), au lieu d'un 0% trompeur.
    auc = plausible_auc(mv.auc_roc if mv else None)

    if rll_total >= MIN_RACES_FOR_PRECISION and auc is not None:
        precision_top3 = round(rll_top3 / rll_total, 4)
    else:
        precision_top3 = None

    roi = plausible_roi(mv.roi_simule if mv else None)

    return {
        "auc_roc": auc,
        "precision_top3": precision_top3,
        "roi_simule": roi,
        "nb_courses_evaluees": rll_total,
    }
