"""Aperçu de l'analyse pour toute une journée (`/programme/apercu`).

Version en LOT de `/courses/{id}/apercu`, servie à la page programme — la
première page que voit un visiteur venu d'une recherche. Elle ne montrait que
des horaires : rien n'y disait qu'un modèle avait travaillé sur ces courses,
donc rien n'invitait à ouvrir une fiche.

L'invariant est le même que pour l'aperçu unitaire, et c'est lui que ce fichier
protège : des agrégats, jamais une identité de cheval.
"""
import uuid
from datetime import datetime, timezone, date, time as dtime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Hippodrome, Reunion, Course, Cheval, Participation, Prediction
from services.temps_courses import PARIS, jour_courses

pytestmark = pytest.mark.asyncio


def _apres_midi() -> datetime:
    """14 h heure de Paris, dans la journée de courses en cours — l'endpoint borne
    sa fenêtre sur le jour PARISIEN. Un `now + 3 h` lancé à 23 h basculerait sur le
    lendemain et rendrait le test dépendant de l'heure d'exécution."""
    return datetime.combine(jour_courses(), dtime(14, 0), tzinfo=PARIS).astimezone(timezone.utc)


async def _course_du_jour(db: AsyncSession, course_id: str, *, accord: bool) -> None:
    """Course notée du jour. `accord=False` → le n°1 du modèle n'est PAS le favori
    des cotes, le cas que la pastille met en avant."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Test Prog", code="TPG")
    db.add(hippo)
    db.add(Reunion(
        reunion_id=f"RP-{course_id}", date=date.today(),
        hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Test Prog", numero=1,
    ))
    db.add(Course(
        course_id=course_id, reunion_id=f"RP-{course_id}", numero=1, nom="Prix Programme",
        date_heure=_apres_midi(),
        hippodrome_nom="Test Prog", discipline="Attelé", distance=2700,
        nb_partants=3, statut="a_venir",
    ))

    # (numéro, cote, proba, rang) — en accord, le rang 1 porte AUSSI la plus petite cote.
    lot = ([(4, 2.1, 0.30, 1), (9, 6.0, 0.20, 2), (2, 55.0, 0.01, 3)] if accord
           else [(4, 9.0, 0.30, 1), (9, 2.2, 0.20, 2), (2, 55.0, 0.01, 3)])
    for numero, cote, proba, rang in lot:
        cheval_id = str(uuid.uuid4())
        db.add(Cheval(cheval_id=cheval_id, nom=f"CHEVAL SECRET {numero}", age=5, sexe="H"))
        part_id = str(uuid.uuid4())
        db.add(Participation(
            participation_id=part_id, course_id=course_id, cheval_id=cheval_id,
            numero=numero, cote_pmu=cote, non_partant=False,
        ))
        db.add(Prediction(
            prediction_id=str(uuid.uuid4()), participation_id=part_id, course_id=course_id,
            proba_top1=proba, proba_top3=min(0.99, proba * 2), rang_predit=rang,
            confidence_score=57.6,
        ))
    await db.commit()


async def test_apercu_programme_agrege_sans_identite(client: AsyncClient, db: AsyncSession):
    await _course_du_jour(db, "PRG1C1", accord=False)
    resp = await client.get("/api/v1/programme/apercu")
    assert resp.status_code == 200

    data = resp.json()
    fiche = data["courses"]["PRG1C1"]
    assert fiche["analysee"] is True
    assert fiche["nb_notes"] == 3
    assert fiche["nb_ecartes"] == 1          # le cheval à 1 % de chances
    assert fiche["confiance"] == 58
    assert fiche["accord_marche"] is False   # n°1 du modèle ≠ favori des cotes

    # AUCUN nom de cheval ne doit transiter : c'est un aperçu, pas le pronostic.
    assert "CHEVAL SECRET" not in resp.text.upper()


async def test_apercu_programme_detecte_l_accord_avec_le_marche(client: AsyncClient, db: AsyncSession):
    await _course_du_jour(db, "PRG2C1", accord=True)
    data = (await client.get("/api/v1/programme/apercu")).json()
    assert data["courses"]["PRG2C1"]["accord_marche"] is True


async def test_apercu_programme_ignore_les_courses_non_analysees(client: AsyncClient, db: AsyncSession):
    """Une course sans prédiction n'a pas de pastille — plutôt que d'afficher
    « analysée » sur une course que le modèle n'a jamais vue."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Sans Note", code="SNT")
    db.add(hippo)
    db.add(Reunion(
        reunion_id="RSN", date=date.today(), hippodrome_id=hippo.hippodrome_id,
        hippodrome_nom="Sans Note", numero=2,
    ))
    db.add(Course(
        course_id="PRG3C1", reunion_id="RSN", numero=1, nom="Prix Sans Note",
        date_heure=_apres_midi(),
        hippodrome_nom="Sans Note", discipline="Plat", distance=1600,
        nb_partants=0, statut="a_venir",
    ))
    await db.commit()

    data = (await client.get("/api/v1/programme/apercu")).json()
    assert "PRG3C1" not in data["courses"]



async def test_apercu_programme_compte_les_ecarts_de_prix(client: AsyncClient, db: AsyncSession):
    """Écart de prix = cote PMU ÷ cote juste (1/proba) − 1 ≥ 8 % : la règle de la
    tuile « Écarts de prix » de la fiche course. Seul le NOMBRE sort."""
    # accord=False : n°4 à 9,0 pour 30 % (juste 3,33 → +170 %) ; n°9 à 2,2 pour
    # 20 % (juste 5,0 → −56 %) ; n°2 à 55 pour 1 % (juste 100 → −45 %).
    await _course_du_jour(db, "PRG4C1", accord=False)
    data = (await client.get("/api/v1/programme/apercu")).json()
    assert data["courses"]["PRG4C1"]["nb_ecarts_prix"] == 1
    assert "CHEVAL SECRET" not in str(data).upper()


async def test_apercu_programme_ecart_sous_le_seuil_non_compte(client: AsyncClient, db: AsyncSession):
    """accord=True : n°4 à 2,1 pour 30 % (juste 3,33 → −37 %), n°9 à 6,0 pour 20 %
    (juste 5,0 → +20 %, compté), n°2 à 55 pour 1 % (juste 100 → −45 %)."""
    await _course_du_jour(db, "PRG5C1", accord=True)
    data = (await client.get("/api/v1/programme/apercu")).json()
    assert data["courses"]["PRG5C1"]["nb_ecarts_prix"] == 1



async def test_apercu_programme_ecart_au_seuil_de_la_fiche(client: AsyncClient, db: AsyncSession):
    """+7 % n'est pas un écart, +8 % en est un : même bord que la fiche course.
    Deux chevaux à 25 % (cote juste 4,00) : l'un à 4,28 (+7 %), l'autre à 4,33 (+8,25 %)."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Seuil", code="SEU")
    db.add(hippo)
    db.add(Reunion(reunion_id="RSEU", date=date.today(), hippodrome_id=hippo.hippodrome_id,
                   hippodrome_nom="Seuil", numero=3))
    db.add(Course(course_id="PRG6C1", reunion_id="RSEU", numero=1, nom="Prix du Seuil",
                  date_heure=_apres_midi(), hippodrome_nom="Seuil", discipline="Plat",
                  distance=2000, nb_partants=2, statut="a_venir"))
    for numero, cote, rang in [(1, 4.28, 1), (2, 4.33, 2)]:
        cheval_id, part_id = str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Cheval(cheval_id=cheval_id, nom=f"SEUIL {numero}", age=4, sexe="F"))
        db.add(Participation(participation_id=part_id, course_id="PRG6C1", cheval_id=cheval_id,
                             numero=numero, cote_pmu=cote, non_partant=False))
        db.add(Prediction(prediction_id=str(uuid.uuid4()), participation_id=part_id,
                          course_id="PRG6C1", proba_top1=0.25, proba_top3=0.5,
                          rang_predit=rang, confidence_score=50.0))
    await db.commit()
    data = (await client.get("/api/v1/programme/apercu")).json()
    assert data["courses"]["PRG6C1"]["nb_ecarts_prix"] == 1


async def test_seuil_ecart_identique_a_la_fiche_course():
    """Le programme et la fiche comptent les écarts avec le même seuil : si l'un
    bouge sans l'autre, les deux pages se contredisent à nouveau."""
    import re
    from pathlib import Path
    from api.routes.courses import ECART_PRIX_MIN
    fiche = Path(__file__).resolve().parents[2] / "frontend/src/components/courses/classement.tsx"
    m = re.search(r"const ECART_MEILLEUR_PRIX = ([0-9.]+);", fiche.read_text(encoding="utf-8"))
    assert m, "ECART_MEILLEUR_PRIX introuvable dans classement.tsx"
    assert float(m.group(1)) == ECART_PRIX_MIN
