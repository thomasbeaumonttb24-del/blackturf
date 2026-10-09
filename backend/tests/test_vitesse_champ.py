"""Atouts de vitesse lus contre les adversaires du jour (narrative._ajoute_vitesse_champ)."""
from ml.narrative import _ajoute_vitesse_champ, _fmt_reduction


def _champ(feats):
    enriched = [{"participation_id": f"p{i}", "numero": i + 1,
                 "explanation": {"facteurs_positifs": [], "facteurs_negatifs": []}}
                for i in range(len(feats))]
    return enriched, {f"p{i}": f for i, f in enumerate(feats)}


def _labels(e, cle="facteurs_positifs"):
    return [f["label"] for f in e["explanation"][cle]]


def test_plus_rapide_du_champ_sur_les_deux_figures():
    feats = [{"speed_figure_best": 1.10 - i * 0.01, "speed_figure_recent": 1.05 - i * 0.01,
              "nb_speed_figures": 3} for i in range(6)]
    enriched, fb = _champ(feats)
    _ajoute_vitesse_champ(enriched, fb)
    assert _labels(enriched[0]) == ["Le plus rapide du champ"]
    assert _labels(enriched[5], "facteurs_negatifs") == ["Le moins rapide du champ"]
    assert all(not _labels(e) for e in enriched[1:])


def test_egalite_en_tete_pas_d_atout():
    feats = [{"speed_figure_best": 1.10, "nb_speed_figures": 2}] * 2 + \
            [{"speed_figure_best": 1.0 - i * 0.01, "nb_speed_figures": 2} for i in range(3)]
    enriched, fb = _champ(feats)
    _ajoute_vitesse_champ(enriched, fb)
    assert not _labels(enriched[0]) and not _labels(enriched[1])


def test_sans_chrono_ignore_et_champ_trop_petit():
    feats = [{"speed_figure_best": 1.0, "nb_speed_figures": 0}] * 5 + \
            [{"speed_figure_best": 1.2, "nb_speed_figures": 2}] * 3
    enriched, fb = _champ(feats)
    _ajoute_vitesse_champ(enriched, fb)  # 3 chronos seulement : pas de classement
    assert all(not _labels(e) for e in enriched)


def test_reduction_km_plus_basse_gagne():
    feats = [{"dyn_reduction_km_moy": 74.0 + i} for i in range(5)] + [{"dyn_reduction_km_moy": 0.0}]
    enriched, fb = _champ(feats)
    _ajoute_vitesse_champ(enriched, fb)
    assert _labels(enriched[0]) == ["Meilleure réduction km du champ"]
    assert "1'14\"0" in enriched[0]["explanation"]["facteurs_positifs"][0]["detail"]
    assert not _labels(enriched[5])


def test_vitesse_relative_contradictoire_retiree():
    feats = [{"speed_figure_best": 1.2 - i * 0.02, "nb_speed_figures": 2} for i in range(5)]
    enriched, fb = _champ(feats)
    enriched[0]["explanation"]["facteurs_negatifs"].append(
        {"feature": "vitesse_relative", "label": "Vitesse en retrait", "score": 0.3})
    _ajoute_vitesse_champ(enriched, fb)
    assert _labels(enriched[0], "facteurs_negatifs") == []


def test_fmt_reduction():
    assert _fmt_reduction(75.3) == "1'15\"3"
    assert _fmt_reduction(74.96) == "1'15\"0"
