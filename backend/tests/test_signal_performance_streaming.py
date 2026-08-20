"""Les agrégats appris la nuit lisent `features_ml` EN ENTIER.

Ces trois fonctions (ROI par signal, ROI par signal × profil, moniteur d'edge)
n'ont aucune borne temporelle : elles ramènent les 212 721 lignes de
`features_ml`, chacune portant un JSONB de 173 clés. Chargées d'un bloc via
`fetchall()`, elles pesaient ~4 Gio sur un hôte de 7,6 Gio partagés — c'est là
que le worker se trouvait quand l'OOM killer l'a désigné le 20/08/2026, et non
dans l'entraînement (1,5 Gio de pic mesuré).

Elles lisent désormais par curseur serveur. Ces tests verrouillent les deux
propriétés qui comptent :
  1. le résultat est INCHANGÉ (une optimisation mémoire qui déplace un ROI
     appris déplacerait la sélection des value bets en production) ;
  2. aucune de ces fonctions ne matérialise le résultat complet — sinon le
     curseur ne sert à rien et l'OOM revient au premier gros volume.
"""
import asyncio

import pytest

from ml.edge_monitor import compute_edge_monitor
from ml.signal_performance import (
    K_SHRINK, compute_signal_performance, compute_signal_performance_by_profile,
)


class _FauxResultat:
    """Résultat en flux qui REFUSE d'être matérialisé.

    `partitions()` ne rend jamais plus de `taille` lignes d'un coup et compte la
    plus grosse tranche vue vivante : un appelant qui reviendrait à un
    `fetchall()` déguisé (tout accumuler avant d'agréger) serait détecté.
    """

    def __init__(self, lignes, taille_max_vue):
        self._lignes = lignes
        self._taille_max_vue = taille_max_vue

    async def partitions(self, taille):
        self._taille_max_vue.append(taille)
        for i in range(0, len(self._lignes), taille):
            yield self._lignes[i:i + taille]


class _FausseSession:
    def __init__(self, lignes):
        self._lignes = lignes
        self.tailles = []
        self.execute_appele = False

    async def stream(self, *_a, **_k):
        return _FauxResultat(self._lignes, self.tailles)

    async def execute(self, *_a, **_k):
        self.execute_appele = True
        raise AssertionError(
            "requête exécutée d'un bloc : le résultat complet revient en RAM"
        )


def _ligne(features, cote, win, top3=None):
    return (features, cote, win) if top3 is None else (features, cote, win, top3)


# `elo_vs_moyenne > 50` déclenche `elo_superieur` et lui seul parmi les signaux
# sensibles à cette clé ; tous les autres restent sur leur valeur par défaut.
FEAT_ELO_FORT = {"elo_vs_moyenne": 120.0}
FEAT_NEUTRE = {"elo_vs_moyenne": 0.0}


def test_roi_par_signal_identique_au_calcul_a_la_main():
    """Trois paris à 1 € sur `elo_superieur`, un gagnant à 4.0."""
    lignes = [
        _ligne(FEAT_ELO_FORT, 4.0, 1),
        _ligne(FEAT_ELO_FORT, 3.0, 0),
        _ligne(FEAT_ELO_FORT, 2.0, 0),
        _ligne(FEAT_NEUTRE, 5.0, 1),   # ne déclenche pas le signal
    ]
    session = _FausseSession(lignes)
    out = asyncio.run(compute_signal_performance(session))

    sig = out["signals"]["elo_superieur"]
    assert sig["n"] == 3
    assert sig["win_rate"] == round(1 / 3, 3)
    assert sig["roi"] == round((4.0 - 3.0) / 3.0, 3)
    assert sig["roi_shrunk"] == round((4.0 - 3.0) / (3.0 + K_SHRINK), 3)
    # n_total comptait `len(rows)` : il doit rester le nombre de lignes LUES,
    # pas le nombre de lignes retenues par un signal.
    assert out["n_total"] == 4


def test_signal_absent_reste_neutre():
    out = asyncio.run(compute_signal_performance(_FausseSession(
        [_ligne(FEAT_NEUTRE, 3.0, 0)])))
    assert out["signals"]["elo_superieur"] == {
        "n": 0, "win_rate": None, "roi": None, "roi_shrunk": 0.0, "multiplier": 1.0}


def test_roi_par_profil_identique_au_calcul_a_la_main():
    """Le profil agressif ne mise QUE sur les cotes >= 6 : deux lignes sur trois
    doivent être ignorées pour lui, mais comptées pour l'équilibré."""
    lignes = [
        _ligne(FEAT_ELO_FORT, 8.0, 1, 1),
        _ligne(FEAT_ELO_FORT, 3.0, 0, 1),
        _ligne(FEAT_ELO_FORT, 2.0, 0, 0),
    ]
    out = asyncio.run(compute_signal_performance_by_profile(_FausseSession(lignes)))

    agressif = out["profils"]["agressif"]["elo_superieur"]
    equilibre = out["profils"]["equilibre"]["elo_superieur"]
    assert agressif["n"] == 1          # seule la ligne à 8.0 est jouée
    assert equilibre["n"] == 3
    assert out["n_total"] == 3


def test_les_agregats_ne_materialisent_jamais_tout_le_resultat():
    """Garde-fou anti-régression : c'est la matérialisation complète qui a coûté
    la nuit d'apprentissage, pas le volume de données en soi."""
    for fn, lignes in (
        (compute_signal_performance, [_ligne(FEAT_ELO_FORT, 2.0, 0)] * 5000),
        (compute_signal_performance_by_profile, [_ligne(FEAT_ELO_FORT, 2.0, 0, 0)] * 5000),
    ):
        session = _FausseSession(lignes)
        asyncio.run(fn(session))
        assert not session.execute_appele
        assert session.tailles, f"{fn.__name__} ne lit pas par partitions"
        assert max(session.tailles) <= 5000, (
            f"{fn.__name__} demande une partition aussi grande que le résultat")


def test_edge_monitor_ne_garde_pas_les_features_brutes():
    """`compute_edge_monitor` a besoin des lignes (découpage train/test temporel)
    mais JAMAIS des features autrement qu'à travers les prédicats : il ne doit
    donc conserver que les booléens, pas les dicts de 173 clés."""
    lignes = [_ligne(dict(FEAT_ELO_FORT), 2.0, i % 2) for i in range(600)]
    session = _FausseSession(lignes)
    out = asyncio.run(compute_edge_monitor(session))

    assert out["n_total"] == 600
    assert not out.get("insufficient")
    # Les dicts fournis ne doivent être référencés nulle part dans le résultat.
    assert "features" not in out


def test_edge_monitor_echantillon_trop_petit():
    lignes = [_ligne(FEAT_NEUTRE, 2.0, 0) for _ in range(10)]
    out = asyncio.run(compute_edge_monitor(_FausseSession(lignes)))
    assert out == {"n_total": 10, "insufficient": True}
