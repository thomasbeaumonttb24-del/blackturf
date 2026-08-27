"""
Test intégration : db_writer rejette les cotes aberrantes (garde-fou intégrité).
"""
import pytest
from sqlalchemy import select

from db.models import Participation, CoteBookmaker
from scraper.base import CoteBookmakerScrape
from scraper.db_writer import save_cote_bookmaker, _historique_numeric


# ── _historique_numeric (pur, sans DB) ──────────────────────────────────────
def test_historique_numeric_valide():
    out = _historique_numeric({"distance": 2700, "nb_partants": 14, "position": 3})
    assert out == {"distance": 2700, "nb_partants": 14, "position_arrivee": 3}


def test_historique_numeric_aberrant_nettoye():
    # distance hors bornes → 0 (sentinelle, colonne NOT NULL) ; le reste → None.
    out = _historique_numeric({"distance": 99999, "nb_partants": 99, "position": 250})
    assert out == {"distance": 0, "nb_partants": None, "position_arrivee": None}


def test_historique_numeric_incident_conserve():
    # 99 = incident (tombé/disqualifié) → conservé, pas nettoyé.
    out = _historique_numeric({"distance": None, "nb_partants": None, "position": 99})
    assert out["position_arrivee"] == 99
    assert out["distance"] == 0  # None → 0 (NOT NULL)


async def _seed_participation(db, pid="pp1"):
    db.add(Participation(participation_id=pid, course_id="C1", cheval_id="A", numero=1))
    await db.commit()
    return pid


@pytest.mark.asyncio
async def test_cote_aberrante_non_stockee(db):
    pid = await _seed_participation(db)
    cote = CoteBookmakerScrape(course_id="C1", numero=1, nom="A",
                               source="winamax", cote=0.4)  # < 1.01 → aberrant
    await save_cote_bookmaker(db, cote, pid, "C1")
    await db.commit()

    rows = (await db.execute(select(CoteBookmaker))).scalars().all()
    assert rows == []   # rien stocké
    part = await db.get(Participation, pid)
    assert part.cote_winamax is None


@pytest.mark.asyncio
async def test_cote_plausible_stockee(db):
    pid = await _seed_participation(db, "pp2")
    cote = CoteBookmakerScrape(course_id="C1", numero=1, nom="A",
                               source="winamax", cote=4.5)
    await save_cote_bookmaker(db, cote, pid, "C1")
    await db.commit()

    rows = (await db.execute(select(CoteBookmaker))).scalars().all()
    assert len(rows) == 1
    assert rows[0].cote == 4.5
    part = await db.get(Participation, pid)
    assert part.cote_winamax == 4.5


# ── Colonnes dénormalisées des bookmakers ───────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,colonne",
    [("geny", "cote_geny"), ("bzh", "cote_bzh"),
     ("bet365", "cote_bet365"), ("ladbrokes", "cote_ladbrokes")],
)
async def test_cote_denormalisee_pour_toutes_les_sources(db, source, colonne):
    """Une source connue doit remplir SA colonne, pas seulement l'historique.

    Jusqu'au 27/08/2026 `col_map` ne listait que winamax/betclic/unibet/betfair :
    geny, bzh, bet365 et ladbrokes écrivaient la ligne d'historique et laissaient
    la colonne à NULL, sans un mot dans les journaux.
    """
    pid = await _seed_participation(db, f"pp_{source}")
    cote = CoteBookmakerScrape(course_id="C1", numero=1, nom="A",
                               source=source, cote=6.2)
    await save_cote_bookmaker(db, cote, pid, "C1")
    await db.commit()

    part = await db.get(Participation, pid)
    assert getattr(part, colonne) == 6.2


def test_upsert_pmu_n_ecrase_pas_cote_geny():
    """`save_course_to_db` ne doit jamais réécrire cote_geny inconditionnellement.

    La source PMU ne fournit PAS cette cote (seul geny.py la lit, et le daemon
    GenyBet l'écrit hors Docker) : la lister dans le `set_` du ON CONFLICT
    remettait la colonne à NULL à chaque re-scrape, par-dessus la valeur du
    daemon — ~250 écrasements par jour, zéro valeur retenue depuis 2025-09.
    Invariant vérifié sur l'AST : le `set_` ne peut contenir qu'une écriture
    CONDITIONNELLE (dépliage `**{...} if ... else {}`).
    """
    import ast
    import inspect
    from scraper import db_writer

    arbre = ast.parse(inspect.getsource(db_writer.save_course_to_db))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.keyword) or noeud.arg != "set_":
            continue
        if not isinstance(noeud.value, ast.Dict):
            continue
        cles = [c.value for c in noeud.value.keys
                if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        assert "cote_geny" not in cles, (
            "cote_geny réintroduit en écriture inconditionnelle dans le ON CONFLICT : "
            "il écraserait la cote du daemon GenyBet à chaque re-scrape PMU"
        )
