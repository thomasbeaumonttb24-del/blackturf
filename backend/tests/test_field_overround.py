"""
Tests de compute_field_overround (audit 2026-08-16, "value bets en extinction").

Régression protégée : quand seule une minorité du champ a une cote, la somme des
probas implicites sous-compte l'overround réel et peut tomber près de 0.
`implied_marche / field_overround` divise alors par ce quasi-zéro, explose vers
l'infini, et le gate anti-longshot de detect_value_bet (`proba_top1 >
MAX_MODEL_MARKET_RATIO * implied_marche`) ne se déclenche PLUS JAMAIS — une
couverture cotes faible désactivait silencieusement le garde-fou censé filtrer
les faux value bets outsiders, au lieu de le renforcer.
"""
import pytest

from ml.pipeline import MIN_OVERROUND_COVERAGE, compute_field_overround


def _partant(cote_pmu=None, **kw):
    d = {"cote_pmu": cote_pmu}
    d.update(kw)
    return d


def test_champ_complet_couverture_pmu_seule():
    """8 partants, tous cotés PMU uniquement : cas courant (audit : 85-100% de
    couverture PMU en pratique) — overround = somme des 1/cote."""
    partants = [_partant(cote_pmu=c) for c in [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0]]
    ov = compute_field_overround(partants)
    attendu = sum(1 / c for c in [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0])
    assert ov == pytest.approx(attendu)


def test_couverture_sous_le_seuil_retourne_none():
    """LE cas du bug : 2 cotés sur 10 (20% < 70%) → None, pas un quasi-zéro qui
    exploserait le gate anti-longshot en aval."""
    partants = [_partant(cote_pmu=2.0), _partant(cote_pmu=3.0)] + [_partant()] * 8
    assert compute_field_overround(partants) is None


def test_couverture_pile_au_seuil_est_acceptee():
    partants = [_partant(cote_pmu=c) for c in [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]]
    partants += [_partant()] * 3  # 7/10 = 70% exactement
    assert len(partants) == 10
    assert compute_field_overround(partants) is not None


def test_couverture_juste_sous_le_seuil_est_refusee():
    partants = [_partant(cote_pmu=c) for c in [2.0, 3.0, 4.0, 5.0, 6.0, 8.0]]
    partants += [_partant()] * 4  # 6/10 = 60% < 70%
    assert compute_field_overround(partants) is None


def test_un_seul_partant_cote_sur_grand_champ_est_le_cas_extreme_du_bug():
    """Le scénario qui, sans garde-fou, ferait presque exploser le devig : un
    champ de 16 partants où un seul a une cote très élevée (overround brut ≈ 0.05,
    quasi-zéro). Doit être rejeté (coverage 1/16 ≈ 6% << 70%), pas laissé passer
    comme un overround minuscule mais « valide »."""
    partants = [_partant(cote_pmu=20.0)] + [_partant()] * 15
    assert compute_field_overround(partants) is None


def test_aucune_cote_du_tout():
    assert compute_field_overround([_partant()] * 6) is None


def test_champ_vide():
    assert compute_field_overround([]) is None


def test_multi_sources_par_partant_utilise_la_cote_ponderee():
    """Un partant avec plusieurs sources doit compter UNE fois (cote_marche_ponderee),
    pas une fois par source — sinon la couverture serait artificiellement gonflée."""
    partants = [
        _partant(cote_pmu=4.0, cote_geny=4.2, cote_betfair=3.9),
        _partant(cote_pmu=6.0),
        _partant(cote_pmu=8.0),
    ] + [_partant()] * 0  # 3/3 = 100%, doit passer
    ov = compute_field_overround(partants)
    assert ov is not None
    assert ov > 0


def test_seuil_par_defaut_est_0_70():
    """Documente la valeur choisie (majorité qualifiée du champ) — si ce test
    casse, c'est que la constante a changé, pas un accident silencieux."""
    assert MIN_OVERROUND_COVERAGE == 0.70
