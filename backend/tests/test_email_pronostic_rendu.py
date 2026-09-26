"""Rendu HTML du mail « pronostic gratuit » (services/email_pronostic.py).

Le mail reproduit la fiche course : on vérifie qu'il porte bien les mêmes
informations (casaques, chiffres formatés comme le site, lecture du prix) et
qu'aucune donnée absente ne casse le rendu.
"""
from datetime import datetime, timezone

from services import email_pronostic as ep


def _cheval(rang, numero, p1, cote=None, juste=None, **extra):
    return {
        "numero": numero, "nom": f"CHEVAL {numero}", "rang_predit": rang,
        "p1": p1, "p3": min(1.0, p1 * 2.5), "cote": cote, "cote_juste": juste,
        "niveau_value_bet": None, "ev_max": None, "signaux": [], **extra,
    }


COURSE = {
    "nom": "Prix d'Essai <b>", "numero_reunion": 1, "numero": 4, "discipline": "Attelé",
    "hippodrome_nom": "Vincennes", "distance": 2700, "nb_partants": 3,
    "date_heure": datetime(2026, 7, 1, 13, 15, tzinfo=timezone.utc), "allocation": 12_000_000,
    "terrain": "Bon", "statut": "a_venir", "est_quinte": True, "est_quarte": False, "est_tierce": False,
}


def _rendu(chevaux):
    return ep.rendu_html(COURSE, chevaux, "https://blackturf.fr/courses/X", "https://blackturf.fr/d?j=1",
                         calcule_a=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc), responsable="Jeu responsable")


def test_casaques_pmu_et_repli_neutre():
    html = _rendu([
        _cheval(1, 7, 0.4, 3.0, 2.5, casaque_url="http://pmu.test/casaques/7.png"),
        _cheval(2, 3, 0.2, 6.0, 5.0),
    ])
    # Casaque PMU servie en https, casaque neutre quand le PMU n'en fournit pas.
    assert 'src="https://pmu.test/casaques/7.png"' in html
    assert "/img/email/casaque-neutre.png" in html


def test_chiffres_formates_comme_le_site():
    html = _rendu([
        _cheval(1, 7, 0.4, 3.0, 2.5, niveau_value_bet=3, ev_max=0.21, musique="1a 2a (25) Da"),
        _cheval(2, 3, 0.004, 99.0, 999.0),
    ])
    assert "40&nbsp;%" in html and "&lt;&nbsp;1&nbsp;%" in html          # pct() du site
    assert "3,0" in html and "2,50" in html               # cote / cote juste
    assert "+20 %" in html                                # lecture du prix 3,0 vs 2,5
    assert "non chiffrable" in html                       # cote juste plafonnée
    assert "VALEUR +21 %" in html and "★★★" in html
    assert ">Da<" in html and "(25)" not in html          # musique en pastilles
    assert "15h15" in html                                # heure de Paris, pas UTC
    assert "Prix d&#x27;Essai &lt;b&gt;" in html          # échappement


def test_rendu_sans_cote_ni_signal():
    html = _rendu([_cheval(1, 1, 0.5)])
    assert "cotes indisponibles" in html
    assert "medaille-1.png" in html
