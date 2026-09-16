"""SUIVI DE LA PRÉCISION — l'algorithme progresse-t-il, jour après jour, sur les
arrivées réelles ?

Pourquoi ce module
──────────────────
Chaque nuit le système réapprend (modèle, mélange avec la cote, modèle technique,
calibrations). Rien ne permettait de SUIVRE, jour après jour et avec des chiffres
réels, si ce qui est servi aux abonnés devient plus juste : les métriques
d'entraînement jugent un hold-out, pas ce qui a été affiché à T-10 avant chaque
course. `avantage_marche_servi` donne un seul chiffre glissant sur 21 jours.

Ce module compare, course par course, ce qui a RÉELLEMENT été servi avant le départ
(le dernier instantané de `prediction_snapshots`, figé moins de deux heures avant)
à l'arrivée officielle, et range les mesures par JOUR DE COURSE (heure de Paris) :

  - classement : le n°1 a-t-il gagné ? le gagnant était-il dans le top 3 ?
    AUC intra-course (part des perdants classés sous le gagnant) ;
  - cote juste : log-vraisemblance du gagnant (1/cote juste lue comme une proba),
    et calibration par tranche de cote juste (annoncé contre réalisé) ;
  - placement : log-loss de la proba placé servie, justesse du top 3 annoncé ;
  - référence MARCHÉ sur les mêmes courses (cote figée au même instant) : la seule
    référence qui dise si le travail du modèle vaut quelque chose ;
  - MODÈLE TECHNIQUE (en observation tant qu'il n'est pas servi), mesuré sur les
    mêmes courses, uniquement quand elles sont postérieures à sa fin
    d'entraînement — jamais en échantillon ;
  - valeurs détectées : les paris de valeur de la course par niveau, réglés au
    rapport PMU officiel du Simple Gagnant.

Aucune valeur n'est inventée : une journée sans course mesurable n'a pas de ligne,
un indicateur sans observation vaut `None`. Les sommes (et sommes de carrés des
écarts appariés) sont stockées plutôt que des moyennes : toute fenêtre s'agrège
EXACTEMENT, avec son intervalle de confiance.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml import melange_arrivees as ma
from ml.learning_steps import _vers_datetime

log = structlog.get_logger(module="suivi_precision")

PARIS = ZoneInfo("Europe/Paris")
FRAICHEUR_MAX_MIN = 120
# Le nocturne recalcule les derniers jours : des résultats ou des rapports peuvent
# arriver en retard (réclamations, rapports internationaux).
JOURS_RECALCULES = 7
# Sous ce nombre de courses, une moyenne glissante sur 7 jours n'est pas affichée :
# en début de série elle repose sur une poignée de courses (un 0 % un jour à 3
# courses se lit comme un effondrement).
MIN_COURSES_GLISSANT = 100
# Premier jour où les prédictions sont figées à T-10 (avant : la veille au soir).
PREMIER_JOUR = date(2026, 8, 17)
WINSOR = 30.0

# Tranches de COTE JUSTE (1/proba) pour la calibration.
TRANCHES = ((1.0, 3.0), (3.0, 6.0), (6.0, 11.0), (11.0, 20.0), (20.0, 40.0), (40.0, 1e9))


def _nom_tranche(bas: float, haut: float) -> str:
    return f"{bas:g}-{haut:g}" if haut < 1e8 else f"{bas:g}+"


# ──────────────────────────────────────────────────────────────────────────────
# Mesure d'UNE course (fonction pure)
# ──────────────────────────────────────────────────────────────────────────────

def _auc(scores: np.ndarray, g: int) -> float:
    return ma._auc_course(np.asarray(scores, dtype=float), g)


def mesurer_course(numeros: Sequence[int], servi1: Sequence[float], servi3: Sequence[float],
                   cotes: Sequence[float], gagnant: int, places: set,
                   tech1: Optional[Sequence[float]] = None,
                   tech3: Optional[Sequence[float]] = None,
                   sg_rang1: Optional[dict] = None,
                   valeurs: Iterable[dict] = ()) -> Optional[dict]:
    """Mesures d'une course, ou None si elle n'est pas mesurable.

    `sg_rang1` = {"gagne": bool, "rapport": float|None} du Simple Gagnant sur le n°1.
    `valeurs` = [{"niveau": int, "gagne": bool, "rapport": float|None}].
    """
    nums = [int(n) for n in numeros]
    if gagnant not in nums or len(nums) < ma.MIN_PARTANTS:
        return None
    q = ma.probas_marche(cotes)
    s1 = np.asarray(servi1, dtype=float)
    if q is None or not np.isfinite(s1).all() or s1.sum() <= 0:
        return None
    s1 = s1 / s1.sum()
    g = nums.index(gagnant)
    y3 = np.array([1.0 if n in places else 0.0 for n in nums])
    m: dict = {
        "n": 1,
        "hit_servi": float(np.argmax(s1) == g),
        "hit_marche": float(np.argmax(q) == g),
        "top3_servi": float(g in np.argsort(-s1)[:3]),
        "auc_servi": _auc(s1, g),
        "auc_marche": _auc(q, g),
        "ll_servi": -math.log(max(float(s1[g]), 1e-15)),
        "ll_marche": -math.log(max(float(q[g]), 1e-15)),
    }
    m["d_auc"] = m["auc_servi"] - m["auc_marche"]
    m["d_ll"] = m["ll_marche"] - m["ll_servi"]           # > 0 : servi plus juste

    s3 = np.asarray(servi3, dtype=float)
    if np.isfinite(s3).all() and s3.size == len(nums):
        p = np.clip(s3, 1e-4, 0.9999)
        m["ll3_servi"] = float(-(y3 * np.log(p) + (1 - y3) * np.log(1 - p)).sum())
        m["n_partants3"] = len(nums)
        m["prec3_servi"] = float(y3[np.argsort(-s3)[:3]].sum() / min(3, len(nums)))

    cal = {}
    for p, gagne in zip(s1, (np.arange(len(nums)) == g)):
        cj = 1.0 / max(float(p), 1e-9)
        for bas, haut in TRANCHES:
            if bas <= cj < haut:
                t = cal.setdefault(_nom_tranche(bas, haut), [0, 0.0, 0])
                t[0] += 1
                t[1] += float(p)
                t[2] += int(gagne)
                break
    m["calibration_servi"] = cal

    if tech1 is not None:
        t1 = np.asarray(tech1, dtype=float)
        if t1.size == len(nums) and np.isfinite(t1).all() and t1.sum() > 0:
            t1 = t1 / t1.sum()
            m["n_tech"] = 1
            m["hit_tech"] = float(np.argmax(t1) == g)
            m["auc_tech"] = _auc(t1, g)
            m["ll_tech"] = -math.log(max(float(t1[g]), 1e-15))
            m["d_auc_tech"] = m["auc_tech"] - m["auc_servi"]
            m["d_ll_tech"] = m["ll_servi"] - m["ll_tech"]   # > 0 : technique plus juste
            if tech3 is not None:
                t3 = np.clip(np.asarray(tech3, dtype=float), 1e-4, 0.9999)
                if t3.size == len(nums):
                    m["ll3_tech"] = float(-(y3 * np.log(t3) + (1 - y3) * np.log(1 - t3)).sum())
                    m["n_partants3_tech"] = len(nums)

    if sg_rang1 is not None and sg_rang1.get("rapport_connu", True):
        r = sg_rang1.get("rapport") if sg_rang1.get("gagne") else 0.0
        if r is not None:
            m["sg1_n"] = 1
            m["sg1_retour"] = float(r)
            m["sg1_retour_w"] = float(min(r, WINSOR))

    vb = {}
    for v in valeurs:
        r = v.get("rapport") if v.get("gagne") else 0.0
        if r is None:
            continue
        t = vb.setdefault(str(int(v["niveau"])), [0, 0, 0.0, 0.0])
        t[0] += 1
        t[1] += int(bool(v.get("gagne")))
        t[2] += float(r)
        t[3] += float(min(r, WINSOR))
    m["valeurs"] = vb
    return m


# ──────────────────────────────────────────────────────────────────────────────
# Agrégation (fonction pure) — sommes exactes, IC sur les écarts appariés
# ──────────────────────────────────────────────────────────────────────────────

_SOMMES = ("n", "hit_servi", "hit_marche", "top3_servi", "auc_servi", "auc_marche",
           "ll_servi", "ll_marche", "ll3_servi", "n_partants3", "prec3_servi",
           "n_tech", "hit_tech", "auc_tech", "ll_tech", "ll3_tech", "n_partants3_tech",
           "sg1_n", "sg1_retour", "sg1_retour_w")
_ECARTS = ("d_auc", "d_ll", "d_auc_tech", "d_ll_tech")


def cumuler(mesures: Iterable[dict]) -> dict:
    """Somme de mesures (courses ou journées) — associatif, donc empilable."""
    tot: dict = {"calibration_servi": {}, "valeurs": {}}
    for m in mesures:
        for k in _SOMMES:
            if m.get(k) is not None:
                tot[k] = tot.get(k, 0) + m[k]
        for k in _ECARTS:
            # Une journée porte déjà ses sommes (`sum_d_auc`…) ; une course, sa valeur.
            if f"sum_{k}" in m:
                tot[f"sum_{k}"] = tot.get(f"sum_{k}", 0.0) + m[f"sum_{k}"]
                tot[f"sq_{k}"] = tot.get(f"sq_{k}", 0.0) + m[f"sq_{k}"]
            elif m.get(k) is not None:
                tot[f"sum_{k}"] = tot.get(f"sum_{k}", 0.0) + m[k]
                tot[f"sq_{k}"] = tot.get(f"sq_{k}", 0.0) + m[k] ** 2
        for nom, (n, sp, w) in (m.get("calibration_servi") or {}).items():
            t = tot["calibration_servi"].setdefault(nom, [0, 0.0, 0])
            t[0] += n
            t[1] += sp
            t[2] += w
        for niv, (n, w, r, rw) in (m.get("valeurs") or {}).items():
            t = tot["valeurs"].setdefault(niv, [0, 0, 0.0, 0.0])
            t[0] += n
            t[1] += w
            t[2] += r
            t[3] += rw
    return tot


def _moyenne_ic(somme: float, carres: float, n: int) -> dict:
    if not n:
        return {"moyenne": None, "ic95": None, "n": 0}
    m = somme / n
    if n < 2:
        return {"moyenne": round(m, 5), "ic95": None, "n": n}
    var = max(carres / n - m * m, 0.0) * n / (n - 1)
    se = math.sqrt(var / n)
    return {"moyenne": round(m, 5), "ic95": [round(m - 1.96 * se, 5), round(m + 1.96 * se, 5)],
            "n": n, "conclusif": bool(m - 1.96 * se > 0 or m + 1.96 * se < 0)}


def lire_cumul(tot: dict) -> dict:
    """Indicateurs lisibles d'un cumul. `None` partout où rien n'a été observé."""
    n = int(tot.get("n") or 0)
    nt = int(tot.get("n_tech") or 0)

    def taux(k, base):
        return round(tot[k] / base, 4) if base and tot.get(k) is not None else None

    out = {
        "n_courses": n,
        "n1_gagne_servi": taux("hit_servi", n),
        "favori_gagne_marche": taux("hit_marche", n),
        "gagnant_dans_top3_servi": taux("top3_servi", n),
        "auc_servi": taux("auc_servi", n),
        "auc_marche": taux("auc_marche", n),
        "logv_servi": taux("ll_servi", n),
        "logv_marche": taux("ll_marche", n),
        "classement_vs_marche": _moyenne_ic(tot.get("sum_d_auc", 0.0), tot.get("sq_d_auc", 0.0), n),
        "cote_juste_vs_marche": _moyenne_ic(tot.get("sum_d_ll", 0.0), tot.get("sq_d_ll", 0.0), n),
        "placement_logloss_servi": (round(tot["ll3_servi"] / tot["n_partants3"], 5)
                                    if tot.get("n_partants3") else None),
        "top3_annonce_juste_servi": taux("prec3_servi", n),
        "technique": {
            "n_courses": nt,
            "n1_gagne": taux("hit_tech", nt),
            "auc": taux("auc_tech", nt),
            "logv": taux("ll_tech", nt),
            "classement_vs_servi": _moyenne_ic(tot.get("sum_d_auc_tech", 0.0),
                                               tot.get("sq_d_auc_tech", 0.0), nt),
            "cote_juste_vs_servi": _moyenne_ic(tot.get("sum_d_ll_tech", 0.0),
                                               tot.get("sq_d_ll_tech", 0.0), nt),
            "placement_logloss": (round(tot["ll3_tech"] / tot["n_partants3_tech"], 5)
                                  if tot.get("n_partants3_tech") else None),
        },
        "simple_gagnant_n1": ({
            "paris": int(tot["sg1_n"]),
            "roi": round(tot["sg1_retour"] / tot["sg1_n"] - 1, 4),
            "roi_winsorise": round(tot["sg1_retour_w"] / tot["sg1_n"] - 1, 4),
        } if tot.get("sg1_n") else None),
        "calibration_cote_juste": [
            {"tranche": nom, "partants": v[0], "annonce": round(v[1] / v[0], 4),
             "realise": round(v[2] / v[0], 4), "victoires": v[2]}
            for nom, v in sorted((tot.get("calibration_servi") or {}).items(),
                                 key=lambda kv: float(kv[0].split("-")[0].rstrip("+")))
            if v[0]
        ],
        "valeurs_detectees": [
            {"niveau": int(niv), "paris": v[0], "gagnants": v[1],
             "roi": round(v[2] / v[0] - 1, 4), "roi_winsorise": round(v[3] / v[0] - 1, 4)}
            for niv, v in sorted((tot.get("valeurs") or {}).items()) if v[0]
        ],
    }
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────────

_DDL = """
    CREATE TABLE IF NOT EXISTS suivi_precision (
        jour VARCHAR(10) NOT NULL,
        segment VARCHAR(20) NOT NULL,
        data TEXT NOT NULL,
        updated_at TIMESTAMP,
        PRIMARY KEY (jour, segment)
    )
"""


def _bornes_jour(j: date) -> tuple[datetime, datetime]:
    debut = datetime.combine(j, time(0), tzinfo=PARIS).astimezone(timezone.utc)
    fin = datetime.combine(j + timedelta(days=1), time(0), tzinfo=PARIS).astimezone(timezone.utc)
    return debut, fin


def _segment(discipline: Optional[str]) -> str:
    d = (discipline or "").lower()
    if d.startswith("attel"):
        return "attele"
    if d.startswith("mont"):
        return "monte"
    if d.startswith("plat"):
        return "plat"
    return "obstacle"


async def mesurer_jour(session: AsyncSession, j: date) -> dict[str, dict]:
    """{segment: cumul} des courses du jour `j` (heure de Paris)."""
    from services.bet_settlement import settle_pari

    debut, fin = _bornes_jour(j)
    try:
        from ml.modele_technique import en_service as _tech
        tech = _tech()
    except Exception:                                            # noqa: BLE001
        tech = None
    # Le modèle technique n'est jugé que sur des courses parties APRÈS son
    # entraînement complet (arbres ET poids du mélange avec la cote, appris sur les
    # 28 jours précédant `entraine_le`) : jamais sur une course qui a servi à le régler.
    tech_ok, entraine_le = False, None
    if tech is not None and tech.train_fin and tech.entraine_le:
        tf, entraine_le = _vers_datetime(tech.train_fin), _vers_datetime(tech.entraine_le)
        tech_ok = tf is not None and entraine_le is not None and entraine_le < fin

    res = await session.stream(text("""
        SELECT pe.course_id, pa.numero, pe.proba_top1, pe.proba_top3, pe.cote_figee,
               pe.created_at, pe.features, c.date_heure, c.discipline,
               r.classement, r.rapports, r.rapports_detail, np.n
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        JOIN (SELECT course_id, count(*) AS n FROM participations
               WHERE COALESCE(non_partant, false) = false
               GROUP BY course_id) np ON np.course_id = pe.course_id
        WHERE pe.proba_top1 IS NOT NULL AND pe.proba_top3 IS NOT NULL
          AND COALESCE(pa.non_partant, false) = false
          AND r.classement IS NOT NULL
          AND pe.created_at IS NOT NULL AND pe.created_at < c.date_heure
          AND c.date_heure >= :debut AND c.date_heure < :fin
        ORDER BY pe.course_id, pa.numero
    """), {"debut": debut, "fin": fin})
    fraicheur = timedelta(minutes=FRAICHEUR_MAX_MIN)
    courses: dict[str, dict] = {}
    async for part in res.partitions(2000):
        for cid, num, p1, p3, cote, cree, feats, dh, disc, classement, rapports, detail, n in part:
            depart, calcul = _vers_datetime(dh), _vers_datetime(cree)
            d = courses.setdefault(cid, {"l": [], "f": [], "disc": disc, "classement": classement,
                                         "rapports": rapports, "detail": detail, "n": int(n or 0),
                                         "depart": depart})
            if depart is None or calcul is None or depart - calcul > fraicheur:
                d["perimee"] = True
                continue
            d["l"].append((int(num), float(p1), float(p3),
                           float(cote) if cote is not None else float("nan")))
            if tech_ok:
                d["f"].append(feats if isinstance(feats, dict) else json.loads(feats or "{}"))

    vb_par_course: dict[str, list] = {}
    if courses:
        rows = (await session.execute(text("""
            SELECT vb.course_id, pa.numero, vb.niveau
            FROM value_bets vb
            JOIN participations pa ON pa.participation_id = vb.participation_id
            JOIN courses c ON c.course_id = vb.course_id
            WHERE c.date_heure >= :debut AND c.date_heure < :fin
        """), {"debut": debut, "fin": fin})).all()
        for cid, num, niv in rows:
            vb_par_course.setdefault(cid, []).append((int(num), int(niv or 0)))

    import pandas as pd
    par_segment: dict[str, list] = {}
    for cid, d in courses.items():
        l = d["l"]
        if d.get("perimee") or len(l) < ma.MIN_PARTANTS or len(l) != d["n"]:
            continue
        classement = d["classement"]
        if isinstance(classement, str):
            classement = json.loads(classement)
        rapports = d["rapports"] if not isinstance(d["rapports"], str) else json.loads(d["rapports"])
        detail = d["detail"] if not isinstance(d["detail"], str) else json.loads(d["detail"])
        from ml.modele_technique import _gagnant_et_places
        gagnant, places = _gagnant_et_places(classement)
        if gagnant is None:
            continue
        nums = [x[0] for x in l]
        cotes = [x[3] for x in l]
        t1 = t3 = None
        if tech_ok and len(d["f"]) == len(l) and d["depart"] is not None and d["depart"] > entraine_le:
            try:
                t1, t3 = tech.servir(pd.DataFrame(d["f"]), cotes)
            except Exception:                                    # noqa: BLE001
                t1 = t3 = None
        s1 = np.array([x[1] for x in l])
        rang1 = nums[int(np.argmax(s1))]

        def _sg(num: int) -> dict:
            r = settle_pari("Simple Gagnant", [num], classement, rapports, len(nums), detail)
            return {"gagne": r["gagne"], "rapport": r["rapport_reel"],
                    "rapport_connu": (not r["gagne"]) or r["rapport_reel"] is not None}

        valeurs = []
        for num, niv in vb_par_course.get(cid, []):
            if num in nums and niv:
                v = _sg(num)
                if v["rapport_connu"]:
                    valeurs.append({"niveau": niv, "gagne": v["gagne"], "rapport": v["rapport"]})
        m = mesurer_course(nums, s1, [x[2] for x in l], cotes, gagnant, places,
                           tech1=t1, tech3=t3, sg_rang1=_sg(rang1), valeurs=valeurs)
        if m is None:
            continue
        par_segment.setdefault("tout", []).append(m)
        par_segment.setdefault(_segment(d["disc"]), []).append(m)
    return {seg: cumuler(ms) for seg, ms in par_segment.items()}


# Mesures du modèle technique FIGÉES dès leur premier calcul. Le nocturne réapprend
# chaque nuit les poids du mélange technique × cote sur les 28 derniers jours : un
# jour déjà passé fait donc partie de l'échantillon des modèles suivants. Recalculer
# sa mesure avec eux la mettrait en échantillon — on garde celle du modèle qui était
# en place quand le jour a été mesuré pour la première fois (étape nocturne placée
# AVANT le réentraînement technique).
_CLES_TECHNIQUE = ("n_tech", "hit_tech", "auc_tech", "ll_tech", "ll3_tech", "n_partants3_tech",
                   "sum_d_auc_tech", "sq_d_auc_tech", "sum_d_ll_tech", "sq_d_ll_tech")


def figer_technique(nouveau: dict, ancien: Optional[dict]) -> dict:
    """`nouveau` avec les mesures techniques d'`ancien` quand elles existent."""
    if not ancien or not ancien.get("n_tech"):
        return nouveau
    out = {k: v for k, v in nouveau.items() if k not in _CLES_TECHNIQUE}
    out.update({k: ancien[k] for k in _CLES_TECHNIQUE if k in ancien})
    return out


async def calculer_et_persister(session: AsyncSession,
                                aujourd_hui: Optional[date] = None) -> dict:
    """Recalcule les derniers jours (et comble ceux qui manquent depuis le 17/08)."""
    await session.execute(text(_DDL))
    aujourd_hui = aujourd_hui or datetime.now(PARIS).date()
    existants: dict[tuple[str, str], dict] = {}
    for j, seg, d in (await session.execute(text(
            "SELECT jour, segment, data FROM suivi_precision"))).all():
        existants[(j, seg)] = json.loads(d) if isinstance(d, str) else d
    deja = {j for j, _ in existants}
    jours = []
    j = PREMIER_JOUR
    while j < aujourd_hui:
        if j.isoformat() not in deja or (aujourd_hui - j).days <= JOURS_RECALCULES:
            jours.append(j)
        j += timedelta(days=1)
    ecrits = 0
    for j in jours:
        segments = await mesurer_jour(session, j)
        await session.execute(text("DELETE FROM suivi_precision WHERE jour = :j"),
                              {"j": j.isoformat()})
        for seg, cumul in segments.items():
            cumul = figer_technique(cumul, existants.get((j.isoformat(), seg)))
            await session.execute(text("""
                INSERT INTO suivi_precision (jour, segment, data, updated_at)
                VALUES (:j, :s, :d, CURRENT_TIMESTAMP)
            """), {"j": j.isoformat(), "s": seg, "d": json.dumps(cumul)})
            ecrits += 1
        await session.commit()
    log.info("suivi_precision.calcule", jours=len(jours), lignes=ecrits)
    return {"status": "ok", "jours_recalcules": len(jours), "lignes": ecrits}


async def lire_suivi(session: AsyncSession, jours: int = 60, segment: str = "tout") -> dict:
    """Séries par jour et par semaine + fenêtres 7 j / 30 j / tout, en chiffres réels."""
    try:
        rows = (await session.execute(text("""
            SELECT jour, data FROM suivi_precision WHERE segment = :s ORDER BY jour
        """), {"s": segment})).all()
    except Exception:                                            # noqa: BLE001
        try:
            await session.rollback()
        except Exception:                                        # noqa: BLE001
            pass
        return {"mesure_disponible": False, "pourquoi": "suivi jamais calculé"}
    if not rows:
        return {"mesure_disponible": False, "pourquoi": "aucune journée mesurée"}
    par_jour = [(date.fromisoformat(j), json.loads(d) if isinstance(d, str) else d) for j, d in rows]
    dernier = par_jour[-1][0]
    limite = dernier - timedelta(days=jours - 1)
    serie = []
    for j, cumul in par_jour:
        if j < limite:
            continue
        fenetre7 = cumuler(c for jj, c in par_jour if j - timedelta(days=6) <= jj <= j)
        l7 = lire_cumul(fenetre7)
        l1 = lire_cumul(cumul)
        if l7["n_courses"] < MIN_COURSES_GLISSANT:
            serie.append({"jour": j.isoformat(), "courses": l1["n_courses"],
                          "courses_7j": l7["n_courses"]})
            continue
        serie.append({
            "jour": j.isoformat(), "courses": l1["n_courses"],
            "n1_gagne_7j": l7["n1_gagne_servi"], "favori_gagne_7j": l7["favori_gagne_marche"],
            "n1_gagne_technique_7j": l7["technique"]["n1_gagne"],
            "cote_juste_vs_marche_7j": l7["cote_juste_vs_marche"]["moyenne"],
            "classement_vs_marche_7j": l7["classement_vs_marche"]["moyenne"],
            "technique_vs_servi_7j": l7["technique"]["cote_juste_vs_servi"]["moyenne"],
            "placement_logloss_7j": l7["placement_logloss_servi"],
            "placement_logloss_technique_7j": l7["technique"]["placement_logloss"],
            "courses_7j": l7["n_courses"],
        })
    semaines: dict[str, list] = {}
    for j, cumul in par_jour:
        if j < limite:
            continue
        lundi = j - timedelta(days=j.weekday())
        semaines.setdefault(lundi.isoformat(), []).append(cumul)
    fen = {}
    for nom, nb in (("7j", 7), ("30j", 30)):
        fen[nom] = lire_cumul(cumuler(c for j, c in par_jour if j > dernier - timedelta(days=nb)))
    fen["tout"] = lire_cumul(cumuler(c for _, c in par_jour))
    return {
        "mesure_disponible": True,
        "segment": segment,
        "premier_jour": par_jour[0][0].isoformat(),
        "dernier_jour": dernier.isoformat(),
        "par_jour": serie,
        "par_semaine": [{"semaine": s, **lire_cumul(cumuler(cs))} for s, cs in sorted(semaines.items())],
        "fenetres": fen,
    }
