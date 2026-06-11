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
