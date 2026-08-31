"""Les chiffres par type de pari de la supervision IA.

Ce module alimente une page d'administration qui sert à décider quoi financer et
quoi couper. Trois garanties doivent tenir, et sont vérifiées ici sur le cas réel
qui les a motivées — le Trio, qui affichait +84 % de ROI sur 1 305 paris dont
24 gagnants et un unique rapport à 4 526 € :

1. un gain aberrant ne commande pas le ROI publié (winsorisation à 50× la mise) ;
2. aucun verdict n'est rendu sous 150 GAGNANTS, quel que soit le nombre de paris ;
3. le test de robustesse montre ce que devient le rendement sans les plus gros gains.
"""
import pytest

from ml.bet_type_analytics import (
    MIN_PARIS_IC,
    MIN_WINS_VERDICT,
    _agg,
    _ic90,
    _reference,
    _robustness,
    _roi,
)


def _bet(mise: float, gain: float, *, course: str = "c1", type_: str = "Trio") -> dict:
    return {
        "log_id": "l", "profil": "equilibre", "course_id": course, "jour": None,
        "date_heure": None, "discipline": "Attelé", "type": type_, "famille": type_,
        "mise": mise, "gain": gain, "gagne": gain > 0, "niveau": "rendement",
    }


# ── Winsorisation ────────────────────────────────────────────────────────────
def test_un_gain_aberrant_ne_commande_pas_le_roi():
    """1 000 paris perdants + un rapport à 4 526 € = ROI brut positif, ROI réel non."""
    bets = [_bet(3.0, 0.0, course=f"c{i}") for i in range(1000)]
    bets.append(_bet(3.0, 4526.0, course="cjackpot"))

    m = _agg(bets)

    assert m["roi_brut_pct"] > 0, "le brut est bien positif — c'est tout le problème"
    assert m["roi_pct"] < 0, "winsorisé, le même échantillon est perdant"
    # Plafond = 50 × 3 € = 150 €, pas 4 526 €.
    assert m["net_winsorise"] == pytest.approx(150.0 - 1001 * 3.0, abs=0.01)
    assert m["gain_max"] == 4526.0, "le gain réel reste exposé, il n'est pas effacé"


def test_le_brut_et_le_winsorise_coincident_sans_gain_extreme():
    bets = [_bet(2.0, 0.0, course=f"c{i}") for i in range(60)]
    bets += [_bet(2.0, 5.0, course=f"w{i}") for i in range(40)]

    m = _agg(bets)

    assert m["roi_pct"] == m["roi_brut_pct"]


# ── Fiabilité comptée en gagnants ────────────────────────────────────────────
def test_aucun_verdict_sous_le_seuil_de_gagnants():
    """5 000 paris à 2 % de réussite (~100 gagnants) ne prouvent rien."""
    n_wins = MIN_WINS_VERDICT - 50
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(5000 - n_wins)]
    bets += [_bet(1.0, 40.0, course=f"w{i}") for i in range(n_wins)]

    m = _agg(bets)

    assert m["n_paris"] == 5000
    assert m["n_gagnants"] == n_wins
    assert m["verdict"] == "insuffisant", "beaucoup de paris ≠ échantillon concluant"


def test_verdict_perdant_seulement_avec_assez_de_gagnants_et_un_ic_negatif():
    n_wins = MIN_WINS_VERDICT + 20
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(3000)]
    bets += [_bet(1.0, 2.0, course=f"w{i}") for i in range(n_wins)]

    m = _agg(bets)

    assert m["n_gagnants"] >= MIN_WINS_VERDICT
    assert m["ic90_roi_pct"][1] < 0, "borne haute de l'IC sous zéro"
    assert m["verdict"] == "perdant"


def test_verdict_rentable_exige_un_ic_entierement_positif():
    n_wins = MIN_WINS_VERDICT + 100
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(200)]
    bets += [_bet(1.0, 3.0, course=f"w{i}") for i in range(n_wins)]

    m = _agg(bets)

    assert m["ic90_roi_pct"][0] > 0
    assert m["verdict"] == "rentable"


def test_un_ic_qui_contient_zero_reste_non_tranche():
    n_wins = MIN_WINS_VERDICT + 10
    # Rendement moyen quasi nul : mises de 1 €, gains de 2 € sur la moitié.
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(n_wins)]
    bets += [_bet(1.0, 2.0, course=f"w{i}") for i in range(n_wins)]

    m = _agg(bets)

    lo, hi = m["ic90_roi_pct"]
    assert lo < 0 < hi
    assert m["verdict"] == "neutre"


# ── Intervalle de confiance ──────────────────────────────────────────────────
def test_pas_dintervalle_sous_le_minimum_dobservations():
    bets = [_bet(1.0, 0.0) for _ in range(MIN_PARIS_IC - 1)]
    assert _agg(bets)["ic90_roi_pct"] is None


def test_lintervalle_se_resserre_quand_lechantillon_grandit():
    petit = _ic90([0.5, -1.0] * (MIN_PARIS_IC // 2), [1.0] * MIN_PARIS_IC)
    grand = _ic90([0.5, -1.0] * 2000, [1.0] * 4000)
    assert (petit[1] - petit[0]) > (grand[1] - grand[0])


def test_lintervalle_entoure_le_roi_publie_meme_avec_des_mises_inegales():
    """Le ROI publié pondère par la mise ; son intervalle doit en faire autant.

    Sans cette pondération, la prod affichait un ROI de -15,96 % encadré par un
    IC [-26,56 % ; -17,59 %] — le chiffre publié tombait hors de son propre
    intervalle. Ici : de gros paris qui perdent peu, de petits qui perdent tout.
    """
    bets = [_bet(20.0, 19.0, course=f"g{i}") for i in range(100)]   # -5 % sur 20 €
    bets += [_bet(1.0, 0.0, course=f"p{i}") for i in range(100)]    # -100 % sur 1 €

    m = _agg(bets)
    lo, hi = m["ic90_roi_pct"]
    assert lo <= m["roi_pct"] <= hi


# ── Robustesse ───────────────────────────────────────────────────────────────
def test_la_robustesse_retire_bien_les_plus_gros_gains():
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(100)]
    bets += [_bet(1.0, 30.0, course=f"w{i}") for i in range(6)]

    points = _robustness(bets)

    assert [p["retires"] for p in points] == [1, 5]  # 20 > taille utile ici
    rois = [p["roi_pct"] for p in points]
    assert rois == sorted(rois, reverse=True), "retirer des gains ne peut qu'abaisser le ROI"
    assert points[-1]["n_restants"] == len(bets) - 5


def test_la_robustesse_ne_retire_rien_si_le_groupe_est_trop_petit():
    assert _robustness([_bet(1.0, 0.0)]) == []


# ── Divers ───────────────────────────────────────────────────────────────────
def test_roi_indefini_sans_mise():
    assert _roi(0.0, 0.0) is None


def test_le_groupe_vide_ne_rend_aucun_verdict():
    m = _agg([])
    assert m["n_paris"] == 0 and m["verdict"] == "insuffisant"


def test_la_reference_pmu_regroupe_les_variantes_de_multi():
    ref = _reference("Mini Multi en 6")
    assert ref is not None
    assert ref["famille"] == "Multi"
    assert ref["prelevement_pct"] > 0


def test_un_type_inconnu_na_pas_de_fiche_inventee():
    assert _reference("Pari Qui N'existe Pas") is None


def test_la_robustesse_ne_retire_jamais_de_perdants():
    """Retirer 20 paris quand il n'y a que 2 gagnants remonterait le ROI : le
    test doit alors s'arrêter, pas produire un chiffre flatteur."""
    bets = [_bet(1.0, 0.0, course=f"c{i}") for i in range(500)]
    bets += [_bet(1.0, 10.0, course="w1"), _bet(1.0, 8.0, course="w2")]

    points = _robustness(bets)

    assert [p["retires"] for p in points] == [1]
    assert points[0]["roi_pct"] < _agg(bets)["roi_pct"]


# ── Courbe de capital : les gains réels ne sont JAMAIS plafonnés ─────────────
def _bet_jour(jour, mise: float, gain: float, *, course: str = "c1") -> dict:
    b = _bet(mise, gain, course=course)
    b["jour"] = jour
    return b


@pytest.mark.asyncio
async def test_la_courbe_de_capital_montre_les_gains_reels(monkeypatch):
    """Le 19/07 a réellement rapporté +4 306 € : la courbe vécue doit le dire.

    Winsoriser cette courbe-là affichait +280 € et retournait même des jours
    bénéficiaires en jours perdants — un mensonge dans les deux sens.
    """
    from datetime import date

    import ml.bet_type_analytics as mod

    j1, j2 = date(2026, 7, 19), date(2026, 7, 20)
    bets = [
        _bet_jour(j1, 3.0, 4526.0, course="cjackpot"),
        *[_bet_jour(j1, 3.0, 0.0, course=f"a{i}") for i in range(10)],
        *[_bet_jour(j2, 3.0, 0.0, course=f"b{i}") for i in range(10)],
    ]

    async def _fake_load(session, since):
        return bets

    monkeypatch.setattr(mod, "_load_bets", _fake_load)
    out = await mod.compute_profitability_timeline(None, days=90)

    jour1 = out["serie"][0]
    assert jour1["net"] == pytest.approx(4526.0 - 33.0)          # réel
    assert jour1["net_winsor"] == pytest.approx(3 * 50 - 33.0)   # plafonné à 50× la mise
    assert out["resume"]["meilleur_jour"]["jour"] == "2026-07-19"
    assert out["resume"]["net_total"] > out["resume"]["net_total_winsor"]
    # Un jour réellement gagnant reste compté gagnant.
    assert out["resume"]["jours_positifs"] == 1


@pytest.mark.asyncio
async def test_sans_gain_extreme_les_deux_series_coincident(monkeypatch):
    """Le plafond ne doit rien changer tant qu'aucun rapport ne le dépasse."""
    from datetime import date

    import ml.bet_type_analytics as mod

    bets = [
        _bet_jour(date(2026, 7, 19), 3.0, 9.0, course="c1"),
        _bet_jour(date(2026, 7, 19), 3.0, 0.0, course="c2"),
    ]

    async def _fake_load(session, since):
        return bets

    monkeypatch.setattr(mod, "_load_bets", _fake_load)
    out = await mod.compute_profitability_timeline(None, days=90)

    assert out["serie"][0]["net"] == out["serie"][0]["net_winsor"]
    assert out["resume"]["net_total"] == out["resume"]["net_total_winsor"]
