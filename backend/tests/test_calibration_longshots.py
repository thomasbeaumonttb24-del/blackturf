"""Tests unitaires des fonctions PURES de scripts/calibration_longshots.

Couvre l'agrégation par bucket (compute_bucket_stats) et la dérivation des
garde-fous (recommend_gate_params) — sans DB. Données synthétiques uniquement.
"""
from scripts.calibration_longshots import (
    bucket_label, compute_bucket_stats, recommend_gate_params, MIN_OBS,
)


def _rows(cote: float, proba: float, n: int, win_every: int, start_course: int = 0):
    """Génère n lignes (proba, cote, numero, course_id) ; 1 gagnant tous les
    win_every. Retourne (rows, winners)."""
    rows, winners = [], {}
    for i in range(n):
        cid = f"c{start_course + i}"
        rows.append((proba, cote, 1, cid))
        winners[cid] = {1} if ((i + 1) % win_every == 0) else {2}  # numero 1 gagne ou pas
    return rows, winners


def _merge(*pairs):
    rows, winners = [], {}
    for r, w in pairs:
        rows.extend(r); winners.update(w)
    return rows, winners


# ── bucket_label ──────────────────────────────────────────────────────────────
def test_bucket_label_bornes():
    assert bucket_label(1.5) == "[1.5 – 2.5)"
    assert bucket_label(2.4) == "[1.5 – 2.5)"
    assert bucket_label(2.5) == "[2.5 – 4)"
    assert bucket_label(35.0) == "[20 – 40)"
    assert bucket_label(50.0) == "[40 – ∞)"


# ── compute_bucket_stats ──────────────────────────────────────────────────────
def test_bucket_sous_min_obs_est_non_fiable():
    rows, winners = _rows(cote=3.0, proba=0.35, n=MIN_OBS - 1, win_every=3)
    stats = compute_bucket_stats(rows, winners)
    b = next(s for s in stats if s["bucket"] == "[2.5 – 4)")
    assert b["n"] == MIN_OBS - 1
    assert b["reliable"] is False
    assert b["ratio"] is None and b["freq"] is None   # pas d'extrapolation


def test_bucket_fiable_calcule_freq_et_ratio():
    # cote 3.0 → bucket [2.5–4) ; proba prédite 0.30 ; 1 gagnant sur 2 → freq 0.5
    rows, winners = _rows(cote=3.0, proba=0.30, n=40, win_every=2)
    stats = compute_bucket_stats(rows, winners)
    b = next(s for s in stats if s["bucket"] == "[2.5 – 4)")
    assert b["reliable"] is True
    assert b["n"] == 40
    assert b["freq"] == 0.5
    assert b["proba_moy"] == 0.30
    assert b["ratio"] == 0.30 / 0.5
    assert b["verdict"] == "sous-évalué"   # ratio 0.6 ≤ 0.67


def test_bucket_surevalue_verdict():
    # longshot : proba prédite 0.10 mais ne gagne quasi jamais (1/40 → freq 0.025)
    rows, winners = _rows(cote=25.0, proba=0.10, n=40, win_every=40)
    stats = compute_bucket_stats(rows, winners)
    b = next(s for s in stats if s["bucket"] == "[20 – 40)")
    assert b["reliable"] is True
    assert b["freq"] == 1 / 40
    assert b["ratio"] >= 1.5
    assert b["verdict"] == "SUR-ÉVALUÉ ⚠"


def test_cote_invalide_ignoree():
    rows = [(0.3, 1.0, 1, "c0"), (0.3, 0.5, 1, "c1")]   # cote ≤ 1 → ignorées
    winners = {"c0": {1}, "c1": {1}}
    stats = compute_bucket_stats(rows, winners)
    assert sum(s["n"] for s in stats) == 0


def test_course_sans_resultat_ignoree():
    rows = [(0.3, 3.0, 1, "c0")]
    stats = compute_bucket_stats(rows, winners={})   # aucun résultat
    assert sum(s["n"] for s in stats) == 0


# ── recommend_gate_params ─────────────────────────────────────────────────────
def test_recommend_sans_bucket_surevalue_renvoie_null():
    # un seul bucket favori bien calibré → rien à recommander
    rows, winners = _rows(cote=3.0, proba=0.30, n=40, win_every=2)
    rec = recommend_gate_params(compute_bucket_stats(rows, winners))
    assert rec["longshot_cote_min"] is None
    assert rec["max_model_market_ratio"] is None
    assert "longshot_cote_min" in rec["insufficient_data"]


def test_recommend_derive_constantes_des_buckets_surevalues():
    # favori calibré (cote 3) + longshot sur-évalué qui s'effondre (cote 25)
    favori = _rows(cote=3.0, proba=0.30, n=40, win_every=2, start_course=0)
    longshot = _rows(cote=25.0, proba=0.10, n=40, win_every=40, start_course=1000)
    rec = recommend_gate_params(compute_bucket_stats(*_merge(favori, longshot)))
    # 1er bucket sur-évalué = [20–40) → borne basse 20
    assert rec["longshot_cote_min"] == 20.0
    assert 1.5 <= rec["max_model_market_ratio"] <= 3.0
    # freq longshot 0.025 > 0.02 → pas d'effondrement → cote_max_vb non calable
    assert rec["cote_max_vb"] is None
    assert "cote_max_vb" in rec["insufficient_data"]


def test_recommend_cote_max_vb_sur_effondrement():
    # longshot qui ne gagne JAMAIS (freq 0 < 0.02) → cote_max_vb calé
    longshot = _rows(cote=25.0, proba=0.10, n=40, win_every=10_000, start_course=2000)
    rec = recommend_gate_params(compute_bucket_stats(*longshot))
    assert rec["cote_max_vb"] == 20.0
    assert rec["rationale"]["cote_max_vb"]
