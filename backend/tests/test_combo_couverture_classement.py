"""Couverture du HAUT DU CLASSEMENT dans le catalogue de combinaisons.

Régression protégée — Vincennes 08/09/2026 R6C3 (7 partants réels). Le profil risqué,
vendu « ×10 minimum », a servi un Simple Gagnant à ×3,2. Cause : les combinaisons
n'étaient fabriquées qu'à partir des 3 premiers du modèle, de l'outsider à valeur et
des chevaux à cote ≥ 12. Le n°3, 4e au classement mais coté 6,6, n'entrait donc dans
AUCUN couplé ni AUCUN trio. Les paris qui respectaient À LA FOIS la tranche du profil
et son plafond de rang existaient pourtant :

    Couplé Gagnant 5-3  →  ×16,7   rang max 4
    Couplé Gagnant 6-3  →  ×10,3   rang max 4

Le moteur ne les a jamais vus. Il ne les a pas écartés : il ne les avait pas énumérés.
"""
import itertools

import pytest

from ml import combo_bets as cb
from services import mise_calculator as mc


# Course RÉELLE 08092026R6C3, cotes figées et probas du modèle, dans l'ordre du rang.
_R6C3 = [
    # numero, cote figée, proba_top1, proba_top3
    (4, 3.2, 0.2817, 0.6814),
    (6, 3.9, 0.2226, 0.7111),
    (5, 6.0, 0.1460, 0.4922),
    (3, 6.6, 0.1287, 0.3259),
    (2, 8.5, 0.0923, 0.2617),
    (8, 9.3, 0.0921, 0.2962),
    (1, 26.0, 0.0366, 0.2316),
]

_INFO = {"nb_partants": 7, "est_simple_gagnant": True, "est_simple_place": True,
         "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True,
         "est_couple_ordre": False, "est_2sur4": False, "est_tierce": False,
         "est_quarte": False, "est_quinte": False}


def _preds():
    return [{"numero": n, "nom_cheval": "Cheval%d" % n, "cote_pmu": c,
             "proba_top1": p1, "proba_top3": p3, "non_partant": False}
            for n, c, p1, p3 in _R6C3]


def _paires_couple_gagnant(cands):
    return {frozenset(int(h["numero"]) for h in c["chevaux"])
            for c in cands if c["type_pari"] == "Couplé Gagnant"}


def test_toutes_les_paires_du_haut_du_classement_sont_enumerees():
    cands = cb.enumerate_bet_candidates(_preds(), _INFO)
    paires = _paires_couple_gagnant(cands)
    tetes = [n for n, _, _, _ in _R6C3][:cb.COMBO_PAIRES_RANGS]
    manquantes = [set(p) for p in itertools.combinations(tetes, 2)
                  if frozenset(p) not in paires]
    assert not manquantes, "paires du haut de classement absentes du catalogue : %s" % manquantes


def test_le_quatrieme_du_classement_existe_dans_le_catalogue():
    """Le cas exact du 08/09 : 4e au classement, cote moyenne — donc invisible pour
    l'ancien catalogue (ni top-3, ni « grosse cote »)."""
    cands = cb.enumerate_bet_candidates(_preds(), _INFO)
    quatrieme = _R6C3[3][0]
    combos = [c for c in cands
              if len(c.get("chevaux", [])) >= 2
              and any(int(h["numero"]) == quatrieme for h in c["chevaux"])]
    assert combos, "le 4e du classement n'apparaît dans aucune combinaison"


def test_le_risque_trouve_un_pari_dans_sa_tranche():
    """L'invariant produit : quand une combinaison respecte À LA FOIS la tranche ×10 et
    le plafond de rang, le profil risqué doit la jouer plutôt que retomber sur le filet
    hors bande (le Simple Gagnant à ×3,2 servi en production)."""
    plan = mc.generer_plan(10, "agressif", _preds(), _INFO, respect_montant=True)
    paris = [p for niv in plan.niveaux for p in niv.paris]
    assert paris, "plan vide"
    rapport_min = mc.PROFIL_CONFIG["agressif"]["rapport_min"]
    assert max(p.rapport_estime for p in paris) >= rapport_min, (
        "aucun pari dans la tranche ×%.0f : %s"
        % (rapport_min, [(p.type, p.rapport_estime) for p in paris]))


def test_le_plafond_de_rang_reste_respecte():
    """L'élargissement du catalogue ne doit PAS faire entrer des chevaux que le modèle
    enterre : le plafond de rang du profil s'applique comme avant."""
    for profil in ("conservateur", "equilibre", "agressif"):
        plan = mc.generer_plan(10, profil, _preds(), _INFO, respect_montant=True)
        rangs = [h.get("rang") for niv in plan.niveaux for p in niv.paris
                 for h in p.chevaux if h.get("rang")]
        if not rangs:
            continue
        plafond = mc._rang_max_effectif(mc.PROFIL_CONFIG[profil]["rang_max"],
                                        _INFO["nb_partants"]) + mc.RANG_MAX_BONUS_PLACE
        assert max(rangs) <= plafond, (
            "%s : cheval au rang %d, plafond %d" % (profil, max(rangs), plafond))
