"""Fiche course : les associations jockey × entraîneur ne sont lues que pour le champ.

`_load_partants` chargeait TOUTES les paires de la saison à chaque fiche course
servie hors cache (vieilles courses : archives, robots), pour n'en garder qu'une
poignée. Le 12/10 au soir, GET /courses/06122025R5C5 est tombé en TimeoutError
pendant la saturation de la base par le recalcul du palmarès : la route doit au
moins ne pas ajouter de lecture inutile à une base déjà chargée.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.courses import _load_partants
from db.models import (
    AssociationJockeyEntraineur, Cheval, Course, Entraineur, Hippodrome, Jockey,
    Participation, Reunion,
)

pytestmark = pytest.mark.asyncio


async def _course_avec_paires(db: AsyncSession) -> tuple[str, str, str]:
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Deauville Test", code="DVT")
    db.add(hippo)
    db.add(Reunion(reunion_id="R5", date=date(2025, 12, 6), hippodrome_id=hippo.hippodrome_id,
                   hippodrome_nom="Deauville Test", numero=5))
    db.add(Course(course_id="06122025R5C5", reunion_id="R5", numero=5, nom="Prix Ancien",
                  date_heure=datetime(2025, 12, 6, 15, 0, tzinfo=timezone.utc),
                  hippodrome_nom="Deauville Test", discipline="Plat", distance=1600,
                  nb_partants=1, statut="termine"))
    jockey = Jockey(jockey_id=str(uuid.uuid4()), nom="J. Dupont")
    entraineur = Entraineur(entraineur_id=str(uuid.uuid4()), nom="E. Martin")
    autre_jockey = Jockey(jockey_id=str(uuid.uuid4()), nom="J. Ailleurs")
    autre_entraineur = Entraineur(entraineur_id=str(uuid.uuid4()), nom="E. Ailleurs")
    db.add_all([jockey, entraineur, autre_jockey, autre_entraineur])
    cheval = Cheval(cheval_id=str(uuid.uuid4()), nom="Vieux Cheval", age=5, sexe="H")
    db.add(cheval)
    db.add(Participation(participation_id=str(uuid.uuid4()), course_id="06122025R5C5",
                         cheval_id=cheval.cheval_id, numero=1, jockey_id=jockey.jockey_id,
                         entraineur_id=entraineur.entraineur_id, non_partant=False))
    saison = datetime.now().year
    # La paire du champ, plus deux paires hors champ (même jockey avec un autre
    # entraîneur, et une paire totalement étrangère).
    db.add_all([
        AssociationJockeyEntraineur(jockey_id=jockey.jockey_id, entraineur_id=entraineur.entraineur_id,
                                    saison=saison, taux_victoire=0.25, nb_courses=12),
        AssociationJockeyEntraineur(jockey_id=jockey.jockey_id,
                                    entraineur_id=autre_entraineur.entraineur_id,
                                    saison=saison, taux_victoire=0.5, nb_courses=4),
        AssociationJockeyEntraineur(jockey_id=autre_jockey.jockey_id,
                                    entraineur_id=autre_entraineur.entraineur_id,
                                    saison=saison, taux_victoire=0.1, nb_courses=30),
    ])
    await db.commit()
    return "06122025R5C5", jockey.jockey_id, entraineur.entraineur_id


async def test_association_du_champ_servie(db: AsyncSession):
    course_id, _, _ = await _course_avec_paires(db)
    partants = await _load_partants(course_id, db)
    assert len(partants) == 1
    assert partants[0].asso_jockey_entraineur_taux == 0.25
    assert partants[0].asso_jockey_entraineur_nb == 12


async def test_associations_lues_seulement_pour_le_champ(db: AsyncSession):
    course_id, _, _ = await _course_avec_paires(db)

    lignes_lues: list[int] = []
    sync_engine = db.bind.sync_engine if hasattr(db.bind, "sync_engine") else db.bind

    def _avant(conn, cursor, statement, parameters, context, executemany):
        if "associations_jockey_entraineur" in statement:
            context._bt_asso = True

    def _apres(conn, cursor, statement, parameters, context, executemany):
        if getattr(context, "_bt_asso", False):
            lignes_lues.append(1)
            # Le filtre sur les acteurs du champ doit figurer dans la requête.
            sql = statement.lower()
            assert "jockey_id in" in sql and "entraineur_id in" in sql, statement

    event.listen(sync_engine, "before_cursor_execute", _avant)
    event.listen(sync_engine, "after_cursor_execute", _apres)
    try:
        partants = await _load_partants(course_id, db)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _avant)
        event.remove(sync_engine, "after_cursor_execute", _apres)

    assert lignes_lues == [1], "une seule lecture des associations, filtrée sur le champ"
    assert partants[0].asso_jockey_entraineur_taux == 0.25
