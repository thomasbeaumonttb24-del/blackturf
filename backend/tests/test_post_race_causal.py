"""
Test d'intégration : PostRaceAnalyzer produit des tags causaux (Phase 3).
"""
from datetime import datetime, timezone

import pytest

from sqlalchemy import select

from db.models import Course, TempsPassage, RaceLearningLog
from ml.post_race_analyzer import PostRaceAnalyzer


@pytest.mark.asyncio
async def test_analyze_race_genere_causal_tags(db):
    db.add(Course(
        course_id="RC1", reunion_id="R1", numero=1, nom="Test",
        date_heure=datetime(2026, 1, 10, 13, 0, tzinfo=timezone.utc),
        hippodrome_nom="Vincennes", discipline="Attelé", distance=2700,
        nb_partants=5, statut="termine",
    ))
    # Position à 500m : le gagnant #5 était 5e → vient de loin (finit fort).
    pos500 = {5: 5, 8: 6, 3: 7, 1: 1, 2: 2}
    for num, p5 in pos500.items():
        db.add(TempsPassage(
            course_id="RC1", numero=num, nom_cheval=f"CH{num}",
            position_500m=p5, passage_dernier_400m="28\"5",
        ))
    await db.commit()

    predictions = [
        {"numero": 5, "proba_top3": 0.25, "cote_pmu": 6.0},
        {"numero": 3, "proba_top3": 0.55, "cote_pmu": 2.5},   # favori IA
        {"numero": 8, "proba_top3": 0.20, "cote_pmu": 8.0},
        {"numero": 1, "proba_top3": 0.10, "cote_pmu": 15.0},
        {"numero": 2, "proba_top3": 0.10, "cote_pmu": 20.0},
    ]
    resultat = {"ordre_arrivee": [
        {"numero": 5, "position": 1},
        {"numero": 8, "position": 2},
        {"numero": 1, "position": 3},
        {"numero": 2, "position": 4},
        {"numero": 3, "position": 5},   # favori IA fini 5e
    ]}

    analyzer = PostRaceAnalyzer()
    rapport = await analyzer.analyze_race(db, "RC1", predictions, resultat)

    assert rapport["gagnant_proba_ia"] == pytest.approx(0.25)
    assert rapport["gagnant_proba_ia_pct"] == pytest.approx(25.0)
    assert "causal_tags" in rapport
    tags = {t["tag"] for t in rapport["causal_tags"]}
    # Gagnant venu de loin + favori hors top-3
    assert "gagnant_finit_fort" in tags
    assert any(t.startswith("favori_") for t in tags)
    # feature_autopsy doit aussi porter les causes (pour l'apprentissage)
    assert "causal_tags" in rapport["feature_autopsy"]

    # Persistance réelle dans race_learning_log (schéma réconcilié)
    row = (await db.execute(
        select(RaceLearningLog).where(RaceLearningLog.course_id == "RC1")
    )).scalar_one_or_none()
    assert row is not None
    assert row.was_surprise is not None
    assert "causal_tags" in (row.feature_autopsy or {})
    # Les extras hors schéma sont préservés dans _meta
    assert row.feature_autopsy["_meta"]["winner_actual"] == 5
