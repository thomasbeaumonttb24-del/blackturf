"""Journal des paris CANDIDATS : tout ce que le moteur a envisagé, retenu ou non,
pour comparer la formule jouée à celles écartées sur la même course."""
import pytest

from ml import candidats_paris as cp
from ml.combo_bets import enumerate_bet_candidates
from services import mise_calculator as mc
from services.bet_catalog import derive_bet_flags

PROFILS = ("conservateur", "equilibre", "agressif")


def _preds(n=12):
    return [{"numero": i + 1, "nom_cheval": f"Cheval{i + 1}", "cote_pmu": 2.0 + i * 1.7,
             "proba_top1": max(0.28 - i * 0.02, 0.01), "proba_top3": max(0.6 - i * 0.04, 0.03),
             "non_partant": False} for i in range(n)]


def _info(n=12):
    info = derive_bet_flags(None, est_tierce=True, est_quarte=True, est_quinte=False,
                            est_2sur4=True)
    info["nb_partants"] = n
    return info


def test_cle_independante_de_l_ordre():
    assert cp.cle_pari("Couplé Gagnant", [5, 2]) == cp.cle_pari("Couplé Gagnant", [2, 5])
    assert cp.cle_pari("Couplé Gagnant", [5, 2]) != cp.cle_pari("Couplé Placé", [2, 5])


def test_les_non_partants_ne_sont_pas_candidats():
    preds = _preds()
    preds[0]["non_partant"] = True
    assert 1 not in {p["numero"] for p in cp.preds_candidats(preds)}


def test_lignes_distinctes_et_retenues_marquees():
    cands = enumerate_bet_candidates(cp.preds_candidats(_preds()), _info())
    lignes = cp.lignes_candidats(cands, {})
    assert lignes and len({l["cle"] for l in lignes}) == len(lignes)
    assert all(l["retenu_par"] == [] for l in lignes)
    premiere = lignes[0]
    marquees = cp.lignes_candidats(cands, {premiere["cle"]: ["agressif"]})
    assert next(l for l in marquees if l["cle"] == premiere["cle"])["retenu_par"] == ["agressif"]


@pytest.mark.parametrize("profil", PROFILS)
def test_chaque_ticket_emis_figure_parmi_les_candidats(profil):
    """Sans cette propriété, `retenu_par` mentirait : un ticket joué serait absent
    du journal et la comparaison joué/écarté perdrait le joué."""
    preds, info = _preds(), _info()
    plan = mc.plan_to_dict(mc.generer_plan(10, profil, preds, info, respect_montant=True))
    retenus = cp.cles_retenues({profil: plan})
    assert retenus, "le plan émet au moins un ticket"
    cles = {l["cle"] for l in cp.lignes_candidats(
        enumerate_bet_candidates(cp.preds_candidats(preds), info), retenus)}
    manquants = set(retenus) - cles
    assert not manquants, manquants
