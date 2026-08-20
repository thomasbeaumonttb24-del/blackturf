"""
Tests du garde-fou de promotion modèle — BlackTurf.

Garantit qu'un modèle sous-aléatoire (ex. walk-forward AUC 0.06, le bug réel qui a
mis un modèle cassé en prod) n'est JAMAIS déployé, même quand l'actif est "non fiable".
"""
import pytest

from ml.pipeline import _should_deploy, MIN_DEPLOYABLE_AUC


# ── Le plancher absolu prime sur tout ──────────────────────────────────

@pytest.mark.parametrize("flag", [
    "current_is_synth", "no_current", "current_unreliable", "data_jump",
])
def test_plancher_bloque_meme_si_actif_remplacable(flag):
    """AUC 0.06 (le bug) ne passe JAMAIS, quelle que soit la raison de promotion."""
    kwargs = dict(
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
    )
    kwargs[flag] = True
    assert _should_deploy(0.06, current_wf=0.0, **kwargs) is False


def test_plancher_bloque_meme_si_meilleur_que_actif_cassé():
    """new_wf 0.40 > current 0.06 mais < plancher → bloqué."""
    assert _should_deploy(
        0.40, current_wf=0.06,
        current_is_synth=False, no_current=False,
        current_unreliable=True, data_jump=False,
    ) is False


def test_juste_sous_plancher_bloque():
    assert _should_deploy(
        MIN_DEPLOYABLE_AUC - 0.001, current_wf=0.0,
        current_is_synth=True, no_current=True,
        current_unreliable=True, data_jump=True,
    ) is False


# ── Au-dessus du plancher : logique de promotion normale ───────────────

def test_deploie_si_actif_synthetique():
    assert _should_deploy(
        0.70, current_wf=0.99,
        current_is_synth=True, no_current=False,
        current_unreliable=False, data_jump=False,
    ) is True


def test_deploie_si_pas_de_modele_actif():
    assert _should_deploy(
        0.55, current_wf=0.0,
        current_is_synth=False, no_current=True,
        current_unreliable=False, data_jump=False,
    ) is True


def test_deploie_si_actif_non_fiable_et_modele_sain():
    """Actif <800 courses + nouveau modèle sain (≥ plancher) → on remplace."""
    assert _should_deploy(
        0.60, current_wf=0.85,
        current_is_synth=False, no_current=False,
        current_unreliable=True, data_jump=False,
    ) is True


def test_deploie_si_walk_forward_au_moins_aussi_bon():
    assert _should_deploy(
        0.80, current_wf=0.80,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
    ) is True


def test_rollback_si_regression_sans_excuse():
    """Nouveau pire que l'actif, actif fiable, pas de saut de données → on garde l'actif."""
    assert _should_deploy(
        0.70, current_wf=0.85,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
    ) is False


def test_tolerance_regression_0_5pct():
    """0.5% de régression tolérée."""
    assert _should_deploy(
        0.845, current_wf=0.85,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
    ) is True


# ── Gate ROI : ne fige pas une amélioration de ranking (régression 2026-06-19) ──

def test_roi_gate_bloque_si_edge_mauvais_et_pas_d_amelioration():
    """Edge paris KO + nouveau modèle PAS meilleur en ranking → on garde l'actif."""
    assert _should_deploy(
        0.80, current_wf=0.805,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        roi_gate_enabled=True, betting_edge_ok=False,
    ) is False


def test_roi_gate_ne_fige_pas_une_amelioration_de_ranking():
    """Régression réelle du 2026-06-19 : wf 0.8165 > 0.8141 mais edge KO → DOIT déployer.

    La gate ROI (couche paris) ne doit pas geler un meilleur classeur (couche modèle).
    """
    assert _should_deploy(
        0.8165, current_wf=0.8141,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        roi_gate_enabled=True, betting_edge_ok=False,
    ) is True


def test_roi_gate_inactif_n_a_aucun_effet():
    """roi_gate_enabled=False (défaut) : edge ignoré, logique wf normale."""
    assert _should_deploy(
        0.80, current_wf=0.805,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        roi_gate_enabled=False, betting_edge_ok=False,
    ) is True


# ── Gate ROI : ne fige pas un REMPLACEMENT STRUCTUREL (régression 2026-06-29) ──

def test_roi_gate_ne_fige_pas_un_data_jump():
    """Régression réelle du 2026-06-29 : modèle 18 mois (data_jump, ~2.5x data, wf
    0.8104) bloqué par v502 (fenêtre courte, wf gonflé 0.8217) car edge KO + wf non
    amélioré → la gate ROI court-circuitait `data_jump`. DOIT déployer : un modèle
    entraîné sur beaucoup plus de données remplace un actif sur-ajusté.
    """
    assert _should_deploy(
        0.8104, current_wf=0.8217,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=True,
        roi_gate_enabled=True, betting_edge_ok=False,
    ) is True


def test_roi_gate_ne_fige_pas_un_actif_non_fiable():
    """Actif <800 courses + edge KO + wf non amélioré → remplacement structurel autorisé."""
    assert _should_deploy(
        0.75, current_wf=0.90,
        current_is_synth=False, no_current=False,
        current_unreliable=True, data_jump=False,
        roi_gate_enabled=True, betting_edge_ok=False,
    ) is True


def test_roi_gate_bloque_toujours_une_regression_sans_structurel():
    """Garde-fou préservé : edge KO + pas d'amélioration ranking + AUCUN signal
    structurel (pas de data_jump / unreliable / synth) → on garde l'actif.
    """
    assert _should_deploy(
        0.80, current_wf=0.82,
        current_is_synth=False, no_current=False,
        current_unreliable=False, data_jump=False,
        roi_gate_enabled=True, betting_edge_ok=False,
    ) is False


# ── Gate marché (diagnostic 2026-08-20) ─────────────────────────────────
# Le gate ne confrontait le challenger qu'au champion précédent. Deux modèles
# sous le niveau d'un simple `ORDER BY cote_pmu` pouvaient donc se succéder
# indéfiniment : mesuré, c'est ce qui s'est produit sur 513 versions, le modèle
# complet étant à 0,7340 d'AUC intra-course contre 0,7351 pour la cote.

BASE_SAINE = dict(
    current_wf=0.70, current_is_synth=False, no_current=False,
    current_unreliable=False, data_jump=False,
)


def test_gate_marche_bloque_un_modele_sous_la_cote():
    assert _should_deploy(
        0.75, market_gate_enabled=True, rank_delta_market=-0.0011, **BASE_SAINE,
    ) is False


def test_gate_marche_laisse_passer_un_modele_au_dessus():
    assert _should_deploy(
        0.75, market_gate_enabled=True, rank_delta_market=+0.0011, **BASE_SAINE,
    ) is True


def test_gate_marche_prime_sur_un_remplacement_structurel():
    """Promouvoir un modèle sous la cote au motif que l'actif est synthétique
    reviendrait à remplacer un mauvais classeur par un autre."""
    for motif in ("current_is_synth", "no_current", "current_unreliable", "data_jump"):
        kwargs = dict(BASE_SAINE)
        kwargs[motif] = True
        assert _should_deploy(
            0.75, market_gate_enabled=True, rank_delta_market=-0.02, **kwargs,
        ) is False, motif


def test_gate_marche_inactif_par_defaut_ne_gele_pas_le_modele():
    """DÉFAUT OFF assumé : aucun modèle actuel ne bat la cote. Activer le gate
    aujourd'hui figerait l'apprentissage — exactement le blocage de 48 jours de
    l'audit 2026-08-16, qu'on ne rejoue pas."""
    assert _should_deploy(0.75, rank_delta_market=-0.02, **BASE_SAINE) is True


def test_mesure_impossible_ne_bloque_pas():
    """`None` = pas de cote exploitable sur le hold-out. Une absence de mesure
    n'est pas une preuve d'échec : bloquer dessus figerait le modèle sur une
    simple panne de collecte de cotes."""
    assert _should_deploy(
        0.75, market_gate_enabled=True, rank_delta_market=None, **BASE_SAINE,
    ) is True


def test_marge_exigible_au_dessus_de_la_simple_egalite():
    kwargs = dict(BASE_SAINE)
    assert _should_deploy(0.75, market_gate_enabled=True, rank_delta_market=0.005,
                          market_gate_margin=0.01, **kwargs) is False
    assert _should_deploy(0.75, market_gate_enabled=True, rank_delta_market=0.02,
                          market_gate_margin=0.01, **kwargs) is True


def test_plancher_absolu_prime_toujours_sur_le_gate_marche():
    """Un modèle sous MIN_DEPLOYABLE_AUC reste refusé même s'il bat la cote."""
    assert _should_deploy(
        0.06, market_gate_enabled=True, rank_delta_market=+0.5, **BASE_SAINE,
    ) is False
