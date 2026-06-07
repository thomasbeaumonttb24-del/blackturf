"""
profil_backtest.py — Backtest des 3 PROFILS de risque sur l'historique réel.

Pour chaque course terminée (avec prédictions FIGÉES avant la course + arrivée
officielle), on génère le plan de mise de chaque profil (conservateur / équilibré
/ agressif) pour une mise fixe, on règle chaque pari sur l'arrivée RÉELLE et on
agrège ROI / gain net / taux de courses bénéficiaires par profil.

Intégrité :
- Sélection = mêmes prédictions figées que celles servies avant la course.
- Issue gagnant/perdant = arrivée officielle PMU (Resultat.classement) — RÉELLE.
- Gains : Simple Gagnant réglé à la COTE PMU RÉELLE ; paris combinés au rapport
  ESTIMÉ par le modèle (TRJ / proba marché) — c'est une SIMULATION de stratégie,
  clairement étiquetée comme telle, pas un relevé de rapports PMU officiels.
"""
from __future__ import annotations

import asyncio
import copy

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Course, Participation, Prediction, Resultat
from ml.combo_bets import enumerate_bet_candidates
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


def _positions(classement) -> dict[int, int]:
    """{numero: position} depuis l'arrivée officielle. Ignore les entrées invalides."""
    pos: dict[int, int] = {}
    if isinstance(classement, list):
        for e in classement:
            if isinstance(e, dict):
                n, p = e.get("numero"), e.get("position")
                if isinstance(n, (int, float)) and isinstance(p, (int, float)):
                    pos[int(n)] = int(p)
    return pos


def _won(type_pari: str, nums: list[int], pos: dict[int, int], place_k: int) -> bool:
    """Le pari est-il gagnant au vu de l'arrivée réelle ?"""
    P = lambda n: pos.get(n, 999)
    t = type_pari
    if t == "Simple Gagnant":
        return P(nums[0]) == 1
    if t == "Simple Placé":
        return P(nums[0]) <= place_k
    if t == "Couplé Gagnant":
        return all(P(n) <= 2 for n in nums)
    if t == "Couplé Placé":
        return all(P(n) <= 3 for n in nums)
    if t == "2sur4":
        return sum(1 for n in nums if P(n) <= 4) >= 2
    if t in ("Trio", "Tiercé Désordre"):
        return all(P(n) <= 3 for n in nums)
    if t == "Tiercé Ordre":
        return [P(n) for n in nums] == [1, 2, 3]
    if t in ("Quarté+ Désordre", "Quarté+"):
        return all(P(n) <= 4 for n in nums)
    if t.startswith("Quinté+"):
        return all(P(n) <= 5 for n in nums)
    return False


def _compute(courses: list[dict], n_sims: int) -> dict:
    """Boucle CPU pure (exécutée hors event-loop via asyncio.to_thread)."""
    agg = {k: {"nb": 0, "mise": 0.0, "gain": 0.0, "benef": 0} for k, _ in PROFILS}
    palier = _palier(MISE)

    for c in courses:
        preds = c["preds"]
        pos = c["pos"]
        if not preds or not pos:
            continue
        nb_part = c["nb_partants"] or len(preds)
        place_k = 3 if nb_part >= 8 else 2
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
            mise_course = sum(x["mise"] for x in sel)
            gain_course = 0.0
            for x in sel:
                nums = [h["numero"] for h in x["chevaux"]]
                if _won(x["type_pari"], nums, pos, place_k):
                    gain_course += x["mise"] * x["rapport_estime"]
            a = agg[key]
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


async def backtest_profils(db: AsyncSession, limit: int = 120, n_sims: int = 3000) -> dict:
    """Charge l'historique (IO async) puis lance le backtest CPU en thread."""
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
    pos_by_course = {r.course_id: _positions(r.classement) for r in res_rows}

    payload = [
        {
            "course_id": c.course_id,
            "preds": preds_by_course.get(c.course_id, []),
            "pos": pos_by_course.get(c.course_id, {}),
            "nb_partants": c.nb_partants,
            "est_quinte": bool(c.est_quinte),
            "est_quarte": bool(c.est_quarte),
            "est_tierce": bool(c.est_tierce),
        }
        for c in courses
    ]

    return await asyncio.to_thread(_compute, payload, n_sims)
