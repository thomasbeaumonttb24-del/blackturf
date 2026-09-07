"""Une source de cotes jugée non fiable ne peut pas créer un pari de valeur.

Constat du 2026-09-07 : `services.data_quality` déclarait Geny non fiable
(corrélation 0,15 avec le PMU sur les courses étrangères), l'affichage
l'excluait, mais le détecteur l'utilisait toujours — 17 % des paris de valeur
de l'été n'existaient que par cette cote.
"""
import ml.valuebets as vbmod
from ml.valuebets import detect_value_bet


def test_geny_seul_ne_cree_pas_de_pari():
    # À la cote PMU (2,5) un cheval à 30 % n'a aucune valeur ; à la cote Geny
    # (9,0, fantaisiste) il en aurait +170 %. Le détecteur doit dire : rien.
    assert detect_value_bet(0.30, cote_pmu=2.5, cote_geny=9.0) is None


def test_meilleure_source_n_est_jamais_une_source_non_fiable():
    vb = detect_value_bet(0.30, cote_pmu=4.5, cote_geny=9.0)
    assert vb is not None
    assert vb["meilleure_source"] == "pmu"
    assert vb["ev_geny"] is None
    assert vb["nb_sources"] == 1


def test_la_liste_fait_foi(monkeypatch):
    # Même appel, liste vidée : Geny redevient une source et fabrique le pari.
    import services.data_quality as dq
    monkeypatch.setattr(dq, "SOURCES_COTES_NON_FIABLES", ())
    vb = detect_value_bet(0.30, cote_pmu=2.5, cote_geny=9.0)
    assert vb is not None and vb["meilleure_source"] == "geny"


def test_helper_sans_liste_ne_retire_rien(monkeypatch):
    import builtins
    vrai_import = builtins.__import__

    def _import(name, *a, **k):
        if name == "services.data_quality":
            raise ImportError("absent en rejeu")
        return vrai_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _import)
    cotes = {"pmu": 3.0, "geny": 5.0}
    assert vbmod._sans_sources_non_fiables(cotes) == cotes
