"""Désaccord marché — commutateur de banc d'essai, INERTE en production.

Ce que la mesure du 2026-09-01 a établi (4 060 courses, cote FIGÉE au moment du
conseil, 1 € Simple Gagnant à plat sur le rang 1, les deux côtés dans la même
requête) :

    accord    (79,3 %, n=3 220)  modèle −16,67 %  marché −16,67 %  écart  +0,00 pt
    désaccord (20,7 %, n=  837)  modèle +11,45 %  marché −20,17 %  écart +31,65 pts

L'avantage est réel et robuste AU NIVEAU DU CLASSEMENT. Le rejeu A/B du moteur
(2 285 courses figées, deux bras dans le même processus) montre qu'il ne survit
PAS à la construction du plan : aucune variante ne gagne sur les trois profils,
et les gains apparents s'effondrent au retrait des 20 plus gros. Le commutateur
reste donc en place pour pouvoir re-mesurer quand le volume aura grandi — il ne
change rien tant que `BT_DESACCORD_MODE` n'est pas posé.

Ces tests verrouillent ce qui doit rester vrai : le défaut est INERTE, le signal
n'est pas inversé, une donnée absente n'est pas un signal, et la variante ne
déborde jamais sur les courses d'accord ni ne supprime le plan.
"""
from __future__ import annotations

import pytest

from services import mise_calculator as mc
from services.mise_calculator import _desaccord_marche, _mode_desaccord


def _preds(*triplets):
    """(numero, proba_top1, cote_pmu) — cote None = cheval non coté."""
    return [{"numero": n, "proba_top1": p, "cote_pmu": c} for n, p, c in triplets]


# --- Le défaut est INERTE ---------------------------------------------------

def test_sans_variable_d_environnement_rien_ne_change(monkeypatch):
    """C'est l'invariant le plus important : la mesure n'a PAS conclu, donc la
    production ne doit pas bouger. Un banc d'essai qui s'active tout seul est une
    modification non décidée."""
    monkeypatch.delenv("BT_DESACCORD_MODE", raising=False)
    assert _mode_desaccord() is None
    preds = _preds((1, 0.20, 2.0), (2, 0.40, 5.0))     # désaccord franc
    assert mc._selection_desaccord([{"type_pari": "Trio"}], [], preds, {}) is None


@pytest.mark.parametrize("valeur", ["", "oui", "1", "true", "SG", "sg-seul", "nimporte"])
def test_une_valeur_inconnue_ne_declenche_rien(monkeypatch, valeur):
    """Une faute de frappe dans la variable ne doit pas activer un mode au hasard,
    ni en activer un « par défaut » : elle doit être sans effet."""
    monkeypatch.setenv("BT_DESACCORD_MODE", valeur)
    assert _mode_desaccord() is None


# --- Sens du signal ---------------------------------------------------------

def test_accord_quand_le_rang_1_est_le_favori_du_marche():
    assert _desaccord_marche(_preds((1, 0.40, 2.0), (2, 0.20, 5.0))) is False


def test_desaccord_quand_le_modele_designe_un_autre_cheval():
    assert _desaccord_marche(_preds((1, 0.20, 2.0), (2, 0.40, 5.0))) is True


@pytest.mark.parametrize("preds", [
    [],
    _preds((1, 0.40, None)),
    _preds((1, 0.40, None), (2, 0.20, None)),
    _preds((1, 0.40, 2.0)),                      # une seule cote : pas de « favori »
    _preds((1, None, 2.0), (2, None, 5.0)),      # aucune proba
])
def test_une_donnee_absente_n_est_pas_un_signal(preds):
    """Une cote manquante ne prouve pas un accord. La lire comme tel ferait d'une
    panne de scraper une décision de jeu, en silence."""
    assert _desaccord_marche(preds) is None


def test_une_cote_invalide_ne_designe_pas_le_favori():
    """`cote_pmu <= 1.0` n'est pas une cote : aucun rapport ne rend moins que la mise.
    La retenir ferait de ce cheval le « favori » de toutes les courses où elle traîne."""
    preds = _preds((1, 0.10, 1.0), (2, 0.40, 3.0), (3, 0.20, 8.0))
    assert _desaccord_marche(preds) is False     # favori réel = n°2, qui est aussi rang 1


# --- Périmètre de la variante ----------------------------------------------

_SG = {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 2}]}
_TRIO = {"type_pari": "Trio", "chevaux": [{"numero": 1}, {"numero": 2}, {"numero": 3}]}
_DESACCORD = _preds((1, 0.20, 2.0), (2, 0.40, 5.0), (3, 0.10, 9.0))
_ACCORD = _preds((1, 0.40, 2.0), (2, 0.20, 5.0), (3, 0.10, 9.0))


def test_la_variante_ne_touche_jamais_les_courses_d_accord(monkeypatch):
    """Le rejeu A/B ne vaut que si le segment témoin est intact : si la variante
    débordait sur l'accord, l'écart mesuré ne serait plus imputable au désaccord."""
    for mode in ("sg_seul", "sg_prioritaire"):
        monkeypatch.setenv("BT_DESACCORD_MODE", mode)
        assert mc._selection_desaccord([_TRIO], [_SG, _TRIO], _ACCORD, {}) is None


def test_sg_seul_reduit_le_plan_au_simple_gagnant_du_rang_1(monkeypatch):
    monkeypatch.setenv("BT_DESACCORD_MODE", "sg_seul")
    out = mc._selection_desaccord([_TRIO], [_SG, _TRIO], _DESACCORD, {})
    assert [p["type_pari"] for p in out] == ["Simple Gagnant"]
    assert out[0]["chevaux"][0]["numero"] == 2


def test_sg_prioritaire_ajoute_en_tete_sans_rien_supprimer(monkeypatch):
    monkeypatch.setenv("BT_DESACCORD_MODE", "sg_prioritaire")
    out = mc._selection_desaccord([_TRIO], [_SG, _TRIO], _DESACCORD, {})
    assert [p["type_pari"] for p in out] == ["Simple Gagnant", "Trio"]


def test_sans_simple_gagnant_candidat_on_garde_la_selection_d_origine(monkeypatch):
    """Les gates du profil peuvent avoir écarté ce Simple Gagnant (hors tranche de
    rapport). On ne le ressuscite pas de force : la variante s'efface."""
    monkeypatch.setenv("BT_DESACCORD_MODE", "sg_seul")
    assert mc._selection_desaccord([_TRIO], [_TRIO], _DESACCORD, {}) is None


def test_la_variante_ne_rend_jamais_une_liste_vide(monkeypatch):
    """Contrat produit : un plan sur CHAQUE course. Un banc d'essai n'a pas le droit
    de supprimer le produit, même sur un cas limite."""
    for mode in ("sg_seul", "sg_prioritaire"):
        monkeypatch.setenv("BT_DESACCORD_MODE", mode)
        for selected, cands in (([_TRIO], [_SG, _TRIO]), ([_SG], [_SG]), ([], [_SG])):
            out = mc._selection_desaccord(selected, cands, _DESACCORD, {})
            assert out is None or len(out) >= 1


def test_la_selection_d_origine_n_est_pas_modifiee_sur_place(monkeypatch):
    """La variante doit rendre une NOUVELLE liste : muter `selected` ferait fuiter
    le bras B dans le bras A du rejeu, et les deux mesures porteraient sur le même
    état — un A/B qui se compare à lui-même."""
    monkeypatch.setenv("BT_DESACCORD_MODE", "sg_prioritaire")
    selected = [_TRIO]
    avant = list(selected)
    mc._selection_desaccord(selected, [_SG, _TRIO], _DESACCORD, {})
    assert selected == avant
