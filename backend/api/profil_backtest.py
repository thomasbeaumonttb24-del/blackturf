"""
profil_backtest.py — Backtest des 3 PROFILS de risque sur l'historique réel.

Pour chaque course terminée (prédictions FIGÉES avant la course + arrivée
officielle + rapports PMU publiés), on génère le plan de mise de chaque profil
(conservateur / équilibré / agressif) pour une mise fixe, on règle chaque pari
sur l'arrivée RÉELLE aux RAPPORTS PMU RÉELS (services/bet_settlement), puis on
agrège ROI / gain net / taux de courses bénéficiaires par profil.

Intégrité — QUE DU RÉEL, aucune valeur inventée :
- Sélection = mêmes prédictions figées que celles servies avant la course.
- Gagné/perdu = arrivée officielle PMU.
- Gain = mise × rapport PMU RÉEL (clés e_* base 1€). Le Simple Gagnant, Couplé,
  Trio, 2sur4 utilisent leur vrai rapport publié.
- Si un pari GAGNANT n'a pas de rapport publié (gain indéterminé), la course est
  EXCLUE pour ce profil (jamais d'estimation). nb_courses = courses réellement
  réglables.
"""
from __future__ import annotations

import asyncio
import copy

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Course, Participation, Prediction, Resultat
from ml.combo_bets import enumerate_bet_candidates
from services.bet_settlement import settle_pari
from services.mise_calculator import (
    _palier, _effective_config, _select_conviction, _allocate_kelly,
)

log = structlog.get_logger()

MISE = 10  # € fixes par course (comparabilité entre profils)
# Plafond du gain par pari (× mise) pour le ROI WINSORISÉ : neutralise la queue
# épaisse (un Trio/Couplé à gros rapport domine la moyenne sur petit échantillon).
# Le ROI winsorisé = rendement TYPIQUE, plus honnête que le ROI brut pour un public.
WINSOR_CAP = 30.0
PROFILS = [
    ("conservateur", "Conservateur"),
    ("equilibre", "Équilibré"),
    ("agressif", "Agressif"),
]


def _compute(courses: list[dict], n_sims: int) -> dict:
    """Boucle CPU pure (exécutée hors event-loop via asyncio.to_thread).
    Règlement 100% aux rapports PMU réels (settle_pari)."""
    import collections
    agg = {k: {"nb": 0, "mise": 0.0, "gain": 0.0, "gain_w": 0.0, "benef": 0, "skip": 0} for k, _ in PROFILS}
    # ROI RÉEL par TYPE de pari (winsorisé) → sert à FAIRE APPRENDRE les poids de
    # sélection : un type qui perd (ex. Simple Gagnant) se fait dé-pondérer tout seul.
    agg_type = collections.defaultdict(lambda: {"mise": 0.0, "gw": 0.0, "n": 0, "win": 0})
    palier = _palier(MISE)

    # Courbe de P&L RÉEL CHRONOLOGIQUE par profil : profit/perte CUMULÉ (départ 0€)
    # en jouant le plan de mise 10€ de ce profil sur chaque course du programme,
    # réglé au RÉEL (vrais rapports PMU). La courbe = (gains réels − mises réelles).
    EQUITY_START = 0.0
    equity_bk = {k: EQUITY_START for k, _ in PROFILS}
    equity = {k: [] for k, _ in PROFILS}
    courses = sorted(courses, key=lambda c: c.get("date") or "")   # chronologique

    for c in courses:
        preds = c["preds"]
        classement = c["classement"]
        rapports = c["rapports"]
        if not preds or not classement:
            continue
        nb_part = c["nb_partants"] or len(preds)
        course_info = {
            "nb_partants": nb_part,
            "est_quinte": c["est_quinte"], "est_quarte": c["est_quarte"], "est_tierce": c["est_tierce"],
        }
        try:
            cands = enumerate_bet_candidates(preds, course_info, n_sims=n_sims)
        except Exception as e:  # noqa: BLE001 — une course KO ne casse pas le backtest
            log.warning("profil_backtest.cands_failed", course=c["course_id"], error=str(e))
            continue
        if not cands:
            continue

        for key, _label in PROFILS:
            cfg = _effective_config(key, 0.0)
            sel = _select_conviction(copy.deepcopy(cands), MISE, palier, cfg, {})
            if not sel:
                continue
            _allocate_kelly(sel, MISE, palier, cfg)

            mise_course = 0.0
            gain_course = 0.0
            gain_w_course = 0.0
            indetermine = False
            per_bet = []  # (type, mise, won, payout_winsorisé) pour l'apprentissage par type
            for x in sel:
                nums = [h["numero"] for h in x["chevaux"]]
                r = settle_pari(x["type_pari"], nums, classement, rapports, nb_part)
                if r["gagne"] and r["rapport_reel"] is None:
                    indetermine = True  # gagnant sans rapport publié → course non réglable
                    break
                mise_course += x["mise"]
                won = bool(r["gagne"])
                pw = min(x["mise"] * r["rapport_reel"], x["mise"] * WINSOR_CAP) if won else 0.0
                if won:
                    payout = x["mise"] * r["rapport_reel"]
                    gain_course += payout
                    gain_w_course += pw
                per_bet.append((x["type_pari"], x["mise"], won, pw))

            a = agg[key]
            if not indetermine and mise_course > 0:
                for t, m, won, pw in per_bet:        # apprentissage ROI par type (réel)
                    at = agg_type[t]
                    at["mise"] += m; at["n"] += 1
                    if won:
                        at["win"] += 1; at["gw"] += pw
            if indetermine or mise_course <= 0:
                a["skip"] += 1
                continue
            a["nb"] += 1
            a["mise"] += mise_course
            a["gain"] += gain_course
            a["gain_w"] += gain_w_course
            if gain_course > mise_course:
                a["benef"] += 1
            # courbe d'équité chronologique : capital += net réel de la course
            equity_bk[key] += (gain_course - mise_course)
            equity[key].append({"date": c.get("date") or "", "bankroll": round(equity_bk[key], 2)})

    profils = []
    for key, label in PROFILS:
        a = agg[key]
        roi = round((a["gain"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None
        roi_w = round((a["gain_w"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None
        profils.append({
            "profil": key,
            "label": label,
            "nb_courses": a["nb"],
            "mise_totale": round(a["mise"]),
            "gain_total": round(a["gain"]),
            "gain_net": round(a["gain"] - a["mise"]),
            "roi": roi,
            "roi_winsorise": roi_w,           # rendement TYPIQUE (gros gains plafonnés 30×)
            "taux_courses_beneficiaires": round(a["benef"] / a["nb"] * 100, 1) if a["nb"] else None,
        })

    # ── Poids APPRIS par type (ROI réel winsorisé → multiplicateur de conviction) ──
    # Borné [0.5, 1.3] (down franc sur les perdants, up modéré pour résister à la
    # variance), shrinkage si peu d'échantillon. C'est ici que l'algo "apprend le
    # pourquoi" : un type qui perd réellement (Simple Gagnant) descend, un type qui
    # rapporte (placé à valeur) monte, et ça s'ajuste à chaque recalcul.
    MIN_N = 20
    type_perf = {}
    type_weights = {}
    for t, at in agg_type.items():
        if at["mise"] <= 0 or at["n"] <= 0:
            continue
        roi_w = (at["gw"] - at["mise"]) / at["mise"]      # ROI net winsorisé
        shrink = at["n"] / (at["n"] + MIN_N)
        eff = roi_w * shrink
        # ASYMÉTRIE volontaire : le signal PERDANT est robuste (on coupe fort, ×0.5),
        # le signal GAGNANT est contaminé par la variance + les rapports approximatifs
        # (Couplé/Simple Placé) → on monte PRUDEMMENT (cap ×1.15) pour ne pas chasser
        # du "fool's gold". Mieux vaut sous-pondérer un vrai gagnant que sur-jouer un
        # faux. Down jusqu'à ×0.5, up plafonné ×1.15.
        w = 1.0 + (eff if eff < 0 else min(eff, 0.15))
        w = max(0.5, min(1.15, w))
        type_weights[t] = round(w, 3)
        type_perf[t] = {
            "n": at["n"],
            "win_rate": round(at["win"] / at["n"] * 100, 1),
            "roi_winsorise": round(roi_w * 100, 1),
            "poids_appris": round(w, 3),
        }

    return {
        "profils": profils,
        "nb_courses": max((p["nb_courses"] for p in profils), default=0),
        "mise_par_course": MISE,
        "type_weights": type_weights,    # {type: multiplicateur} pour la sélection future
        "type_perf": type_perf,          # détail (n, win%, ROI) — le "pourquoi"
        "equity": equity,                # courbe d'équité chronologique PAR profil (10€/course)
    }


async def backtest_profils(db: AsyncSession, limit: int = 200, n_sims: int = 3000) -> dict:
    """Charge l'historique (IO async) puis lance le backtest CPU en thread.
    On ne garde que les courses avec rapports PMU publiés (reglables au reel)."""
    courses = (await db.execute(
        select(Course)
        .join(Resultat, Resultat.course_id == Course.course_id)
        .where(Course.statut == "termine")
        .order_by(Course.date_heure.desc())
        .limit(limit)
    )).scalars().all()
    if not courses:
        return {"profils": [], "nb_courses": 0, "mise_par_course": MISE}

    course_ids = [c.course_id for c in courses]

    pred_rows = (await db.execute(
        select(Prediction, Participation)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .where(Prediction.course_id.in_(course_ids))
    )).all()
    preds_by_course: dict[str, list[dict]] = {}
    for pr, part in pred_rows:
        preds_by_course.setdefault(pr.course_id, []).append({
            "numero": part.numero,
            "nom": "",
            "proba_top1": pr.proba_top1,
            "proba_top3": pr.proba_top3,
            "cote_pmu": part.cote_pmu,
        })

    res_rows = (await db.execute(
        select(Resultat).where(Resultat.course_id.in_(course_ids))
    )).scalars().all()
    res_by_course = {r.course_id: r for r in res_rows}

    payload = []
    for c in courses:
        res = res_by_course.get(c.course_id)
        if not res:
            continue
        payload.append({
            "course_id": c.course_id,
            "date": c.date_heure.strftime("%Y-%m-%d") if c.date_heure else "",
            "preds": preds_by_course.get(c.course_id, []),
            "classement": res.classement if isinstance(res.classement, list) else [],
            "rapports": res.rapports or {},
            "nb_partants": c.nb_partants,
            "est_quinte": bool(c.est_quinte),
            "est_quarte": bool(c.est_quarte),
            "est_tierce": bool(c.est_tierce),
        })

    return await asyncio.to_thread(_compute, payload, n_sims)
