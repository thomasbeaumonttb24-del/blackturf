"""Une ligne d'historique déjà connue doit pouvoir se remplir, pas rester vide.

`ecart_longueurs` est resté NULL sur les 330 145 lignes de `historique_courses`
pendant des mois : le PMU renvoie un OBJET là où le writer attendait un nombre.
Le correctif du 2026-08-31 a rétabli l'extraction — mais la dédup faisait « on
saute » sur toute course déjà connue, donc une ligne ancienne restait vide POUR
TOUJOURS, alors que le PMU la renvoie chaque fois qu'un de ses partants recourt.
Mesure au lendemain : 432 lignes remplies sur 331 492, soit 0,13 %.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from db.models import Cheval, HistoriqueCourse
from scraper.db_writer import save_historique_pmu


def _course_pmu(ecart):
    """Une course passée telle que la renvoie /performances-detaillees."""
    return {
        "date_ms": 1_750_000_000_000, "hippodrome": "VINCENNES",
        "discipline": "Attelé", "distance": 2700, "nb_partants": 12,
        "position": 4, "ecart": ecart,
    }


async def _cheval(db, nom="TORNADE DU LOIR"):
    db.add(Cheval(cheval_id="ch-1", nom=nom))
    await db.commit()
    return nom


@pytest.mark.asyncio
async def test_une_ligne_existante_sans_ecart_est_comblee(db):
    nom = await _cheval(db)
    # Première passe : le PMU ne publiait pas la marge (chaîne incomplète → None).
    assert await save_historique_pmu(db, nom, [_course_pmu(None)]) == 1
    await db.commit()
    assert (await db.execute(text(
        "SELECT ecart_longueurs FROM historique_courses"))).scalar() is None

    # Seconde passe, la marge est calculable : la ligne se remplit AU LIEU d'être sautée.
    assert await save_historique_pmu(db, nom, [_course_pmu(2.05)]) == 0
    await db.commit()
    lignes = (await db.execute(text(
        "SELECT ecart_longueurs FROM historique_courses"))).all()
    assert len(lignes) == 1, "la dédup doit tenir : on enrichit, on ne duplique pas"
    assert lignes[0][0] == pytest.approx(2.05)


@pytest.mark.asyncio
async def test_une_valeur_deja_presente_n_est_jamais_ecrasee(db):
    """Une observation n'est pas un brouillon.

    Si la valeur en base et celle du jour divergent, c'est un signal à
    diagnostiquer, pas quelque chose à recouvrir en silence.
    """
    nom = await _cheval(db)
    await save_historique_pmu(db, nom, [_course_pmu(1.5)])
    await db.commit()
    await save_historique_pmu(db, nom, [_course_pmu(9.9)])
    await db.commit()
    assert (await db.execute(text(
        "SELECT ecart_longueurs FROM historique_courses"))).scalar() == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_sans_marge_exploitable_rien_n_est_ecrit(db):
    nom = await _cheval(db)
    await save_historique_pmu(db, nom, [_course_pmu(None)])
    await db.commit()
    await save_historique_pmu(db, nom, [_course_pmu(None)])
    await db.commit()
    lignes = (await db.execute(text(
        "SELECT ecart_longueurs FROM historique_courses"))).all()
    assert len(lignes) == 1 and lignes[0][0] is None
