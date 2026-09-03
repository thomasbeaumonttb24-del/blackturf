"""
Cliquet anti-dérive de la promotion nocturne (2026-09-03).

Le défaut corrigé était nommé depuis le 2026-08-31 et laissé ouvert : le gate
tolère une régression de 0,002 par nuit CONTRE LE CHAMPION DE LA VEILLE, jamais
contre le meilleur niveau jamais atteint. Chaque nuit passe donc sous le seuil et
la dérive s'accumule indéfiniment. Mesuré en production du 25 au 31/08 :

    classement    0,7632 → 0,7608      walk-forward  0,7886 → 0,7869

sept nuits, aucune ne dépassant la tolérance, toutes promues, et le rapport
matinal annonçant chaque matin une amélioration.

Le témoin négatif de ce fichier est `test_derive_lente_sept_nuits` : il rejoue
exactement cette séquence et prouve que l'ANCIEN critère l'accepte en entier là
où le nouveau la coupe à la première nuit.
"""
import pytest

from ml.pipeline import H2H_TOLERANCE, _nouvelle_dette, _should_deploy


# Contexte neutre : ni remplacement structurel, ni gate ROI, ni gate marché.
# Seul le mérite de ranking décide, ce qui est exactement ce qu'on teste.
NEUTRE = dict(
    current_is_synth=False,
    no_current=False,
    current_unreliable=False,
    data_jump=False,
)


def _promu(delta, dette=0.0, **extra):
    return _should_deploy(0.786, 0.786, h2h_delta=delta, dette_h2h=dette,
                          **{**NEUTRE, **extra})


# ── La dette elle-même ───────────────────────────────────────────────────────

def test_dette_cumule_les_regressions():
    assert _nouvelle_dette(0.0, -0.0015) == pytest.approx(-0.0015)
    assert _nouvelle_dette(-0.0015, -0.0015) == pytest.approx(-0.0030)


def test_une_nuit_meilleure_rembourse():
    assert _nouvelle_dette(-0.0030, 0.0010) == pytest.approx(-0.0020)


def test_dette_jamais_creditrice():
    """Un bon soir ne doit pas ACHETER le droit de reculer les suivants.

    Sans le plafond à 0, un challenger à +0,05 ouvrirait un crédit qui laisserait
    ensuite passer vingt-cinq nuits de régression : le cliquet ne cliquetterait
    plus, il compterait juste la moyenne.
    """
    assert _nouvelle_dette(-0.0030, 0.0500) == 0.0
    assert _nouvelle_dette(0.0, 0.0200) == 0.0


def test_dette_inchangee_sans_head_to_head():
    """Promotion décidée sur le walk-forward : rien à cumuler.

    Le walk-forward ré-entraîne un modèle jetable sur des folds du dataset
    COURANT : il mesure le dataset autant que le modèle. Y accumuler une dette
    reviendrait à cliqueter sur la dérive des DONNÉES.
    """
    assert _nouvelle_dette(-0.0030, None) == pytest.approx(-0.0030)


# ── Le gate ──────────────────────────────────────────────────────────────────

def test_dette_nulle_ne_change_rien():
    """Témoin de non-régression : à dette nulle, le critère est celui d'avant.

    Le cliquet ne doit pas resserrer le gate en régime sain, sinon il rejouerait
    le gel de 48 jours de l'audit 2026-08-16 sous un autre nom.
    """
    for delta in (0.01, 0.0, -0.001, -H2H_TOLERANCE, -0.0021, -0.05):
        assert _promu(delta, dette=0.0) is (delta >= -H2H_TOLERANCE)


def test_derive_lente_sept_nuits():
    """TÉMOIN NÉGATIF — la séquence de production du 25 au 31/08.

    Sept nuits à −0,0015 : chacune sous la tolérance de 0,002, donc chacune
    acceptée par l'ancien critère. Le cumul vaut −0,0105, soit cinq fois la
    tolérance que le gate croyait faire respecter.
    """
    nuits = [-0.0015] * 7

    # ANCIEN critère (dette toujours nulle) : les sept passent.
    assert all(_promu(d, dette=0.0) for d in nuits)

    # NOUVEAU : la dette court, et coupe dès que le cumul dépasse la tolérance.
    dette, promues = 0.0, 0
    for d in nuits:
        if _promu(d, dette=dette):
            promues += 1
            dette = _nouvelle_dette(dette, d)
    assert promues == 1, "une seule régression tolérée, pas sept"
    assert dette == pytest.approx(-0.0015)


def test_cliquet_laisse_passer_une_amelioration():
    """Le cliquet borne la DÉRIVE, il ne gèle pas le progrès.

    Distinction décisive avec le gel de 2026-08-16 : la référence n'y était jamais
    recalculée. Ici un challenger meilleur passe quelle que soit la dette.
    """
    assert _promu(0.0200, dette=-0.0100) is True
    assert _promu(0.0000, dette=-0.0100) is False


def test_remplacement_structurel_court_circuite_le_cliquet():
    """Un champion synthétique ou non fiable reste remplaçable, dette ou pas.

    Sans cette porte, une dette accumulée empêcherait de sortir d'un modèle de
    secours — le cliquet deviendrait un piège au lieu d'un garde-fou.
    """
    assert _promu(-0.05, dette=-0.02, current_is_synth=True) is True
    assert _promu(-0.05, dette=-0.02, current_unreliable=True) is True
    assert _promu(-0.05, dette=-0.02, no_current=True) is True


def test_plancher_absolu_reste_prioritaire():
    """MIN_DEPLOYABLE_AUC passe avant tout, y compris devant une dette nulle."""
    assert _should_deploy(0.40, 0.30, h2h_delta=0.05, dette_h2h=0.0,
                          **NEUTRE) is False


def test_dette_positive_traitee_comme_nulle():
    """Une dette positive lue en base (donnée corrompue) ne doit pas ÉLARGIR le gate.

    `min(0.0, dette)` dans le gate : une valeur aberrante rend le critère
    identique à l'ancien, jamais plus permissif.
    """
    assert _promu(-0.05, dette=+0.10) is False


# ── Classement de la proba SERVIE (mélange marché) ───────────────────────────
# Le head-to-head notait le modèle NU. Or le produit sert le mélange, et les deux
# ne donnent pas le même verdict : mesuré le 2026-09-02 sur 727 courses, le modèle
# nu perd contre la cote (−0,0114) quand la proba servie la bat (+0,0012).

import numpy as np  # noqa: E402

from ml.pipeline import _rang_melange  # noqa: E402
from ml.ranking_metrics import within_race_auc  # noqa: E402


def _jeu(n_courses=40, partants=8, graine=7):
    """Courses jouets : le MARCHÉ classe bien, le modèle classe au hasard."""
    rng = np.random.default_rng(graine)
    labels, probas, cotes, groupes = [], [], [], []
    for c in range(n_courses):
        gagnant = int(rng.integers(partants))
        for j in range(partants):
            labels.append(1.0 if j == gagnant else 0.0)
            probas.append(float(rng.random()))
            # Cote basse pour le vrai gagnant : un marché informatif.
            cotes.append(2.0 if j == gagnant else float(4 + j))
            groupes.append(c)
    return (np.array(labels), np.array(probas), np.array(cotes),
            np.array(groupes))


def test_melange_a_alpha_1_rend_exactement_le_modele():
    """TÉMOIN EXACT du branchement : à alpha = 1, le mélange EST le modèle.

    Toutes les cotes sont sous le seuil de décroissance (12), donc alpha vaut 1
    partout et la normalisation par course ne change aucun ordre. Si ce test
    échoue, le regroupement par course est faux — le défaut qui, autrement,
    passerait totalement inaperçu puisque la valeur resterait plausible.
    """
    labels, probas, cotes, groupes = _jeu()
    nu = within_race_auc(labels, probas, groupes)
    assert _rang_melange(labels, probas, cotes, groupes, 1.0) == pytest.approx(nu)


def test_melange_a_alpha_0_rend_exactement_le_marche():
    """L'autre borne : à alpha = 0, le mélange EST la cote."""
    from ml.ranking_metrics import market_scores_from_cotes
    labels, probas, cotes, groupes = _jeu()
    marche = within_race_auc(labels, market_scores_from_cotes(cotes), groupes)
    assert _rang_melange(labels, probas, cotes, groupes, 0.0) == pytest.approx(marche)


def test_melange_recupere_l_information_du_marche():
    """Modèle au hasard + marché informatif : le servi doit battre le nu."""
    labels, probas, cotes, groupes = _jeu()
    nu = within_race_auc(labels, probas, groupes)
    servi = _rang_melange(labels, probas, cotes, groupes, 0.42)
    assert servi > nu


def test_sans_cote_pas_de_mesure_servie():
    labels, probas, _, groupes = _jeu()
    assert _rang_melange(labels, probas, None, groupes, 0.42) is None


def test_entree_incoherente_ne_leve_jamais():
    """Contenu : cette mesure ne doit pas pouvoir ÉTEINDRE l'arbitrage.

    Elle est appelée dans le bloc dont l'exception vaut « head-to-head
    impossible » et fait retomber la promotion sur le walk-forward — que le
    pipeline déclare lui-même non comparable d'une génération à l'autre. Une
    mesure ajoutée pour éclairer ne doit jamais éteindre le gate.
    """
    labels, probas, cotes, groupes = _jeu()
    assert _rang_melange(labels, probas, cotes[:5], groupes, 0.42) is None
