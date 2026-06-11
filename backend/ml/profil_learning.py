"""
profil_learning.py — Apprentissage sur les PRONOSTICS RÉELLEMENT ÉMIS par profil.

Différence fondamentale avec profil_backtest (rejeu nightly a posteriori) :
ici, chaque prédiction de course FIGE le plan de mise des 3 profils
(conservateur / équilibré / agressif) AVANT la course (table profil_run_log),
puis le règlement post-course (vrais rapports PMU) écrit le résultat sur CES
pronos figés. L'algorithme apprend donc de SES propres recommandations émises,
pas du top-3 du modèle ni d'une reconstruction.

Intégrité : pari gagnant sans rapport publié → statut "en_attente" (run
"partial", re-réglable) — jamais de gain estimé. Poids sans échantillon
suffisant → neutre 1.0 (aucune invention).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

PROFILS = ("conservateur", "equilibre", "agressif")
MISE_REF = 10            # € fixes par run (comparabilité inter-profils)
MIN_RUNS_FOR_WEIGHTS = 10   # en-dessous, poids neutres (pas d'invention)
SHRINK_K = 15            # shrinkage du ROI vers 0 (anti sur-réaction petit n)
W_MIN, W_MAX = 0.5, 1.6


# ─────────────────────────────────────────────────────────────
# Schéma (pattern maison : inline CREATE IF NOT EXISTS, cf. signal_performance)
# ─────────────────────────────────────────────────────────────
async def ensure_tables(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS profil_run_log (
            log_id VARCHAR(36) PRIMARY KEY,
            course_id VARCHAR(36) NOT NULL,
            profil VARCHAR(20) NOT NULL,
            model_version_id VARCHAR(36),
            plan JSONB NOT NULL,
            resultat JSONB,
            roi_reel FLOAT,
            nb_paris INTEGER NOT NULL DEFAULT 0,
            statut VARCHAR(20) NOT NULL DEFAULT 'pending',
            meta JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            settled_at TIMESTAMPTZ,
            UNIQUE (course_id, profil)
        )
    """))
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_profil_run_log_course ON profil_run_log (course_id)"
    ))
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_profil_run_log_statut ON profil_run_log (statut)"
    ))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS profil_learning_state (
            id INTEGER PRIMARY KEY,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.commit()


# ─────────────────────────────────────────────────────────────
# 1. FIGER les pronos par profil au moment de la prédiction
# ─────────────────────────────────────────────────────────────
async def record_profil_runs(session: AsyncSession, course_id: str,
                             model_version_id: Optional[str] = None) -> int:
    """Génère + fige le plan 10€ des 3 profils pour une course À VENIR.

    Mêmes entrées que la route /mise-plan (heat réel, ROI weights réels,
    signal_mults par profil) → ce qui est journalisé = ce que l'utilisateur
    aurait vu. Re-prédiction avant course → écrase (le DERNIER prono avant
    départ fait foi). Course déjà réglée → intouchée.
    """
    from services.mise_calculator import generer_plan, plan_to_dict

    await ensure_tables(session)

    rows = (await session.execute(text("""
        SELECT p.numero, ch.nom, pr.proba_top1, pr.proba_top3,
               COALESCE(pr.cote_figee, p.cote_pmu) AS cote_pmu,
               p.non_partant, f.features
        FROM predictions pr
        JOIN participations p ON p.participation_id = pr.participation_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN features_ml f ON f.participation_id = pr.participation_id
        WHERE p.course_id = :cid
        ORDER BY pr.rang_predit
    """), {"cid": course_id})).all()
    if not rows:
        return 0

    course = (await session.execute(text("""
        SELECT statut, nb_partants, est_quinte, est_quarte, est_tierce, est_2sur4
        FROM courses WHERE course_id = :cid
    """), {"cid": course_id})).first()
    if not course or course[0] not in ("a_venir", "en_cours"):
        return 0

    preds = []
    feats_by_num: dict[int, dict] = {}
    for numero, nom, p1, p3, cote, np_, feats in rows:
        preds.append({
            "numero": numero, "nom_cheval": nom,
            "proba_top1": p1, "proba_top3": p3,
            "cote_pmu": cote, "non_partant": np_,
        })
        feats_by_num[int(numero)] = feats or {}

    course_info = {
        "nb_partants": course[1], "est_quinte": bool(course[2]),
        "est_quarte": bool(course[3]), "est_tierce": bool(course[4]),
        "est_2sur4": bool(course[5]),
    }

    # Contexte d'apprentissage réel (mêmes sources que /mise-plan)
    try:
        from ml.bet_performance import get_model_heat
        heat = await get_model_heat(session)
    except Exception:
        heat = 0.0
    try:
        from ml.signal_performance import load_signal_performance, signal_multiplier
        sig_perf = await load_signal_performance(session)
    except Exception:
        sig_perf = None

    n_written = 0
    for profil in PROFILS:
        try:
            from ml.bet_performance import get_learned_type_weights
            roi_weights = await get_learned_type_weights(session, profil=profil)
        except Exception:
            roi_weights = {}
        sig_mults = {}
        if sig_perf:
            try:
                from ml.signal_performance import signal_multiplier as _sm
                sig_mults = {n: _sm(f, sig_perf, profil) for n, f in feats_by_num.items()}
            except Exception:
                sig_mults = {}
        try:
            plan = generer_plan(MISE_REF, profil, preds, course_info,
                                None, roi_weights, heat, sig_mults)
            plan_d = plan_to_dict(plan)
        except Exception as e:
            log.warning("profil_learning.plan_failed", course_id=course_id,
                        profil=profil, err=str(e)[:140])
            continue
        nb_paris = sum(len(n.get("paris", [])) for n in plan_d.get("niveaux", []))
        if nb_paris == 0:
            continue
        # Upsert idempotent — n'écrase JAMAIS un run déjà réglé.
        await session.execute(text("""
            INSERT INTO profil_run_log
                (log_id, course_id, profil, model_version_id, plan, nb_paris, statut, meta)
            VALUES (:id, :cid, :prof, :mv, CAST(:plan AS jsonb), :nb, 'pending',
                    CAST(:meta AS jsonb))
            ON CONFLICT (course_id, profil) DO UPDATE SET
                plan = EXCLUDED.plan,
                nb_paris = EXCLUDED.nb_paris,
                model_version_id = EXCLUDED.model_version_id,
                meta = EXCLUDED.meta,
                created_at = now()
            WHERE profil_run_log.statut = 'pending'
        """), {
            "id": str(uuid.uuid4()), "cid": course_id, "prof": profil,
            "mv": model_version_id, "plan": json.dumps(plan_d),
            "nb": nb_paris,
            # pre_course=true : marqueur explicite « prono figé AVANT le départ »
            # (preuve d'intégrité pour le palmarès, en plus de created_at < date_heure).
            "meta": json.dumps({"heat": round(float(heat), 3), "mise": MISE_REF,
                                "pre_course": True}),
        })
        n_written += 1
    await session.commit()
    if n_written:
        log.info("profil_learning.runs_recorded", course_id=course_id, n=n_written)
    return n_written


# ─────────────────────────────────────────────────────────────
# 2. RÉGLER les runs à la fin de course (vrais rapports PMU)
# ─────────────────────────────────────────────────────────────
async def settle_profil_runs(session: AsyncSession, course_id: str) -> int:
    """Règle les runs pending/partial de la course contre l'arrivée officielle.
    Idempotent ; gagnant sans rapport publié → 'partial' (re-tenté plus tard)."""
    from services.bet_settlement import settle_plan

    await ensure_tables(session)

    res = (await session.execute(text("""
        SELECT r.classement, r.rapports, c.nb_partants, r.rapports_detail
        FROM resultats r JOIN courses c ON c.course_id = r.course_id
        WHERE r.course_id = :cid
    """), {"cid": course_id})).first()
    if not res or not res[0]:
        return 0
    classement = res[0] if isinstance(res[0], list) else []
    rapports = res[1] or {}
    nb_partants = res[2] or len(classement)
    rapports_detail = res[3] or None

    runs = (await session.execute(text("""
        SELECT log_id, plan FROM profil_run_log
        WHERE course_id = :cid AND statut IN ('pending', 'partial')
    """), {"cid": course_id})).all()

    n_settled = 0
    for log_id, plan in runs:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan)
        bilan = settle_plan(plan_d, classement, rapports, nb_partants, rapports_detail)
        statut = "partial" if bilan.get("en_attente") else "settled"
        roi = bilan.get("roi")
        await session.execute(text("""
            UPDATE profil_run_log
            SET resultat = CAST(:res AS jsonb), roi_reel = :roi, statut = :st,
                settled_at = now()
            WHERE log_id = :id
        """), {
            "res": json.dumps(bilan), "roi": (roi / 100.0) if roi is not None else None,
            "st": statut, "id": log_id,
        })
        n_settled += 1
    await session.commit()
    if n_settled:
        log.info("profil_learning.runs_settled", course_id=course_id, n=n_settled)
    return n_settled


# ─────────────────────────────────────────────────────────────
# 3. POIDS D'APPRENTISSAGE depuis les pronos émis réglés
# ─────────────────────────────────────────────────────────────
def shrunk_weight(net: float, mise: float, n: int,
                  k: int = SHRINK_K, w_min: float = W_MIN, w_max: float = W_MAX) -> float:
    """Multiplicateur appris : 1 + ROI shrinké vers 0 (n/(n+k)), borné [w_min, w_max].
    Fonction PURE (testable sans DB). n ou mise nuls → neutre 1.0."""
    if mise <= 0 or n <= 0:
        return 1.0
    roi = net / mise
    eff = roi * (n / (n + k))
    return max(w_min, min(w_max, 1.0 + eff))


async def compute_profil_weights(session: AsyncSession) -> dict:
    """Agrège les runs RÉGLÉS par profil × type de pari → multiplicateurs appris.
    Persiste dans profil_learning_state (singleton JSONB). Recalculé nightly +
    purgeable à chaque fin de course (peu coûteux)."""
    await ensure_tables(session)

    rows = (await session.execute(text("""
        SELECT profil, resultat, roi_reel
        FROM profil_run_log
        WHERE statut = 'settled' AND resultat IS NOT NULL
    """))).all()

    by_profil: dict[str, dict] = {
        p: {"types": {}, "n_runs": 0, "mise": 0.0, "gain": 0.0, "runs_benef": 0}
        for p in PROFILS
    }
    for profil, resultat, _roi in rows:
        if profil not in by_profil:
            continue
        res = resultat if isinstance(resultat, dict) else json.loads(resultat)
        agg = by_profil[profil]
        agg["n_runs"] += 1
        agg["mise"] += float(res.get("total_mise") or 0)
        agg["gain"] += float(res.get("total_gain") or 0)
        if float(res.get("net") or 0) > 0:
            agg["runs_benef"] += 1
        for pari in res.get("paris", []):
            t = pari.get("type")
            if not t:
                continue
            ts = agg["types"].setdefault(t, {"n": 0, "mise": 0.0, "gain": 0.0, "win": 0})
            ts["n"] += 1
            ts["mise"] += float(pari.get("mise") or 0)
            if pari.get("statut") == "gagne":
                ts["win"] += 1
                ts["gain"] += float(pari.get("gain") or 0)

    out = {"profils": {}, "n_total_runs": sum(a["n_runs"] for a in by_profil.values())}
    for profil, agg in by_profil.items():
        weights = {}
        detail = {}
        for t, ts in agg["types"].items():
            if ts["n"] >= MIN_RUNS_FOR_WEIGHTS:
                w = shrunk_weight(ts["gain"] - ts["mise"], ts["mise"], ts["n"])
            else:
                w = 1.0          # échantillon insuffisant → neutre, pas d'invention
            weights[t] = round(w, 3)
            detail[t] = {
                "n": ts["n"], "win_rate": round(ts["win"] / ts["n"] * 100, 1) if ts["n"] else None,
                "roi": round((ts["gain"] - ts["mise"]) / ts["mise"] * 100, 1) if ts["mise"] > 0 else None,
                "poids": round(w, 3),
            }
        mise, gain = agg["mise"], agg["gain"]
        out["profils"][profil] = {
            "n_runs": agg["n_runs"],
            "roi_global": round((gain - mise) / mise * 100, 1) if mise > 0 else None,
            "taux_runs_beneficiaires": round(agg["runs_benef"] / agg["n_runs"] * 100, 1) if agg["n_runs"] else None,
            "type_weights": weights,
            "type_detail": detail,
        }

    await session.execute(text("""
        INSERT INTO profil_learning_state (id, data, updated_at)
        VALUES (1, CAST(:d AS jsonb), now())
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
    """), {"d": json.dumps(out)})
    await session.commit()
    log.info("profil_learning.weights_computed", n_runs=out["n_total_runs"])
    return out


async def load_profil_weights(session: AsyncSession) -> dict | None:
    """Charge l'état appris (None si jamais calculé)."""
    try:
        await ensure_tables(session)
        r = (await session.execute(text(
            "SELECT data FROM profil_learning_state WHERE id = 1"
        ))).first()
        if not r:
            return None
        return r[0] if isinstance(r[0], dict) else json.loads(r[0])
    except Exception as e:
        log.warning("profil_learning.load_failed", err=str(e)[:140])
        return None
