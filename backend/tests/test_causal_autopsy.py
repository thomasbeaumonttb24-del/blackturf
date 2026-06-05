"""
Tests autopsie causale (Phase 3) — tags purs depuis dynamique de course.
"""
from ml.causal_autopsy import tag_race_causes


def _tags(*args, **kwargs):
    return {t["tag"] for t in tag_race_causes(*args, **kwargs)}


def test_gagnant_mene_bout_en_bout():
    # Gagnant #5 en tête à 500m (pos 1) et gagne.
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 3: 2, 7: 3},
        pos500_by_num={5: 1, 3: 2, 7: 3},
    )
    assert "gagnant_mene_bout_en_bout" in tags


def test_gagnant_finit_fort():
    # Gagnant #5 était 6e à 500m → vient de loin.
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 3: 2, 7: 3, 1: 4},
        pos500_by_num={5: 6, 3: 1, 7: 2, 1: 3},
    )
    assert "gagnant_finit_fort" in tags


def test_favori_faiblit():
    # Favori IA #3 bien placé à 500m (2e) mais fini 7e.
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 8: 2, 9: 3, 3: 7},
        pos500_by_num={3: 2, 5: 3, 8: 4, 9: 5},
        proba_by_num={3: 0.55, 5: 0.20, 8: 0.10, 9: 0.10},
    )
    assert "favori_faiblit" in tags


def test_favori_jamais_dans_le_coup():
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 8: 2, 9: 3, 3: 8},
        pos500_by_num={3: 7, 5: 1, 8: 2, 9: 3},
        proba_by_num={3: 0.50, 5: 0.25, 8: 0.15, 9: 0.10},
    )
    assert "favori_jamais_dans_le_coup" in tags


def test_surprise_outsider():
    tags = _tags(
        winner_num=11,
        position_reelle={11: 1, 3: 2, 5: 3},
        proba_by_num={11: 0.08, 3: 0.40, 5: 0.30},
    )
    assert "surprise_outsider" in tags


def test_train_lent_sprint_final():
    # Plusieurs chevaux remontent ≥3 places, dont le gagnant.
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 8: 2, 3: 3, 1: 4, 2: 5},
        pos500_by_num={5: 5, 8: 6, 3: 7, 1: 1, 2: 2},
    )
    assert "train_lent_sprint_final" in tags


def test_aucun_tag_sans_donnees_dynamique():
    # Sans pos500 ni proba : favori inconnu, pas de dynamique → liste vide.
    tags = _tags(
        winner_num=5,
        position_reelle={5: 1, 3: 2, 7: 3},
    )
    assert tags == set()


def test_incident_gagnant_absent_pas_de_crash():
    tags = tag_race_causes(winner_num=None, position_reelle={})
    assert tags == []
