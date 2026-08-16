"""
Tests backtest ROI (Phase 4) — règlement pur + métriques + runner DB.
"""
from datetime import datetime, timezone

import pytest

from ml.backtest import (
    Bet, settle_bet, place_paid, max_drawdown, compute_metrics,
    value_bet_strategy, portfolio_strategy, run_backtest,
    bet_won, arrivee_order,
)
from db.models import Course, Participation, Prediction, Resultat


# ── Règlement pur ──────────────────────────────────────────────
def test_settle_gagnant_win():
    b = Bet("C1", 3, "gagnant", stake=10.0, cote=4.0)
    sb = settle_bet(b, {3: 1, 5: 2}, nb_partants=10)
    assert sb.won is True
    assert sb.payout == 40.0
    assert sb.profit == 30.0


def test_settle_gagnant_lose():
    b = Bet("C1", 3, "gagnant", stake=10.0, cote=4.0)
    sb = settle_bet(b, {3: 4, 5: 1}, nb_partants=10)
    assert sb.won is False
    assert sb.payout == 0.0
    assert sb.profit == -10.0


def test_settle_incident_lose():
    b = Bet("C1", 3, "gagnant", stake=10.0, cote=4.0)
    sb = settle_bet(b, {3: 99, 5: 1, 7: 2}, nb_partants=10)  # #3 disq., #5 gagne
    assert sb.won is False
    assert sb.profit == -10.0


def test_arrivee_order_exclut_incidents():
    assert arrivee_order({5: 2, 3: 1, 7: 99, 9: 4}) == [3, 5, 9]


# ── Combinés (réglés via rapports réels) ───────────────────────
def test_bet_won_couple_gagnant():
    arrivee = {5: 1, 3: 2, 7: 3, 9: 4}
    assert bet_won("Couplé Gagnant", [3, 5], arrivee, 12) is True   # 1er+2e quelconque ordre
    assert bet_won("Couplé Gagnant", [5, 7], arrivee, 12) is False


def test_bet_won_tierce_ordre_vs_desordre():
    arrivee = {5: 1, 3: 2, 7: 3}
    assert bet_won("Tiercé", [7, 3, 5], arrivee, 10) is True        # désordre → ok
    assert bet_won("Tiercé Ordre", [7, 3, 5], arrivee, 10) is False
    assert bet_won("Tiercé Ordre", [5, 3, 7], arrivee, 10) is True


def test_settle_combine_via_rapport():
    b = Bet("C1", 3, "Couplé Gagnant", stake=2.0, numeros=[3, 5])
    arrivee = {5: 1, 3: 2, 7: 3}
    sb = settle_bet(b, arrivee, nb_partants=12, rapports={"couple_gagnant": 15.5})
    assert sb.won is True
    assert sb.payout == 31.0          # 2 × 15.5
    assert sb.profit == 29.0


def test_settle_combine_gagnant_sans_rapport_non_reglable():
    b = Bet("C1", 3, "Couplé Gagnant", stake=2.0, numeros=[3, 5])
    arrivee = {5: 1, 3: 2}
    sb = settle_bet(b, arrivee, nb_partants=12, rapports={})  # pas de rapport → None
    assert sb is None


def test_settle_combine_perdant_reglable_sans_rapport():
    # Perdu : on sait que c'est -mise même sans rapport.
    b = Bet("C1", 3, "Couplé Gagnant", stake=2.0, numeros=[3, 9])
    arrivee = {5: 1, 3: 2, 7: 3}
    sb = settle_bet(b, arrivee, nb_partants=12, rapports={})
    assert sb.won is False
    assert sb.profit == -2.0


def test_settle_type_inconnu_non_reglable():
    b = Bet("C1", 3, "Multi en 7", stake=2.0, numeros=[3])
    assert settle_bet(b, {3: 1}, nb_partants=12) is None


def test_place_paid_thresholds():
    assert place_paid(12) == 3
    assert place_paid(8) == 3
    assert place_paid(7) == 2
    assert place_paid(4) == 2
    assert place_paid(3) == 1


def test_settle_place_win_top3():
    b = Bet("C1", 3, "place", stake=10.0, cote=1.8)
    sb = settle_bet(b, {3: 3}, nb_partants=12)   # 3e dans champ de 12 → payé
    assert sb.won is True


def test_settle_place_lose():
    b = Bet("C1", 3, "place", stake=10.0, cote=1.8)
    sb = settle_bet(b, {3: 4, 1: 1, 2: 2, 5: 3}, nb_partants=12)   # 4e → non payé
    assert sb.won is False


# ── Drawdown + métriques ───────────────────────────────────────
def test_max_drawdown():
    # pic à +30, retombe à +10 → drawdown 20
    assert max_drawdown([10, 30, 25, 10, 40]) == 20.0
    assert max_drawdown([5, 10, 15]) == 0.0       # monotone croissant
    assert max_drawdown([]) == 0.0


def test_compute_metrics_roi_et_ventilation():
    settled = [
        settle_bet(Bet("C1", 1, "gagnant", 10.0, 3.0), {1: 1, 2: 2}),   # +20
        settle_bet(Bet("C2", 2, "gagnant", 10.0, 3.0), {2: 5, 1: 1}),   # -10
        settle_bet(Bet("C3", 3, "gagnant", 10.0, 2.0), {3: 1, 2: 2}),   # +10
    ]
    res = compute_metrics(settled, nb_courses=3)
    assert res.nb_bets == 3
    assert res.nb_wins == 2
    assert res.total_staked == 30.0
    assert res.profit == 20.0
    assert res.roi == pytest.approx(0.6667, abs=0.001)
    assert res.hit_rate == pytest.approx(0.6667, abs=0.001)
    assert res.by_type["gagnant"]["nb"] == 3
    assert res.equity_curve == [20.0, 10.0, 20.0]


# ── Stratégie ──────────────────────────────────────────────────
def test_value_bet_strategy_genere_pari_sur_edge():
    partants = [{
        "course_id": "C1", "numero": 4, "proba_top3": 0.5,
        "cotes": {"pmu": 3.0},   # EV = 3.0*0.5 - 1 = 0.5 (fort)
    }]
    bets = value_bet_strategy(partants, bankroll=100.0)
    assert len(bets) == 1
    assert bets[0].type == "gagnant"
    assert bets[0].numero == 4
    assert bets[0].cote == 3.0
    assert bets[0].stake > 0


def test_portfolio_strategy_genere_paris_diversifies():
    partants = [
        {"course_id": "C1", "numero": 1, "nom": "FAVORI", "proba_top3": 0.55, "cotes": {"pmu": 2.5}},
        {"course_id": "C1", "numero": 2, "nom": "DEUXIEME", "proba_top3": 0.42, "cotes": {"pmu": 3.5}},
        {"course_id": "C1", "numero": 3, "nom": "OUTSIDER", "proba_top3": 0.18, "cotes": {"pmu": 12.0}},
    ]
    course_info = {"course_id": "C1", "nb_partants": 12, "est_tierce": True,
                   "est_quarte": False, "est_quinte": False}
    bets = portfolio_strategy(partants, course_info=course_info, bankroll=200.0)
    assert len(bets) >= 1
    # paris backtestables : type non vide, mise > 0, numéros présents
    for b in bets:
        assert b.stake > 0
        assert b.numeros
        assert b.type


def test_value_bet_strategy_pas_de_pari_sans_edge():
    partants = [{
        "course_id": "C1", "numero": 4, "proba_top3": 0.10,
        "cotes": {"pmu": 2.0},   # EV = 2.0*0.10 - 1 = -0.8 → pas de VB
    }]
    assert value_bet_strategy(partants, bankroll=100.0) == []


# ── Runner DB ──────────────────────────────────────────────────
# proba=0.8 → proba_top1=0.4 ; à cote 3.0, EV gagnant = 3.0×0.4−1 = +0.2 → vrai
# value bet (le runner détecte sur P(victoire), pas sur la proba placé).
async def _seed_course(db, cid, num1_pos, cote=3.0, proba=0.8, cote_figee=None):
    db.add(Course(
        course_id=cid, reunion_id="R1", numero=1, nom="Test",
        date_heure=datetime(2026, 1, int(cid[-1]) + 1, 13, 0, tzinfo=timezone.utc),
        hippodrome_nom="Pau", discipline="Plat", distance=2000,
        nb_partants=10, statut="termine",
    ))
    db.add(Participation(
        participation_id=f"p-{cid}-1", course_id=cid, cheval_id=f"ch-{cid}-1",
        numero=1, cote_pmu=cote,
    ))
    db.add(Prediction(
        prediction_id=f"pred-{cid}-1", participation_id=f"p-{cid}-1",
        course_id=cid, proba_top1=proba / 2, proba_top3=proba, rang_predit=1,
        cote_figee=cote_figee,
    ))
    # Arrivée réaliste : le cheval prédit (#1) + un autre (#2) comme gagnant de secours
    autre_pos = 1 if num1_pos != 1 else 2
    db.add(Resultat(course_id=cid, classement=[
        {"numero": 1, "position": num1_pos},
        {"numero": 2, "position": autre_pos},
    ]))


@pytest.mark.asyncio
async def test_run_backtest_end_to_end(db):
    # C1 : le cheval prédit gagne → profit positif. C2 : il perd → perte.
    await _seed_course(db, "C1", num1_pos=1)
    await _seed_course(db, "C2", num1_pos=5)
    await db.commit()

    res = await run_backtest(db, ["C1", "C2"], bankroll=100.0)
    assert res.nb_courses == 2
    assert res.nb_bets == 2
    assert res.nb_wins == 1
    assert res.total_staked > 0
    # 1 gagné à cote 3 (+2×mise), 1 perdu (-mise) → profit net positif
    assert res.profit > 0
    assert len(res.equity_curve) == 2


@pytest.mark.asyncio
async def test_run_backtest_selection_cote_figee_gain_cote_finale(db):
    """La cote pré-course pilote l'éligibilité, mais le gain est payé à la cote finale."""
    await _seed_course(db, "C3", num1_pos=1, cote=5.0, cote_figee=3.0)
    await db.commit()

    res = await run_backtest(db, ["C3"], bankroll=100.0)

    assert res.nb_bets == 1
    assert res.nb_wins == 1
    assert res.total_returned == pytest.approx(res.total_staked * 5.0, abs=0.01)


@pytest.mark.asyncio
async def test_run_backtest_ignore_course_sans_resultat(db):
    db.add(Course(
        course_id="CX", reunion_id="R1", numero=1, nom="NoRes",
        date_heure=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
        hippodrome_nom="Pau", discipline="Plat", distance=2000,
        nb_partants=10, statut="termine",
    ))
    await db.commit()
    res = await run_backtest(db, ["CX"], bankroll=100.0)
    assert res.nb_courses == 0
    assert res.nb_bets == 0
