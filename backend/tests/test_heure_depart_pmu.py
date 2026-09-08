"""L'heure de départ affichée doit être celle du PMU, y compris quand il la décale.

Le PMU repousse les départs en cours de journée : une réunion qui prend du retard
décale toutes ses courses suivantes. Constaté le 2026-09-08 vers 19 h — l'écart
grandissait course après course, sans un mot dans les journaux :

    R4C6 Vincennes   BlackTurf 19:27   pmu.fr 19h37   (+10 min)
    R4C7 Vincennes   BlackTurf 19:59   pmu.fr 20h10   (+11 min)
    R5C8 Mons        BlackTurf 22:15   pmu.fr 22h23   (+8 min)

Cause : `date_heure` figurait dans le INSERT de `save_course_to_db` mais PAS dans sa
clause ON CONFLICT. L'heure du tout PREMIER scrape de la journée ne bougeait donc
plus jamais, quels que soient les cycles PMU suivants.
"""
from datetime import datetime, timezone

import pytest

from scraper.base import CourseScrape
from scraper.db_writer import _parse_datetime, _parse_datetime_strict, champs_maj_course


def _course(date_heure="1788889020000") -> CourseScrape:
    return CourseScrape(
        reunion_id="4", course_id="08092026R4C6", hippodrome="HIPPODROME DE PARIS-VINCENNES",
        date_heure=date_heure, discipline="Attelé", distance=2175, nb_partants=10, partants=[],
    )


# ── Lecture de l'heure PMU ──────────────────────────────────────────────────
def test_epoch_ms_lu_en_utc():
    """`heureDepart` PMU est un epoch ms — donc un INSTANT, pas une heure murale.

    `datetime.fromtimestamp(ms/1000)` sans tzinfo rendait « l'heure locale du
    conteneur » : juste par accident, tant que le conteneur tourne en UTC.
    """
    dt = _parse_datetime_strict("1788889020000")
    assert dt == datetime(2026, 9, 8, 17, 37, tzinfo=timezone.utc)  # 19h37 à Paris
    assert dt.tzinfo is not None


def test_iso_naif_considere_utc():
    assert _parse_datetime_strict("2026-09-08T17:37:00") == datetime(2026, 9, 8, 17, 37, tzinfo=timezone.utc)


@pytest.mark.parametrize("valeur", ["", None, "n/a", "PROGRAMMEE", 0])
def test_valeur_illisible_rend_none(valeur):
    """Version stricte : PAS de repli sur « maintenant ».

    Un repli silencieux sur l'instant du scrape, en UPDATE, écraserait une heure de
    départ correcte par l'heure à laquelle le scraper est passé.
    """
    assert _parse_datetime_strict(valeur) is None


def test_repli_seulement_pour_l_insert():
    """`_parse_datetime` (repli « maintenant ») reste réservé aux écritures NOT NULL."""
    assert _parse_datetime("").tzinfo is not None


# ── Le champ doit être RÉÉCRIT à chaque re-scrape ───────────────────────────
def test_heure_depart_rafraichie_a_chaque_scrape():
    """LA régression à empêcher : sans `date_heure` ici, l'heure fige au 1er scrape."""
    heure = _parse_datetime_strict("1788889020000")
    champs = champs_maj_course(_course(), heure, None)
    assert champs["date_heure"] == heure


def test_heure_illisible_ne_touche_pas_la_base():
    """Payload PMU cassé → on garde l'heure déjà connue, on ne la remplace pas."""
    champs = champs_maj_course(_course(date_heure=""), None, None)
    assert "date_heure" not in champs


def test_annulation_conditionnelle_preservee():
    """Un re-scrape ne ressuscite jamais une course finie : `statut` reste conditionnel."""
    assert "statut" not in champs_maj_course(_course(), _parse_datetime_strict("1788889020000"), None)
    assert champs_maj_course(_course(), None, "annule")["statut"] == "annule"


def test_upsert_course_utilise_bien_ces_champs():
    """Le garde-fou ne vaut que si l'upsert appelle RÉELLEMENT `champs_maj_course`."""
    import inspect

    from scraper import db_writer

    src = inspect.getsource(db_writer.save_course_to_db)
    assert "set_=champs_maj_course(" in src
