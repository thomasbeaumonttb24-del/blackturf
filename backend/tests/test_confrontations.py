"""
Tests confrontations directes — head-to-head depuis l'historique.
"""
from datetime import date

import pytest

from db.models import Cheval, Participation, HistoriqueCourse
from services.confrontations import compute_confrontations, _norm_hippo


def _hist(cheval_id, d, hippo, pos, ecart=None, dist=2000, disc="Plat"):
    return HistoriqueCourse(
        cheval_id=cheval_id,
        date_course=d,
        hippodrome=hippo,
        discipline=disc,
        distance=dist,
        position_arrivee=pos,
        ecart_longueurs=ecart,
    )


async def _seed_field(db, course_id="R1C1"):
    """3 partants A/B/C avec un historique de duels connus."""
    db.add_all([
        Cheval(cheval_id="A", nom="ALPHA"),
        Cheval(cheval_id="B", nom="BRAVO"),
        Cheval(cheval_id="C", nom="CHARLIE"),
    ])
    for cid, num in [("A", 1), ("B", 2), ("C", 3)]:
        db.add(Participation(
            participation_id=f"p-{cid}", course_id=course_id,
            cheval_id=cid, numero=num,
        ))
    # Course passée 1 : A(1) bat B(2) — et C(4) présent, A bat C, B bat C
    db.add_all([
        _hist("A", date(2026, 1, 10), "Vincennes", 1, ecart=0.0),
        _hist("B", date(2026, 1, 10), "Vincennes", 2, ecart=1.5),
        _hist("C", date(2026, 1, 10), "Vincennes", 4, ecart=6.0),
    ])
    # Course passée 2 : B(1) bat A(3) — accent + casse différents → doit matcher
    db.add_all([
        _hist("B", date(2026, 2, 20), "VINCÉNNES", 1, ecart=0.0),
        _hist("A", date(2026, 2, 20), "VINCÉNNES", 3, ecart=2.0),
    ])
    # Course passée 3 : A présent mais incident (disq.) → pas de duel valide avec B
    db.add_all([
        _hist("A", date(2026, 3, 5), "Enghien", 99),
        _hist("B", date(2026, 3, 5), "Enghien", 1),
    ])
    await db.commit()
    return course_id


def test_norm_hippo_strips_accents_and_case():
    assert _norm_hippo("VINCÉNNES") == _norm_hippo("vincennes")
    assert _norm_hippo("  Paris-Longchamp ") == "paris-longchamp"
    assert _norm_hippo(None) == ""


@pytest.mark.asyncio
async def test_confrontations_basic(db):
    course_id = await _seed_field(db)
    res = await compute_confrontations(db, course_id)

    assert res["nb_partants"] == 3
    paires = {(p["a_nom"], p["b_nom"]): p for p in res["paires"]}

    # A vs B : 2 rencontres valides (incident exclu), 1 victoire chacun
    ab = paires.get(("ALPHA", "BRAVO"))
    assert ab is not None
    assert ab["nb_rencontres"] == 2
    assert ab["a_victoires"] == 1
    assert ab["b_victoires"] == 1
    # Dernière rencontre = 2026-02-20, B(1) devant A(3)
    assert ab["derniere_rencontre"]["date"] == date(2026, 2, 20)


@pytest.mark.asyncio
async def test_confrontations_incident_excluded(db):
    course_id = await _seed_field(db)
    res = await compute_confrontations(db, course_id)
    ab = next(p for p in res["paires"] if {p["a_nom"], p["b_nom"]} == {"ALPHA", "BRAVO"})
    # 3e course (Enghien) ignorée car A en incident → 2 et non 3
    assert ab["nb_rencontres"] == 2


@pytest.mark.asyncio
async def test_confrontations_bilan_par_cheval(db):
    course_id = await _seed_field(db)
    res = await compute_confrontations(db, course_id)
    par = {c["nom"]: c for c in res["par_cheval"]}

    # C a perdu contre A et B (course 1), n'a jamais gagné
    assert par["CHARLIE"]["victoires"] == 0
    assert par["CHARLIE"]["defaites"] == 2
    assert par["CHARLIE"]["bilan"] == "0-2"
    assert par["CHARLIE"]["nb_adversaires_connus"] == 2
    assert par["CHARLIE"]["top_victime"] is None
    assert par["CHARLIE"]["bete_noire"] is not None


@pytest.mark.asyncio
async def test_confrontations_no_field(db):
    res = await compute_confrontations(db, "INEXISTANT")
    assert res["nb_partants"] == 0
    assert res["paires"] == []
    assert res["par_cheval"] == []
