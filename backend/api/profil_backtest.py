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
PROFILS = [
    ("conservateur", "Conservateur"),
    ("equilibre", "Équilibré"),
    ("agressif", "Agressif"),
]


def _compute(courses: list[dict], n_sims: int) -> dict:
    """Boucle CPU pure (exécutée hors event-loop via asyncio.to_thread).
    Règlement 100% aux rapports PMU réels (settle_pari)."""
    agg = {k: {"nb": 0, "mise": 0.0, "gain": 0.0, "benef": 0, "skip": 0} for k, _ in PROFILS}
    palier = _palier(MISE)

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
            indetermine = False
            for x in sel:
                nums = [h["numero"] for h in x["chevaux"]]
                r = settle_pari(x["type_pari"], nums, classement, rapports, nb_part)
                if r["gagne"] and r["rapport_reel"] is None:
                    indetermine = True  # gagnant sans rapport publié → course non réglable
                    break
                mise_course += x["mise"]
                if r["gagne"]:
                    gain_course += x["mise"] * r["rapport_reel"]

            a = agg[key]
            if indetermine or mise_course <= 0:
                a["skip"] += 1
                continue
            a["nb"] += 1
            a["mise"] += mise_course
            a["gain"] += gain_course
            if gain_course > mise_course:
                a["benef"] += 1

    profils = []
    for key, label in PROFILS:
        a = agg[key]
        roi = round((a["gain"] - a["mise"]) / a["mise"] * 100, 1) if a["mise"] > 0 else None
        profils.append({
            "profil": key,
            "label": label,
            "nb_courses": a["nb"],
            "mise_totale": round(a["mise"]),
            "gain_total": round(a["gain"]),
            "gain_net": round(a["gain"] - a["mise"]),
            "roi": roi,
            "taux_courses_beneficiaires": round(a["benef"] / a["nb"] * 100, 1) if a["nb"] else None,
        })
    return {
        "profils": profils,
        "nb_courses": max((p["nb_courses"] for p in profils), default=0),
        "mise_par_course": MISE,
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
            "preds": preds_by_course.get(c.course_id, []),
            "classement": res.classement if isinstance(res.classement, list) else [],
            "rapports": res.rapports or {},
            "nb_partants": c.nb_partants,
            "est_quinte": bool(c.est_quinte),
            "est_quarte": bool(c.est_quarte),
            "est_tierce": bool(c.est_tierce),
        })

    return await asyncio.to_thread(_compute, payload, n_sims)
