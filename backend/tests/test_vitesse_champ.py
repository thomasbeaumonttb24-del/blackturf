"""Atouts de vitesse lus contre les adversaires du jour (narrative._ajoute_vitesse_champ).

Les chiffres des cas « Hyères » viennent des performances détaillées PMU du
09/10 (R3C1), contre lesquelles la première version s'est révélée fausse."""
from ml.narrative import _ajoute_vitesse_champ, _fmt_reduction


def _champ(n):
    return [{"participation_id": f"p{i}", "numero": i + 1,
             "explanation": {"facteurs_positifs": [], "facteurs_negatifs": []}}
            for i in range(n)]


def _labels(e, cle="facteurs_positifs"):
    return [f["label"] for f in e["explanation"][cle]]


def _r(*mmss):
    """1'15"1 → 75.1 ; les sorties de la plus récente à la plus ancienne."""
    return [int(x.split("'")[0]) * 60 + float(x.split("'")[1].replace('"', ".")) for x in mmss]


# Hyères R3C1, 09/10, réductions PMU réelles des 5 dernières sorties.
HYERES_R3C1 = {
    1: _r("1'15\"1", "1'13\"4", "1'19\"8"),
    2: _r("1'19\"0", "1'16\"4", "1'16\"1", "1'15\"7"),
    3: _r("1'18\"9", "1'16\"3", "1'18\"9", "1'14\"9"),
    4: _r("1'20\"3", "1'15\"9", "1'13\"5", "1'16\"2", "1'16\"3"),
    5: _r("1'15\"2", "1'17\"8", "1'15\"5", "1'16\"4", "1'15\"3"),
    6: _r("1'16\"5", "1'17\"2", "1'15\"0", "1'16\"5"),
    7: _r("1'16\"1", "1'15\"2", "1'20\"0", "1'16\"5", "1'20\"9"),
    8: _r("1'16\"8", "1'16\"8", "1'14\"7"),
    9: _r("1'18\"1", "1'18\"8", "1'20\"4", "1'20\"7", "1'15\"7"),
}


def test_hyeres_r3c1_conforme_au_pmu():
    enriched = _champ(9)
    _ajoute_vitesse_champ(enriched, HYERES_R3C1, "Attelé")
    lab = {e["numero"]: _labels(e) for e in enriched}
    # Moyenne : n°5 1'16"0 devant n°1 1'16"1. Meilleur chrono et dernière sortie : n°1.
    assert lab[5] == ["Meilleure réduction km du champ"]
    assert lab[1] == ["Meilleur chrono du champ", "Plus rapide du champ à sa dernière sortie"]
    assert "2e : n°1 en 1'16\"1" in enriched[4]["explanation"]["facteurs_positifs"][0]["detail"]
    assert _labels(enriched[8], "facteurs_negatifs") == ["Le moins rapide du champ"]
    assert all(not lab[n] for n in (2, 3, 4, 6, 7, 8, 9))


def test_moyenne_et_meilleur_chrono_fusionnes():
    red = {1: _r("1'12\"0", "1'13\"0")} | {i: _r(f"1'1{i}\"5", f"1'1{i}\"9") for i in range(2, 7)}
    enriched = _champ(6)
    _ajoute_vitesse_champ(enriched, red, "Monté")
    assert _labels(enriched[0]) == ["Le plus rapide du champ"]


def test_plat_aucun_badge():
    enriched = _champ(9)
    _ajoute_vitesse_champ(enriched, HYERES_R3C1, "Plat")
    assert all(not _labels(e) and not _labels(e, "facteurs_negatifs") for e in enriched)


def test_couverture_insuffisante_pas_de_du_champ():
    # 4 chronométrés sur 9 partants : « 1er du champ » serait faux.
    red = {k: HYERES_R3C1[k] for k in (1, 2, 3, 4)}
    enriched = _champ(9)
    _ajoute_vitesse_champ(enriched, red, "Attelé")
    assert all(not _labels(e) for e in enriched)


def test_egalite_au_dixieme_pas_d_atout():
    red = {1: _r("1'14\"0"), 2: _r("1'14\"0"), 3: _r("1'15\"0"), 4: _r("1'16\"0")}
    enriched = _champ(4)
    _ajoute_vitesse_champ(enriched, red, "Attelé")
    assert not _labels(enriched[0]) and not _labels(enriched[1])


def test_vitesse_relative_contradictoire_retiree():
    enriched = _champ(9)
    enriched[4]["explanation"]["facteurs_negatifs"].append(
        {"feature": "vitesse_relative", "label": "Vitesse en retrait", "score": 0.3})
    _ajoute_vitesse_champ(enriched, HYERES_R3C1, "Attelé")
    assert _labels(enriched[4], "facteurs_negatifs") == []


def test_fmt_reduction():
    assert _fmt_reduction(75.3) == "1'15\"3"
    assert _fmt_reduction(74.96) == "1'15\"0"


def test_lecture_fiche_pmu_ordre_bornes_et_absents_du_classement():
    from ml.narrative import reductions_depuis_performances

    def sortie(date, rk):
        return {"date": date, "participants": [{"itsHim": True, "reductionKilometrique": rk},
                                               {"itsHim": False, "reductionKilometrique": 70000}]}
    data = {"participants": [
        # Sorties volontairement dans le désordre ; 39 200 = 0'39"2 publié par le PMU.
        {"numPmu": 3, "coursesCourues": [sortie(1, 76000), sortie(5, 75100), sortie(3, 39200),
                                         sortie(4, None), sortie(2, 77000), sortie(0, 74000)]},
        {"numPmu": 4, "coursesCourues": []},
    ]}
    assert reductions_depuis_performances(data) == {3: [75.1, 77.0, 76.0]}
    # Un numéro absent du classement (non-partant) n'est jamais classé.
    enriched = _champ(4)
    red = {1: _r("1'14\"0"), 2: _r("1'15\"0"), 3: _r("1'16\"0"), 4: _r("1'17\"0"), 9: _r("1'10\"0")}
    _ajoute_vitesse_champ(enriched, red, "Attelé")
    assert _labels(enriched[0]) == ["Le plus rapide du champ"]
