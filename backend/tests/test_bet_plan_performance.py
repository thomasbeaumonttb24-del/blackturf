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


def test_gate_reduit_sur_serie_perdante_bien_au_dela_de_l_attendu():
    # 1 réussite sur 2 sur 100 plans → série perdante attendue ≈ 6,6 ; observée 20,
    # soit 3× l'attendu, sans avantage démontré → réduction (pas suspension).
    perf = {"segments": {"Placé": {
        "reliable": True, "roi_pct": -5.0, "edge_pct": -1.0, "n_paris": 60,
        "n_plans": 100, "drawdown_max": 55.0, "montant_mise": 100.0,
        "losing_streak_attendue": 6.6, "losing_streak_max": 20,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Placé"]["status"] == "reduced"
    assert gates["Placé"]["factor"] == bpp.REDUCE_FACTOR


def _mini_multi_en_4(**override) -> dict:
    """« Mini Multi en 4 » tel que mesuré en prod, paramétrable."""
    seg = {
        "reliable": True, "roi_pct": 332.3, "roi_pct_winsor": 332.3,
        "edge_pct": 362.3, "edge_pct_winsor": 362.3, "prelevement_pct": 30.0,
        "n_paris": 215, "n_courses": 215, "n_plans": 300,
        "drawdown_max": 900.0, "montant_mise": 1000.0,
        "losing_streak_attendue": 60.5, "losing_streak_max": 200,
    }
    seg.update(override)
    return {"segments": {"Mini Multi en 4": seg}}


def test_gate_ne_penalise_pas_un_pari_rare_mais_rentable():
    """Un pari qui tombe une fois sur onze enchaîne NORMALEMENT de longues séries
    perdantes. Tant que son avantage est positif, ce n'est pas un signal de risque —
    l'ancienne règle (drawdown ≥ 50 % de la mise) rétrogradait « Mini Multi en 4 »
    mesuré à +332 % de ROI.

    La série perdante ne doit toujours pas suffire à le rétrograder, à condition
    qu'il ait été observé sur assez de COURSES distinctes (cf. le test suivant)."""
    gates = bpp.evaluate_segment_gates(_mini_multi_en_4(n_courses=215))
    assert gates["Mini Multi en 4"]["status"] == "active"
    assert gates["Mini Multi en 4"]["factor"] == 1.0


def test_le_meme_pari_est_reduit_quand_les_215_paris_ne_font_que_17_courses():
    """Le chiffre réel de la production au 2026-08-31 : ces 215 paris ne couvrent
    que **17 courses**, parce qu'un plan est ré-émis à chaque mouvement de cote
    (~33 snapshots par course). Le +332 % de ROI ne repose donc pas sur 215
    observations indépendantes, et un ROI non winsorisé sur 17 courses n'est pas
    une preuve de rentabilité. On ne coupe pas — rien ne prouve que ce type soit
    mauvais — mais on refuse de miser à plein régime dessus."""
    gates = bpp.evaluate_segment_gates(_mini_multi_en_4(n_courses=17))
    assert gates["Mini Multi en 4"]["status"] == "reduced"
    assert gates["Mini Multi en 4"]["factor"] == bpp.REDUCE_FACTOR
    assert "17 courses" in gates["Mini Multi en 4"]["reason"]


def test_gate_juge_l_avantage_sur_le_pool_pas_le_roi_absolu():
    """Valeurs réelles mesurées en prod le 2026-08-23 (fenêtre 90 j) : le Couplé Placé
    a un ROI MEILLEUR que le Mini Multi en 6, mais un prélèvement bien plus faible —
    c'est donc lui qui est réellement plus loin du hasard sur son propre pool."""
    perf = {"segments": {
        "Couplé Placé": {"reliable": True, "roi_pct": -32.7, "prelevement_pct": 23.0,
                         "edge_pct": -9.7, "n_paris": 2738, "n_plans": 2000,
                         "losing_streak_attendue": 20.0, "losing_streak_max": 25},
        "Mini Multi en 6": {"reliable": True, "roi_pct": -37.8, "prelevement_pct": 30.0,
                            "edge_pct": -7.8, "n_paris": 186, "n_plans": 180,
                            "losing_streak_attendue": 30.0, "losing_streak_max": 35},
    }}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Couplé Placé"]["status"] == "suspended"
    assert gates["Mini Multi en 6"]["status"] == "active"


def test_gate_repli_sur_le_roi_absolu_quand_le_prelevement_est_inconnu():
    perf = {"segments": {"Type inconnu": {
        "reliable": True, "roi_pct": -35.0, "edge_pct": None, "n_paris": 80,
        "n_plans": 40, "drawdown_max": 10.0, "montant_mise": 80.0,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Type inconnu"]["status"] == "suspended"
    assert "repli" in gates["Type inconnu"]["reason"]


def test_prelevement_moyen_est_pondere_par_la_mise():
    """9 € sur un couplé (23 %) et 1 € sur un simple (15,5 %) → 22,25 %, pas 19,25 %
    (moyenne par ticket) : c'est l'argent engagé qui subit le prélèvement."""
    bets = [{"mise": 9.0, "type": "Couplé Gagnant", "gain": None, "statut": "perdu"},
            {"mise": 1.0, "type": "Simple Gagnant", "gain": None, "statut": "perdu"}]
    assert bpp._prelevement_moyen_pct(bets) == 22.25


def test_avantage_ajoute_le_prelevement_au_roi():
    bets = [{"mise": 1.0, "type": "Couplé Gagnant", "gain": None, "statut": "perdu"}
            for _ in range(bpp.MIN_SEGMENT_OBS)]
    bets[0] = {"mise": 1.0, "type": "Couplé Gagnant", "gain": 25.0, "statut": "gagne"}
    m = bpp._metrics_for_group(bets, [])
    assert m["prelevement_pct"] == 23.0
    assert m["edge_pct"] == round(m["roi_pct"] + 23.0, 2)


def test_streak_attendue_croit_quand_le_pari_est_rare():
    rare = bpp._streak_attendue(0.09, 300)
    frequent = bpp._streak_attendue(0.50, 300)
    assert rare > frequent > 0
    assert bpp._streak_attendue(None, 300) is None
    assert bpp._streak_attendue(0.0, 300) is None
    assert bpp._streak_attendue(0.5, 1) is None


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
                params["status"], params["factor"], params["reason"],
                params.get("roi"), params.get("n"))
            return None
        if "SELECT segment_key, status, factor, reason" in sql:
            # roi_pct et n_paris sont lus depuis 2026-08-20 : ils servent à classer les
            # types quand un profil doit en réanimer (garde-fou de catalogue).
            dim = params["dim"]
            matches = [(k[1], v[0], v[1], v[2], v[3], v[4])
                       for k, v in self.rows.items() if k[0] == dim]
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


# ── Référence CLASSEMENT : la sélection apporte-t-elle quelque chose ? ───────

def test_taille_baseline_par_type():
    assert bpp._taille_baseline("Simple Placé") == 1
    assert bpp._taille_baseline("Couplé Gagnant") == 2
    assert bpp._taille_baseline("Trio") == 3
    assert bpp._taille_baseline("Multi en 6") == 6
    assert bpp._taille_baseline("Mini Multi en 4") == 4
    assert bpp._taille_baseline("Type exotique") is None


async def _seed_course_classement(db, course_id, *, arrivee, rangs, rapports,
                                  non_partants=(), nb_partants=10, created_at=None):
    """Une course terminée + le classement prédit, pour la référence classement.

    `rangs` : {rang_predit: numero}. `arrivee` : numéros dans l'ordre d'arrivée.
    """
    db.add(Course(course_id=course_id, reunion_id="R9", numero=1, nom="T",
                  date_heure=DEPART, hippodrome_nom="Vincennes", discipline="Attelé",
                  distance=2700, nb_partants=nb_partants, statut="termine"))
    for rang, numero in rangs.items():
        pid = f"pa-{course_id}-{numero}"
        db.add(Participation(participation_id=pid, course_id=course_id,
                             cheval_id=f"ch-{course_id}-{numero}", numero=numero,
                             cote_pmu=3.0, non_partant=(numero in non_partants)))
        db.add(Prediction(prediction_id=f"pr-{course_id}-{numero}",
                          participation_id=pid, course_id=course_id,
                          proba_top1=0.5, proba_top3=0.7, rang_predit=rang,
                          # created_at EXPLICITE : la référence classement ne lit que
                          # les pronostics antérieurs au départ. Sans cette date, le
                          # défaut `now()` tombe après DEPART et la référence est vide.
                          created_at=created_at or (DEPART - timedelta(minutes=10))))
    db.add(Resultat(course_id=course_id, rapports=rapports, classement=[
        {"numero": n, "position": i + 1} for i, n in enumerate(arrivee)]))


@pytest.mark.asyncio
async def test_baseline_classement_mesure_le_simple_suivi_du_classement(db):
    # Course A : le n°1 du classement gagne, rapport 4.0 → +3 €.
    await _seed_course_classement(db, "B1", arrivee=[7, 8, 9],
                                  rangs={1: 7, 2: 8, 3: 9},
                                  rapports={"e_simple_gagnant": 4.0})
    # Course B : le n°1 du classement perd → −1 €.
    await _seed_course_classement(db, "B2", arrivee=[9, 8, 7],
                                  rangs={1: 7, 2: 8, 3: 9},
                                  rapports={"e_simple_gagnant": 4.0})
    await db.commit()

    out = await bpp._baseline_classement_par_type(db, ["B1", "B2"], ["Simple Gagnant"])
    sg = out["Simple Gagnant"]
    assert sg["n_courses"] == 2 and sg["mise"] == 2.0
    assert sg["gain"] == 4.0          # une seule course gagnante, rapport 4
    assert sg["roi_pct"] == 100.0     # 4 € rendus pour 2 € engagés
    assert sg["prelevement_pct"] == 15.5
    assert sg["edge_pct"] == 115.5


@pytest.mark.asyncio
async def test_baseline_exclut_un_gagnant_sans_rapport_publie(db):
    """Même règle d'honnêteté que le règlement : un gain inconnu sort de la mesure,
    il n'est jamais compté 0 — sinon la référence se dégrade toute seule."""
    await _seed_course_classement(db, "B3", arrivee=[7, 8, 9],
                                  rangs={1: 7, 2: 8, 3: 9}, rapports={})
    await db.commit()

    out = await bpp._baseline_classement_par_type(db, ["B3"], ["Simple Gagnant"])
    sg = out["Simple Gagnant"]
    assert sg["n_courses"] == 0 and sg["n_rapport_absent"] == 1
    assert sg["roi_pct"] is None


@pytest.mark.asyncio
async def test_baseline_ignore_les_non_partants_dans_le_classement(db):
    """Le n°1 du classement est non-partant → la référence joue le suivant, pas un
    cheval absent (et ne se règle pas en 'remboursé')."""
    await _seed_course_classement(db, "B4", arrivee=[8, 9, 6],
                                  rangs={1: 7, 2: 8, 3: 9}, non_partants=(7,),
                                  rapports={"e_simple_gagnant": 5.0})
    await db.commit()

    out = await bpp._baseline_classement_par_type(db, ["B4"], ["Simple Gagnant"])
    sg = out["Simple Gagnant"]
    assert sg["n_courses"] == 1
    assert sg["gain"] == 5.0          # le n°2 du classement (8) a gagné


def test_gate_reduit_une_selection_sous_la_reference_classement():
    """Valeurs réelles du 2026-08-23 : le moteur rend −32,7 % sur le Couplé Placé
    là où « les 2 premiers du classement » rend −11,5 %."""
    perf = {"segments": {"Couplé Placé": {
        "reliable": True, "roi_pct": -32.7, "prelevement_pct": 23.0, "edge_pct": -5.0,
        "n_paris": 2738, "n_plans": 2000,
        "baseline_classement": {"roi_pct": -11.5, "n_courses": 695, "edge_pct": 11.5},
        "delta_vs_classement_pct": -21.2,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Couplé Placé"]["status"] == "reduced"
    assert gates["Couplé Placé"]["factor"] == bpp.REDUCE_FACTOR
    assert "classement" in gates["Couplé Placé"]["reason"]


def test_gate_ignore_une_reference_classement_trop_courte():
    perf = {"segments": {"Trio": {
        "reliable": True, "roi_pct": -30.0, "prelevement_pct": 25.0, "edge_pct": -5.0,
        "n_paris": 200, "n_plans": 150,
        "baseline_classement": {"roi_pct": 5.0, "n_courses": 4},
        "delta_vs_classement_pct": -35.0,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Trio"]["status"] == "active"


def test_gate_ne_ressuscite_pas_un_type_dont_la_reference_perd_aussi():
    """Valeurs du 2026-08-23 : le Trio est 12 pts sous sa référence classement, mais
    cette référence perd elle-même (avantage −6,2) — le type reste suspendu. Seul un
    type viable EN SUIVANT LE CLASSEMENT échappe à la suspension."""
    perf = {"segments": {"Trio": {
        "reliable": True, "roi_pct": -43.4, "prelevement_pct": 25.0, "edge_pct": -18.4,
        "n_paris": 3755, "n_plans": 3000,
        "baseline_classement": {"roi_pct": -31.2, "edge_pct": -6.2, "n_courses": 205},
        "delta_vs_classement_pct": -12.2,
    }}}
    gates = bpp.evaluate_segment_gates(perf)
    assert gates["Trio"]["status"] == "suspended"
    assert gates["Trio"]["factor"] == 0.0


@pytest.mark.asyncio
async def test_la_reference_classement_ignore_un_pronostic_ecrit_apres_le_depart(db):
    """Un pronostic postérieur au départ n'a pas sa place dans un comparateur.

    La référence « classement » décide d'une suspension via `delta_vs_classement` :
    la nourrir d'un pronostic écrit après l'arrivée y ferait entrer de la
    connaissance du résultat. En production 1 000 prédictions (90 courses) sont
    dans ce cas — aucune n'appartenait encore à la cohorte des plans le
    2026-08-31 (0 sur 628), le garde-fou est donc préventif.
    """
    await _seed_course_classement(db, "BF", arrivee=[7, 8, 9],
                                  rangs={1: 7, 2: 8, 3: 9},
                                  rapports={"e_simple_gagnant": 4.0},
                                  created_at=DEPART + timedelta(minutes=30))
    await db.commit()
    out = await bpp._baseline_classement_par_type(db, ["BF"], ["Simple Gagnant"])
    assert "Simple Gagnant" not in out or out["Simple Gagnant"]["n_courses"] == 0, (
        "la référence a compté une course dont le pronostic est postérieur au départ")
