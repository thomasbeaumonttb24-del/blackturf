"""Le motif de promotion doit dire la vérité sur ce qui a emporté la décision.

Régression protégée (2026-08-31) : le libellé `reason` du log `retrain.deployed` était
écrit sans jamais comparer les walk-forward. Hors remplacement structurel, il retombait
sur « better_wf » — y compris quand le nouveau modèle était PIRE. Trois nuits sur quatre
ont ainsi été promues en baisse (0.7884→0.7883, 0.7883→0.7873, 0.7878→0.7869) et
rapportées comme des améliorations, le rapport matinal lisant ce champ.

Ces tests ne portent PAS sur la décision de promotion (voir test_deploy_gate*) : ils
verrouillent uniquement le fait qu'une régression tolérée ne puisse plus se faire passer
pour un progrès.
"""
import pytest

from ml.pipeline import _motif_promotion


def _motif(**kw):
    base = dict(
        new_wf=0.79,
        current_wf=0.78,
        current_is_synth=False,
        current_unreliable=False,
        data_jump=False,
        h2h_delta=None,
    )
    base.update(kw)
    return _motif_promotion(**base)


class TestReplisWalkForward:
    """Sans head-to-head mesurable — le régime réel de toutes les nuits observées."""

    def test_walk_forward_en_hausse_est_une_amelioration(self):
        assert _motif(new_wf=0.7900, current_wf=0.7878) == "better_wf"

    def test_walk_forward_en_baisse_n_est_pas_une_amelioration(self):
        # La nuit du 31/08 exactement : promue, mais en baisse.
        assert _motif(new_wf=0.7869, current_wf=0.7878) == "regression_toleree_wf"

    def test_baisse_infime_reste_une_regression(self):
        # -0.0001 : sous le seuil de tolérance, donc promu — mais nommé pour ce
        # qu'il est. C'est le cumul de ces micro-baisses qui constitue la dérive.
        assert _motif(new_wf=0.7883, current_wf=0.7884) == "regression_toleree_wf"

    def test_egalite_compte_comme_non_regressive(self):
        assert _motif(new_wf=0.7878, current_wf=0.7878) == "better_wf"


class TestHeadToHead:
    """Quand l'arbitre honnête a pu être mesuré, c'est lui qui nomme la décision."""

    def test_delta_positif(self):
        assert _motif(h2h_delta=0.004) == "better_h2h"

    def test_delta_nul(self):
        assert _motif(h2h_delta=0.0) == "better_h2h"

    def test_delta_negatif_tolere(self):
        assert _motif(h2h_delta=-0.001) == "regression_toleree_h2h"

    def test_h2h_prime_sur_le_walk_forward(self):
        # wf en hausse mais head-to-head en baisse : c'est le h2h qui fait foi,
        # comme dans `_should_deploy`. Sinon le libellé contredirait la décision.
        assert _motif(new_wf=0.80, current_wf=0.78, h2h_delta=-0.001) == (
            "regression_toleree_h2h"
        )


class TestRemplacementStructurel:
    """Le remplacement structurel court-circuite le mérite de ranking : il doit donc
    se nommer en premier, sans quoi le motif contredirait `_should_deploy`."""

    @pytest.mark.parametrize(
        "drapeau,attendu",
        [
            ("current_is_synth", "synth"),
            ("current_unreliable", "unreliable_active"),
            ("data_jump", "data_jump"),
        ],
    )
    def test_drapeau_structurel_prime(self, drapeau, attendu):
        # Walk-forward en BAISSE : sans la priorité structurelle on lirait
        # « regression_toleree_wf » alors que ce n'est pas ce qui a décidé.
        assert _motif(new_wf=0.70, current_wf=0.78, **{drapeau: True}) == attendu

    def test_ordre_synth_avant_unreliable(self):
        assert _motif(current_is_synth=True, current_unreliable=True) == "synth"
