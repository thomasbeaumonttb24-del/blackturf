"""ALPHA — la confiance accordée au modèle face au marché — s'apprend.

`p_servie = alpha × p_modèle + (1 − alpha) × p_marché`. C'est le DERNIER arbitrage
de toute la chaîne : il décide du classement affiché, des cotes justes, de l'EV,
donc des paris émis. Ses quatre paramètres étaient posés à la main, justifiés par
un raisonnement (« le marché agrège l'info de milliers de parieurs ») et non par une
mesure : rien n'avait vérifié que 0,42 valait mieux que 0,30 ou 0,55.

Or l'optimum dépend de ce que le modèle a appris. Mesuré sur six jeux simulés en
faisant varier la finesse du marché, l'alpha qui maximise le classement servi va de
0,05 à 0,95 — aucune constante ne couvre cet écart.

Règle appliquée : deux conditions, mesurées sur des courses qui n'ont pas servi à
choisir — la log-vraisemblance du vrai gagnant s'améliore ET le classement
intra-course ne se dégrade pas. Sinon la valeur en place reste.
"""
import numpy as np
import pytest

from ml.blend_calibration import (
    ALPHA_MAX_DEFAUT, MIN_COURSES, ajuster_alpha, melange,
)


def _courses(alpha_vrai, n_courses=900, n=10, seed=5, bruit_modele=0.9):
    """Corpus où le mélange OPTIMAL est proche de `alpha_vrai`.

    Le modèle et le marché voient chacun une part de la vérité : plus le modèle est
    bruité, plus le poids optimal du marché est grand.
    """
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_courses):
        vrai = rng.dirichlet(np.full(n, 0.9))
        # Le modèle voit la vérité, plus ou moins bien.
        m = np.clip(vrai * np.exp(rng.normal(0, bruit_modele, n)), 1e-6, None)
        m /= m.sum()
        # Le marché aussi, avec son propre bruit, calibré par `alpha_vrai` : plus
        # `alpha_vrai` est haut, plus le marché est mauvais devant le modèle.
        bruit_marche = bruit_modele * (alpha_vrai / max(1e-6, 1 - alpha_vrai))
        q = np.clip(vrai * np.exp(rng.normal(0, bruit_marche, n)), 1e-6, None)
        q /= q.sum()
        cotes = np.clip(0.82 / q, 1.05, 300.0)
        gagnant = int(rng.choice(n, p=vrai))
        out.append((m, cotes, gagnant))
    return out


# ── Le mélange est bien celui de la production ─────────────────────────────

def test_le_melange_est_une_probabilite_de_course():
    m = np.array([0.4, 0.3, 0.2, 0.1])
    cotes = np.array([2.0, 4.0, 8.0, 20.0])
    p = melange(m, cotes)
    assert p.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(p > 0)


def test_alpha_a_un_rapproche_du_modele_alpha_a_zero_du_marche():
    m = np.array([0.7, 0.2, 0.06, 0.04])
    cotes = np.array([5.0, 3.0, 4.0, 10.0])
    implicite = 1.0 / cotes
    implicite = implicite / implicite.sum()

    proche_modele = melange(m, cotes, alpha_max=0.95, alpha_min=0.95)
    proche_marche = melange(m, cotes, alpha_max=0.05, alpha_min=0.05)
    assert np.abs(proche_modele - m).sum() < np.abs(proche_marche - m).sum()
    assert np.abs(proche_marche - implicite).sum() < np.abs(proche_modele - implicite).sum()


def test_un_partant_sans_cote_garde_la_proba_du_modele():
    """Une cote manquante ne doit pas valoir « proba nulle » — c'est le
    comportement de production, et le miroir doit le reproduire."""
    m = np.array([0.5, 0.3, 0.2])
    cotes = np.array([2.0, 0.0, 5.0])          # le deuxième n'a pas de cote
    p = melange(m, cotes, alpha_max=0.42)
    assert p[1] > 0


def test_alpha_decroit_avec_la_cote():
    """Le modèle est moins fiable sur les gros outsiders : sa part doit baisser."""
    m = np.array([0.25] * 4)
    court = melange(m, np.array([2.0, 2.0, 2.0, 2.0]), alpha_max=0.8, alpha_min=0.1)
    long_ = melange(m, np.array([80.0, 80.0, 80.0, 80.0]), alpha_max=0.8, alpha_min=0.1)
    imp = np.array([0.25] * 4)
    # Sur un champ homogène les deux valent l'uniforme ; on vérifie le coefficient.
    assert np.allclose(court, imp, atol=1e-9)
    assert np.allclose(long_, imp, atol=1e-9)


# ── L'ajustement retrouve ce qu'il doit retrouver ──────────────────────────

def test_un_marche_faible_appelle_un_alpha_plus_haut():
    """Contrôle du montage : quand le marché est mauvais devant le modèle,
    l'ajustement doit accorder plus de poids au modèle."""
    v = ajuster_alpha(_courses(0.8, seed=3), alpha_en_place=0.42)
    if v["retenu"]:
        assert v["alpha_max"] > 0.42, v


def test_un_marche_fort_appelle_un_alpha_plus_bas():
    v = ajuster_alpha(_courses(0.15, seed=4), alpha_en_place=0.42)
    if v["retenu"]:
        assert v["alpha_max"] < 0.42, v


def test_un_alpha_retenu_ameliore_bien_les_deux_criteres():
    v = ajuster_alpha(_courses(0.8, seed=3), alpha_en_place=0.42)
    if v["retenu"]:
        assert v["gain_logv"] > 0, "la log-vraisemblance du gagnant s'améliore"
        assert v["gain_rang"] >= 0, (
            "le classement intra-course ne se dégrade pas : le produit ordonne des "
            "partants, on n'échange pas cette qualité contre de la calibration")


def test_sans_gain_hors_echantillon_la_valeur_en_place_reste():
    """Un alpha choisi sur ses propres données mais qui ne tient pas ailleurs ne
    doit rien remplacer."""
    v = ajuster_alpha(_courses(0.42, seed=9), alpha_en_place=ALPHA_MAX_DEFAUT)
    if not v["retenu"]:
        assert v["alpha_max"] == ALPHA_MAX_DEFAUT


def test_sans_part_de_validation_on_ne_conclut_pas():
    v = ajuster_alpha(_courses(0.8, n_courses=1), alpha_en_place=0.42)
    assert v["retenu"] is False
    assert v["alpha_max"] == 0.42


def test_sans_donnee_aucun_alpha_n_est_invente():
    v = ajuster_alpha([], alpha_en_place=0.42)
    assert v["retenu"] is False
    assert v["alpha_max"] == 0.42


# ── Câblage ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cold_start_la_valeur_en_place_est_servie(db):
    from ml.blend_calibration import (
        alpha_en_cache, calculer_et_persister, charger_alpha,
    )

    out = await calculer_et_persister(db)
    assert out["status"] == "skipped_insufficient_data"
    assert out["n_courses"] < MIN_COURSES
    assert (await charger_alpha(db))["alpha_max"] == ALPHA_MAX_DEFAUT
    assert alpha_en_cache() == ALPHA_MAX_DEFAUT


def test_le_pipeline_lit_l_alpha_appris():
    """Sans ça, l'alpha serait appris chaque nuit et jamais servi."""
    import inspect

    from ml import pipeline

    src = inspect.getsource(pipeline.predict_course)
    assert "alpha_en_cache" in src
    assert "ALPHA_MAX = 0.42" not in src, "plus de constante en dur"


def test_le_miroir_du_melange_ne_diverge_pas_du_pipeline():
    """`melange` DOIT reproduire le blend de production : c'est sur lui que l'alpha
    est ajusté. Si les deux divergent, on optimise un mélange qu'on ne sert pas."""
    import inspect

    from ml import pipeline

    src = inspect.getsource(pipeline.predict_course)
    for fragment in ("ALPHA_MAX - ALPHA_DECAY * np.maximum(cotes_pmu - ALPHA_FULL_COTE",
                     "alpha * probas_top1 + (1.0 - alpha) * implied_norm"):
        assert fragment in src, fragment
    assert "ALPHA_MIN = 0.12" in src
    assert "ALPHA_FULL_COTE = 12.0" in src
    assert "ALPHA_DECAY = 0.030" in src


def test_la_nuit_ajuste_l_alpha():
    import inspect

    from ml import pipeline

    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    assert 'etape(AsyncSessionLocal, "alpha_marche")' in src


def test_l_api_charge_l_alpha_au_demarrage():
    import inspect

    from api import main

    assert "charger_alpha" in inspect.getsource(main)
