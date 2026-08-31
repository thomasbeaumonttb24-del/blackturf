"""
Invariant produit : la calibration ne doit pas EFFACER l'écart entre deux chevaux.

Cause racine mesurée le 2026-08-31 : l'isotone classique est une fonction en escalier
(courbe prod : 62 points de rupture pour 31 `y` distincts). Deux chevaux d'une même
course dont la proba modèle diffère de 25 % en relatif ressortaient avec exactement la
même proba calibrée, donc la même « cote juste » affichée. Sur 7 jours de prod : 10.99
probas distinctes en brut pour 11.06 partants → 6.70 après calibration.
"""
import numpy as np
import pytest

from ml.isotonic_utils import centered_isotonic_curve, restore_within_race_order
from ml.isotonic_calibration import apply_calibration
from services.cote_juste import cote_juste


def _jeu_realiste(n=4000, seed=7):
    """Probas + issues binaires cohérentes (la fréquence suit la proba, avec du bruit)."""
    rng = np.random.default_rng(seed)
    x = rng.beta(1.4, 12.0, size=n)          # beaucoup d'outsiders, peu de favoris
    y = (rng.random(n) < np.clip(x * 0.85, 0, 1)).astype(float)
    return x, y


def test_courbe_cir_strictement_croissante():
    x, y = _jeu_realiste()
    c = centered_isotonic_curve(x, y)
    assert c["x"], "le fit doit produire une courbe sur 4000 observations"
    ys = np.asarray(c["y"], dtype=float)
    xs = np.asarray(c["x"], dtype=float)
    assert np.all(np.diff(xs) > 0), "abscisses strictement croissantes"
    assert np.all(np.diff(ys) > 0), "AUCUN palier : c'est tout l'objet du CIR"
    assert len(np.unique(ys)) == len(ys)


def test_pas_de_quasi_palier():
    """Un pas strictement positif ne suffit pas : un y qui bouge de 1e-4 quand x
    bouge de 40 % est un palier déguisé, invisible à l'affichage. Régression du
    lissage bloc-par-bloc qui cassait la monotonie de PAVA (mesuré en prod : x de
    0.0473 à 0.0675 pour 0,02 % de y)."""
    x, y = _jeu_realiste()
    c = centered_isotonic_curve(x, y)
    xs = np.asarray(c["x"], dtype=float)
    ys = np.asarray(c["y"], dtype=float)
    dx = np.diff(xs) / xs[:-1]
    dy = np.diff(ys) / ys[:-1]
    suspects = [(float(xs[i]), float(dx[i]), float(dy[i]))
                for i in range(len(dx)) if dx[i] > 0.10 and dy[i] < 0.001]
    assert not suspects, f"quasi-paliers (x bouge >10 %, y <0,1 %) : {suspects}"


def test_cir_conserve_lordre_et_la_distinction_intra_course():
    """Douze probas distinctes en entrée → douze probas distinctes en sortie, même ordre."""
    x, y = _jeu_realiste()
    curve = centered_isotonic_curve(x, y)
    curve["n_obs"] = len(x)

    champ = np.array([0.31, 0.18, 0.093, 0.071, 0.062, 0.058,
                      0.047, 0.0455, 0.0447, 0.031, 0.018, 0.009])
    sortie = apply_calibration(champ, curve)

    assert len(np.unique(np.round(sortie, 12))) == len(champ), "aucun ex æquo fabriqué"
    assert list(np.argsort(-sortie)) == list(np.argsort(-champ)), "ordre préservé"
    assert abs(float(sortie.sum()) - 1.0) < 1e-9, "Σ = 1 (un seul gagnant)"


def test_escalier_ne_produit_plus_dex_aequo_affiches():
    """Filet : même avec une courbe EN ESCALIER encore en base, deux chevaux que le
    modèle sépare ne doivent pas ressortir avec la même cote juste."""
    escalier = {  # palier réel relevé en prod
        "x": [0.0, 0.036317, 0.047025, 0.047026, 1.0],
        "y": [0.0, 0.042435, 0.042435, 0.052632, 0.60],
        "n_obs": 6329,
    }
    champ = np.array([0.30, 0.20, 0.0463, 0.0442, 0.0398, 0.0372])
    sortie = apply_calibration(champ, escalier)

    justes = [cote_juste(float(p)) for p in sortie]
    assert len(set(justes)) == len(justes), f"cotes justes en doublon : {justes}"
    assert list(np.argsort(-sortie)) == list(np.argsort(-champ)), "ordre préservé"


def test_ex_aequo_reels_restent_ex_aequo():
    """On répare un artefact de palier — on n'invente jamais un écart absent du modèle."""
    source = np.array([0.10, 0.10, 0.05, 0.02])
    mapped = np.array([0.12, 0.12, 0.06, 0.03])
    out = restore_within_race_order(mapped, source)
    assert out[0] == out[1], "deux chevaux identiques pour le modèle restent identiques"


def test_restore_ne_franchit_pas_les_voisins():
    source = np.array([0.101, 0.100, 0.0999])
    mapped = np.array([0.12, 0.12, 0.1199])
    out = restore_within_race_order(mapped, source)
    assert out[0] > out[1] > out[2], "l'étalement ne doit pas doubler le voisin du dessous"


@pytest.mark.parametrize(
    "proba,attendu",
    [
        (0.25, 4.0),      # < 10 → 2 décimales
        (0.2439, 4.1),
        (0.0621, 16.1),   # 10–100 → 1 décimale
        (0.0457, 21.9),
        (0.0045, 222.0),  # ≥ 100 → entier (l'ancien plafond 100 écrasait tout ici)
        (0.0005, None),   # sous le seuil : non chiffrable, pas une valeur inventée
    ],
)
def test_precision_cote_juste(proba, attendu):
    assert cote_juste(proba) == attendu


def test_cote_juste_separe_deux_favoris_proches():
    """À 1 décimale fixe, 4.12 et 4.14 s'affichaient tous les deux « 4.1 »."""
    assert cote_juste(1 / 4.12) != cote_juste(1 / 4.14)
