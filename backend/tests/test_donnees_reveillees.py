"""Données stockées mais jamais lues, branchées le 2026-09-24 : jockey de chaque
sortie, œillères portées, type de départ, jument pleine, cote de référence,
temps officiel. Chaque trait doit être NEUTRE quand la donnée manque."""
from datetime import date

import pytest

from ml.features import (
    mouvement_ouverture, oeilleres_portees, traits_depart, traits_jockey_historique,
    traits_oeilleres, vitesse_propre_depuis_temps,
)


def _h(pos, jockey=None, oeil=None, temps=None):
    """Tuple d'historique au format du batch (index 0 position, 16 jockey,
    17 équipement, 18 temps officiel, 19 course_id, -1 allocation)."""
    row = [pos, 2700, "bon", "VINCENNES", date(2026, 8, 1), 12, 5.0, "Attelé", 0,
           None, None, None, None, None, None, None,
           jockey, ({"oeilleres": oeil} if oeil is not None else None), temps, None, 0.0]
    return tuple(row)


def test_jockey_du_jour_reconnu_malgre_casse_et_ponctuation():
    hist = [_h(1, "M. Abrivard"), _h(2, "M. ABRIVARD"), _h(9, "E. RAFFIN"),
            _h(99, "E. RAFFIN"), _h(3, "X")]
    t = traits_jockey_historique(hist, "m abrivard", 12)
    assert t["jockey_hist_nb"] == 2
    assert t["jockey_hist_delta"] > 0.3
    assert t["jockey_hist_inedit"] == 0.0


def test_jockey_jamais_associe_et_donnee_absente():
    hist = [_h(1, "E. RAFFIN"), _h(2, "E. RAFFIN"), _h(3, "E. RAFFIN")]
    assert traits_jockey_historique(hist, "M. ABRIVARD", 12)["jockey_hist_inedit"] == 1.0
    vide = traits_jockey_historique([_h(1), _h(2)], "M. ABRIVARD", 12)
    assert vide == {"jockey_hist_nb": 0, "jockey_hist_score": 0.0,
                    "jockey_hist_delta": 0.0, "jockey_hist_inedit": 0.0}


@pytest.mark.parametrize("raw,attendu", [
    ("SANS_OEILLERES", False), ("OEILLERES_AUSTRALIENNES", True), ("Standard", True),
    ("Sans", False), (None, None), ("", None), (True, True)])
def test_libelles_oeilleres(raw, attendu):
    assert oeilleres_portees(raw) is attendu if attendu is not None else oeilleres_portees(raw) is None


def test_oeilleres_meme_configuration():
    hist = [_h(1, oeil=True), _h(2, oeil=True), _h(9, oeil=False), _h(99, oeil=False)]
    t = traits_oeilleres(hist, "OEILLERES_AUSTRALIENNES", 12)
    assert t["oeilleres_jour"] == 1.0 and t["oeilleres_meme_config_nb"] == 2
    assert t["oeilleres_delta"] > 0
    inconnu = traits_oeilleres(hist, None, 12)
    assert inconnu == {"oeilleres_jour": -1.0, "oeilleres_meme_config_nb": 0,
                       "oeilleres_delta": 0.0}


def test_depart_volte_seulement_au_trot():
    assert traits_depart("VOLTE", 0.4, True) == {
        "depart_volte": 1.0, "depart_autostart": 0.0, "risque_galop_volte": 0.4}
    assert traits_depart("AUTOS", 0.4, True)["depart_autostart"] == 1.0
    assert traits_depart("VOLTE", 0.4, False)["depart_volte"] == 0.0
    assert traits_depart(None, 0.4, True)["risque_galop_volte"] == 0.0


def test_mouvement_depuis_la_cote_de_reference():
    assert mouvement_ouverture(12, 6) == pytest.approx(0.6931, abs=1e-3)
    assert mouvement_ouverture(5, 10) < 0
    assert mouvement_ouverture(None, 6) == 0.0 and mouvement_ouverture(12, None) == 0.0
    assert mouvement_ouverture(1000, 1.1) == 1.5          # borné


def test_vitesse_depuis_le_temps_officiel():
    assert vitesse_propre_depuis_temps("125.5", 2000) == pytest.approx(15.94, abs=0.01)
    assert vitesse_propre_depuis_temps("2'05\"5", 2000) == pytest.approx(15.94, abs=0.01)
    assert vitesse_propre_depuis_temps(None, 2000) is None
    assert vitesse_propre_depuis_temps("abc", 2000) is None


def test_mouvement_ouverture_est_une_colonne_de_marche():
    from ml.models import COLONNES_MARCHE, META_COLS
    from ml.modele_technique import COLONNES_PARIEURS
    assert "mouvement_ouverture" in COLONNES_MARCHE and "mouvement_ouverture" in COLONNES_PARIEURS
    assert "elo_vs_champ" not in META_COLS            # réintégré au modèle
