"""Code d'hippodrome unique et upsert par NOM (audit 2026-09-28).

Le code tronqué à 20 caractères faisait partager `HIPPODROME_DE_SAINT_` à Saint-Brieuc,
Saint-Malo et Saint-Galmier : chaque import renommait la ligne, et 211 courses d'un an
n'avaient plus d'hippodrome (donc plus de pays) pour les jointures faites après coup.
"""
from scraper.db_writer import CODE_HIPPODROME_MAX, code_hippodrome


def test_nom_court_code_inchange():
    assert code_hippodrome("PAU") == "PAU"
    assert code_hippodrome("HIPPODROME DE VICHY") == "HIPPODROME_DE_VICHY"


def test_noms_longs_codes_distincts_et_bornes():
    noms = ["HIPPODROME DE SAINT BRIEUC", "HIPPODROME DE SAINT MALO",
            "HIPPODROME DE SAINT GALMIER", "HIPPODROME DE MUNICH-RIEM ALL",
            "HIPPODROME DE MUNICH-DAGLFING ALL", "HIPPODROME DE HAMBOURG HORN ALL",
            "HIPPODROME DE HAMBOURG ALL"]
    codes = [code_hippodrome(n) for n in noms]
    assert len(set(codes)) == len(codes)
    assert all(len(c) <= CODE_HIPPODROME_MAX for c in codes)


def test_code_stable():
    assert code_hippodrome("HIPPODROME DE SAINT MALO") == code_hippodrome("HIPPODROME DE SAINT MALO")


def test_upsert_se_regle_sur_le_nom_et_ne_perd_pas_le_pays():
    import inspect
    from scraper import db_writer
    src = inspect.getsource(db_writer.upsert_hippodrome)
    assert 'index_elements=["nom"]' in src
    assert 'func.nullif(stmt.excluded.pays, "UNK")' in src
