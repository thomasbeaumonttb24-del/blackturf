"""Règle de visibilité des paris de valeur — une seule, partagée.

Ce que ces tests verrouillent : la fiche course (`visible`) et les requêtes
listant les paris (`filtres_sql`) appliquent la MÊME règle, délai Standard
compris. Le 2026-09-07 la fiche recalculait ses propres paris sans délai et une
page pouvait montrer un pari que l'autre taisait.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.valuebets_visibilite import (
    DELAI_STANDARD, cutoff_detection, filtres_sql, visible,
)

NOW = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)


def _vb(actif=True, il_y_a=timedelta(0), naif=False):
    d = NOW - il_y_a
    if naif:
        d = d.replace(tzinfo=None)
    return SimpleNamespace(actif=actif, detecte_a=d)


def test_plans_en_direct_sans_delai():
    for plan in ("expert", "pro", "starter", None, "admin"):
        assert cutoff_detection(plan, NOW) is None
        assert visible(_vb(), plan, NOW) is True


def test_standard_attend_quinze_minutes():
    assert cutoff_detection("standard", NOW) == NOW - DELAI_STANDARD
    assert visible(_vb(il_y_a=timedelta(minutes=1)), "standard", NOW) is False
    assert visible(_vb(il_y_a=timedelta(minutes=14)), "standard", NOW) is False
    assert visible(_vb(il_y_a=timedelta(minutes=15)), "standard", NOW) is True
    assert visible(_vb(il_y_a=timedelta(minutes=40)), "standard", NOW) is True


def test_inactif_jamais_visible():
    assert visible(_vb(actif=False, il_y_a=timedelta(hours=1)), "expert", NOW) is False
    assert visible(_vb(actif=False, il_y_a=timedelta(hours=1)), "standard", NOW) is False


def test_horodatage_naif_lu_comme_utc():
    # Le cycle écrit `datetime.now()` sans fuseau ; SQLite le relit naïf. Une
    # comparaison naïf/aware lèverait TypeError et vider la fiche en silence.
    assert visible(_vb(il_y_a=timedelta(minutes=1), naif=True), "standard", NOW) is False
    assert visible(_vb(il_y_a=timedelta(minutes=30), naif=True), "standard", NOW) is True


def test_sans_horodatage_le_delai_ne_peut_pas_etre_prouve():
    vb = SimpleNamespace(actif=True, detecte_a=None)
    assert visible(vb, "standard", NOW) is False
    assert visible(vb, "expert", NOW) is True


def test_filtres_sql_meme_regle_que_visible():
    # 3 conditions pour un plan en direct, 4 pour Standard (le délai).
    assert len(filtres_sql("expert", NOW)) == 3
    assert len(filtres_sql(None, NOW)) == 3
    conds = filtres_sql("standard", NOW)
    assert len(conds) == 4
    assert "detecte_a" in str(conds[-1])
