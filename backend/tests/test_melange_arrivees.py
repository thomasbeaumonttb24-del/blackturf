"""La proba de victoire servie annonçait moins juste que la cote qu'elle corrige.

Mesure en production (2026-09-16), prédictions figées à T-10, hors échantillon,
1 607 courses — log-vraisemblance du gagnant :

    chaîne servie (isotone → mélange linéaire → netteté)   1,9853
    cote seule                                             1,9586
    logit conditionnel modèle × marché (2 paramètres)      1,9479

`ml.melange_arrivees` apprend ce second étage chaque nuit. Ces tests verrouillent
les propriétés dont dépendent la cote juste et le rang affiché.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from sqlalchemy import text

from ml import melange_arrivees as ma
from ml import reglages_appris


# ── La transformation ────────────────────────────────────────────────────────

def test_la_somme_vaut_un_et_rien_n_est_nul():
    p = ma.appliquer([0.5, 0.3, 0.15, 0.05], [2.1, 4.0, 7.5, 30.0], 0.31, 0.71)
    assert p is not None
    assert float(p.sum()) == pytest.approx(1.0, abs=1e-12)
    assert (p > 0).all()


def test_poids_marche_seul_rend_la_cote_sans_marge():
    cotes = [2.0, 3.5, 6.0, 12.0, 40.0]
    q = 1.0 / np.array(cotes)
    p = ma.appliquer([0.2] * 5, cotes, 0.0, 1.0)
    assert np.allclose(p, q / q.sum())


def test_poids_modele_seul_rend_le_modele_normalise():
    brut = np.array([0.40, 0.25, 0.20, 0.10, 0.05]) * 3.0   # non normalisée
    p = ma.appliquer(brut, [9.0, 2.0, 5.0, 4.0, 3.0], 1.0, 0.0)
    assert np.allclose(p, brut / brut.sum())


def test_le_modele_deplace_un_cheval_par_un_facteur_pas_un_ecart():
    """Ce que le mélange linéaire ne savait pas faire : à cote égale, doubler la
    proba du modèle multiplie la proba servie par 2^β, quel que soit le niveau."""
    cotes = [3.0, 3.0, 20.0, 20.0, 8.0]
    brut = [0.10, 0.20, 0.02, 0.04, 0.64]
    p = ma.appliquer(brut, cotes, 0.3, 0.7)
    assert p[1] / p[0] == pytest.approx(2 ** 0.3, rel=1e-9)
    assert p[3] / p[2] == pytest.approx(2 ** 0.3, rel=1e-9)


def test_une_cote_manquante_laisse_la_chaine_d_avant():
    """Une donnée absente ne se remplace pas par une valeur devinée."""
    assert ma.appliquer([0.5, 0.3, 0.2], [2.0, None, 5.0], 0.3, 0.7) is None
    assert ma.appliquer([0.5, 0.3, 0.2], [2.0, 0.0, 5.0], 0.3, 0.7) is None
    assert ma.appliquer([0.5, 0.3, 0.2], [2.0, float("nan"), 5.0], 0.3, 0.7) is None


def test_entrees_degenerees_ou_poids_hors_bornes_ne_levent_jamais():
    cotes = [2.0, 3.0, 5.0]
    assert ma.appliquer([0, 0, 0], cotes, 0.3, 0.7) is None
    assert ma.appliquer([0.5, 0.5], cotes, 0.3, 0.7) is None          # tailles
    assert ma.appliquer([0.5, 0.3, 0.2], cotes, -0.1, 0.7) is None    # négatif
    assert ma.appliquer([0.5, 0.3, 0.2], cotes, 0.3, 2.5) is None     # trop pointu
    assert ma.appliquer([0.5, 0.3, 0.2], cotes, "x", 0.7) is None
    assert ma.appliquer([0.5, 0.3, 0.2], cotes, 0.0, 0.0) is None


def test_rien_n_est_servi_tant_que_rien_n_est_retenu():
    ma._cache = None
    assert ma.en_service() is None
    ma._cache = {"retenu": False, "beta_modele": 0.3, "beta_marche": 0.7}
    assert ma.en_service() is None
    ma._cache = {"retenu": True, "beta_modele": 0.3, "beta_marche": 0.7}
    assert ma.en_service() == (0.3, 0.7)
    ma._cache = None


# ── L'ajustement ─────────────────────────────────────────────────────────────

def _simuler(n_courses: int, beta_vrai=(0.4, 0.7), bruit_modele: float = 1.0,
             seed: int = 3) -> list[dict]:
    """Courses dont le gagnant est tiré du VRAI logit conditionnel.

    `bruit_modele` = 0 rend le modèle pur bruit (aucune information propre).
    """
    rng = np.random.default_rng(seed)
    courses = []
    for _ in range(n_courses):
        k = int(rng.integers(6, 15))
        force_marche = rng.normal(0, 1.0, k)
        q = np.exp(force_marche) / np.exp(force_marche).sum()
        signal = rng.normal(0, 1.0, k)
        m = np.exp(signal) / np.exp(signal).sum()
        z = beta_vrai[0] * np.log(m) * bruit_modele + beta_vrai[1] * np.log(q)
        vrai = np.exp(z - z.max())
        vrai /= vrai.sum()
        gagnant = int(rng.choice(k, p=vrai))
        cotes = 1.0 / (q * 1.15)                    # marge du PMU
        servi = 0.5 * m + 0.5 * q                   # « chaîne d'avant » linéaire
        c = ma._vers_course(m, cotes, gagnant, servi)
        assert c is not None
        courses.append(c)
    return courses


def test_l_ajustement_retrouve_les_vrais_poids():
    b = ma.ajuster_beta(_simuler(3000))
    assert b[0] == pytest.approx(0.4, abs=0.08)
    assert b[1] == pytest.approx(0.7, abs=0.08)


def test_un_modele_informatif_est_retenu():
    v = ma.evaluer(_simuler(1500))
    assert v["retenu"] is True, v
    assert v["gain_logv_vs_marche_ic95"][0] > 0
    assert v["gain_logv_vs_servi"] > 0


def test_un_modele_sans_information_n_est_pas_retenu():
    """Le critère décisif : battre la COTE SEULE, intervalle entièrement positif.
    Un modèle qui n'apporte rien ne passe pas, même s'il bat la chaîne servie."""
    v = ma.evaluer(_simuler(1500, beta_vrai=(0.4, 1.0), bruit_modele=0.0, seed=11))
    assert v["retenu"] is False
    assert v["raison"] == "ne bat pas la cote seule hors échantillon"


def test_sous_le_volume_minimal_on_ne_conclut_pas():
    v = ma.evaluer(_simuler(ma.MIN_COURSES - 100))
    assert v["retenu"] is False
    assert v["raison"] == "échantillon trop court"


def test_chaque_course_est_jugee_avec_des_poids_appris_sur_l_autre_moitie():
    v = ma.evaluer(_simuler(1200))
    assert len(v["betas_par_moitie"]) == 2
    assert v["n_courses"] == 1200


# ── Le tour complet, sur base ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demarrage_a_froid_trace_l_examen_et_ne_met_rien_en_service(db):
    ma._cache = None
    out = await ma.calculer_et_persister(db)
    await db.commit()
    assert out["status"] == "valeur_conservee"
    examen = await ma.charger_dernier_examen(db)
    assert examen is not None and examen["retenu"] is False and examen["examine_le"]
    assert (await ma.charger(db))["retenu"] is False
    assert ma.en_service() is None


@pytest.mark.asyncio
async def test_des_poids_en_base_sont_relus_par_le_rafraichissement(db):
    await db.execute(text(ma._DDL))
    await db.execute(text("INSERT INTO melange_arrivees (id, data) VALUES (1, :d)"),
                     {"d": json.dumps({"retenu": True, "beta_modele": 0.31,
                                       "beta_marche": 0.71})})
    await db.commit()
    ma._cache = None
    assert await reglages_appris.rafraichir(db, force=True) is True
    assert ma.en_service() == (0.31, 0.71)
    # Dans le délai : aucune relecture.
    assert await reglages_appris.rafraichir(db) is False
    ma._cache = None


# ── Les covariables du marché (2026-09-27) ───────────────────────────────────
# Mesure en production, 2 096 courses : +0,018 de log-vraisemblance sur le mélange à
# deux paramètres ; gros favoris annoncés 46 % pour 40 % réalisés et « sous-cotés »
# annoncés 7,1 % pour 4,7 % avant elles, calibrés après.

def test_sans_gammas_rien_ne_change_et_gammas_nuls_rendent_deux_parametres():
    p, cotes = [0.5, 0.3, 0.2], [2.0, 4.0, 5.0]
    cov = ma.matrice_covariables(cotes, [0.1, -0.2, 0.0], [2.2, 3.5, 6.0])
    deux = ma.appliquer(p, cotes, 0.3, 0.7)
    assert np.allclose(ma.appliquer(p, cotes, 0.3, 0.7, covariables=cov,
                                    gammas=[0.0, 0.0, 0.0]), deux)


def test_gammas_sans_covariables_ou_hors_bornes_ne_servent_rien():
    p, cotes = [0.5, 0.3, 0.2], [2.0, 4.0, 5.0]
    assert ma.appliquer(p, cotes, 0.3, 0.7, gammas=[0.1, 0.1, 0.1]) is None
    cov = ma.matrice_covariables(cotes)
    assert ma.appliquer(p, cotes, 0.3, 0.7, covariables=cov, gammas=[0.1, 0.1]) is None
    assert ma.appliquer(p, cotes, 0.3, 0.7, covariables=cov,
                        gammas=[ma.GAMMA_MAX + 1, 0, 0]) is None


def test_covariables_absentes_prennent_la_valeur_neutre_des_features():
    cotes = [3.0, 2.0, 8.0]
    cov = ma.matrice_covariables(cotes, [None, "x", 5.0], [None, 0.0, float("nan")])
    assert cov.shape == (3, 3)
    assert list(cov[:, 0]) == [0.0, 0.0, ma.MOUVEMENT_BORNE]        # borné
    assert np.allclose(cov[:, 1], np.log(ma.probas_marche(cotes)))  # Geny = PMU
    assert list(cov[:, 2]) == [0.0, 1.0, 0.0]                        # favori = plus petite cote
    assert ma.matrice_covariables([3.0, None, 8.0]) is None


def test_un_gamma_favori_negatif_allonge_la_cote_juste_du_favori():
    p, cotes = [0.5, 0.3, 0.2], [2.0, 4.0, 5.0]
    cov = ma.matrice_covariables(cotes)
    deux = ma.appliquer(p, cotes, 0.3, 0.7)
    avec = ma.appliquer(p, cotes, 0.3, 0.7, covariables=cov, gammas=[0.0, 0.0, -0.3])
    assert avec[0] < deux[0] and abs(avec.sum() - 1) < 1e-12


def test_les_covariables_se_lisent_dans_les_features_servies():
    feats = [{"mouvement_30min": 0.2, "cote_geny": 2.5}, {"cote_geny": 4.0}, {}]
    cov = ma.covariables_de_features(feats, [2.0, 4.0, 5.0])
    assert cov[0, 0] == pytest.approx(0.2) and cov[1, 0] == 0.0
    assert cov[2, 1] == pytest.approx(np.log(ma.probas_marche([2.5, 4.0, 5.0])[2]))


def _simuler_cov(n_courses: int, gammas=(-0.3, 0.25, -0.35), seed: int = 5,
                 servi_vrai: bool = False) -> list[dict]:
    """Courses dont le gagnant suit le logit AVEC covariables `gammas`."""
    rng = np.random.default_rng(seed)
    g = np.asarray(gammas, dtype=float)
    courses = []
    for _ in range(n_courses):
        k = int(rng.integers(6, 15))
        fm = rng.normal(0, 1.0, k)
        q = np.exp(fm) / np.exp(fm).sum()
        sig = rng.normal(0, 1.0, k)
        m = np.exp(sig) / np.exp(sig).sum()
        cotes = 1.0 / (q * 1.15)
        mv = rng.normal(0, 0.25, k)
        geny = cotes * np.exp(rng.normal(0, 0.3, k))
        cov = ma.matrice_covariables(cotes, mv, geny)
        if cov is None:                             # favori écrasant : cote ≤ 1
            continue
        z = 0.35 * np.log(m) + 0.7 * np.log(q) + cov @ g
        vrai = np.exp(z - z.max())
        vrai /= vrai.sum()
        gagnant = int(rng.choice(k, p=vrai))
        servi = vrai if servi_vrai else 0.5 * m + 0.5 * q
        c = ma._vers_course(m, cotes, gagnant, servi, cov)
        assert c is not None and c["x"].shape == (k, 5)
        courses.append(c)
    return courses


def test_des_covariables_informatives_sont_retenues_et_retrouvees():
    v = ma.evaluer(_simuler_cov(2500))
    assert v["retenu"] is True
    e = v["etendu"]
    assert e["retenu"] is True, e
    assert e["gain_logv_vs_deux_parametres_ic95"][0] > 0
    assert e["gammas"][0] == pytest.approx(-0.3, abs=0.15)
    assert e["gammas"][2] == pytest.approx(-0.35, abs=0.15)
    ma._cache = {"retenu": True, "beta_modele": v["beta_modele"],
                 "beta_marche": v["beta_marche"], "etendu": e}
    bm, bk, gm = ma.en_service_etendu()
    assert len(gm) == len(ma.COVARIABLES) and ma.en_service() == (v["beta_modele"],
                                                                  v["beta_marche"])
    ma._cache = None


def test_des_covariables_sans_information_ne_sont_pas_servies():
    v = ma.evaluer(_simuler_cov(1500, gammas=(0.0, 0.0, 0.0), seed=9))
    assert v["retenu"] is True
    assert v["etendu"]["retenu"] is False
    assert v["etendu"]["raison"] in ("ne bat pas le mélange à deux paramètres",
                                     "coefficients instables d'une moitié à l'autre")
    ma._cache = {"retenu": True, "beta_modele": 0.3, "beta_marche": 0.7,
                 "etendu": v["etendu"]}
    assert ma.en_service_etendu() is None
    ma._cache = None


def test_une_fois_les_covariables_servies_le_reapprentissage_ne_se_fige_pas():
    """La proba servie EST le mélange étendu : deux paramètres échouent face à elle
    (critère b), mais le mélange étendu, lui, doit rester retenu la nuit suivante."""
    v = ma.evaluer(_simuler_cov(4000, servi_vrai=True, seed=13))
    assert v["gain_logv_vs_servi"] < -ma.TOL_LOGV
    assert v["etendu"]["retenu"] is True
    assert v["retenu"] is True


def test_les_anciens_appelants_a_deux_colonnes_sont_inchanges():
    """modele_technique, les bancs et le contrôle de promotion passent des courses à
    deux colonnes : pas de clé `etendu`, même verdict qu'avant."""
    v = ma.evaluer(_simuler(1500))
    assert "etendu" not in v and v["retenu"] is True
