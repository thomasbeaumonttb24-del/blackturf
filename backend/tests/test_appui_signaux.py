"""Appui des signaux (services.appui_signaux) — demande produit du 2026-10-07.

Un cheval n'entre pas dans un plan pour son seul rang : écart de prix modèle /
marché, détection d'outsider et profil (forme, terrain, jockey, argent qui rentre,
presse) le soutiennent ou le contredisent, et le plan le dit.
"""
import pytest

from services import mise_calculator as mc
from services.appui_signaux import (
    MULT_MAX, MULT_MIN, appui_candidat, appui_par_cheval, chances_marche,
    multiplicateur_appui,
)


def _p(numero, p1, cote, **kw):
    return {"numero": numero, "proba_top1": p1, "cote_pmu": cote, **kw}


def test_chances_marche_devig_et_sans_cote_absente():
    q = chances_marche([_p(1, 0.5, 2.0), _p(2, 0.5, 2.0), _p(3, 0.1, None)])
    assert q == {1: 0.5, 2: 0.5}            # aucun marché inventé pour le N°3


def test_cheval_sous_cote_appuye_sur_cote_contredit():
    a = appui_par_cheval([_p(1, 0.50, 4.0), _p(2, 0.25, 2.0), _p(3, 0.25, 4.0)])
    assert a[1]["score"] > 0 and any("sous-coté" in s for s in a[1]["pour"])
    assert a[2]["score"] < 0 and any("sur-joué" in s for s in a[2]["contre"])


def test_outsider_detecte_cite_et_compte():
    preds = [_p(1, 0.5, 2.0), _p(2, 0.45, 2.2),
             _p(3, 0.05, 20.0, outsider={"chance_place": 0.30, "niveau": "fort"})]
    a = appui_par_cheval(preds)
    assert a[3]["composantes"]["outsider"] > 0.9
    assert any("outsider détecté (fort)" in s for s in a[3]["pour"])


def test_profil_du_cheval_et_argent_qui_rentre():
    ctx = {"profil_score": 0.5, "qualite_donnee": 0.8, "signaux": {
        "forme_recente": {"disponible": True, "sous_score": 0.6, "valeurs_brutes": {}},
        "cote_enjeux": {"disponible": True, "sous_score": 0.3,
                        "valeurs_brutes": {"mouvement_30min": 0.12}},
        "presse": {"disponible": True, "sous_score": -0.4, "valeurs_brutes": {}},
    }}
    a = appui_par_cheval([_p(1, 0.5, 2.0), _p(2, 0.5, 2.0)], {1: ctx})
    assert "profil" in a[1]["composantes"] and "profil" not in a[2]["composantes"]
    assert "forme récente favorable" in a[1]["pour"]
    assert any("l'argent rentre" in s for s in a[1]["pour"])
    assert "presse défavorable" in a[1]["contre"]


def test_aucune_donnee_aucun_effet():
    a = appui_par_cheval([_p(1, None, None), _p(2, None, None)])
    assert a[1]["score"] is None
    assert multiplicateur_appui([1, 2], a) == 1.0


def test_combinaison_jugee_aussi_sur_son_maillon_faible():
    appui = {1: {"score": 0.8}, 2: {"score": -0.6}}
    assert appui_candidat([1, 2], appui) == pytest.approx(0.5 * 0.1 + 0.5 * -0.6)
    assert MULT_MIN <= multiplicateur_appui([1, 2], appui) < 1.0


def test_multiplicateur_borne():
    assert multiplicateur_appui([1], {1: {"score": 1.0}}) <= MULT_MAX
    assert multiplicateur_appui([1], {1: {"score": -1.0}}) >= MULT_MIN


_INFO = {"nb_partants": 12, "est_simple_gagnant": True, "est_simple_place": True,
         "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True,
         "est_couple_ordre": False, "est_2sur4": True}


def _field(n=12):
    return [{"numero": i + 1, "nom_cheval": f"C{i + 1}", "cote_pmu": 2.5 + i * 1.6,
             "proba_top1": max(0.24 - i * 0.017, 0.01), "proba_top3": max(0.6 - i * 0.04, 0.05),
             "non_partant": False} for i in range(n)]


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_plan_explique_ses_chevaux_par_leurs_signaux(profil):
    d = mc.plan_to_dict(mc.generer_plan(10, profil, _field(), _INFO, respect_montant=True))
    paris = [p for n in d["niveaux"] for p in n["paris"]]
    assert paris
    assert sum(p["mise"] for p in paris) == 10, "chaque course reste jouée en entier"
    assert any("appuyé par" in r or "signal contraire" in r or "prix conforme" in r
               for p in paris for r in p.get("raisons") or [])


def test_signaux_deplacent_la_conviction():
    """À données identiques, un cheval que le marché sur-joue perd la préférence."""
    base = _field()
    d0 = mc.plan_to_dict(mc.generer_plan(10, "conservateur", base, _INFO, respect_montant=True))
    pris = [h["numero"] for p in d0["niveaux"][0]["paris"] for h in p["chevaux"]]
    # On fait du cheval retenu le grand favori du marché (cote écrasée) : le modèle ne
    # change pas, mais le prix ne le justifie plus.
    autre = [dict(p) for p in base]
    for p in autre:
        if p["numero"] == pris[0]:
            p["cote_pmu"] = 1.3
    cands = mc.generer_plan(10, "conservateur", autre, _INFO, respect_montant=True)
    assert cands is not None
    a = appui_par_cheval(autre)
    assert a[pris[0]]["score"] < appui_par_cheval(base)[pris[0]]["score"]
