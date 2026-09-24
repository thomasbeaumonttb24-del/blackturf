"""Ablation hors temps : la cote, le modèle, et ce qu'on sert — LECTURE SEULE.

La question (audit du 2026-09-23, P0 « la cote pilote le score final »)
─────────────────────────────────────────────────────────────────────
Quatre systèmes jugés sur EXACTEMENT les mêmes courses, avec les prédictions
réellement émises AVANT le départ (`prediction_evaluation`, `created_at <
date_heure`) et la cote figée au moment du conseil (`cote_figee`) :

    marche          la cote seule, 1/cote normalisée sur la course (dévigée) ;
    sans_marche     un modèle de victoire entraîné SANS les colonnes de marché
                    (option `--modeles`, voir la sous-commande `entrainer`) ;
    brut            la proba de victoire BRUTE réellement servie
                    (`proba_top1_raw`, normalisée par course) — c'est le « modèle
                    complet nu » : en production `BT_MARKET_RESIDUAL` n'est pas
                    défini, le modèle apprend donc AVEC la cote ;
    servi           la proba de victoire réellement affichée (`proba_top1`) ;
    servi_actuel    la chaîne d'AUJOURD'HUI rejouée sur toute la fenêtre :
                    `melange_arrivees` (β en service) appliqué à `brut`. Avant le
                    16/09 le servi venait d'une autre chaîne (isotone + mélange
                    linéaire + netteté) : sans ce rejeu, la fenêtre mélangerait
                    deux produits.

Avec `--modeles`, deux systèmes de plus, entraînés par ce script jusqu'à une
coupure ANTÉRIEURE à la fenêtre, même recette, seule la liste de colonnes change :
`sans_marche` (sans `COLONNES_MARCHE`, ce que ferait `BT_MARKET_RESIDUAL=1`) et
`complet_meme_recette` (avec). C'est leur écart qui isole l'apport des colonnes de
marché ; comparer `sans_marche` à `brut` confondrait colonnes, recette et
fraîcheur d'entraînement.

Mesures, par course puis moyennées (chaque course pèse pareil)
──────────────────────────────────────────────────────────────
- `gagne_r1`   le rang 1 du système gagne (0/1) ;
- `logloss`    −ln p(gagnant), proba normalisée sur la course (↓ mieux) ;
- `auc`        AUC intra-course du gagnant contre les autres partants ;
- `roi_fige`   un euro sur le rang 1, payé à la cote figée (net, −1 si perdu) ;
- `roi_pmu`    le même euro payé au rapport officiel du Simple Gagnant (le PMU
               paie la clôture, pas la cote figée — cf. verdict du 17/09).

Chaque écart est APPARIÉ (différence course par course, IC 95 % normal). Il est
aussi recalculé sur les deux moitiés chronologiques de la fenêtre : une mesure
concluante dont les moitiés se contredisent est marquée « NE RÉPLIQUE PAS »
(règle du 03/09 : une mesure sur une seule fenêtre est du bruit ajusté).

Usage (depuis `backend/`, variables BT_* comme en production)
─────────────────────────────────────────────────────────────
    # 1. (facultatif) entraîner les deux bras sans/avec marché, coupure avant la fenêtre
    python -m scripts.ablation_cote_servi entrainer --coupure 2026-08-15 \
        --sortie /tmp/ablation_modeles.pkl
    # 2. mesurer
    python -m scripts.ablation_cote_servi mesurer --depuis 2026-06-26 \
        [--modeles /tmp/ablation_modeles.pkl] [--json sortie.json]

Aucune écriture : les sessions sont ouvertes en `default_transaction_read_only`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import pickle
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PLANCHER_P = 1e-6
BANDES_PROBA = (0.0, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0001)
BANDES_COTE_FAVORI = ((0.0, 2.0, "favori < 2"), (2.0, 3.0, "favori 2-3"),
                      (3.0, 5.0, "favori 3-5"), (5.0, 1e9, "favori >= 5"))
BANDES_EV = ((-1e9, 0.0, "EV < 0"), (0.0, 0.10, "EV 0-10 %"), (0.10, 1e9, "EV >= 10 %"))
METRIQUES = ("gagne_r1", "logloss", "auc", "roi_fige", "roi_pmu")
# Comparaisons publiées : (a, b) → écart a − b. Pour la log-loss, NÉGATIF = a meilleur.
COMPARAISONS = (
    ("brut", "marche"),
    ("servi", "marche"),
    ("servi_actuel", "marche"),
    ("servi", "brut"),
    ("servi_actuel", "brut"),
    ("servi_actuel", "servi"),
    ("sans_marche", "marche"),
    ("complet_meme_recette", "marche"),
    ("sans_marche", "complet_meme_recette"),
    ("sans_marche", "brut"),
    # Même colonnes que la production, entraînement plus frais (coupure du bras) :
    # isole ce que coûte l'âge du modèle servi, indépendamment de la cote.
    ("complet_meme_recette", "brut"),
    # APRÈS mélange à la cote (β en validation croisée) : ce que chaque bras
    # donnerait une fois servi.
    ("brut_melange", "marche"),
    ("sans_marche_melange", "marche"),
    ("complet_meme_recette_melange", "marche"),
    ("sans_marche_melange", "complet_meme_recette_melange"),
    ("sans_marche_melange", "brut_melange"),
    ("complet_meme_recette_melange", "brut_melange"),
)


# ──────────────────────────────────────────────────────────────────────────────
# Fonctions pures (testées dans tests/test_ablation_cote_servi.py)
# ──────────────────────────────────────────────────────────────────────────────

def discipline_normalisee(d: Optional[str]) -> str:
    if not d:
        return "inconnue"
    s = unicodedata.normalize("NFKD", str(d)).encode("ascii", "ignore").decode().lower()
    for cle in ("plat", "attele", "monte", "obstacle", "haies", "steeple", "cross"):
        if cle in s:
            return "obstacle" if cle in ("haies", "steeple", "cross") else cle
    return s or "inconnue"


def bande_favori(cote_min: float) -> str:
    for bas, haut, nom in BANDES_COTE_FAVORI:
        if bas <= cote_min < haut:
            return nom
    return BANDES_COTE_FAVORI[-1][2]


def rang1(p: np.ndarray, cotes: np.ndarray) -> int:
    """Indice du rang 1 : proba maximale, ex æquo départagés par la plus petite
    cote (ce que ferait un lecteur), puis par l'ordre des partants."""
    p = np.asarray(p, dtype=float)
    meilleurs = np.flatnonzero(p >= p.max() - 1e-15)
    if len(meilleurs) == 1:
        return int(meilleurs[0])
    return int(meilleurs[np.argmin(np.asarray(cotes, dtype=float)[meilleurs])])


def auc_gagnant(p: np.ndarray, g: int) -> float:
    """Part des perdants classés SOUS le gagnant (ex æquo = 0,5)."""
    p = np.asarray(p, dtype=float)
    autres = np.delete(p, g)
    if autres.size == 0:
        return float("nan")
    return float(((p[g] > autres).sum() + 0.5 * (p[g] == autres).sum()) / autres.size)


def metriques_course(p: Sequence[float], g: int, cotes: Sequence[float],
                     rapport_sg: Optional[float]) -> Optional[dict]:
    """Mesures d'UN système sur UNE course. None si la proba est inexploitable."""
    p = np.asarray(p, dtype=float)
    c = np.asarray(cotes, dtype=float)
    if p.size < 2 or not np.isfinite(p).all() or p.sum() <= 0 or not 0 <= g < p.size:
        return None
    p = p / p.sum()
    r = rang1(p, c)
    gagne = r == g
    return {
        "gagne_r1": 1.0 if gagne else 0.0,
        "logloss": -math.log(max(float(p[g]), PLANCHER_P)),
        "auc": auc_gagnant(p, g),
        "roi_fige": (float(c[r]) - 1.0) if gagne else -1.0,
        # Sans rapport officiel connu, un rang 1 gagnant n'a pas de retour mesurable :
        # la course sort de CETTE mesure (None), jamais comptée à 0.
        "roi_pmu": ((float(rapport_sg) - 1.0) if rapport_sg else None) if gagne else -1.0,
        "p_r1": float(p[r]),
        "cote_r1": float(c[r]),
    }


def ecart_apparie(a: dict, b: dict, cles: Optional[Sequence] = None) -> dict:
    """Moyenne des différences a − b course par course, IC 95 % normal."""
    cles = [k for k in (cles if cles is not None else a) if k in a and k in b
            and a[k] is not None and b[k] is not None]
    d = np.array([a[k] - b[k] for k in cles], dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 2:
        return {"n": n, "ecart": None, "ic95": None, "conclut": False}
    m = float(d.mean())
    se = float(d.std(ddof=1) / math.sqrt(n))
    bas, haut = m - 1.96 * se, m + 1.96 * se
    return {"n": n, "ecart": m, "ic95": [bas, haut], "conclut": bool(bas > 0 or haut < 0)}


def verdict_replication(total: dict, moitie1: dict, moitie2: dict) -> str:
    """« réplique », « NE RÉPLIQUE PAS » ou « non concluant ».

    - non concluant : l'IC de la fenêtre entière contient zéro ;
    - réplique : concluant ET les deux moitiés vont dans le même sens ;
    - NE RÉPLIQUE PAS : concluant mais une moitié va dans l'autre sens.
    """
    if not total.get("conclut") or total.get("ecart") is None:
        return "non concluant"
    s = math.copysign(1.0, total["ecart"])
    for m in (moitie1, moitie2):
        if m.get("ecart") is None or math.copysign(1.0, m["ecart"]) != s:
            return "NE RÉPLIQUE PAS"
    return "réplique"


def calibration_par_bande(p: np.ndarray, y: np.ndarray,
                          bornes: Sequence[float] = BANDES_PROBA) -> list[dict]:
    """Proba annoncée contre fréquence réalisée, par bande de proba (par partant)."""
    out = []
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    for bas, haut in zip(bornes[:-1], bornes[1:]):
        m = (p >= bas) & (p < haut)
        n = int(m.sum())
        if n == 0:
            continue
        f = float(y[m].mean())
        # IC de Wilson : la fréquence d'une bande à 30 chevaux n'est pas une mesure.
        z = 1.96
        centre = (f + z * z / (2 * n)) / (1 + z * z / n)
        demi = z * math.sqrt(f * (1 - f) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        out.append({"bande": f"{bas:.2f}-{min(haut, 1.0):.2f}", "n": n,
                    "annonce": float(p[m].mean()), "realise": f,
                    "ic95_realise": [centre - demi, centre + demi]})
    return out


def preparer_courses(lignes: list[dict], gagnants: dict, rapports: dict,
                     partants: dict) -> tuple[list[dict], dict]:
    """Regroupe les lignes par course et écarte ce qui n'est pas comparable.

    Une course n'entre que COMPLÈTE : tous ses partants présents, tous cotés
    (> 1), une proba servie et brute pour chacun, un gagnant unique parmi eux.
    Sinon la normalisation du marché ne porterait pas sur le même champ que
    celle du modèle, et l'écart mesurerait une différence de périmètre.
    """
    par_course: dict[str, dict] = {}
    for l in lignes:
        d = par_course.setdefault(l["course_id"], {
            "course_id": l["course_id"], "date_heure": l["date_heure"],
            "discipline": discipline_normalisee(l.get("discipline")),
            "num": [], "servi": [], "brut": [], "cote": [], "frais": True,
            "features": [], "avec_features": True})
        d["num"].append(int(l["numero"]))
        d["servi"].append(l["servi"])
        d["brut"].append(l["brut"])
        d["cote"].append(l["cote"])
        d["frais"] = d["frais"] and bool(l.get("frais"))
        if l.get("features") is None:
            d["avec_features"] = False
        else:
            d["features"].append(l["features"])
    exclusions = {"incomplete": 0, "sans_cote": 0, "sans_proba": 0, "sans_gagnant": 0,
                  "dead_heat_ou_absent": 0}
    out = []
    for cid, d in par_course.items():
        n_attendus = partants.get(cid)
        if n_attendus is None or len(d["num"]) != n_attendus or len(d["num"]) < 2:
            exclusions["incomplete"] += 1
            continue
        cotes = np.array([np.nan if c is None else float(c) for c in d["cote"]])
        if not np.isfinite(cotes).all() or (cotes <= 1.0).any():
            exclusions["sans_cote"] += 1
            continue
        if any(v is None for v in d["servi"]) or any(v is None for v in d["brut"]):
            exclusions["sans_proba"] += 1
            continue
        g_nums = gagnants.get(cid)
        if not g_nums:
            exclusions["sans_gagnant"] += 1
            continue
        if len(g_nums) != 1 or g_nums[0] not in d["num"]:
            exclusions["dead_heat_ou_absent"] += 1
            continue
        g = d["num"].index(g_nums[0])
        q = 1.0 / cotes
        out.append({
            "course_id": cid, "date_heure": d["date_heure"], "discipline": d["discipline"],
            "num": d["num"], "g": g, "cotes": cotes, "frais": d["frais"],
            "rapport_sg": rapports.get(cid),
            "bande_favori": bande_favori(float(cotes.min())),
            "probas": {"marche": q / q.sum(),
                       "brut": np.array(d["brut"], dtype=float),
                       "servi": np.array(d["servi"], dtype=float)},
            "features": d["features"] if d["avec_features"] else None,
        })
    out.sort(key=lambda c: (c["date_heure"], c["course_id"]))
    return out, exclusions


def ajouter_servi_actuel(courses: list[dict], betas: Optional[tuple]) -> None:
    """Rejoue `melange_arrivees` (β en service) sur la proba brute de chaque course."""
    if betas is None:
        return
    from ml import melange_arrivees as ma
    for c in courses:
        p = ma.appliquer(c["probas"]["brut"], c["cotes"], betas[0], betas[1])
        if p is not None:
            c["probas"]["servi_actuel"] = p


def ajouter_melanges_croises(courses: list[dict], noms: Sequence[str]) -> dict:
    """`<nom>_melange` : le système `nom` mélangé à la cote par `melange_arrivees`,
    β appris en VALIDATION CROISÉE chronologique (β d'une moitié appliqué à
    l'autre). Aucun bras n'est ainsi jugé sur les courses qui ont fixé son β —
    c'est ce qui rend « brut », « sans_marche » et « complet » comparables APRÈS
    mélange, contrairement à `servi_actuel` dont le β a vu une partie de la fenêtre."""
    from ml import melange_arrivees as ma
    betas: dict = {}
    for nom in noms:
        sel = [c for c in courses if nom in c["probas"]]
        if len(sel) < 100:
            continue
        moitie = len(sel) // 2
        betas[nom] = []
        for app, val in ((sel[:moitie], sel[moitie:]), (sel[moitie:], sel[:moitie])):
            dicts = [d for d in (ma._vers_course(c["probas"][nom], c["cotes"], c["g"],
                                                 c["probas"][nom]) for c in app) if d]
            b = ma.ajuster_beta(dicts)
            betas[nom].append([float(b[0]), float(b[1])])
            for c in val:
                p = ma.appliquer(c["probas"][nom], c["cotes"], b[0], b[1])
                if p is not None:
                    c["probas"][f"{nom}_melange"] = p
    return betas


def mesurer(courses: list[dict], systemes: Sequence[str]) -> dict:
    """{système: {course_id: métriques}}."""
    out: dict = {s: {} for s in systemes}
    for c in courses:
        for s in systemes:
            p = c["probas"].get(s)
            if p is None:
                continue
            m = metriques_course(p, c["g"], c["cotes"], c["rapport_sg"])
            if m is not None:
                out[s][c["course_id"]] = m
    return out


def _serie(par_course: dict, metrique: str) -> dict:
    return {k: v[metrique] for k, v in par_course.items() if v.get(metrique) is not None}


def tableau_niveaux(mes: dict, cles: Sequence[str]) -> dict:
    """Niveau moyen de chaque métrique pour chaque système sur les MÊMES courses."""
    out = {}
    for s, par_course in mes.items():
        sous = [par_course[k] for k in cles if k in par_course]
        if not sous:
            continue
        ligne = {"n": len(sous)}
        for m in METRIQUES:
            v = [x[m] for x in sous if x.get(m) is not None]
            ligne[m] = float(np.mean(v)) if v else None
        out[s] = ligne
    return out


def comparer(mes: dict, cles: Sequence[str], moitie1: set, moitie2: set) -> list[dict]:
    lignes = []
    for a, b in COMPARAISONS:
        if a not in mes or b not in mes or not mes[a] or not mes[b]:
            continue
        for m in METRIQUES:
            sa, sb = _serie(mes[a], m), _serie(mes[b], m)
            tot = ecart_apparie(sa, sb, cles)
            h1 = ecart_apparie(sa, sb, [k for k in cles if k in moitie1])
            h2 = ecart_apparie(sa, sb, [k for k in cles if k in moitie2])
            lignes.append({"a": a, "b": b, "metrique": m, "total": tot,
                           "moitie1": h1, "moitie2": h2,
                           "verdict": verdict_replication(tot, h1, h2)})
    return lignes


def ev_rang1(mes: dict, courses: list[dict], systeme: str) -> list[dict]:
    """Rang 1 du système, par bande d'EV annoncée (p × cote figée − 1) : annoncé,
    réalisé, ROI à la cote figée. C'est le « signal de forte valeur » de l'audit."""
    par = mes.get(systeme) or {}
    out = []
    for bas, haut, nom in BANDES_EV:
        sel = [v for k, v in par.items() if bas <= v["p_r1"] * v["cote_r1"] - 1.0 < haut]
        if not sel:
            continue
        ligne = {"bande": nom, "n": len(sel),
                 "p_annoncee": float(np.mean([v["p_r1"] for v in sel])),
                 "gagne": float(np.mean([v["gagne_r1"] for v in sel]))}
        for cle in ("roi_fige", "roi_pmu"):
            roi = np.array([v[cle] for v in sel if v.get(cle) is not None], dtype=float)
            ligne[cle] = float(roi.mean()) if len(roi) else None
            ligne[f"{cle}_ic95"] = ([float(roi.mean() - 1.96 * roi.std(ddof=1) / math.sqrt(len(roi))),
                                     float(roi.mean() + 1.96 * roi.std(ddof=1) / math.sqrt(len(roi)))]
                                    if len(roi) > 1 else None)
        out.append(ligne)
    return out


def analyser(courses: list[dict], systemes: Sequence[str]) -> dict:
    """Tout le rapport sur un ensemble de courses."""
    mes = mesurer(courses, systemes)
    # Ensemble commun : une course n'entre que si TOUS les systèmes présents l'ont
    # mesurée — c'est ce qui rend les niveaux comparables entre eux.
    presents = [s for s in systemes if mes.get(s)]
    communes = set.intersection(*(set(mes[s]) for s in presents)) if presents else set()
    ordre = [c["course_id"] for c in courses if c["course_id"] in communes]
    moitie1, moitie2 = set(ordre[:len(ordre) // 2]), set(ordre[len(ordre) // 2:])
    rapport = {
        "n_courses": len(ordre),
        "systemes": presents,
        "periode": [str(courses[0]["date_heure"]), str(courses[-1]["date_heure"])] if courses else None,
        "coupure_moities": (str(next(c["date_heure"] for c in courses
                                     if c["course_id"] == ordre[len(ordre) // 2]))
                            if len(ordre) > 1 else None),
        "niveaux": tableau_niveaux(mes, ordre),
        "comparaisons": comparer(mes, ordre, moitie1, moitie2),
        "par_discipline": {}, "par_bande_favori": {},
        "calibration": {}, "ev_rang1": {},
    }
    for cle, champ in (("par_discipline", "discipline"), ("par_bande_favori", "bande_favori")):
        for valeur in sorted({c[champ] for c in courses}):
            sous = [c["course_id"] for c in courses
                    if c[champ] == valeur and c["course_id"] in communes]
            if len(sous) < 30:
                continue
            s1, s2 = set(sous[:len(sous) // 2]), set(sous[len(sous) // 2:])
            rapport[cle][valeur] = {"n": len(sous), "niveaux": tableau_niveaux(mes, sous),
                                    "comparaisons": comparer(mes, sous, s1, s2)}
    for s in presents:
        ps, ys = [], []
        for c in courses:
            if c["course_id"] in communes and s in c["probas"]:
                p = np.asarray(c["probas"][s], dtype=float)
                ps.append(p / p.sum())
                y = np.zeros(len(p))
                y[c["g"]] = 1.0
                ys.append(y)
        if ps:
            rapport["calibration"][s] = calibration_par_bande(np.concatenate(ps), np.concatenate(ys))
        rapport["ev_rang1"][s] = ev_rang1({s: {k: v for k, v in mes[s].items() if k in communes}},
                                          courses, s)
    return rapport


# ──────────────────────────────────────────────────────────────────────────────
# Accès base (lecture seule)
# ──────────────────────────────────────────────────────────────────────────────

def _moteur_lecture_seule():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from api.config import get_settings
    url = get_settings().database_url
    kwargs: dict = {}
    if not url.startswith("sqlite"):
        kwargs = {"pool_size": 2, "max_overflow": 0,
                  "connect_args": {"server_settings": {
                      "default_transaction_read_only": "on",
                      "statement_timeout": "600000"}}}
    moteur = create_async_engine(url, **kwargs)
    return moteur, async_sessionmaker(moteur, class_=AsyncSession, expire_on_commit=False)


_REQUETE = """
    SELECT pe.course_id, pa.numero::int AS numero, pe.proba_top1, pe.proba_top1_raw,
           pe.cote_figee, pe.created_at, c.date_heure, c.discipline,
           {features}
    FROM prediction_evaluation pe
    JOIN participations pa ON pa.participation_id = pe.participation_id
    JOIN courses c         ON c.course_id         = pe.course_id
    WHERE pe.created_at IS NOT NULL AND c.date_heure IS NOT NULL
      AND pe.created_at < c.date_heure
      AND c.date_heure >= :depuis AND c.date_heure < :jusqu
      AND COALESCE(pa.non_partant, false) = false
"""
_PARTANTS = """
    SELECT p.course_id, count(*) FROM participations p JOIN courses c ON c.course_id = p.course_id
    WHERE c.date_heure >= :depuis AND c.date_heure < :jusqu
      AND COALESCE(p.non_partant, false) = false
    GROUP BY p.course_id
"""
_RESULTATS = """
    SELECT r.course_id, r.classement, r.rapports_detail
    FROM resultats r JOIN courses c ON c.course_id = r.course_id
    WHERE c.date_heure >= :depuis AND c.date_heure < :jusqu AND r.classement IS NOT NULL
"""


def _json(x):
    if x is None or isinstance(x, (dict, list)):
        return x
    try:
        return json.loads(x)
    except (TypeError, ValueError):
        return None


def gagnants_et_rapport(classement, rapports_detail) -> tuple[list[int], Optional[float]]:
    gagnants = []
    for e in _json(classement) or []:
        try:
            if int(e.get("position")) == 1:
                gagnants.append(int(e.get("numero")))
        except (TypeError, ValueError, AttributeError):
            continue
    rapport = None
    sg = (_json(rapports_detail) or {}).get("e_simple_gagnant") or []
    if len(gagnants) == 1:
        for r in sg:
            try:
                if int(str(r.get("combinaison")).strip()) == gagnants[0]:
                    rapport = float(r.get("rapport"))
                    break
            except (TypeError, ValueError, AttributeError):
                continue
    return gagnants, rapport


def vecteur(features, colonnes: Sequence[str]) -> np.ndarray:
    """Features figées → vecteur float32 dans l'ordre `colonnes` (absente/illisible = 0,
    comme à l'entraînement). Converti À LA LECTURE : un partant pèse ~30 Ko en dict
    Python, et la fenêtre en compte des dizaines de milliers."""
    f = _json(features) or {}
    out = np.zeros(len(colonnes), dtype=np.float32)
    for i, c in enumerate(colonnes):
        v = f.get(c)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[i] = v
    return out


async def charger(depuis: datetime, jusqu: datetime,
                  colonnes: Optional[Sequence[str]] = None,
                  fraicheur_min: int = 120) -> tuple[list[dict], dict, Optional[tuple]]:
    avec_features = colonnes is not None
    from sqlalchemy import text
    from ml import melange_arrivees as ma
    moteur, Session = _moteur_lecture_seule()
    params = {"depuis": depuis, "jusqu": jusqu}
    try:
        async with Session() as s:
            await ma.charger(s)
            betas = ma.en_service()
            partants = {r[0]: int(r[1]) for r in (await s.execute(text(_PARTANTS), params)).all()}
            gagnants, rapports = {}, {}
            for cid, cl, rd in (await s.execute(text(_RESULTATS), params)).all():
                g, r = gagnants_et_rapport(cl, rd)
                gagnants[cid], rapports[cid] = g, r
            sql = _REQUETE.format(features="pe.features" if avec_features else "NULL AS features")
            lignes = []
            res = await s.stream(text(sql), params)
            async for part in res.partitions(5000):
                for cid, num, servi, brut, cote, cree, dh, disc, feats in part:
                    lignes.append({
                        "course_id": cid, "numero": num,
                        "servi": None if servi is None else float(servi),
                        "brut": None if brut is None else float(brut),
                        "cote": None if cote is None else float(cote),
                        "date_heure": dh, "discipline": disc,
                        "frais": (dh - cree) <= timedelta(minutes=fraicheur_min),
                        "features": (vecteur(feats, colonnes)
                                     if avec_features and feats is not None else None),
                    })
    finally:
        await moteur.dispose()
    courses, exclusions = preparer_courses(lignes, gagnants, rapports, partants)
    return courses, exclusions, betas


# ──────────────────────────────────────────────────────────────────────────────
# Bras « sans marché » / « complet, même recette »
# ──────────────────────────────────────────────────────────────────────────────

def _params_xgb() -> dict:
    from ml.modele_technique import PARAMS_XGB
    return dict(PARAMS_XGB)


async def entrainer(coupure: datetime, sortie: Path, mois: int = 12) -> dict:
    """Deux modèles de VICTOIRE, même données, même recette, coupure `coupure` :
    l'un sans `COLONNES_MARCHE`, l'autre avec. Rien n'est écrit en base ni dans
    le dossier des modèles servis."""
    from xgboost import XGBClassifier
    from ml.models import COLONNES_MARCHE, META_COLS, _N_JOBS
    from ml.pipeline import _build_training_dataset_from_db
    from api.config import get_settings
    moteur, Session = _moteur_lecture_seule()
    try:
        async with Session() as s:
            X, _y3, yw = await _build_training_dataset_from_db(
                s, mois, max_rows=get_settings().retrain_max_rows, date_fin=coupure)
    finally:
        await moteur.dispose()
    base = [c for c in X.columns if c not in set(META_COLS)
            and pd.api.types.is_numeric_dtype(X[c]) and X[c].nunique(dropna=False) > 1]
    bras = {"sans_marche": [c for c in base if c not in COLONNES_MARCHE],
            "complet_meme_recette": base}
    modeles = {"coupure": coupure.isoformat(), "n_lignes": int(len(X)), "bras": {}}
    for nom, cols in bras.items():
        m = XGBClassifier(**_params_xgb(), n_jobs=_N_JOBS)
        m.fit(X[cols].fillna(0).astype("float32"), np.asarray(yw))
        modeles["bras"][nom] = {"colonnes": cols, "modele": m}
        print(f"  {nom}: {len(cols)} colonnes", flush=True)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with open(sortie, "wb") as f:
        pickle.dump(modeles, f, protocol=pickle.HIGHEST_PROTOCOL)
    return {"coupure": modeles["coupure"], "n_lignes": modeles["n_lignes"],
            "colonnes": {k: len(v) for k, v in bras.items()}}


def charger_bras(chemin: Path) -> tuple[dict, list[str]]:
    """Les bras entraînés, et l'union de leurs colonnes (ordre de lecture)."""
    with open(chemin, "rb") as f:
        modeles = pickle.load(f)
    colonnes: list[str] = []
    for b in modeles["bras"].values():
        colonnes += [c for c in b["colonnes"] if c not in set(colonnes)]
    return modeles, colonnes


def ajouter_bras(courses: list[dict], modeles: dict, colonnes: Sequence[str]) -> dict:
    """Score chaque course dotée de features figées avec les bras entraînés.
    Seules les courses postérieures à la coupure sont scorées : les autres ont
    été vues à l'entraînement."""
    coupure = datetime.fromisoformat(modeles["coupure"])
    if coupure.tzinfo is None:
        coupure = coupure.replace(tzinfo=timezone.utc)
    index = {c: i for i, c in enumerate(colonnes)}
    n = 0
    for c in courses:
        if c["features"] is None or c["date_heure"] <= coupure:
            continue
        F = np.vstack(c["features"])
        for nom, b in modeles["bras"].items():
            M = pd.DataFrame(F[:, [index[k] for k in b["colonnes"]]], columns=b["colonnes"])
            c["probas"][nom] = b["modele"].predict_proba(M)[:, 1]
        n += 1
    return {"coupure": modeles["coupure"], "courses_scorees": n}


# ──────────────────────────────────────────────────────────────────────────────
# Sortie texte
# ──────────────────────────────────────────────────────────────────────────────

def _f(x, nd=4):
    return "—" if x is None else f"{x:+.{nd}f}"


def imprimer(r: dict, titre: str) -> None:
    print(f"\n=== {titre} — {r['n_courses']} courses, {r['periode']}, "
          f"moitiés coupées au {r['coupure_moities']}")
    print(f"{'système':22s} {'gagne_r1':>9s} {'logloss':>8s} {'auc':>7s} {'roi_fige':>9s} {'roi_pmu':>8s}")
    for s, l in r["niveaux"].items():
        print(f"{s:22s} {l['gagne_r1']:9.4f} {l['logloss']:8.4f} {l['auc']:7.4f} "
              f"{l['roi_fige']:+9.4f} {(l['roi_pmu'] if l['roi_pmu'] is not None else float('nan')):+8.4f}")
    print("écarts appariés (a − b), IC 95 %, moitié 1 | moitié 2 → verdict")
    for c in r["comparaisons"]:
        t = c["total"]
        print(f"  {c['a']:>20s} − {c['b']:<20s} {c['metrique']:9s} {_f(t['ecart'])} "
              f"[{_f(t['ic95'][0]) if t['ic95'] else '—'} ; {_f(t['ic95'][1]) if t['ic95'] else '—'}] "
              f"n={t['n']:5d} | {_f(c['moitie1']['ecart'])} | {_f(c['moitie2']['ecart'])} → {c['verdict']}")


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


async def principal_mesurer(args) -> dict:
    jusqu = (datetime.fromisoformat(args.jusqu).replace(tzinfo=timezone.utc)
             if args.jusqu else datetime.now(timezone.utc))
    depuis = (datetime.fromisoformat(args.depuis).replace(tzinfo=timezone.utc)
              if args.depuis else jusqu - timedelta(days=args.jours))
    modeles, colonnes = charger_bras(Path(args.modeles)) if args.modeles else (None, None)
    courses, exclusions, betas = await charger(depuis, jusqu, colonnes=colonnes)
    ajouter_servi_actuel(courses, betas)
    sortie = {"depuis": depuis.isoformat(), "jusqu": jusqu.isoformat(),
              "betas_melange_en_service": betas, "exclusions": exclusions,
              "n_courses_chargees": len(courses)}
    systemes = ["marche", "brut", "servi", "servi_actuel"]
    sortie["fenetre_complete"] = analyser(courses, systemes)
    imprimer(sortie["fenetre_complete"], "FENÊTRE COMPLÈTE (quatre systèmes servis)")
    fraiches = [c for c in courses if c["frais"]]
    sortie["fenetre_fraiche"] = analyser(fraiches, systemes)
    imprimer(sortie["fenetre_fraiche"], "PRÉDICTIONS FRAÎCHES (≤ 2 h avant départ)")
    if args.modeles:
        sortie["bras"] = ajouter_bras(courses, modeles, colonnes)
        avec = [c for c in courses if "sans_marche" in c["probas"]]
        bras = ["brut", "sans_marche", "complet_meme_recette"]
        sortie["betas_croises"] = ajouter_melanges_croises(avec, bras)
        sortie["avec_bras"] = analyser(
            avec, systemes + bras[1:] + [f"{b}_melange" for b in bras])
        imprimer(sortie["avec_bras"], "SIX SYSTÈMES (courses après la coupure des bras)")
    if args.json:
        Path(args.json).write_text(json.dumps(_jsonable(sortie), ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return sortie


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("entrainer")
    e.add_argument("--coupure", required=True)
    e.add_argument("--sortie", required=True)
    e.add_argument("--mois", type=int, default=12)
    m = sub.add_parser("mesurer")
    m.add_argument("--jours", type=int, default=90)
    m.add_argument("--depuis")
    m.add_argument("--jusqu")
    m.add_argument("--modeles")
    m.add_argument("--json")
    args = ap.parse_args(argv)
    if args.cmd == "entrainer":
        coupure = datetime.fromisoformat(args.coupure).replace(tzinfo=timezone.utc)
        print(json.dumps(asyncio.run(entrainer(coupure, Path(args.sortie), args.mois))))
    else:
        asyncio.run(principal_mesurer(args))


if __name__ == "__main__":
    main()
