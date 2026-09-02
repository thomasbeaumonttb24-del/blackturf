"""Le biais de Harville : mesuré sur les arrivées réelles, jamais deviné.

Prendre les probabilités de VICTOIRE comme forces d'un Plackett-Luce reproduit
exactement la première place — P(i gagne) = s_i / Σs par construction — mais suppose
que la course pour la DEUXIÈME place obéit à la même hiérarchie. Elle n'y obéit pas
(Henery 1981, Stern 1990), et l'erreur va toujours dans le même sens : le placé du
favori est surestimé, celui des outsiders sous-estimé.

Ça compte parce que tout le catalogue combiné en dépend — Couplé Placé, Trio, 2sur4,
Multi. Une probabilité de placé surestimée donne une EV surestimée, donc des paris
émis qui ne devaient pas l'être.

Règle appliquée ici : sans mesure suffisante, les exposants valent 1,0 et le
comportement est identique à celui d'aujourd'hui. Aucune correction inventée.
"""
import numpy as np
import pytest

from ml.harville_calibration import (
    LAMBDA_MAX, LAMBDA_MIN, MIN_COURSES, ajuster_exposants, log_vraisemblance,
)
from ml.plackett_luce import EXPOSANTS_NEUTRES, forces_par_position, p_ordre_exact


def _tirer_arrivee(forces, exposants, rng):
    """Tire une arrivée SOUS le modèle à exposants — le seul moyen honnête de
    fabriquer des données dont on connaît la vérité."""
    n = len(forces)
    restants = list(range(n))
    ordre = []
    for pos in range(3):
        lam = exposants[min(pos, len(exposants) - 1)]
        poids = np.array([forces[i] ** lam for i in restants], dtype=float)
        poids = poids / poids.sum()
        choisi = restants[int(rng.choice(len(restants), p=poids))]
        ordre.append(choisi)
        restants.remove(choisi)
    return ordre


def _corpus(exposants_vrais, n_courses=900, n=10, seed=5):
    rng = np.random.default_rng(seed)
    courses = []
    for _ in range(n_courses):
        f = rng.dirichlet(np.full(n, 0.8))
        index = {h: i for i, h in enumerate(range(n))}
        ordre = _tirer_arrivee(f, exposants_vrais, rng)
        courses.append((f, [index[h] for h in ordre]))
    return courses


# ── La vraisemblance est une vraie vraisemblance ───────────────────────────

def test_la_log_vraisemblance_est_maximale_au_vrai_exposant():
    """Test de contrôle du montage : si on génère les arrivées SOUS un exposant
    connu, la vraisemblance doit pointer dessus."""
    vrais = (1.0, 0.65, 0.55, 0.55, 0.55)
    courses = _corpus(vrais)
    v_vrai = log_vraisemblance(courses, vrais)
    v_neutre = log_vraisemblance(courses, EXPOSANTS_NEUTRES)
    assert v_vrai > v_neutre, (
        "sur des arrivées engendrées avec λ<1, le modèle nu doit être moins probable")


def test_l_ajustement_retrouve_l_exposant_qui_a_engendre_les_arrivees():
    courses = _corpus((1.0, 0.65, 0.55, 0.55, 0.55))
    verdict = ajuster_exposants(courses)
    assert verdict["retenus"] is True
    assert verdict["exposants"][0] == 1.0, "la victoire est exacte : λ₁ ne bouge pas"
    assert 0.45 <= verdict["exposants"][1] <= 0.90, verdict["exposants"]
    assert verdict["gain"] > 0


def test_sur_des_arrivees_vraiment_plackett_luce_on_ne_corrige_rien():
    """Contrôle inverse, celui qui compte : si le modèle nu est le bon, l'ajustement
    ne doit PAS inventer une correction."""
    courses = _corpus(EXPOSANTS_NEUTRES, n_courses=900, seed=11)
    verdict = ajuster_exposants(courses)
    if verdict["retenus"]:
        # Une correction retenue doit alors être marginale ET justifiée par un gain.
        assert abs(verdict["exposants"][1] - 1.0) < 0.20, verdict["exposants"]
        assert verdict["gain"] > 0
    else:
        assert verdict["exposants"] == list(EXPOSANTS_NEUTRES)


def test_les_exposants_restent_ordonnes():
    """λ₁ ≥ λ₂ ≥ λ₃ : la hiérarchie s'aplatit en descendant les positions, elle ne
    se renverse pas."""
    courses = _corpus((1.0, 0.6, 0.5, 0.5, 0.5))
    exps = ajuster_exposants(courses)["exposants"]
    assert exps[0] >= exps[1] >= exps[2]


def test_les_exposants_restent_dans_leurs_bornes():
    courses = _corpus((1.0, 0.45, 0.45, 0.45, 0.45))
    exps = ajuster_exposants(courses)["exposants"]
    for lam in exps[1:]:
        assert LAMBDA_MIN <= lam <= LAMBDA_MAX


def test_sans_donnee_aucun_exposant_n_est_invente():
    verdict = ajuster_exposants([])
    assert verdict["retenus"] is False
    assert verdict["exposants"] == list(EXPOSANTS_NEUTRES)


def test_un_gain_nul_conserve_le_modele_nu():
    """À égalité, on garde le comportement d'avant — jamais une correction gratuite."""
    courses = _corpus(EXPOSANTS_NEUTRES, n_courses=60, seed=3)
    verdict = ajuster_exposants(courses, lambda_min=1.0, lambda_max=1.0, n_pas=1)
    assert verdict["retenus"] is False


# ── Effet réel sur les probabilités servies ────────────────────────────────

def test_la_correction_deplace_le_place_du_favori_vers_les_outsiders():
    from ml.plackett_luce import p_dans_topk_tous

    forces = [0.34, 0.20, 0.14, 0.11, 0.09, 0.07, 0.05]
    nu = p_dans_topk_tous(forces_par_position(forces), 3)
    corrige = p_dans_topk_tous(
        forces_par_position(forces, (1.0, 0.65, 0.55, 0.55, 0.55)), 3)

    assert corrige[0] < nu[0], "le placé du favori est ramené"
    assert corrige[-1] > nu[-1], "celui du dernier remonte"
    assert sum(nu) == pytest.approx(3.0, abs=1e-9)
    assert sum(corrige) == pytest.approx(3.0, abs=1e-9), (
        "la contrainte « trois places à distribuer » tient dans les deux cas")


def test_la_victoire_n_est_jamais_touchee():
    forces = [0.34, 0.20, 0.14, 0.11, 0.09, 0.07, 0.05]
    nu = forces_par_position(forces)
    corrige = forces_par_position(forces, (1.0, 0.5, 0.4, 0.4, 0.4))
    for i in range(len(forces)):
        assert p_ordre_exact(corrige, [i]) == pytest.approx(
            p_ordre_exact(nu, [i]), abs=1e-12)


# ── Persistance et cold start ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cold_start_aucune_ecriture_aucune_correction(db):
    from ml.harville_calibration import calculer_et_persister, charger_exposants

    out = await calculer_et_persister(db)
    assert out["status"] == "skipped_insufficient_data"
    assert out["n_courses"] < MIN_COURSES
    assert await charger_exposants(db) == EXPOSANTS_NEUTRES


def test_le_moteur_de_plan_lit_le_cache_sans_toucher_la_base():
    """`ml.combo_bets` est appelé en synchrone depuis le moteur de plan : il ne peut
    pas ouvrir de session. Une lecture base ici ferait tomber la génération de plan."""
    import inspect

    from ml import combo_bets

    src = inspect.getsource(combo_bets._exposants_harville)
    assert "exposants_en_cache" in src
    assert "await" not in src
    assert combo_bets._exposants_harville() is not None


def test_la_nuit_ajuste_les_exposants():
    import inspect

    from ml import pipeline

    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    assert 'etape(AsyncSessionLocal, "exposants_harville")' in src


def test_l_api_charge_les_exposants_au_demarrage():
    """Sans ce chargement, une correction apprise resterait apprise et jamais
    servie jusqu'au redémarrage suivant."""
    import inspect

    from api import main

    src = inspect.getsource(main)
    assert "charger_exposants" in src
    assert src.count("from ml.harville_calibration import charger_exposants") == 1


def test_les_exposants_sont_valides_hors_de_leurs_propres_donnees():
    """Choisis sur une part des courses, validés sur l'autre. Deux paramètres sur
    des milliers de courses ne peuvent pas beaucoup sur-apprendre — mais « pas
    beaucoup » n'est pas « pas du tout », et c'est l'exigence appliquée partout
    ailleurs : un correcteur qui n'a rien prouvé hors de ses propres données ne
    corrige rien."""
    courses = _corpus((1.0, 0.65, 0.55, 0.55, 0.55))
    verdict = ajuster_exposants(courses)
    assert verdict["retenus"] is True
    assert verdict["gain"] > 0, "gain sur la part d'ajustement"
    assert verdict["gain_validation"] > 0, "gain confirmé sur les courses non vues"


def test_un_gain_qui_ne_survit_pas_a_la_validation_est_rejete():
    """Montage : les courses d'AJUSTEMENT sont engendrées avec λ = 0,5, celles de
    VALIDATION avec λ = 1. Un ajustement qui ne regarderait que la première moitié
    retiendrait une correction que la seconde contredit."""
    biaisees = _corpus((1.0, 0.5, 0.45, 0.45, 0.45), n_courses=800, seed=21)
    neutres = _corpus(EXPOSANTS_NEUTRES, n_courses=200, seed=22)
    verdict = ajuster_exposants(biaisees + neutres, frac_ajustement=0.8)
    assert verdict["gain"] > 0, "la part d'ajustement, elle, est bien améliorée"
    if verdict["retenus"]:
        assert verdict["gain_validation"] > 0, (
            "on ne retient que ce qui tient AUSSI hors échantillon")


def test_sans_part_de_validation_on_ne_conclut_pas():
    """Une seule course : impossible de valider, donc impossible de corriger."""
    verdict = ajuster_exposants(_corpus((1.0, 0.6, 0.5, 0.5, 0.5), n_courses=1))
    assert verdict["retenus"] is False
    assert verdict["exposants"] == list(EXPOSANTS_NEUTRES)
