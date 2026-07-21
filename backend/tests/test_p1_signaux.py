"""Tests P1 (audit ROI 2026-07-02, volet précision) :
- signaux marché PMU vivants (steam_pmu_30min / drift_out_30min) + terrain_ideal
  réparé (condition running_style morte retirée) ;
- rang prédit du gagnant ALIGNÉ sur le classement affiché (rang_predit) dans
  race_learning_log — fini les 99 à tort quand le tri proba_top3 divergeait.
"""
from datetime import datetime, timezone

import pytest

from ml.signal_performance import SIGNALS


# ── Signaux marché PMU (mouvement_30min : positif = cote en baisse) ───────────
class TestSignauxMarchePMU:
    def test_steam_pmu_declenche_sur_baisse(self):
        assert SIGNALS["steam_pmu_30min"]({"mouvement_30min": 0.12}) is True
        assert SIGNALS["steam_pmu_30min"]({"mouvement_30min": 0.03}) is False
        assert SIGNALS["steam_pmu_30min"]({}) is False                 # absent → neutre

    def test_drift_out_declenche_sur_hausse(self):
        assert SIGNALS["drift_out_30min"]({"mouvement_30min": -0.08}) is True
        assert SIGNALS["drift_out_30min"]({"mouvement_30min": -0.02}) is False
        assert SIGNALS["drift_out_30min"]({"mouvement_30min": 0.10}) is False

    def test_terrain_ideal_sans_running_style(self):
        """running_style jamais peuplé (0/50645) : le signal ne doit plus en dépendre."""
        assert SIGNALS["terrain_ideal"]({"pref_terrain_actuel": 0.80}) is True
        assert SIGNALS["terrain_ideal"]({"pref_terrain_actuel": 0.50}) is False


# ── Rang prédit du gagnant aligné sur le classement AFFICHÉ ───────────────────
@pytest.mark.asyncio
async def test_rang_gagnant_suit_rang_predit_affiche(db):
    """Gagnant classé 2e par rang_predit (affiché) mais 4e par proba_top3 seule :
    l'ancien tri le marquait 99 (hors top-3) → accuracy palmarès faussée. Le log
    doit maintenant refléter le classement que voit l'utilisateur."""
    from db.models import Course, RaceLearningLog
    from ml.post_race_analyzer import PostRaceAnalyzer
    from sqlalchemy import select

    db.add(Course(
        course_id="RC99", reunion_id="R1", numero=1, nom="Test",
        date_heure=datetime(2026, 1, 10, 13, 0, tzinfo=timezone.utc),
        hippodrome_nom="Vincennes", discipline="Attelé", distance=2700,
        nb_partants=5, statut="termine",
    ))
    await db.commit()

    # N°7 : gros proba_top1 (gagneur sec) → rang_predit 2, mais proba_top3 faible
    # (4e par placé). Les N°1/2/3 ont des proba_top3 plus hautes.
    predictions = [
        {"numero": 1, "proba_top1": 0.30, "proba_top3": 0.70, "cote_pmu": 2.5, "rang_predit": 1},
        {"numero": 7, "proba_top1": 0.25, "proba_top3": 0.35, "cote_pmu": 4.0, "rang_predit": 2},
        {"numero": 2, "proba_top1": 0.10, "proba_top3": 0.60, "cote_pmu": 6.0, "rang_predit": 3},
        {"numero": 3, "proba_top1": 0.08, "proba_top3": 0.55, "cote_pmu": 8.0, "rang_predit": 4},
        {"numero": 4, "proba_top1": 0.05, "proba_top3": 0.30, "cote_pmu": 12.0, "rang_predit": 5},
    ]
    resultat = {"ordre_arrivee": [
        {"numero": 7, "position": 1},
        {"numero": 1, "position": 2},
        {"numero": 3, "position": 3},
        {"numero": 2, "position": 4},
        {"numero": 4, "position": 5},
    ]}

    analyzer = PostRaceAnalyzer()
    await analyzer.analyze_race(db, "RC99", predictions, resultat)

    row = (await db.execute(
        select(RaceLearningLog).where(RaceLearningLog.course_id == "RC99")
    )).scalar_one_or_none()
    assert row is not None
    # Ancien tri (proba_top3) : top-3 = {1, 2, 3} → gagnant N°7 marqué 99.
    # Nouveau (rang_predit affiché) : top-3 = {1, 7, 2} → rang 2.
    assert row.gagnant_rang_predit == 2
    assert row.feature_autopsy["_meta"]["top3_precision"] is True
