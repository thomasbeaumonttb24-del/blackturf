"""La probabilité servie était trop concentrée sur le haut du classement.

Mesure en production, fenêtre 90 jours (`data_quality.calibration_par_bande`) :

    bande      n servi   réel    écart
    0,00-0,40  46 497  0,0880  0,0893  -0,0013
    0,40-0,50     354  0,4427  0,3639  +0,0788   <- l'alerte
    0,70+          29  0,7936  0,4138  +0,3798

Les deux bouts disent la même chose : la masse qui manque en bas (≈ 60 victoires)
est celle qui déborde en haut (≈ 45). La forme de la distribution est trop pointue.
`ml.sharpness_calibration` la corrige par une puissance — la seule transformation
qui survive à la renormalisation Σ=1, puisqu'elle en fait partie.

Ces tests verrouillent les propriétés dont dépend cette affirmation.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from sqlalchemy import text

from ml import sharpness_calibration as sc


# ── La transformation elle-même ───────────────────────────────────────────────

def test_exposant_neutre_est_l_identite_exacte():
    """Tant que rien n'est prouvé, la chaîne doit rendre EXACTEMENT ce qu'elle rendait."""
    p = np.array([0.44, 0.21, 0.15, 0.11, 0.09])
    assert np.array_equal(sc.appliquer(p, 1.0), p)


def test_la_somme_vaut_toujours_un():
    """Σ=1 est vrai PAR CONSTRUCTION : c'est ce qui empêche une renormalisation
    ultérieure de défaire la correction — le mécanisme identifié par l'audit."""
    p = np.array([0.60, 0.20, 0.12, 0.05, 0.03])
    for e in (0.6, 0.8, 1.0, 1.2, 1.4):
        assert float(sc.appliquer(p, e).sum()) == pytest.approx(1.0, abs=1e-12)


def test_l_ordre_intra_course_ne_bouge_jamais():
    """Une puissance est croissante : le classement affiché, le rang prédit et
    l'ordre des value bets sont identiques au partant près. Seules les VALEURS
    changent — précisément ce que l'alerte dit faussé."""
    rng = np.random.default_rng(7)
    for _ in range(50):
        p = rng.random(12)
        p = p / p.sum()
        attendu = np.argsort(-p)
        for e in (0.5, 0.7, 0.95, 1.05, 1.3, 1.5):
            assert np.array_equal(np.argsort(-sc.appliquer(p, e)), attendu)


def test_un_exposant_sous_un_aplatit_le_favori_et_remonte_le_champ():
    p = np.array([0.44, 0.20, 0.16, 0.12, 0.08])
    q = sc.appliquer(p, 0.8)
    assert q[0] < p[0]           # le favori descend
    assert q[-1] > p[-1]         # la queue remonte
    assert float(q.sum()) == pytest.approx(1.0)


def test_la_composition_des_exposants_est_exacte():
    """(p^a)^b = p^(ab), et la renormalisation commute avec la puissance.

    C'est ce qui autorise à ajuster sur la proba SERVIE — qui porte déjà l'exposant
    en vigueur — puis à composer, au lieu de chasser son propre résidu."""
    p = np.array([0.5, 0.25, 0.15, 0.10])
    en_deux_temps = sc.appliquer(sc.appliquer(p, 0.9), 1.1)
    d_un_coup = sc.appliquer(p, 0.9 * 1.1)
    assert np.allclose(en_deux_temps, d_un_coup, atol=1e-12)


def test_l_exposant_est_borne_meme_si_on_lui_en_demande_un_absurde():
    p = np.array([0.5, 0.3, 0.2])
    assert np.allclose(sc.appliquer(p, 9.0), sc.appliquer(p, sc.EXPOSANT_MAX))
    assert np.allclose(sc.appliquer(p, 0.01), sc.appliquer(p, sc.EXPOSANT_MIN))


def test_une_entree_degeneree_ne_leve_jamais():
    """Appelée sur CHAQUE course servie : elle ne doit jamais casser un pronostic."""
    assert sc.appliquer(np.array([]), 0.8).size == 0
    assert np.array_equal(sc.appliquer(np.array([0.0, 0.0]), 0.8),
                          np.array([0.0, 0.0]))
    p = np.array([0.6, 0.4])
    assert np.array_equal(sc.appliquer(p, float("nan")), p)
    assert np.array_equal(sc.appliquer(p, "n'importe quoi"), p)


# ── L'ajustement, et ce qu'il refuse ──────────────────────────────────────────

def _courses_trop_pointues(n=1200, graine=3):
    """Courses dont la proba servie est trop CONCENTRÉE sur le favori.

    On tire la vérité (p_vrai), on tire le gagnant SOUS p_vrai, et on sert
    p_vrai^1,25 renormalisée. L'exposant qui répare est donc 1/1,25 = 0,8, et il
    existe une réponse connue à retrouver — pas une préférence esthétique.
    """
    rng = np.random.default_rng(graine)
    courses = []
    for _ in range(n):
        k = int(rng.integers(8, 16))
        vrai = rng.dirichlet(np.full(k, 0.7))
        gagnant = int(rng.choice(k, p=vrai))
        servi = vrai ** 1.25
        courses.append((servi / servi.sum(), gagnant))
    return courses


def test_l_ajustement_retrouve_l_exposant_qui_repare():
    verdict = sc.ajuster_exposant(_courses_trop_pointues())
    assert verdict["retenu"] is True
    # 0,8 est la valeur exacte ; la grille a un pas de 0,02 et l'échantillon du bruit.
    assert verdict["exposant"] == pytest.approx(0.8, abs=0.08)
    assert verdict["gain_logv"] > 0


def test_l_ajustement_redresse_l_ecart_de_la_bande_haute():
    """Le critère de l'alerte, mesuré avant/après sur la part de validation."""
    courses = _courses_trop_pointues()
    avant, n_avant = sc.ecart_bande_haute(courses, 1.0)
    apres, _ = sc.ecart_bande_haute(courses, sc.ajuster_exposant(courses)["exposant"])
    assert n_avant > 0
    assert avant > 0                      # sur-confiance de départ
    assert abs(apres) < abs(avant)        # et elle diminue


def test_une_distribution_deja_juste_ne_bouge_pas():
    """Le risque symétrique : corriger ce qui n'a pas besoin de l'être."""
    rng = np.random.default_rng(11)
    courses = []
    for _ in range(1200):
        k = int(rng.integers(8, 16))
        vrai = rng.dirichlet(np.full(k, 0.7))
        courses.append((vrai, int(rng.choice(k, p=vrai))))
    verdict = sc.ajuster_exposant(courses)
    # Soit on ne retient rien, soit on retient un exposant à peine distinct de 1.
    assert verdict["retenu"] is False or verdict["exposant"] == pytest.approx(1.0, abs=0.06)


def test_sans_part_de_validation_on_ne_conclut_pas():
    assert sc.ajuster_exposant([])["retenu"] is False


def test_l_exposant_en_place_est_conserve_quand_la_mesure_ne_conclut_pas():
    """Un refus ne doit jamais RÉINITIALISER une correction déjà prouvée."""
    verdict = sc.ajuster_exposant([], exposant_en_place=0.85)
    assert verdict["retenu"] is False and verdict["exposant"] == 0.85


# ── Le tour complet, sur base ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demarrage_a_froid_ne_touche_a_rien(db):
    """Base vide : aucune table, aucun exposant, et surtout aucune exception."""
    out = await sc.calculer_et_persister(db)
    assert out["status"] == "skipped_insufficient_data"
    assert out["exposant"] == sc.EXPOSANT_NEUTRE


@pytest.mark.asyncio
async def test_l_exposant_persiste_est_relu_et_mis_en_cache(db):
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS sharpness_calibration (
            id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TIMESTAMP)
    """))
    await db.execute(
        text("INSERT INTO sharpness_calibration (id, data) VALUES (1, :d)"),
        {"d": json.dumps({"exposant": 0.86, "retenu": True})})
    await db.commit()

    charge = await sc.charger_exposant(db)
    assert charge["exposant"] == 0.86
    # L'inférence lit un cache mémoire, sans base : c'est ce chemin qui sert.
    assert sc.exposant_en_cache() == 0.86
    sc._cache = None
