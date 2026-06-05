"""
Tests boucle causale → poids de features (Phase 3 complète).
"""
from ml.adaptive_learning import (
    AdaptiveLearning, causal_weight_nudges, WEIGHT_CLIP, DEFAULT_FEATURE_WEIGHTS,
)


def test_nudge_favori_faiblit_touche_dynamique_et_confrontation():
    n = causal_weight_nudges([{"tag": "favori_faiblit"}])
    assert "dynamique" in n
    assert "confrontation" in n
    assert all(0 < v <= WEIGHT_CLIP for v in n.values())


def test_nudge_tag_inconnu_ignore():
    assert causal_weight_nudges([{"tag": "tag_bidon"}]) == {}
    assert causal_weight_nudges([]) == {}


def test_nudge_agrege_et_borne():
    # Plusieurs tags poussant "dynamique" → cumulé mais borné à WEIGHT_CLIP.
    n = causal_weight_nudges([
        {"tag": "gagnant_finit_fort"},
        {"tag": "train_lent_sprint_final"},
        {"tag": "favori_faiblit"},
    ])
    assert n["dynamique"] == WEIGHT_CLIP   # plafonné


def test_nudge_accepte_tags_strings():
    n = causal_weight_nudges(["surprise_outsider"])
    assert "signaux_avances" in n


def test_update_feature_weights_applique_nudge_hors_surprise():
    al = AdaptiveLearning()
    w0 = al.feature_weights["dynamique"]
    updates = al._update_feature_weights(
        {"causal_tags": [{"tag": "gagnant_finit_fort"}]},
        was_surprise=False,   # même sans surprise, le nudge causal s'applique
    )
    assert "dynamique" in updates
    assert al.feature_weights["dynamique"] > w0


def test_update_feature_weights_sans_causal_hors_surprise_ne_change_rien():
    al = AdaptiveLearning()
    w0 = dict(al.feature_weights)
    updates = al._update_feature_weights({}, was_surprise=False)
    assert updates == {}
    assert al.feature_weights == w0


def test_nouveaux_groupes_presents():
    assert "dynamique" in DEFAULT_FEATURE_WEIGHTS
    assert "confrontation" in DEFAULT_FEATURE_WEIGHTS
