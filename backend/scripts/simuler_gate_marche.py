"""Qu'auraient décidé les gates marché sur les promotions passées ? — LECTURE SEULE.

Deux gates, deux questions :

    ANCIEN   `rank_delta_market` du modèle NU ≥ marge (0,0) — relu tel qu'il a été
             stocké dans `model_versions` au moment de chaque promotion.
    NOUVEAU  le classement SERVI du challenger ne recule pas, face à la cote, par
             rapport à celui du champion (`ml.avantage_marche.mesure_gate_servi`).

Le nouveau gate se mesure en production sur le hold-out de la nuit, qui n'est pas
conservé. Ce script le rejoue avec les archives de modèles encore présentes
(`models/model_v*.pkl`, les cinq dernières) sur les courses RÉELLEMENT servies
avant départ dont les features figées sont en base (`prediction_evaluation`,
depuis le 17/08) et postérieures à la fin d'apprentissage de tous les modèles
comparés : hors échantillon pour chacun, même statistique, autre échantillon.

Usage (depuis `backend/`) :
    python -m scripts.simuler_gate_marche --modeles /chemin/model_v0540.pkl ... \
        [--depuis 2026-08-17] [--json sortie.json]

Les archives se lisent sans rien toucher au conteneur :
    ssh vps "docker exec blackturf_worker cat /app/models/model_v0540.pkl" > model_v0540.pkl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ablation_cote_servi import _jsonable, _moteur_lecture_seule, charger  # noqa: E402


def gate_ancien(rank_delta_market, marge: float = 0.0) -> str:
    if rank_delta_market is None:
        return "non mesuré → passe"
    return "BLOQUÉ" if rank_delta_market < marge else "passe"


async def _versions_en_base() -> dict:
    from sqlalchemy import text
    moteur, Session = _moteur_lecture_seule()
    try:
        async with Session() as s:
            rows = (await s.execute(text(
                "SELECT version_num, created_at, train_fin, rank_delta_market, rank_source "
                "FROM model_versions WHERE version_num >= 520 ORDER BY version_num"))).all()
    finally:
        await moteur.dispose()
    return {int(r[0]): {"promu_le": r[1], "train_fin": r[2], "rank_delta_market": r[3],
                        "rank_source": r[4]} for r in rows}


async def principal(args) -> dict:
    from ml import melange_arrivees as ma
    from ml.avantage_marche import (
        GATE_TOLERANCE, _auc_gagnant, _ecart_apparie, _par_course, auc_marche_par_course,
        auc_servie_par_course, mesure_gate_servi)
    from ml.models import BlackTurfEnsemble

    versions = await _versions_en_base()
    sortie: dict = {"ancien_gate": [], "nouveau_gate": [], "par_version": {}}

    # ── ANCIEN gate : relu en base, sur toutes les promotions depuis v520 ──
    for v, d in versions.items():
        sortie["ancien_gate"].append({
            "version": v, "promu_le": str(d["promu_le"])[:10],
            "rank_delta_market": d["rank_delta_market"], "source": d["rank_source"],
            "verdict": gate_ancien(d["rank_delta_market"])})

    # ── NOUVEAU gate : rejoué sur les archives disponibles ──
    modeles = {}
    for chemin in args.modeles:
        m = re.search(r"model_v(\d+)\.pkl", Path(chemin).name)
        if not m:
            continue
        modeles[int(m.group(1))] = BlackTurfEnsemble.load(Path(chemin))
    if len(modeles) < 2:
        return sortie
    colonnes: list[str] = []
    for mod in modeles.values():
        colonnes += [c for c in mod.feature_names if c not in set(colonnes)]
    fins = [versions[v]["train_fin"] for v in modeles if versions.get(v, {}).get("train_fin")]
    depuis = datetime.fromisoformat(args.depuis).replace(tzinfo=timezone.utc)
    if fins:
        depuis = max(depuis, max(fins) + timedelta(days=1))
    jusqu = datetime.now(timezone.utc)
    courses, exclusions, betas = await charger(depuis, jusqu, colonnes=colonnes)
    courses = [c for c in courses if c["features"] is not None]
    sortie.update({"depuis": depuis.isoformat(), "betas": betas, "exclusions": exclusions,
                   "n_courses": len(courses)})
    y, g, cotes, blocs = [], [], [], []
    for c in courses:
        n = len(c["num"])
        yy = np.zeros(n)
        yy[c["g"]] = 1.0
        y.append(yy)
        g += [c["course_id"]] * n
        cotes.append(c["cotes"])
        blocs.append(np.vstack(c["features"]))
    y, g, cotes = np.concatenate(y), np.array(g), np.concatenate(cotes)
    X = pd.DataFrame(np.vstack(blocs), columns=colonnes)
    auc_marche = auc_marche_par_course(y, g, cotes)
    servis, bruts = {}, {}
    for v, mod in sorted(modeles.items()):
        pw = mod.predict_win_proba(X)
        servis[v] = auc_servie_par_course(pw, y, g, cotes, betas)
        pw = np.asarray(pw, dtype=float)
        bruts[v] = {k: a for k, idx, gg in _par_course(g, y)
                    if (a := _auc_gagnant(pw[idx], gg)) is not None}
        communes = set(servis[v]) & set(auc_marche)
        sortie["par_version"][v] = {
            "servi_vs_marche": _ecart_apparie(servis[v], auc_marche, communes),
            "nu_vs_marche": _ecart_apparie(bruts[v], auc_marche, communes),
            "rank_delta_market_stocke": versions.get(v, {}).get("rank_delta_market"),
        }
    ordre = sorted(modeles)
    for champion, challenger in zip(ordre[:-1], ordre[1:]):
        m = mesure_gate_servi(servis[champion], servis[challenger], auc_marche,
                              tolerance=GATE_TOLERANCE)
        sortie["nouveau_gate"].append({"champion": champion, "challenger": challenger, **(m or {}),
                                       "verdict": ("BLOQUÉ" if m and m["bloque"] else "passe")})
    _imprimer(sortie)
    if args.json:
        Path(args.json).write_text(json.dumps(_jsonable(sortie), ensure_ascii=False, indent=1,
                                              default=str), encoding="utf-8")
    return sortie


def _imprimer(s: dict) -> None:
    print("\n=== ANCIEN gate (modèle nu ≥ cote), relu dans model_versions")
    for l in s["ancien_gate"]:
        d = l["rank_delta_market"]
        print(f"  v{l['version']} {l['promu_le']}  delta nu {d:+.4f} ({l['source'] or 'walk_forward'})"
              f"  → {l['verdict']}" if d is not None else f"  v{l['version']} → {l['verdict']}")
    print(f"\n=== NOUVEAU gate rejoué — {s.get('n_courses')} courses depuis {s.get('depuis')}, β={s.get('betas')}")
    for v, d in s["par_version"].items():
        a, b = d["servi_vs_marche"], d["nu_vs_marche"]
        print(f"  v{v}: servi − cote {a['ecart']:+.4f} {a['ic95']}  |  nu − cote {b['ecart']:+.4f} {b['ic95']}"
              f"  (stocké au hold-out : {d['rank_delta_market_stocke']})")
    for l in s["nouveau_gate"]:
        print(f"  v{l['champion']} → v{l['challenger']}: régression {l.get('regression')} "
              f"IC {l.get('ic95_regression')} n={l.get('n_courses')} → {l['verdict']}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--modeles", nargs="+", required=True)
    ap.add_argument("--depuis", default="2026-08-17")
    ap.add_argument("--json")
    asyncio.run(principal(ap.parse_args(argv)))


if __name__ == "__main__":
    main()
