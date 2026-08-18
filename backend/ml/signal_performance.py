"""
signal_performance.py — Apprentissage par SIGNAL (auto-amélioration, renta).

Pour chaque signal qualitatif (mêmes définitions que narrative.explain_prediction :
steam, forme excellente, ELO > champ, duo J×E, descente de catégorie, terrain idéal,
draw favorable, SPI…), mesure sur l'HISTORIQUE RÉEL :
  - n          : nb de fois où un partant portait ce signal
  - win_rate   : taux de victoire réel de ces partants
  - roi        : ROI d'un 1€ Simple Gagnant à la cote PMU réelle (Σpayout−Σstake)/Σstake
  - roi_shrunk : ROI shrinké vers 0 (break-even) par pseudo-compte K → pas de
                 sur-réaction sur petit échantillon

→ On apprend ce qui RAPPORTE souvent vs ce qui ne rapporte casi jamais, et on en
nourrit la sélection des value bets (signal_multiplier). Recalculé nightly.
Aucune valeur inventée : tout vient des résultats réels ; signal absent → neutre.
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.prediction_evaluation import (
    MIN_EV_BAND_OBS,
    MIN_EV_BAND_REPLAYABLE_OBS,
    MIN_RAPPORT_CALIB_RUNS,
    MIN_SIGNAL_PERF_OBS,
)

log = structlog.get_logger()

# Définitions des signaux = (nom, prédicat sur le dict features). Alignées sur
# narrative.explain_prediction pour cohérence avec ce que l'utilisateur voit.
SIGNALS: dict = {
    # SOURCES MORTES (audit 2026-07-02) : scrapers bookmakers = 0 ligne, ces signaux
    # ne se déclenchent jamais (n=0, neutres). Conservés : ils se réactiveront seuls
    # si les sources revivent. Les équivalents PMU vivants sont ci-dessous.
    "steam_betclic":      lambda f: (f.get("steam_move_betclic") or 0) > 0.08,
    "gap_pmu_betfair":    lambda f: (f.get("gap_pmu_betfair") or 0) > 0.10,
    "spi_actif":          lambda f: (f.get("spi_score") or 0) > 0.15,
    # STEAM PMU (2026-07-02) : mouvement_30min = (début−fin)/début sur cotes_historique
    # PMU 45 min (peuplé à ~80%, positif = cote en BAISSE). Complète spi_actif (spi_score
    # null sur 76% des partants). ROI appris nightly par profil comme tout signal.
    "steam_pmu_30min":    lambda f: (f.get("mouvement_30min") or 0) > 0.08,
    # DRIFT OUT PMU (2026-07-02) : cote qui MONTE ≥5% — l'hypothèse « value contrarian »
    # du clv_monitor (seg_driftout). Forward marginal mesuré −6.6% (le cumul +3.9%
    # masquait la dégradation) → PAS de boost aveugle : signal APPRIS, le multiplicateur
    # par profil suivra son ROI réel et le coupera/boostera tout seul.
    "drift_out_30min":    lambda f: (f.get("mouvement_30min") or 0) < -0.05,
    "forme_excellente":   lambda f: (f.get("forme_5_courses") or 0.5) > 0.65,
    "forme_basse":        lambda f: (f.get("forme_5_courses") or 0.5) < 0.35,
    "en_progression":     lambda f: (f.get("forme_tendance") or 0) > 0.20,
    "en_regression":      lambda f: (f.get("forme_tendance") or 0) < -0.20,
    "descente_categorie": lambda f: (f.get("class_drop_ratio") or 1.0) < 0.75,
    "montee_categorie":   lambda f: (f.get("class_drop_ratio") or 1.0) > 1.40,
    # terrain_ideal : condition `running_style_terrain_fit > 0.6` RETIRÉE (2026-07-02) —
    # running_style jamais peuplé (0/50645 chevaux) → le AND rendait le signal
    # inerte à vie alors que pref_terrain_actuel vit (terrain_defavorable n=14k).
    "terrain_ideal":      lambda f: (f.get("pref_terrain_actuel") or 0.5) > 0.65,
    "terrain_defavorable": lambda f: (f.get("pref_terrain_actuel") or 0.5) < 0.35,
    "elo_superieur":      lambda f: (f.get("elo_vs_moyenne") or 0) > 50,
    "elo_inferieur":      lambda f: (f.get("elo_vs_moyenne") or 0) < -50,
    "duo_je_efficace":    lambda f: (f.get("asso_jockey_entraineur_nb") or 0) >= 5 and (f.get("asso_jockey_entraineur_taux") or 0) > 0.25,
    "premier_deferre":    lambda f: bool(f.get("premier_deferre")),
    "nouvelles_oeilleres": lambda f: bool(f.get("nouvelles_oeilleres")),
    "draw_favorable":     lambda f: (f.get("draw_bias_score") or 0) > 0.10,
    "sire_dist_fort":     lambda f: (f.get("sire_dist_winrate") or 0.5) > 0.55,
    "pace_conflict":      lambda f: (f.get("pace_conflict_score") or 0) > 0.6,
}

K_SHRINK = 40.0   # pseudo-paris (mise) shrinkant le ROI vers 0


async def compute_signal_performance(session: AsyncSession) -> dict:
    rows = (await session.execute(text("""
        SELECT fm.features, pa.cote_pmu,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE : ne garder que les features FIGÉES AVANT le départ.
          -- Tout backfill/recompute post-course bump computed_at à now() (> date_heure)
          -- → exclu. Sinon on apprend "ce qui rapporte" sur des features reconstruites
          -- a posteriori (fuite temporelle) qui pilotent ensuite les value bets en prod.
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
    """))).fetchall()

    agg = {name: {"n": 0, "wins": 0, "stake": 0.0, "payout": 0.0} for name in SIGNALS}
    for feats, cote, win in rows:
        f = feats if isinstance(feats, dict) else json.loads(feats)
        cote = float(cote)
        for name, pred in SIGNALS.items():
            try:
                if pred(f):
                    a = agg[name]
                    a["n"] += 1
                    a["wins"] += int(win)
                    a["stake"] += 1.0
                    a["payout"] += cote if win else 0.0
            except Exception:
                continue

    signals = {}
    for name, a in agg.items():
        n = a["n"]
        if n == 0:
            signals[name] = {"n": 0, "win_rate": None, "roi": None, "roi_shrunk": 0.0, "multiplier": 1.0}
            continue
        roi = (a["payout"] - a["stake"]) / a["stake"]
        # ROI shrinké : (payout - stake) / (stake + K) → tend vers 0 si n petit
        roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + K_SHRINK)
        # multiplicateur de conviction borné : 1 + roi_shrunk, clampé [0.6, 1.6]
        mult = float(max(0.6, min(1.6, 1.0 + roi_shrunk)))
        signals[name] = {
            "n": n,
            "win_rate": round(a["wins"] / n, 3),
            "roi": round(roi, 3),
            "roi_shrunk": round(roi_shrunk, 3),
            "multiplier": round(mult, 3),
        }
    return {"signals": signals, "n_total": len(rows)}


def _profile_pnl(profil: str, win: int, top3: int, cote: float) -> tuple[float, float]:
    """(mise, gain) d'un 1€ selon l'OBJECTIF du profil — c'est ce qui différencie
    quels signaux "rapportent" pour chaque profil :
      - conservateur : Simple Placé (réussite = top-3) ; rapport placé ≈ (cote-1)/4+1.
      - équilibré    : Simple Gagnant (réussite = victoire) ; toutes cotes.
      - agressif     : Simple Gagnant mais GROS GAINS → ne compte que cote ≥ 6
                        (les outsiders qui gagnent), 0 sinon (ne joue pas les favoris)."""
    if profil == "conservateur":
        rapport_place = max(1.1, (cote - 1) / 4.0 + 1.0)
        return 1.0, (rapport_place if top3 else 0.0)
    if profil == "agressif":
        if cote < 6.0:
            return 0.0, 0.0  # le profil agressif ne parie pas les courtes cotes
        return 1.0, (cote if win else 0.0)
    # équilibré
    return 1.0, (cote if win else 0.0)


async def compute_signal_performance_by_profile(session: AsyncSession) -> dict:
    """Comme compute_signal_performance mais PAR PROFIL (conservateur/équilibré/agressif),
    avec l'objectif propre à chaque profil → les multiplicateurs diffèrent par profil.
    → permet un pronostic adapté au profil sélectionné."""
    rows = (await session.execute(text("""
        SELECT fm.features, pa.cote_pmu,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win,
               CASE WHEN pa.numero IN (
                    SELECT (e->>'numero')::int FROM jsonb_array_elements(r.classement)
                    WITH ORDINALITY a(e,o) WHERE o <= 3
               ) THEN 1 ELSE 0 END AS top3
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE pa.cote_pmu > 1 AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE (cf. compute_signal_performance) : features pré-départ only.
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
    """))).fetchall()

    profils = ["conservateur", "equilibre", "agressif"]
    agg = {p: {name: {"n": 0, "stake": 0.0, "payout": 0.0, "hits": 0} for name in SIGNALS} for p in profils}
    parsed = []
    for feats, cote, win, top3 in rows:
        f = feats if isinstance(feats, dict) else json.loads(feats)
        parsed.append((f, float(cote), int(win), int(top3)))

    for f, cote, win, top3 in parsed:
        present = [name for name, pred in SIGNALS.items() if _safe(pred, f)]
        for p in profils:
            stake, payout = _profile_pnl(p, win, top3, cote)
            if stake <= 0:
                continue
            success = top3 if p == "conservateur" else win
            for name in present:
                a = agg[p][name]
                a["n"] += 1
                a["stake"] += stake
                a["payout"] += payout
                a["hits"] += success

    out = {}
    for p in profils:
        sig = {}
        for name, a in agg[p].items():
            if a["stake"] <= 0:
                sig[name] = {"n": a["n"], "roi_shrunk": 0.0, "multiplier": 1.0, "hit_rate": None}
                continue
            roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + K_SHRINK)
            sig[name] = {
                "n": a["n"],
                "hit_rate": round(a["hits"] / a["n"], 3) if a["n"] else None,
                "roi": round((a["payout"] - a["stake"]) / a["stake"], 3),
                "roi_shrunk": round(roi_shrunk, 3),
                "multiplier": round(float(max(0.6, min(1.6, 1.0 + roi_shrunk))), 3),
            }
        out[p] = sig
    return {"profils": out, "n_total": len(rows)}


def _safe(pred, f) -> bool:
    try:
        return bool(pred(f))
    except Exception:
        return False


async def persist_signal_performance(session: AsyncSession, perf: dict) -> bool:
    """Persiste les multiplicateurs de signaux. False = état existant PRÉSERVÉ.

    Cold start : la garde anti-leakage (features figées avant départ) peut ne
    retenir aucune ligne. ``compute_signal_performance`` renvoie alors tous les
    signaux à multiplier=1.0 — une structure complète, donc indiscernable d'un
    apprentissage légitime une fois écrite. On refuse l'écriture sous le seuil.
    """
    if int(perf.get("n_total") or 0) < MIN_SIGNAL_PERF_OBS:
        log.warning(
            "signal_performance.skipped_insufficient_replayable_data",
            n_obs=int(perf.get("n_total") or 0), min_obs=MIN_SIGNAL_PERF_OBS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS signal_performance (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT signal_perf_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO signal_performance (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_signal_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM signal_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


# ── Apprentissage par BANDE D'EV ─────────────────────────────────────────────
# ev = cote_figée × proba_modèle − 1 (excédent d'EV ; 0 = break-even). On mesure le
# ROI RÉEL d'un 1€ Simple Gagnant flat par bande → la sélection des value bets
# rétrograde les bandes perdantes et promeut les gagnantes, au lieu d'un couperet
# dur. Borné par bande [début, fin). Recalculé nightly. Aucune valeur inventée.
EV_BANDS: list[tuple[float, float]] = [
    (-1.0, 0.00),   # EV négatif (sur-coté côté marché)
    (0.00, 0.10),   # léger edge
    (0.10, 0.20),
    (0.20, 0.35),
    (0.35, 0.60),
    (0.60, 99.0),   # gros edge claironné = souvent sur-confiance longshot
]
EV_K_SHRINK = 60.0   # pseudo-mises shrinkant le ROI d'une bande vers 0


def _ev_band_key(ev: float) -> str:
    for lo, hi in EV_BANDS:
        if lo <= ev < hi:
            return f"{lo:.2f}_{hi:.2f}"
    return f"{EV_BANDS[-1][0]:.2f}_{EV_BANDS[-1][1]:.2f}"


async def compute_ev_band_performance(session: AsyncSession) -> dict:
    """ROI réel par bande d'EV, depuis les pronostics FIGÉS avant départ ⋈ résultats.
    ev = cote_figee × proba_top1 − 1. Flat 1€ Simple Gagnant à la cote figée."""
    rows = (await session.execute(text("""
        SELECT p.cote_figee, p.proba_top1,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM prediction_evaluation p
        JOIN participations pa ON pa.participation_id = p.participation_id
        JOIN courses c ON c.course_id = p.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = p.course_id
        WHERE p.cote_figee IS NOT NULL AND p.cote_figee > 1
          AND p.proba_top1 IS NOT NULL AND jsonb_typeof(r.classement) = 'array'
          -- ANTI-LEAKAGE : prono FIGÉ avant le départ uniquement (cf. signal learner).
          AND c.date_heure IS NOT NULL AND p.created_at < c.date_heure
          AND p.is_replayable = true
    """))).fetchall()

    agg = {f"{lo:.2f}_{hi:.2f}": {"n": 0, "wins": 0, "stake": 0.0, "payout": 0.0}
           for lo, hi in EV_BANDS}
    for cote, proba, win in rows:
        cote = float(cote); proba = float(proba)
        ev = cote * proba - 1.0
        a = agg[_ev_band_key(ev)]
        a["n"] += 1
        a["wins"] += int(win)
        a["stake"] += 1.0
        a["payout"] += cote if win else 0.0

    bands = {}
    for key, a in agg.items():
        n = a["n"]
        if n == 0:
            bands[key] = {"n": 0, "win_rate": None, "roi": None, "roi_shrunk": 0.0, "multiplier": 1.0}
            continue
        roi = (a["payout"] - a["stake"]) / a["stake"]
        roi_shrunk = (a["payout"] - a["stake"]) / (a["stake"] + EV_K_SHRINK)
        reliable = n >= MIN_EV_BAND_OBS
        mult = float(max(0.5, min(1.6, 1.0 + roi_shrunk))) if reliable else 1.0
        bands[key] = {
            "n": n,
            "win_rate": round(a["wins"] / n, 3),
            "roi": round(roi, 3),
            "roi_shrunk": round(roi_shrunk, 3),
            "multiplier": round(mult, 3),
            "reliable": reliable,
        }
    return {"bands": bands, "n_total": len(rows)}


async def persist_ev_band_performance(session: AsyncSession, perf: dict) -> bool:
    if int(perf.get("n_total") or 0) < MIN_EV_BAND_REPLAYABLE_OBS:
        log.warning(
            "ev_band_performance.skipped_insufficient_replayable_data",
            n_obs=int(perf.get("n_total") or 0),
            min_obs=MIN_EV_BAND_REPLAYABLE_OBS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS ev_band_performance (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ev_band_perf_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO ev_band_performance (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_ev_band_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM ev_band_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def ev_band_multiplier(ev: float, perf: dict | None) -> float:
    """Multiplicateur de conviction pour la bande d'EV de ce pari, appris du ROI réel.
    1.0 si pas de table / bande inconnue / échantillon nul → neutre."""
    if not perf:
        return 1.0
    bands = perf.get("bands") or {}
    band = bands.get(_ev_band_key(ev))
    if not band or not band.get("n"):
        return 1.0
    return float(band.get("multiplier", 1.0))


# ── Calibration RAPPORT estimé → RÉEL par (profil × type) ─────────────────────
# PROBLÈME RÉSOLU : le moteur estime le rapport d'un pari (TRJ / proba_marché) AVANT la
# course, mais le rapport PMU RÉELLEMENT payé diffère — un Simple Placé sur favori court
# est estimé ~×1.9 (passe la bande prudent ×1.8) mais paie ~×1.3 en réalité → la bande
# affichée dans le BILAN est violée. On apprend, depuis les pronos FIGÉS réglés
# (profil_run_log), le facteur médian rapport_RÉEL / rapport_ESTIMÉ parmi les paris
# GAGNANTS, PAR (profil × type). Le gate de bande s'applique alors au rapport ATTENDU
# (estimé × facteur) : un type qui paie systématiquement sous la bande de son profil est
# ÉCARTÉ — c'est l'apprentissage qui empêche la violation des tranches sur le réel.
# Aucune valeur inventée : facteur 1.0 (neutre) tant que < RC_MIN_WINS gagnants.
RC_K_SHRINK = 12.0          # pseudo-gagnants shrinkant le facteur vers 1.0 (anti petit n)
RC_MIN_WINS = 8             # nb de gagnants min (avec estimé connu) avant d'appliquer un facteur
RC_F_MIN, RC_F_MAX = 0.40, 1.30   # bornes du facteur (correction prudente)


def _bet_key(type_pari, chevaux) -> tuple:
    """Clé d'un pari = (type, numéros triés) pour matcher plan figé ⋈ bilan réglé."""
    nums = tuple(sorted(int(h["numero"]) for h in (chevaux or [])
                        if h.get("numero") is not None))
    return (type_pari, nums)


async def compute_rapport_calibration(session: AsyncSession) -> dict:
    """Facteur rapport_réel / rapport_estimé par (profil × type), depuis profil_run_log
    réglé (figé AVANT départ). Lecture seule. Mêmes gardes anti-leakage que
    compute_profil_weights (flag oos_weights → pronos pré-départ non backfillés)."""
    try:
        from ml.algo_flags import FLAGS as _AF
        oos = bool(getattr(_AF, "oos_weights", False))
    except Exception:
        oos = False
    guard = ("AND c.date_heure IS NOT NULL AND r.created_at < c.date_heure "
             "AND COALESCE(r.meta->>'backfill','') <> 'true'") if oos else ""
    rows = (await session.execute(text(f"""
        SELECT r.profil, r.plan, r.resultat
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL AND r.plan IS NOT NULL
          {guard}
    """))).all()

    # agg[profil][type] = {n_win, sum_est, sum_real, n, mise, gain}
    agg: dict = {}
    for profil, plan, resultat in rows:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan)
        res = resultat if isinstance(resultat, dict) else json.loads(resultat)
        # rapport ESTIMÉ par pari, reconstruit depuis le plan figé (gain_potentiel/mise)
        est: dict = {}
        for niv in plan_d.get("niveaux", []):
            for p in niv.get("paris", []):
                mise = float(p.get("mise") or 0)
                if mise > 0:
                    est[_bet_key(p.get("type"), p.get("chevaux"))] = \
                        float(p.get("gain_potentiel") or 0) / mise
        pa = agg.setdefault(profil, {})
        for p in res.get("paris", []):
            if p.get("statut") == "rembourse":
                continue                          # NP : neutre, jamais compté
            t = p.get("type")
            if not t:
                continue
            ta = pa.setdefault(t, {"n_win": 0, "sum_est": 0.0, "sum_real": 0.0,
                                   "n": 0, "mise": 0.0, "gain": 0.0})
            ta["n"] += 1
            ta["mise"] += float(p.get("mise") or 0)
            if p.get("statut") == "gagne" and p.get("rapport_reel"):
                re_ = est.get(_bet_key(t, p.get("chevaux")))
                ta["gain"] += float(p.get("gain") or 0)
                if re_ and re_ > 0:               # estimé connu → couple (estimé, réel)
                    ta["n_win"] += 1
                    ta["sum_est"] += re_
                    ta["sum_real"] += float(p["rapport_reel"])

    def _factor(a: dict) -> float:
        if a["n_win"] >= RC_MIN_WINS and a["sum_est"] > 0:
            raw = a["sum_real"] / a["sum_est"]
            w = a["n_win"] / (a["n_win"] + RC_K_SHRINK)       # shrink vers 1.0
            return float(max(RC_F_MIN, min(RC_F_MAX, 1.0 + (raw - 1.0) * w)))
        return 1.0                                            # échantillon insuffisant → neutre

    def _entry(a: dict) -> dict:
        return {
            "factor": round(_factor(a), 3),
            "n_win": a["n_win"], "n": a["n"],
            "real_mean": round(a["sum_real"] / a["n_win"], 2) if a["n_win"] else None,
            "est_mean": round(a["sum_est"] / a["n_win"], 2) if a["n_win"] else None,
            "roi": round((a["gain"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None,
        }

    # POOL GLOBAL PAR TYPE (tous profils confondus) — fallback quand le couple
    # (profil × type) n'a pas assez de gagnants. Cas mesuré (audit 2026-07-02) :
    # Couplé Ordre estimé ×40 payé ×11 mais 5 gagnants en risqué (< RC_MIN_WINS)
    # → facteur neutre à vie PAR profil alors que le pool tous-profils (21 gagnants)
    # prouve la surestimation. Le rapport parimutuel ne dépend pas du profil.
    out = {"profils": {}, "global": {}, "n_runs": len(rows)}
    glob: dict = {}
    for profil, types in agg.items():
        po = {}
        for t, a in types.items():
            po[t] = _entry(a)
            g = glob.setdefault(t, {"n_win": 0, "sum_est": 0.0, "sum_real": 0.0,
                                    "n": 0, "mise": 0.0, "gain": 0.0})
            for k in g:
                g[k] += a[k]
        out["profils"][profil] = po
    for t, a in glob.items():
        out["global"][t] = _entry(a)
    return out


async def persist_rapport_calibration(session: AsyncSession, perf: dict) -> bool:
    """Persiste la calibration estimé→réel des rapports. False = état PRÉSERVÉ.

    Source : ``profil_run_log`` réglé, filtré par les gardes anti-leakage. Si ce
    filtre ne laisse plus rien (règlement en retard, backfills exclus), les
    facteurs retombent tous à 1.0 et le gate de bande cesserait d'écarter les
    types qui paient sous la tranche de leur profil.
    """
    if int(perf.get("n_runs") or 0) < MIN_RAPPORT_CALIB_RUNS:
        log.warning(
            "rapport_calibration.skipped_insufficient_replayable_data",
            n_runs=int(perf.get("n_runs") or 0), min_runs=MIN_RAPPORT_CALIB_RUNS,
        )
        return False
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS rapport_calibration (
            id INT PRIMARY KEY DEFAULT 1,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT rapport_calib_singleton CHECK (id = 1)
        )
    """))
    await session.execute(text("""
        INSERT INTO rapport_calibration (id, data, updated_at) VALUES (1, :d, now())
        ON CONFLICT (id) DO UPDATE SET data = :d, updated_at = now()
    """), {"d": json.dumps(perf)})
    await session.commit()
    return True


async def load_rapport_calibration(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text(
            "SELECT data FROM rapport_calibration WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


def rapport_realization_factor(profil: str | None, type_pari: str | None,
                               calib: dict | None) -> float:
    """Facteur estimé→réel pour ce (profil × type). Fallback sur le POOL GLOBAL du
    type (tous profils) quand le couple (profil × type) n'a pas de facteur appris —
    le rapport parimutuel réel ne dépend pas du profil qui joue. 1.0 (neutre) si pas
    de table / type inconnu / échantillon insuffisant → aucun effet (cold-start sûr)."""
    if not calib or not profil or not type_pari:
        return 1.0
    t = (calib.get("profils") or {}).get(profil, {}).get(type_pari)
    f = float((t or {}).get("factor", 1.0) or 1.0)
    if f != 1.0:
        return f
    g = (calib.get("global") or {}).get(type_pari)
    return float((g or {}).get("factor", 1.0) or 1.0)


def signal_multiplier(features: dict, perf: dict | None, profil: str | None = None) -> float:
    """Multiplicateur de conviction d'un partant = produit (borné) des multiplicateurs
    des signaux qu'il porte, appris du ROI réel. PROFILE-AWARE : si `profil` fourni et
    une table par profil existe, on utilise le ROI appris POUR CE PROFIL (un même
    signal peut aider à se placer mais pas à gagner). Fallback table globale. 1.0 sinon."""
    if not perf:
        return 1.0
    sigs = None
    if profil and perf.get("profils", {}).get(profil):
        sigs = perf["profils"][profil]
    elif perf.get("signals"):
        sigs = perf["signals"]
    if not sigs:
        return 1.0
    m = 1.0
    for name, pred in SIGNALS.items():
        try:
            if pred(features) and name in sigs:
                m *= sigs[name].get("multiplier", 1.0)
        except Exception:
            continue
    return float(max(0.5, min(2.0, m)))
