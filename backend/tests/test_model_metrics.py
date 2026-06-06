"""
Tests métriques modèle FIABLES — BlackTurf.

Garantit la règle projet : NE JAMAIS afficher de fausse donnée.
- ROI aberrant (ex. +602.9%) masqué → None
- précision top-3 = valeur RÉELLE observée sur race_learning_log
- pas assez de courses évaluées → précision None (pas de chiffre inventé)
"""
import uuid

import pytest

from api.model_metrics import (
    ROI_MAX_PLAUSIBLE,
    ROI_MIN_PLAUSIBLE,
    plausible_roi,
    real_model_metrics,
)
from db.models import ModelVersion, RaceLearningLog


# ─── plausible_roi (pur) ──────────────────────────────────────────────

@pytest.mark.parametrize("roi,attendu", [
    (None, None),
    (6.029, None),       # +602.9% → aberrant, masqué
    (1.5, None),         # +150% > borne haute
    (-0.8, None),        # -80% < borne basse
    (0.084, 0.084),      # +8.4% plausible
    (-0.5, -0.5),        # borne basse incluse
    (1.0, 1.0),          # borne haute incluse
    (0.0, 0.0),
])
def test_plausible_roi(roi, attendu):
    assert plausible_roi(roi) == attendu


def test_bornes_coherentes():
    assert ROI_MIN_PLAUSIBLE < ROI_MAX_PLAUSIBLE


# ─── real_model_metrics (DB) ──────────────────────────────────────────

def _mv(roi_simule: float, precision_top3: float = 0.0) -> ModelVersion:
    return ModelVersion(
        version_id=str(uuid.uuid4()),
        version_num=1,
        nom_fichier="model_v0001.pkl",
        auc_roc=0.71,
        brier_score=0.18,
        precision_top3=precision_top3,
        roi_simule=roi_simule,
        nb_courses_train=500,
        est_actif=True,
    )


async def _add_rll(db, n_total: int, n_top3: int):
    """n_total courses évaluées, dont n_top3 avec gagnant dans le top-3 prédit."""
    for i in range(n_total):
        db.add(RaceLearningLog(
            log_id=str(uuid.uuid4()),
            course_id=f"course-{i}-{uuid.uuid4().hex[:8]}",
            gagnant_rang_predit=(2 if i < n_top3 else 7),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_roi_aberrant_masque(db):
    """roi_simule=6.029 (le bug réel) ne doit JAMAIS sortir brut."""
    await _add_rll(db, n_total=77, n_top3=54)
    out = await real_model_metrics(db, _mv(roi_simule=6.029))
    assert out["roi_simule"] is None


@pytest.mark.asyncio
async def test_precision_reelle_observee(db):
    """Précision = ratio réel race_learning_log, pas la métadonnée train (0.0)."""
    await _add_rll(db, n_total=77, n_top3=54)  # 54/77 ≈ 0.7013
    out = await real_model_metrics(db, _mv(roi_simule=6.029, precision_top3=0.0))
    assert out["precision_top3"] == pytest.approx(54 / 77, abs=1e-4)
    assert out["nb_courses_evaluees"] == 77


@pytest.mark.asyncio
async def test_precision_none_si_pas_assez_de_courses(db):
    """< 10 courses évaluées → pas de précision inventée."""
    await _add_rll(db, n_total=5, n_top3=4)
    out = await real_model_metrics(db, _mv(roi_simule=0.084))
    assert out["precision_top3"] is None
    assert out["nb_courses_evaluees"] == 5


@pytest.mark.asyncio
async def test_roi_plausible_conserve(db):
    """ROI crédible est conservé tel quel (fraction)."""
    await _add_rll(db, n_total=20, n_top3=14)
    out = await real_model_metrics(db, _mv(roi_simule=0.084))
    assert out["roi_simule"] == pytest.approx(0.084)


@pytest.mark.asyncio
async def test_sans_modele(db):
    """mv=None → aucune valeur fabriquée."""
    out = await real_model_metrics(db, None)
    assert out["roi_simule"] is None
    assert out["precision_top3"] is None
    assert out["nb_courses_evaluees"] == 0
