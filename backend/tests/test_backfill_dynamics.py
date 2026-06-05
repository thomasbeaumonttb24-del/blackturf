"""
Test backfill dynamique (Phase 1) — rétro-remplissage réduction km + accélération.
"""
from datetime import date

import pytest

from db.models import HistoriqueCourse, Participation, TempsPassage
from ml.backfill_dynamics import backfill_historique_dynamics


@pytest.mark.asyncio
async def test_backfill_remplit_reduction_et_acceleration(db):
    # H1 : course interne avec temps + dernier 400m → réduction + accélération
    db.add(HistoriqueCourse(
        historique_id="h1", cheval_id="A", course_id="RC1",
        date_course=date(2026, 1, 10), hippodrome="Vincennes", discipline="Attelé",
        distance=2700, temps_officiel="3'24\"",
    ))
    db.add(Participation(participation_id="p1", course_id="RC1", cheval_id="A", numero=1))
    db.add(TempsPassage(course_id="RC1", numero=1, nom_cheval="A",
                        passage_dernier_400m="28\"5"))
    # H2 : course externe (course_id NULL) avec temps → réduction seulement
    db.add(HistoriqueCourse(
        historique_id="h2", cheval_id="B", course_id=None,
        date_course=date(2026, 1, 5), hippodrome="UK", discipline="Plat",
        distance=2000, temps_officiel="2'05\"",
    ))
    # H3 : pas de temps officiel → non remplissable, reste NULL
    db.add(HistoriqueCourse(
        historique_id="h3", cheval_id="C", course_id=None,
        date_course=date(2026, 1, 1), hippodrome="X", discipline="Plat",
        distance=2000, temps_officiel=None,
    ))
    await db.commit()

    stats = await backfill_historique_dynamics(db, batch_size=10)

    assert stats["rows_scannees"] == 3
    assert stats["reduction_remplie"] == 2
    assert stats["acceleration_remplie"] == 1

    h1 = await db.get(HistoriqueCourse, "h1")
    h2 = await db.get(HistoriqueCourse, "h2")
    h3 = await db.get(HistoriqueCourse, "h3")
    assert h1.reduction_km == pytest.approx(75.56, abs=0.01)
    assert h1.acceleration_label == "accelere"
    assert h2.reduction_km == pytest.approx(62.5, abs=0.01)
    assert h2.acceleration_label is None      # pas de course interne
    assert h3.reduction_km is None            # non remplissable, jamais inventé


@pytest.mark.asyncio
async def test_backfill_idempotent_et_pas_de_boucle(db):
    db.add(HistoriqueCourse(
        historique_id="z1", cheval_id="A", course_id=None,
        date_course=date(2026, 1, 1), hippodrome="X", discipline="Plat",
        distance=2000, temps_officiel=None,   # jamais remplissable
    ))
    await db.commit()
    # Ne doit pas boucler à l'infini sur la ligne non remplissable.
    stats = await backfill_historique_dynamics(db, batch_size=10)
    assert stats["rows_scannees"] == 1
    assert stats["reduction_remplie"] == 0
    # 2e passage : rien de neuf
    stats2 = await backfill_historique_dynamics(db, batch_size=10)
    assert stats2["reduction_remplie"] == 0
