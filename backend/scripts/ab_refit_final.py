"""Refit final (BT_REFIT_FULL) contre le modèle servi aujourd'hui — rejeu, n'écrit RIEN.

La question
───────────
Le modèle servi est celui entraîné sur les 80 % de courses les plus anciennes du
jeu (hold-out temporel de `BlackTurfEnsemble.train`) : v544, promu le 24/09, porte
`train_fin = 2026-07-08`. Le drapeau `refit_full` garde la décision et sert, une
fois la promotion décidée, la même procédure rejouée sur TOUT le jeu
(`ml.pipeline._modele_a_servir`). Que gagne-t-on, sur des courses que ni l'un ni
l'autre n'a vues ?

Protocole
─────────
Pour chaque date de coupure C :
  1. jeu d'entraînement = douze mois avant C, features figées AVANT le départ
     (mêmes gardes que la production, `_build_training_dataset_from_db`) ;
  2. bras « actuel » = `train()` 80/20, exactement le modèle qu'on sert ;
     bras « refit » = `_modele_a_servir(actuel, …, refit=True)` ;
  3. évaluation sur les courses de ]C ; C + horizon] — hors échantillon pour les
     DEUX bras, reconstruites par le même constructeur (mêmes labels, mêmes
     gardes) ;
  4. mesures PAR COURSE, puis écart APPARIÉ refit − actuel avec IC à 95 %
     (`ml.avantage_marche._ecart_apparie`).

Le walk-forward ne produit que des MESURES (aucun objet servi n'en dépend) : il
n'est exécuté que pour la première coupure, qui sert aussi à chronométrer la nuit
telle qu'elle tournerait en production. Les autres coupures le court-circuitent,
ce qui ne change pas un seul arbre des deux bras.

Garanties : session PostgreSQL en LECTURE SEULE, aucune écriture de modèle
(`save` / `deploy` ne sont jamais appelés), résultats en JSON dans `--sortie`.

Usage (conteneur jetable, cf. P0_B_retrain_2026-09-24.md) :
    python -m scripts.ab_refit_final --coupures 2026-08-24,2026-07-24,2026-06-24
"""
import argparse
import asyncio
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import get_settings
from ml import melange_arrivees as _ma
from ml.avantage_marche import _ecart_apparie
from ml.models import BlackTurfEnsemble, temporal_holdout_mask
from ml.pipeline import _build_training_dataset_from_db, _modele_a_servir
from ml.ranking_metrics import within_race_auc_par_course


# ── Mémoire : pic RSS PAR PHASE (VmHWM remis à zéro par clear_refs) ─────────
def _statut(cle: str) -> float:
    try:
        with open("/proc/self/status") as fh:
            for ligne in fh:
                if ligne.startswith(cle):
                    return round(int(ligne.split()[1]) / 1024, 1)
    except OSError:
        pass
    return 0.0


def _raz_pic() -> bool:
    try:
        with open("/proc/self/clear_refs", "w") as fh:
            fh.write("5")
        return True
    except OSError:
        return False


class _Phase:
    def __init__(self, nom: str, journal: dict):
        self.nom, self.journal = nom, journal

    def __enter__(self):
        self.raz = _raz_pic()
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.journal[self.nom] = {
            "duree_s": round(time.monotonic() - self.t0, 1),
            "pic_rss_mo": _statut("VmHWM"),
            "pic_par_phase": self.raz,
            "rss_fin_mo": _statut("VmRSS"),
        }
        print(f"  [{self.nom}] {self.journal[self.nom]}", flush=True)


# ── Mesures par course ───────────────────────────────────────────────────────
def _par_course(modele, E: pd.DataFrame, y3: np.ndarray, yw: np.ndarray,
                betas) -> dict:
    """{mesure: {course_id: valeur}} pour un modèle sur le jeu d'évaluation."""
    cid = E["course_id"].to_numpy()
    cotes = E["cote_pmu"].to_numpy(dtype=float) if "cote_pmu" in E.columns else None
    p3 = np.asarray(modele.predict_proba(E), dtype=float)
    pw = modele.predict_win_proba(E)
    pw = np.asarray(pw, dtype=float) if pw is not None else None

    out = {"auc_top3": within_race_auc_par_course(y3, p3, cid),
           "ll_top3": {}, "auc_victoire": {}, "ll_victoire": {},
           "rang1_gagne": {}, "ll_victoire_servie": {}, "rang1_gagne_servi": {}}
    if pw is not None:
        out["auc_victoire"] = within_race_auc_par_course(yw, pw, cid)

    ordre = np.argsort(cid, kind="stable")
    bornes = np.flatnonzero(np.r_[True, cid[ordre][1:] != cid[ordre][:-1], True])
    for a, b in zip(bornes[:-1], bornes[1:]):
        idx = ordre[a:b]
        c = cid[idx[0]]
        # Log-loss binaire du top-3, moyennée sur les partants de la course.
        p = np.clip(p3[idx], 1e-6, 1 - 1e-6)
        t = y3[idx]
        out["ll_top3"][c] = float(-(t * np.log(p) + (1 - t) * np.log(1 - p)).mean())
        if pw is None or len(idx) < 2 or yw[idx].sum() != 1:
            continue
        g = int(np.argmax(yw[idx]))
        q = pw[idx]
        if not np.isfinite(q).all() or q.sum() <= 0:
            continue
        qn = q / q.sum()
        out["ll_victoire"][c] = -math.log(max(float(qn[g]), 1e-15))
        out["rang1_gagne"][c] = float(int(np.argmax(qn)) == g)
        # Proba de victoire SERVIE : mélange appris sur les arrivées (β en service).
        if betas is not None and cotes is not None:
            s = _ma.appliquer(q, cotes[idx], betas[0], betas[1])
            if s is not None:
                out["ll_victoire_servie"][c] = -math.log(max(float(s[g]), 1e-15))
                out["rang1_gagne_servi"][c] = float(int(np.argmax(s)) == g)
    return out


def _marche_par_course(E: pd.DataFrame, yw: np.ndarray) -> dict:
    """Référence : 1/cote normalisée dans la course."""
    cid = E["course_id"].to_numpy()
    cotes = E["cote_pmu"].to_numpy(dtype=float)
    ll, r1 = {}, {}
    ordre = np.argsort(cid, kind="stable")
    bornes = np.flatnonzero(np.r_[True, cid[ordre][1:] != cid[ordre][:-1], True])
    for a, b in zip(bornes[:-1], bornes[1:]):
        idx = ordre[a:b]
        if len(idx) < 2 or yw[idx].sum() != 1:
            continue
        q = _ma.probas_marche(cotes[idx])
        if q is None:
            continue
        g = int(np.argmax(yw[idx]))
        ll[cid[idx[0]]] = -math.log(max(float(q[g]), 1e-15))
        r1[cid[idx[0]]] = float(int(np.argmax(q)) == g)
    return {"ll_victoire": ll, "rang1_gagne": r1}


MESURES = (  # (clé, sens : +1 = plus haut est mieux)
    ("auc_top3", +1), ("ll_top3", -1), ("auc_victoire", +1), ("ll_victoire", -1),
    ("rang1_gagne", +1), ("ll_victoire_servie", -1), ("rang1_gagne_servi", +1),
)


async def _une_coupure(session, coupure: datetime, horizon: int, mois: int,
                       max_rows, avec_wf: bool, betas) -> dict:
    journal: dict = {}
    print(f"\n=== coupure {coupure:%Y-%m-%d}  (évaluation → +{horizon} j) ===", flush=True)
    with _Phase("dataset_entrainement", journal):
        X, y, y_win = await _build_training_dataset_from_db(
            session, mois, max_rows=max_rows, date_fin=coupure)
    fin_eval_j = coupure + timedelta(days=horizon)
    with _Phase("dataset_evaluation", journal):
        # Même constructeur, fenêtre ]coupure ; coupure + horizon[ : `date_limite`
        # vaut date_fin − 30 × mois, donc mois = horizon / 30.
        E, E3, Ew = await _build_training_dataset_from_db(
            session, horizon // 30, max_rows=None, date_fin=fin_eval_j)

    hm = temporal_holdout_mask(X)
    cid_x = X["course_id"]
    derniers = {"actuel": cid_x[~hm].iloc[-1], "refit": cid_x.iloc[-1]}
    fins = {}
    for bras, c in derniers.items():
        fins[bras] = (await session.execute(
            text("SELECT date_heure FROM courses WHERE course_id = :c"), {"c": c})).scalar()
    print(f"  entraînement : {len(X)} partants / {cid_x.nunique()} courses "
          f"(hold-out {int(hm.sum())} lignes)", flush=True)
    print(f"  train_fin actuel {fins['actuel']}   refit {fins['refit']}", flush=True)
    print(f"  évaluation   : {len(E)} partants / {E['course_id'].nunique()} courses", flush=True)

    orig_wf = BlackTurfEnsemble._walk_forward_validation
    if not avec_wf:
        BlackTurfEnsemble._walk_forward_validation = lambda self, *a, **k: [0.5]
    try:
        with _Phase("entrainement_evaluation" + ("" if avec_wf else "_sans_wf"), journal):
            actuel = BlackTurfEnsemble()
            metrics = actuel.train(X, y, y_win)
    finally:
        BlackTurfEnsemble._walk_forward_validation = orig_wf
    with _Phase("refit", journal):
        refit = _modele_a_servir(actuel, X, y, y_win, refit=True)
    n_train = len(X)
    del X, y, y_win

    y3, yw = E3.to_numpy(), Ew.to_numpy()
    with _Phase("mesures", journal):
        m = {"actuel": _par_course(actuel, E, y3, yw, betas),
             "refit": _par_course(refit, E, y3, yw, betas)}
        marche = _marche_par_course(E, yw)

    resultat = {
        "coupure": coupure.isoformat(), "horizon_jours": horizon,
        "n_lignes_train": n_train, "n_courses_eval": int(E["course_id"].nunique()),
        "train_fin": {k: str(v) for k, v in fins.items()},
        "retard_a_la_coupure_j": {k: round((coupure - v).total_seconds() / 86400, 1)
                                   for k, v in fins.items() if v is not None},
        "metriques_hold_out_actuel": {k: metrics.get(k) for k in (
            "auc_roc", "rank_auc", "market_rank_auc", "rank_delta_market",
            "walk_forward_auc", "win_auc")},
        "ressources": journal,
        "moyennes": {}, "apparie_refit_moins_actuel": {},
        "marche": {k: float(np.mean(list(v.values()))) for k, v in marche.items() if v},
        "_par_course": {b: m[b] for b in m},
    }
    for cle, _ in MESURES:
        a, b = m["actuel"][cle], m["refit"][cle]
        communes = set(a) & set(b)
        if not communes:
            continue
        resultat["moyennes"][cle] = {
            "actuel": float(np.mean([a[c] for c in communes])),
            "refit": float(np.mean([b[c] for c in communes])), "n": len(communes)}
        resultat["apparie_refit_moins_actuel"][cle] = _ecart_apparie(b, a, communes)
    for cle, sens in MESURES:
        if cle in resultat["moyennes"]:
            mo, ap = resultat["moyennes"][cle], resultat["apparie_refit_moins_actuel"][cle]
            print(f"  {cle:<20} actuel {mo['actuel']:.4f}  refit {mo['refit']:.4f}  "
                  f"écart {ap['ecart']:+.4f} IC {ap['ic95']}  n={ap['n']}  "
                  f"({'plus haut' if sens > 0 else 'plus bas'} = mieux)", flush=True)
    return resultat


async def main(coupures: list[datetime], horizon: int, mois: int, max_rows,
               sortie: Path) -> int:
    if horizon % 30:
        raise SystemExit("l'horizon doit être un multiple de 30 jours (constructeur mensuel)")
    sortie.mkdir(parents=True, exist_ok=True)
    resultats = []
    # LECTURE SEULE au niveau du SERVEUR : chaque connexion de ce moteur ouvre ses
    # transactions en `READ ONLY`, une écriture échouerait côté PostgreSQL.
    moteur = create_async_engine(get_settings().database_url, pool_pre_ping=True,
                                 connect_args={"server_settings": {
                                     "default_transaction_read_only": "on",
                                     "statement_timeout": "900000"}})
    fabrique = async_sessionmaker(moteur, expire_on_commit=False)
    async with fabrique() as session:
        ro = (await session.execute(text("SHOW default_transaction_read_only"))).scalar()
        print(f"session en lecture seule : {ro}", flush=True)
        if ro != "on":
            raise SystemExit("session non protégée en écriture : abandon")
        await _ma.charger(session)
        betas = _ma.en_service()
        print(f"mélange sur les arrivées en service : {betas}", flush=True)
        for i, c in enumerate(coupures):
            resultats.append(await _une_coupure(session, c, horizon, mois, max_rows,
                                                avec_wf=(i == 0), betas=betas))
            await session.rollback()          # referme la transaction de lecture

    # Agrégat APPARIÉ sur toutes les coupures (fenêtres disjointes).
    total = {}
    for cle, sens in MESURES:
        a, b = {}, {}
        for r in resultats:
            pa, pb = r["_par_course"]["actuel"][cle], r["_par_course"]["refit"][cle]
            a.update({f"{r['coupure']}|{k}": v for k, v in pa.items()})
            b.update({f"{r['coupure']}|{k}": v for k, v in pb.items()})
        communes = set(a) & set(b)
        if communes:
            total[cle] = {"actuel": float(np.mean([a[k] for k in communes])),
                          "refit": float(np.mean([b[k] for k in communes])),
                          **_ecart_apparie(b, a, communes)}
    print("\n=== TOUTES COUPURES (apparié, refit − actuel) ===")
    for cle, sens in MESURES:
        if cle in total:
            t = total[cle]
            print(f"  {cle:<20} actuel {t['actuel']:.4f}  refit {t['refit']:.4f}  "
                  f"écart {t['ecart']:+.4f} IC {t['ic95']}  n={t['n']}  "
                  f"conclut={t['conclut']} ({'plus haut' if sens > 0 else 'plus bas'} = mieux)")
    for r in resultats:
        r.pop("_par_course")
    await moteur.dispose()
    fichier = sortie / f"ab_refit_final_{datetime.now(timezone.utc):%Y%m%dT%H%M}.json"
    fichier.write_text(json.dumps({"coupures": resultats, "total": total},
                                  indent=2, default=str, ensure_ascii=False))
    print(f"\nrésultats : {fichier}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coupures", required=True,
                    help="dates ISO séparées par des virgules ; la PREMIÈRE est chronométrée "
                         "avec walk-forward")
    ap.add_argument("--horizon-jours", type=int, default=30)
    ap.add_argument("--mois", type=int, default=12)
    ap.add_argument("--max-rows", type=int, default=220_000)
    ap.add_argument("--sortie", default="/out")
    args = ap.parse_args()
    _c = [datetime.fromisoformat(s.strip()).replace(tzinfo=timezone.utc)
          for s in args.coupures.split(",")]
    raise SystemExit(asyncio.run(main(_c, args.horizon_jours, args.mois,
                                      args.max_rows, Path(args.sortie))))
