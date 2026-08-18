"""Rentabilité forward des plans émis : agrégats, seuils de fiabilité, gates."""

from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    BetPlanSettlement, BetPlanSnapshot, Course, Participation, Prediction,
    Resultat,
)
from ml import bet_plan_performance as bpp


# ── _flatten_plan_bets : même ordre que settle_plan ──────────────────────────

def test_flatten_conserve_l_ordre_niveaux_puis_paris():
    plan = {
        "niveaux": [
            {"niveau": "securite", "paris": [
                {"type": "Placé", "chevaux": [{"numero": 3}], "ev_estime": 0.1},
                {"type": "Placé", "chevaux": [{"numero": 7}], "ev_estime": 0.2},
            ]},
            {"niveau": "coup", "paris": [
                {"type": "Couplé", "chevaux": [{"numero": 3}, {"numero": 7}], "ev_estime": 0.5},
            ]},
        ]
    }
    flat = bpp._flatten_plan_bets(plan)
    assert [f["type"] for f in flat] == ["Placé", "Placé", "Couplé"]
    assert flat[2]["chevaux"] == [3, 7]
    assert flat[2]["ev_estime"] == 0.5


# ── Buckets ───────────────────────────────────────────────────────────────────

def test_cote_band_suit_les_bornes_de_cote_calibration():
    row_favori = {"cote_moyenne": 1.5}
    row_outsider = {"cote_moyenne": 30.0}
    assert bpp._segment_key("cote_band", row_favori) == "[1-2)"
    assert bpp._segment_key("cote_band", row_outsider) == "[25+)"
    assert bpp._segment_key("cote_band", {"cote_moyenne": None}) is None


def test_ev_band_utilise_les_bandes_partagees_avec_signal_performance():
    from ml.signal_performance import _ev_band_key
    assert bpp._segment_key("ev_band", {"ev_estime": 0.15}) == _ev_band_key(0.15)
    assert bpp._segment_key("ev_band", {"ev_estime": 0.05}) == "0.00_0.10"
    assert bpp._segment_key("ev_band", {"ev_estime": None}) is None


def test_peloton_bucket_reutilise_isotonic_calibration():
    assert bpp._segment_key("peloton", {"nb_partants": 6}) == "small"
    assert bpp._segment_key("peloton", {"nb_partants": 16}) == "large"


def test_combo_distingue_simple_et_combinaison():
    assert bpp._segment_key("combo", {"is_combo": False}) == "simple"
    assert bpp._segment_key("combo", {"is_combo": True}) == "combinaison"


def test_snapshot_age_bucket():
    assert bpp._segment_key("snapshot_age", {"snapshot_age_s": 300}) == "0-10min"
    assert bpp._segment_key("snapshot_age", {"snapshot_age_s": 7200}) == "1-24h"
    assert bpp._segment_key("snapshot_age", {"snapshot_age_s": None}) is None


# ── Drawdown / losing streak : chronologie, pas tri par résultat ─────────────

def test_drawdown_mesure_la_pire_chute_depuis_le_pic():
    # +10, +10, -25, +5 → pic à 20, creux à -5 après le -25 → drawdown 25.
    dd, streak = bpp._drawdown_and_streak([10, 10, -25, 5])
    assert dd == 25.0
    assert streak == 1


def test_losing_streak_compte_les_pertes_consecutives():
    dd, streak = bpp._drawdown_and_streak([5, -1, -1, -1, 5, -1])
    assert streak == 3


def test_serie_gagnante_a_drawdown_nul():
    dd, streak = bpp._drawdown_and_streak([5, 5, 5])
    assert dd == 0.0
    assert streak == 0


# ── Bootstrap CI ──────────────────────────────────────────────────────────────

def test_bootstrap_ci_absent_sous_10_points():
    assert bpp._bootstrap_ci([1.0] * 9) is None


def test_bootstrap_ci_deterministe_et_centre_sur_la_moyenne():
    values = [1.0] * 20
    ci = bpp._bootstrap_ci(values)
    assert ci is not None
    lo, hi = ci
    assert abs(lo - 1.0) < 1e-6 and abs(hi - 1.0) < 1e-6
    # Même graine → même résultat d'un appel à l'autre (reproductibilité).
    assert bpp._bootstrap_ci(values) == ci


# ── Seuils de fiabilité : jamais "profitable"/"losing" sous le seuil ────────

def _bet(mise=1.0, gain=None, statut="perdu"):
    return {"mise": mise, "gain": gain, "statut": statut}


def test_segment_sous_le_seuil_reste_observed_meme_avec_gros_gain():
    bets = [_bet(mise=1.0, gain=50.0, statut="gagne")] + \
           [_bet(mise=1.0, statut="perdu") for _ in range(5)]
    plans = [{"course_id": f"C{i}", "net": -1.0, "emitted_at": None} for i in range(5)]
    m = bpp._metrics_for_group(bets, plans)
    assert m["n_paris"] == 6 < bpp.MIN_SEGMENT_OBS
    assert m["status"] == "observed"
    assert m["roi_pct"] is None          # jamais publié sous le seuil
    assert m["roi_pct_raw"] is not None  # mais calculé (diagnostic)


def test_segment_au_dessus_du_seuil_est_tranche():
    bets = [_bet(mise=1.0, statut="perdu") for _ in range(bpp.MIN_SEGMENT_OBS)]
    m = bpp._metrics_for_group(bets, [])
    assert m["status"] == "losing"
    assert m["roi_pct"] == -100.0


def test_drawdown_absent_sous_min_plans_for_series():
    bets = [_bet(mise=1.0, gain=1.0, statut="gagne") for _ in range(bpp.MIN_SEGMENT_OBS)]
    plans = [{"course_id": f"C{i}", "net": 0.0, "emitted_at": None}
             for i in range(bpp.MIN_PLANS_FOR_SERIES - 1)]
    m = bpp._metrics_for_group(bets, plans)
    assert m["drawdown_max"] is None
    assert m["ic90_moyenne_plan"] is None


# ── Gates automatiques ────────────────────────────────────────────────────────

def test_gate_suspend_un_segment_fiable_et_durablement_negatif():
    perf = {"segments": {"Tiercé Désordre": {
        "reliable": True, "roi_pct": -35.0, "n_paris": 80, "n_plans": 40,
        "drawdown_max": 10.0, "montant_mise": 80.0,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Tiercé Désordre"]["status"] == "suspended"
    assert gates["Tiercé Désordre"]["factor"] == 0.0


def test_gate_reduit_sur_drawdown_excessif_sans_segment_prouve_perdant():
    perf = {"segments": {"Placé": {
        "reliable": True, "roi_pct": -5.0, "n_paris": 60, "n_plans": 30,
        "drawdown_max": 55.0, "montant_mise": 100.0,   # 55% > seuil 50%
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Placé"]["status"] == "reduced"
    assert gates["Placé"]["factor"] == bpp.REDUCE_FACTOR


def test_gate_reste_actif_sous_le_seuil_de_fiabilite_meme_si_roi_tres_negatif():
    perf = {"segments": {"Simple Gagnant": {
        "reliable": False, "roi_pct": None, "roi_pct_raw": -90.0,
        "n_paris": 5, "n_plans": 2, "drawdown_max": None, "montant_mise": 5.0,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Simple Gagnant"]["status"] == "active"
    assert gates["Simple Gagnant"]["factor"] == 1.0


# ── Gates : persistance / lecture / application (session factice) ───────────

class _FakeGateSession:
    def __init__(self, existing=None):
        self.rows = dict(existing or {})
        self.committed = 0

    async def execute(self, statement, params=None, *_a, **_k):
        sql = str(statement)
        params = params or {}
        if "INSERT INTO bet_plan_segment_gates" in sql:
            self.rows[(params["dim"], params["key"])] = (
                params["status"], params["factor"], params["reason"])
            return None
        if "SELECT segment_key, status, factor, reason" in sql:
            dim = params["dim"]
            matches = [(k[1], v[0], v[1], v[2]) for k, v in self.rows.items() if k[0] == dim]
            return _Result(matches)
        raise AssertionError(f"requête inattendue: {sql[:80]}")

    async def commit(self):
        self.committed += 1


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_apply_type_gates_n_abaisse_jamais_au_dela_du_facteur():
    session = _FakeGateSession()
    gates = {"Tiercé Désordre": {"status": "suspended", "factor": 0.0, "reason": "x", "roi_pct": -30, "n_paris": 40}}
    await bpp.persist_segment_gates(session, "type_pari", gates)
    assert session.committed == 1

    weights = {"Placé": 1.4, "Tiercé Désordre": 1.1}
    out = await bpp.apply_type_gates(session, weights)
    assert out["Tiercé Désordre"] == 0.0
    assert out["Placé"] == 1.4   # non gaté → poids appris intact


@pytest.mark.asyncio
async def test_load_segment_gates_ne_leve_jamais_si_table_absente():
    class _Broken:
        async def execute(self, *_a, **_k):
            raise Exception("no such table: bet_plan_segment_gates")

        async def rollback(self):
            pass

    out = await bpp.load_segment_gates(_Broken(), "type_pari")
    assert out == {}


# ── Intégration réelle (SQLite en mémoire, via la fixture `db`) ──────────────

DEPART = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)


def _plan(mise: float, numero: int, type_: str = "Placé", ev: float = 0.1) -> dict:
    return {
        "montant_joue": mise, "ev_global": ev, "esperance_gain": mise * ev,
        "niveaux": [{"niveau": "securite", "paris": [{
            "type": type_, "chevaux": [{"numero": numero, "nom": "X"}],
            "mise": mise, "gain_potentiel": mise * 3, "probabilite": 0.4,
            "ev_estime": ev, "description": "d",
        }]}],
    }


async def _seed(db, course_id, *, numero, gagne, mise=4.0, type_="Placé",
                emitted_at, cote=3.0):
    db.add(Course(course_id=course_id, reunion_id="R1", numero=1, nom="T",
                  date_heure=DEPART, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Participation(participation_id=f"p-{course_id}", course_id=course_id,
                         cheval_id=f"ch-{course_id}", numero=numero, cote_pmu=cote))
    db.add(Resultat(course_id=course_id, classement=[
        {"numero": numero if gagne else numero + 1, "position": 1},
        {"numero": numero if not gagne else numero + 1, "position": 2},
    ]))
    plan = _plan(mise, numero, type_=type_)
    db.add(BetPlanSnapshot(
        plan_snapshot_id=f"bp-{course_id}", course_id=course_id,
        subject_hash="system", profil="equilibre", montant_demande=10.0,
        plan=plan, plan_hash=f"h-{course_id}",
        cotes_utilisees={str(numero): cote}, algo_config={}, algo_version="mp-t",
        nb_paris=1, montant_joue=mise, emitted_at=emitted_at,
        course_start_at=DEPART, is_pre_course=True, origin="mise_plan",
    ))
    net = (mise * 2.5 - mise) if gagne else -mise
    db.add(BetPlanSettlement(
        settlement_id=f"st-{course_id}", plan_snapshot_id=f"bp-{course_id}",
        course_id=course_id,
        bilan={"paris": [{"type": type_, "mise": mise,
                          "gain": mise * 2.5 if gagne else 0.0,
                          "statut": "gagne" if gagne else "perdu"}]},
        montant_mise=mise, montant_retour=mise * 2.5 if gagne else 0.0,
        net=net, roi=(net / mise * 100), nb_paris=1, nb_gagnes=1 if gagne else 0,
        statut="settled", settled_at=emitted_at + timedelta(hours=3),
    ))


@pytest.mark.asyncio
async def test_compute_forward_performance_bout_en_bout(db):
    base = DEPART - timedelta(days=5)
    await _seed(db, "C1", numero=1, gagne=True, emitted_at=base)
    await _seed(db, "C2", numero=2, gagne=False, emitted_at=base + timedelta(hours=1))
    await _seed(db, "C3", numero=3, gagne=False, emitted_at=base + timedelta(hours=2))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    assert out["dimension"] == "type_pari"
    seg = out["segments"]["Placé"]
    assert seg["n_paris"] == 3
    assert seg["n_plans"] == 3
    assert seg["montant_mise"] == 12.0
    assert seg["montant_retour"] == 10.0   # 1 gagné à 4×2.5=10, 2 perdus à 0
    assert seg["net_profit"] == -2.0
    assert out["global"]["n_paris"] == 3


@pytest.mark.asyncio
async def test_compute_forward_performance_respecte_since(db):
    old = DEPART - timedelta(days=200)
    recent = DEPART - timedelta(days=5)
    await _seed(db, "C4", numero=4, gagne=True, emitted_at=old)
    await _seed(db, "C5", numero=5, gagne=True, emitted_at=recent)
    await db.commit()

    since = DEPART - timedelta(days=90)
    out = await bpp.compute_forward_performance(db, "profil", since=since)
    assert out["global"]["n_plans"] == 1   # seule C5 est réglée après `since`


@pytest.mark.asyncio
async def test_naive_favorite_utilise_la_position_pas_l_ordre_du_tableau(db):
    """Le classement n'est PAS garanti trié par position (cf. calibration_longshots.
    fetch_winners) : le favori (cote la plus basse dans cotes_utilisees) doit être
    comparé au numéro dont position == 1, jamais à l'entrée d'index 0."""
    db.add(Course(course_id="CF", reunion_id="R1", numero=1, nom="T",
                  date_heure=DEPART, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Participation(participation_id="p-CF", course_id="CF",
                         cheval_id="ch-CF", numero=7, cote_pmu=2.0))
    # Index 0 = numéro 9 (2e), index 1 = numéro 7 (1er) : ordre INVERSÉ du classement.
    db.add(Resultat(course_id="CF", classement=[
        {"numero": 9, "position": 2},
        {"numero": 7, "position": 1},
    ]))
    db.add(BetPlanSnapshot(
        plan_snapshot_id="bp-CF", course_id="CF", subject_hash="system",
        profil="equilibre", montant_demande=10.0, plan={}, plan_hash="h-CF",
        cotes_utilisees={"7": 2.0, "9": 5.0}, algo_config={}, algo_version="mp-t",
        nb_paris=0, montant_joue=0.0, emitted_at=DEPART - timedelta(hours=1),
        course_start_at=DEPART, is_pre_course=True, origin="mise_plan",
    ))
    await db.commit()

    out = await bpp._naive_favorite_roi(db, ["CF"])
    assert out is not None
    assert out["net_profit"] == 1.0   # favori (7, cote 2.0) a bien gagné → +1€
