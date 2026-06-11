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

log = structlog.get_logger()

# Définitions des signaux = (nom, prédicat sur le dict features). Alignées sur
# narrative.explain_prediction pour cohérence avec ce que l'utilisateur voit.
SIGNALS: dict = {
    "steam_betclic":      lambda f: (f.get("steam_move_betclic") or 0) > 0.08,
    "gap_pmu_betfair":    lambda f: (f.get("gap_pmu_betfair") or 0) > 0.10,
    "spi_actif":          lambda f: (f.get("spi_score") or 0) > 0.15,
    "forme_excellente":   lambda f: (f.get("forme_5_courses") or 0.5) > 0.65,
    "forme_basse":        lambda f: (f.get("forme_5_courses") or 0.5) < 0.35,
    "en_progression":     lambda f: (f.get("forme_tendance") or 0) > 0.20,
    "en_regression":      lambda f: (f.get("forme_tendance") or 0) < -0.20,
    "descente_categorie": lambda f: (f.get("class_drop_ratio") or 1.0) < 0.75,
    "montee_categorie":   lambda f: (f.get("class_drop_ratio") or 1.0) > 1.40,
    "terrain_ideal":      lambda f: (f.get("pref_terrain_actuel") or 0.5) > 0.65 and (f.get("running_style_terrain_fit") or 0.5) > 0.6,
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


async def persist_signal_performance(session: AsyncSession, perf: dict) -> None:
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


async def load_signal_performance(session: AsyncSession) -> dict | None:
    try:
        r = (await session.execute(text("SELECT data FROM signal_performance WHERE id=1"))).first()
        return r[0] if r else None
    except Exception:
        return None


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
