"""
Tests métriques modèle FIABLES — BlackTurf.

Garantit la règle projet : NE JAMAIS afficher de fausse donnée.
- ROI aberrant (ex. +602.9%) masqué → None
- précision top-3 = valeur RÉELLE observée sur race_learning_log
- pas assez de courses évaluées → précision None (pas de chiffre inventé)
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from api.model_metrics import (
    ROI_MAX_PLAUSIBLE,
    ROI_MIN_PLAUSIBLE,
    plausible_auc,
    plausible_roi,
    plausible_roi_pct,
    real_model_metrics,
)
from db.models import (
    Course, ModelVersion, Prediction, PredictionSnapshot, RaceLearningLog,
)


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


@pytest.mark.parametrize("auc,attendu", [
    (None, None),
    (0.06, None),        # le bug réel : pire que le hasard → masqué
    (0.49, None),        # juste sous 0.5
    (0.5, 0.5),          # borne basse incluse
    (0.71, 0.71),        # plausible
    (1.0, 1.0),          # borne haute incluse
    (1.2, None),         # impossible
])
def test_plausible_auc(auc, attendu):
    assert plausible_auc(auc) == attendu


@pytest.mark.parametrize("roi_pct,attendu", [
    (None, None),
    (307.0, None),       # +307% → aberrant longshot, masqué
    (150.0, None),       # > borne haute
    (-60.0, None),       # < borne basse
    (15.6, 15.6),        # plausible
    (-50.0, -50.0),      # borne basse incluse
    (100.0, 100.0),      # borne haute incluse
    (0.0, 0.0),
])
def test_plausible_roi_pct(roi_pct, attendu):
    assert plausible_roi_pct(roi_pct) == attendu


# ─── real_model_metrics (DB) ──────────────────────────────────────────

def _mv(roi_simule: float, precision_top3: float = 0.0, auc_roc: float = 0.71) -> ModelVersion:
    return ModelVersion(
        version_id=str(uuid.uuid4()),
        version_num=1,
        nom_fichier="model_v0001.pkl",
        auc_roc=auc_roc,
        brier_score=0.18,
        precision_top3=precision_top3,
        roi_simule=roi_simule,
        nb_courses_train=500,
        est_actif=True,
    )


async def _add_rll(db, n_total: int, n_top3: int, n_contaminated: int = 0):
    """n_total courses évaluées, dont n_top3 avec gagnant dans le top-3 prédit."""
    for i in range(n_total):
        course_id = f"course-{i}-{uuid.uuid4().hex[:8]}"
        depart = datetime.now(timezone.utc) - timedelta(days=1)
        db.add(Course(
            course_id=course_id,
            reunion_id=f"reunion-{i}",
            numero=i + 1,
            date_heure=depart,
            hippodrome_nom="Test",
            discipline="Plat",
            distance=2000,
            nb_partants=1,
            statut="termine",
        ))
        prediction_id = str(uuid.uuid4())
        participation_id = str(uuid.uuid4())
        is_replayable = i < n_total - n_contaminated
        observed_at = depart - timedelta(minutes=10) if is_replayable else depart + timedelta(minutes=1)
        db.add(Prediction(
            prediction_id=prediction_id,
            participation_id=participation_id,
            course_id=course_id,
            proba_top1=0.2,
            proba_top3=0.5,
            rang_predit=1,
            created_at=observed_at,
        ))
        db.add(PredictionSnapshot(
            snapshot_id=str(uuid.uuid4()),
            prediction_run_id=str(uuid.uuid4()),
            prediction_id=prediction_id,
            participation_id=participation_id,
            course_id=course_id,
            features={},
            features_hash="a" * 64,
            feature_schema_hash="b" * 64,
            proba_top1=0.2,
            proba_top3=0.5,
            rang_predit=1,
            observed_at=observed_at,
            course_start_at=depart,
            is_pre_course=is_replayable,
            origin="live",
            is_replayable=True,
        ))
        db.add(RaceLearningLog(
            log_id=str(uuid.uuid4()),
            course_id=course_id,
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
    assert out["prediction_data_quality"]["n_replayable"] == 77


@pytest.mark.asyncio
async def test_predictions_post_course_sont_exclues_des_metriques(db):
    await _add_rll(db, n_total=12, n_top3=12, n_contaminated=2)
    out = await real_model_metrics(db, _mv(roi_simule=0.0))
    assert out["nb_courses_evaluees"] == 10
    assert out["precision_top3"] == 1.0


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
async def test_auc_credible_expose(db):
    """AUC plausible exposée telle quelle dans le dict."""
    await _add_rll(db, n_total=20, n_top3=14)
    out = await real_model_metrics(db, _mv(roi_simule=0.084, auc_roc=0.71))
    assert out["auc_roc"] == pytest.approx(0.71)
    assert out["precision_top3"] == pytest.approx(14 / 20, abs=1e-4)


@pytest.mark.asyncio
async def test_modele_casse_masque_auc_et_precision(db):
    """AUC=0.06 (modèle cassé) → auc_roc None ET precision None malgré assez de courses."""
    await _add_rll(db, n_total=77, n_top3=0)  # 0% observé sur modèle cassé
    out = await real_model_metrics(db, _mv(roi_simule=0.084, auc_roc=0.06))
    assert out["auc_roc"] is None
    assert out["precision_top3"] is None
    assert out["nb_courses_evaluees"] == 77


@pytest.mark.asyncio
async def test_sans_modele(db):
    """mv=None → aucune valeur fabriquée."""
    out = await real_model_metrics(db, None)
    assert out["auc_roc"] is None
    assert out["roi_simule"] is None
    assert out["precision_top3"] is None
    assert out["nb_courses_evaluees"] == 0


# ─── Sonde en échec : la transaction doit être désempoisonnée ──────────

class _SessionQuiEchoue:
    """Session dont CHAQUE requête échoue, et qui compte ses rollbacks."""

    def __init__(self):
        self.rollbacks = 0

    async def execute(self, *_a, **_k):
        raise RuntimeError("could not resize shared memory segment")

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_sonde_en_echec_annule_la_transaction():
    """Une sonde ratée ne doit pas faire tomber les requêtes SUIVANTES.

    PostgreSQL marque la transaction entière comme avortée dès qu'une requête
    échoue. Sans rollback, l'appelant se prenait « current transaction is
    aborted » sur un simple `count(courses)` — le 500 de /admin/api/dashboard du
    20/08/2026, dont la cause réelle (un /dev/shm de 64 Mo côté PostgreSQL) était
    avalée quatre appels plus haut.
    """
    session = _SessionQuiEchoue()

    out = await real_model_metrics(session, None)

    assert session.rollbacks >= 1
    # Échec FERMÉ : aucune métrique inventée à partir d'une sonde morte.
    assert out["nb_courses_evaluees"] == 0
    assert out["precision_top3"] is None
    assert out["roi_reel"] is None
