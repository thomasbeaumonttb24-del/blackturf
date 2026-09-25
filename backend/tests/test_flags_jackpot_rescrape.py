"""Un re-scrape sans liste de paris ne doit pas effacer la désignation Quinté+.

Constaté le 2026-09-25 : /quinte-du-jour annonçait « Le support du Quinté+ n'est pas
encore publié » en pleine journée. La page cherche la course `est_quinte` dans le
programme ; or chaque cycle PMU réécrivait les drapeaux jackpot à partir de
`paris[].codePari`. Un payload où `paris` manquait (ou était vide) donnait
`est_quinte=False`, qui écrasait la valeur correcte en base.
"""
from scraper.base import CourseScrape
from scraper.db_writer import champs_maj_course

DRAPEAUX = ("est_quinte", "est_quarte", "est_tierce", "est_2sur4", "paris_disponibles")


def _course(**kw) -> CourseScrape:
    return CourseScrape(
        reunion_id="1", course_id="25092026R1C3", hippodrome="HIPPODROME DE PARISLONGCHAMP",
        date_heure="1790343300000", discipline="Plat", distance=2100, nb_partants=16,
        partants=[], **kw,
    )


def test_payload_sans_paris_ne_touche_pas_aux_drapeaux():
    for paris in (None, []):
        champs = champs_maj_course(_course(paris_disponibles=paris), None, None)
        assert not any(k in champs for k in DRAPEAUX)


def test_payload_avec_paris_met_a_jour_les_drapeaux():
    c = _course(
        est_quinte=True, est_quarte=True, est_tierce=True,
        paris_disponibles=["E_QUARTE_PLUS", "E_QUINTE_PLUS", "E_SIMPLE_GAGNANT", "E_TIERCE"],
    )
    champs = champs_maj_course(c, None, None)
    assert champs["est_quinte"] is True
    assert champs["paris_disponibles"] == c.paris_disponibles


def test_retrait_reel_d_un_pari_reste_pris_en_compte():
    """Liste présente mais sans Quinté+ : c'est une vraie information, on l'écrit."""
    champs = champs_maj_course(_course(paris_disponibles=["E_SIMPLE_GAGNANT"]), None, None)
    assert champs["est_quinte"] is False
