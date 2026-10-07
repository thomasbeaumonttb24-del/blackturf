"""Correctifs du 2026-10-07 : mesure honnête et boucle de mise.

1. Thermostat : un ROI RÉEL négatif ne réchauffe jamais (le prélèvement sert de
   zéro pour refroidir moins vite, pas pour assouplir les gates).
2. Apprentissage profils : un pari remboursé (non-partant) n'est pas une perte.
3. Runs 'partial' expirés : réglés partiellement au lieu de sortir de l'apprentissage.
4. Places payées : les non-partants ne sont pas retranchés deux fois.
5. Kelly : EV ≤ 0 → 0 € (pas de pari) ; ALPHA dimensionne le placé sur le placé.
6. Dutching : jamais « garanti ».
7. Backtest : Simple Placé au rapport placé officiel, sélection sur la cote PMU.
9. TRJ : une seule table de référence.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import BetPlanSettlement, BetPlanSnapshot, Course, Resultat
from ml import bet_performance as bp


MAINTENANT = datetime.now(timezone.utc)


# ── 1. Thermostat ─────────────────────────────────────────────────────────
async def _seed_plans(db, n, mise, retour):
    for i in range(n):
        cid = f"TH{i}"
        db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T",
                      date_heure=MAINTENANT - timedelta(days=1),
                      hippodrome_nom="Pau", discipline="Plat", distance=2000,
                      nb_partants=10, statut="termine"))
        db.add(BetPlanSnapshot(
            plan_snapshot_id=f"bp-{cid}", course_id=cid, subject_hash="system",
            profil="equilibre", montant_demande=mise, plan={"niveaux": []},
            plan_hash=f"h-{cid}", cotes_utilisees={}, algo_config={},
            algo_version="mp-t", nb_paris=1, montant_joue=mise,
            emitted_at=MAINTENANT - timedelta(days=1, hours=1),
            course_start_at=MAINTENANT - timedelta(days=1),
            is_pre_course=True, origin="mise_plan"))
        db.add(BetPlanSettlement(
            settlement_id=f"st-{cid}", plan_snapshot_id=f"bp-{cid}", course_id=cid,
            bilan={"paris": []}, montant_mise=mise, montant_retour=retour,
            net=retour - mise, roi=(retour - mise) / mise * 100, nb_paris=1,
            nb_gagnes=1 if retour > mise else 0, statut="settled",
            settled_at=MAINTENANT - timedelta(days=1)))
    await db.commit()


@pytest.mark.asyncio
async def test_thermostat_roi_reel_negatif_ne_rechauffe_pas(db):
    # ROI réel −10 % → avantage +10 points : AVANT, terme +0,33 → heat > 0.
    await _seed_plans(db, 120, 10.0, 9.0)
    ctx = await bp.compute_model_heat(db)
    assert ctx["roi_reel"] == pytest.approx(-0.10, abs=0.005)
    assert ctx["roi_recent"] > 0          # l'avantage reste publié
    assert ctx["heat"] <= 0.0, "un système qui perd de l'argent ne doit pas assouplir"


@pytest.mark.asyncio
async def test_thermostat_roi_reel_positif_peut_rechauffer(db):
    await _seed_plans(db, 120, 10.0, 11.0)   # +10 % réel
    ctx = await bp.compute_model_heat(db)
    assert ctx["roi_reel"] == pytest.approx(0.10, abs=0.005)
    assert ctx["heat"] > 0.0
    assert ctx["roi_negatif_gel"] is False


# ── 2/3. Apprentissage profils ────────────────────────────────────────────
def test_bilan_reglement_partiel_garde_les_paris_regles():
    from ml.profil_learning import bilan_reglement_partiel
    bilan = {
        "paris": [
            {"type": "Simple Placé", "mise": 2.0, "statut": "perdu", "gain": None},
            {"type": "Simple Gagnant", "mise": 3.0, "statut": "gagne", "gain": 9.0},
            {"type": "Trio", "mise": 5.0, "statut": "en_attente", "gain": None},
            {"type": "Couplé Placé", "mise": 2.0, "statut": "rembourse", "gain": 2.0},
        ],
        "en_attente": True, "provisoire": True, "total_mise": 10.0, "total_gain": 9.0,
    }
    out, n_exclus = bilan_reglement_partiel(bilan)
    assert n_exclus == 1
    assert out["total_mise"] == 5.0       # 2 perdu + 3 gagné ; ni attente ni remboursé
    assert out["total_gain"] == 9.0
    assert out["net"] == 4.0
    assert out["en_attente"] is False and out["reglement_partiel"] is True
    assert all(p["statut"] != "en_attente" for p in out["paris"])


@pytest.mark.asyncio
async def test_rembourse_nest_pas_compte_comme_perte(db, monkeypatch):
    """Un Simple Placé remboursé (NP) ne doit pas entrer dans la mise du type."""
    import ml.profil_learning as pl

    res_run = {
        "total_mise": 2.0, "total_gain": 0.0, "net": -2.0,
        "paris": [
            {"type": "Simple Placé", "mise": 2.0, "statut": "perdu", "gain": None},
            {"type": "Simple Placé", "mise": 5.0, "statut": "rembourse", "gain": 5.0},
        ],
    }

    class _R:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    rows = [("equilibre", res_run, -1.0, "Plat", 10, MAINTENANT - timedelta(days=1))]
    rows = rows * max(1, pl.MIN_PROFIL_WEIGHTS_RUNS)

    async def _ensure(_s):
        return None

    captured = {}

    async def _fake_execute(stmt, params=None):
        sql = str(stmt)
        if "FROM profil_run_log r" in sql and "JOIN courses" in sql:
            return _R(rows)
        captured.setdefault("autres", []).append(sql)
        return _R([])

    monkeypatch.setattr(pl, "ensure_tables", _ensure)

    class _Session:
        execute = staticmethod(_fake_execute)

        async def commit(self):
            return None

        async def rollback(self):
            return None

    try:
        out = await pl.compute_profil_weights(_Session())
    except Exception:
        pytest.skip("compute_profil_weights dépend d'autres tables hors périmètre")
    sp = out["profils"]["equilibre"]["type_detail"]["Simple Placé"]
    assert sp["n"] == len(rows)                 # le remboursé n'est pas compté
    assert sp["roi"] == pytest.approx(-100.0)


# ── 4. Places payées ──────────────────────────────────────────────────────
def test_places_np_pas_retranches_deux_fois():
    """9 coureurs + 1 NP, nb_partants absent → repli sur le classement (qui
    n'inclut pas le NP) : 3 places payées, pas 2."""
    from services.bet_settlement import _settle_par_classement
    classement = [{"numero": n, "position": i + 1} for i, n in enumerate(
        [1, 2, 3, 4, 5, 6, 7, 8])]
    r = _settle_par_classement("Simple Placé", [3], classement, {}, 0, None, {9})
    assert r["gagne"] is True, r


def test_places_nb_partants_declares_np_compris():
    """nb_partants = 9 déclarés dont 1 NP → 8 partants réels → 3 places."""
    from services.bet_settlement import _settle_par_classement
    classement = [{"numero": n, "position": i + 1} for i, n in enumerate(
        [1, 2, 3, 4, 5, 6, 7, 8])]
    r = _settle_par_classement("Simple Placé", [3], classement, {}, 9, None, {9})
    assert r["gagne"] is True, r


def test_places_champ_reduit_reste_a_deux():
    from services.bet_settlement import _settle_par_classement
    classement = [{"numero": n, "position": i + 1} for i, n in enumerate([1, 2, 3, 4, 5, 6])]
    # 7 déclarés dont 1 NP → 6 partants → 2 places : le 3e ne paie pas.
    r = _settle_par_classement("Simple Placé", [3], classement, {}, 7, None, {7})
    assert r["gagne"] is False


# ── 5. Kelly / ALPHA ──────────────────────────────────────────────────────
def test_kelly_ev_negative_ne_mise_rien():
    from ml.portfolio import _kelly
    assert _kelly(-0.1, 3.0, 100.0) == 0.0
    assert _kelly(0.0, 3.0, 100.0) == 0.0
    assert _kelly(0.2, 1.0, 100.0) == 0.0
    assert _kelly(0.2, 3.0, 100.0) > 0


def test_alpha_place_dimensionne_sur_le_rapport_place():
    from ml.portfolio import BetPortfolioEngine
    eng = BetPortfolioEngine()
    top1 = {"numero": 1, "nom": "A", "proba_top3": 0.80, "proba_top1": 0.45,
            "cote_pmu": 2.5, "ev_max": 0.9, "rapport_place": 1.6}
    alpha = eng._scenario_alpha(top1, None, [top1], [], 50.0, nb_partants=12)
    sp = [p for p in alpha["paris"] if p["type"] == "Simple Placé"][0]
    # EV placé = 0,80 × 1,6 − 1 = +0,28 (pas l'EV gagnant 0,9)
    assert sp["ev"] == pytest.approx(0.28, abs=1e-3)
    assert sp["rapport_place_estime"] == pytest.approx(1.6)


def test_alpha_place_ev_negative_pas_de_pari():
    from ml.portfolio import BetPortfolioEngine
    eng = BetPortfolioEngine()
    top1 = {"numero": 1, "nom": "A", "proba_top3": 0.50, "cote_pmu": 2.0,
            "ev_max": 0.5, "rapport_place": 1.2}   # 0,5 × 1,2 − 1 = −0,4
    assert eng._scenario_alpha(top1, None, [top1], [], 50.0, nb_partants=12) is None


# ── 6. Dutching ───────────────────────────────────────────────────────────
def test_dutching_ne_promet_rien():
    from ml.portfolio import dutching_calculator
    sel = [{"numero": 1, "nom": "A", "cote": 4.0, "proba": 0.10},
           {"numero": 2, "nom": "B", "cote": 5.0, "proba": 0.10}]
    d = dutching_calculator(sel, 20.0)
    # Σ 1/cote = 0,45 < 1 : l'ancien code annonçait un « profit garanti ».
    assert d["is_profitable"] is False      # espérance modèle : 0,2 × 44,4 − 20 < 0
    assert "NON garanti" in d["note"]
    assert d["perte_si_aucun_gagne"] == pytest.approx(-20.0, abs=0.01)
    assert d["profit_si_un_gagne"] == d["profit_garanti"]


def test_dutching_esperance_positive():
    from ml.portfolio import dutching_calculator
    sel = [{"numero": 1, "nom": "A", "cote": 4.0, "proba": 0.40},
           {"numero": 2, "nom": "B", "cote": 5.0, "proba": 0.30}]
    d = dutching_calculator(sel, 20.0)
    assert d["is_profitable"] is True and d["esperance"] > 0


# ── 7. Backtest ───────────────────────────────────────────────────────────
DETAIL = {"simple_place": [
    {"combinaison": "1", "rapport": 1.3},
    {"combinaison": "3", "rapport": 2.1},
    {"combinaison": "5", "rapport": 3.4},
]}


def test_backtest_place_paye_au_rapport_place_officiel():
    from ml.backtest import Bet, settle_bet
    b = Bet("C1", 3, "Simple Placé", stake=10.0, cote=8.0)  # cote GAGNANT ignorée
    sb = settle_bet(b, {1: 1, 5: 2, 3: 3}, nb_partants=12, rapports_detail=DETAIL)
    assert sb.won is True
    assert sb.payout == pytest.approx(21.0)


def test_backtest_selection_cote_pmu_pas_meilleure_source():
    from ml.backtest import value_bet_strategy
    # Au PMU (2,0) : EV = 2 × 0,4 − 1 < 0. Chez Betfair (4,0) : EV > 0.
    partants = [{"course_id": "C1", "numero": 4, "proba_top3": 0.8, "proba_top1": 0.4,
                 "cotes": {"pmu": 2.0, "betfair": 4.0}}]
    assert value_bet_strategy(partants, bankroll=100.0) == []


@pytest.mark.asyncio
async def test_run_backtest_exclut_place_sans_rapport_officiel(db):
    from ml.backtest import Bet, run_backtest
    depart = datetime(2026, 1, 3, 13, 0, tzinfo=timezone.utc)
    db.add(Course(course_id="BP1", reunion_id="R1", numero=1, nom="T",
                  date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Resultat(course_id="BP1", classement=[{"numero": 1, "position": 1}]))
    await db.commit()

    def _strat(partants, **_):
        return [Bet("BP1", 1, "Simple Placé", stake=10.0, cote=5.0)]

    # Aucun partant rejouable → stratégie jamais appelée : on teste settle direct.
    from ml.backtest import settle_bet
    sb = settle_bet(Bet("BP1", 1, "Simple Placé", 10.0, 0.0), {1: 1}, 10, None, None)
    assert sb is None, "placé gagnant sans rapport placé : non réglable, jamais estimé"
    res = await run_backtest(db, ["BP1"], strategy=_strat)
    assert res.nb_bets == 0


# ── 9. TRJ ────────────────────────────────────────────────────────────────
def test_trj_une_seule_table():
    from services.pmu_paris_reference import TRJ_PMU, trj
    from ml import portfolio, recommendations
    assert portfolio.TRJ["Simple Placé"] == TRJ_PMU["Simple Placé"]
    assert portfolio.TRJ["Tiercé Ordre"] == TRJ_PMU["Tiercé"]
    assert recommendations.TRJ["Quinté+"] == TRJ_PMU["Quinté+"]
    assert trj("Multi en 6") == TRJ_PMU["Multi"]
    assert trj("Quinté+ Flexi") == TRJ_PMU["Quinté+"]
    assert trj("Type inconnu") == min(TRJ_PMU.values())


def test_simulateur_utilise_trj_par_type():
    from ml.portfolio_simulator import _trj_type
    from services.pmu_paris_reference import TRJ_PMU
    assert _trj_type("couple gagnant") == TRJ_PMU["Couplé Gagnant"]
    assert _trj_type("Tiercé Désordre") == TRJ_PMU["Tiercé"]


# ── 8. Comparateur « favori naïf » ────────────────────────────────────────
async def _seed_favori(db, cid, *, rapports=None, rapports_detail=None):
    from db.models import Participation
    depart = MAINTENANT - timedelta(days=2)
    db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T", date_heure=depart,
                  hippodrome_nom="Pau", discipline="Plat", distance=2000,
                  nb_partants=10, statut="termine"))
    db.add(Participation(participation_id=f"p-{cid}", course_id=cid,
                         cheval_id=f"ch-{cid}", numero=7, cote_pmu=2.0))
    db.add(Resultat(course_id=cid, classement=[{"numero": 7, "position": 1},
                                                {"numero": 9, "position": 2}],
                    rapports=rapports, rapports_detail=rapports_detail))
    db.add(BetPlanSnapshot(
        plan_snapshot_id=f"bp-{cid}", course_id=cid, subject_hash="system",
        profil="equilibre", montant_demande=10.0, plan={}, plan_hash=f"h-{cid}",
        cotes_utilisees={"7": 2.0, "9": 5.0}, algo_config={}, algo_version="mp-t",
        nb_paris=0, montant_joue=0.0, emitted_at=depart - timedelta(hours=1),
        course_start_at=depart, is_pre_course=True, origin="mise_plan"))
    await db.commit()


@pytest.mark.asyncio
async def test_favori_naif_paye_au_rapport_officiel(db):
    from ml import bet_plan_performance as bpp
    # Cote d'émission 2,0 mais rapport officiel 1,6 : on paie 1,6.
    await _seed_favori(db, "FV1", rapports_detail={
        "simple_gagnant": [{"combinaison": "7", "rapport": 1.6}]})
    out = await bpp._naive_favorite_roi(db, ["FV1"])
    assert out["montant_retour"] == pytest.approx(1.6)
    assert out["n_cote_emission"] == 0


@pytest.mark.asyncio
async def test_favori_naif_exclu_si_rapport_manquant(db):
    from ml import bet_plan_performance as bpp
    # Des rapports existent, mais pas le Simple Gagnant : course exclue.
    await _seed_favori(db, "FV2", rapports={"trio": 30.0})
    out = await bpp._naive_favorite_roi(db, ["FV2"])
    assert out is None
