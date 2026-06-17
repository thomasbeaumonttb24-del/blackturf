"""
edge_truth_test.py — READ-ONLY. Ne déploie rien, n'écrit rien en base.

Répond à 2 questions décisives (audit 2026-06-17) :
  Q1 (skew cotes) : dropper cote_geny/bzh/unibet/winamax/betclic (qui en LIVE valent
      cote_pmu — sources mortes, geny 403) fait-il chuter l'AUC walk-forward ? Si non,
      ces colonnes sont du phantom (train/serve skew) → dédup sûr.
  Q2 (vrai edge) : un modèle FORME-PURE (zéro feature marché) garde-t-il de l'AUC et
      génère-t-il un ROI POSITIF hors-échantillon contre le marché DÉ-VIGGÉ ? → edge réel.

Méthode : mêmes features prod (_build_training_dataset_from_db respecte BT_TRAIN_PRERACE_ONLY),
walk-forward expandant PAR COURSE (group split, comme la prod). Ablation = drop de colonnes.
ROI sim = pari Simple Gagnant flat sur held-out, value = p_model > p_fair(dé-viggé), payout réel.
"""
import asyncio
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score

from db.database import AsyncSessionLocal
from ml.pipeline import _build_training_dataset_from_db
from ml.models import build_training_dataset, META_COLS

# Colonnes cotes "phantom" en live (sources mortes → = cote_pmu) + leurs dérivées
DUP_ODDS = [
    "cote_geny", "cote_bzh", "cote_unibet", "cote_winamax", "cote_betclic",
    "cote_betfair_exchange", "cote_marche_min", "ratio_pmu_geny", "gap_pmu_betfair",
    "spread_bookmakers", "decote_detectee", "valeur_latente", "steam_move_betclic",
]
# Tout le marché + sagesse des foules (pour le modèle forme-pure)
MARKET_ALL = DUP_ODDS + [
    "cote_pmu", "prob_implicite", "rang_cote", "rang_cote_relatif", "est_favori",
    "variance_cotes_7j", "momentum_3j", "mouvement_30min", "mouvement_bm_pct",
    "spi_score", "market_timing_score", "pool_gagnant_ratio", "tendance_force",
    "rang_popularite", "rang_pronostic_geny", "pronostic_expert_rang",
    "sagesse_foules_score", "consensus_sources", "nb_experts_presse",
    "nb_premier_presse", "presse_consensus_score",
]
# Stats agrégées SAISON (stats_jockeys/entraineurs/associations join saison=YEAR) =
# suspects de FUITE quand on recompute une vieille course (saison complète = futur).
SEASON_STATS = [
    "jockey_taux_victoire_global", "jockey_taux_place_global", "jockey_roi",
    "jockey_victoires_saison", "jockey_montes_30j", "jockey_forme_30j",
    "entraineur_taux_global", "entraineur_taux_place", "entraineur_roi",
    "entraineur_victoires_saison", "entraineur_forme_30j",
    "asso_jockey_entraineur_taux", "asso_jockey_entraineur_nb",
    "asso_jockey_entraineur_fiable", "combo_jockey_entraineur",
]

XGB_KW = dict(n_estimators=120, max_depth=4, learning_rate=0.08,
              subsample=0.85, colsample_bytree=0.85,
              eval_metric="logloss", random_state=42, n_jobs=-1)


def _folds(courses_ordered, n_splits=6):
    nc = len(courses_ordered)
    min_train = max(2, int(nc * 0.5))
    fold = max(1, (nc - min_train) // n_splits)
    for i in range(n_splits):
        tr_end = min_train + i * fold
        te_end = tr_end + fold
        if te_end > nc:
            break
        yield set(courses_ordered[:tr_end]), set(courses_ordered[tr_end:te_end])


def _devig_fair(df_course):
    """p_fair dé-viggé par course = (1/cote) normalisé Σ=1."""
    inv = 1.0 / df_course["cote_pmu"].clip(lower=1.01)
    s = inv.sum()
    return inv / s if s > 0 else inv * 0.0


def run_variant(name, X, y_top3, y_win, groups, feat_cols, do_roi=True):
    courses_ordered = list(dict.fromkeys(groups.tolist()))
    g = groups.to_numpy()
    cote = X["cote_pmu"].to_numpy()
    cid_arr = groups.to_numpy()
    auc3, aucw = [], []
    roi_raw_n = roi_raw_g = roi_dv_n = roi_dv_g = 0.0
    nbets_raw = nbets_dv = 0
    Xf = X[feat_cols].fillna(0)
    yw = y_win.to_numpy()
    for tr, te in _folds(courses_ordered):
        trm = np.isin(g, list(tr)); tem = np.isin(g, list(te))
        if y_top3[tem].nunique() < 2 or y_win[tem].nunique() < 2:
            continue
        m3 = XGBClassifier(**XGB_KW); m3.fit(Xf[trm], y_top3[trm])
        auc3.append(roc_auc_score(y_top3[tem], m3.predict_proba(Xf[tem])[:, 1]))
        mw = XGBClassifier(**XGB_KW); mw.fit(Xf[trm], y_win[trm])
        pw = mw.predict_proba(Xf[tem])[:, 1]
        aucw.append(roc_auc_score(y_win[tem], pw))
        if do_roi:
            # vectorisé : dé-vig p_fair par course via groupby.transform
            d = pd.DataFrame({"cid": cid_arr[tem], "cote": cote[tem],
                              "pw": pw, "won": yw[tem]})
            d = d[(d["cote"] > 1.0) & (d["cote"] <= 30.0)]
            inv = 1.0 / d["cote"]
            d["fair"] = inv / d.groupby("cid")["cote"].transform(lambda s: (1.0 / s).sum())
            mask_raw = (d["pw"] * d["cote"] - 1.0) > 0.05
            mask_dv = d["pw"] > d["fair"] * 1.05
            roi_raw_g += mask_raw.sum(); nbets_raw += int(mask_raw.sum())
            roi_raw_n += (d.loc[mask_raw, "cote"] * (d.loc[mask_raw, "won"] == 1)).sum()
            roi_dv_g += mask_dv.sum(); nbets_dv += int(mask_dv.sum())
            roi_dv_n += (d.loc[mask_dv, "cote"] * (d.loc[mask_dv, "won"] == 1)).sum()
    def pct(net, gr):
        return 100.0 * (net - gr) / gr if gr > 0 else float("nan")
    print(f"\n=== {name}  (n_feat={len(feat_cols)}) ===", flush=True)
    print(f"  walk-forward AUC top3 : {np.mean(auc3):.4f}  (folds {[round(x,3) for x in auc3]})", flush=True)
    print(f"  walk-forward AUC win  : {np.mean(aucw):.4f}", flush=True)
    if do_roi:
        print(f"  ROI value-vs-coteBRUTE : {pct(roi_raw_n, roi_raw_g):+.1f}%  (n={nbets_raw})", flush=True)
        print(f"  ROI value-vs-DEVIGGE   : {pct(roi_dv_n, roi_dv_g):+.1f}%  (n={nbets_dv})", flush=True)
    return float(np.mean(auc3)), float(np.mean(aucw))


async def main():
    async with AsyncSessionLocal() as s:
        feats, res = await _build_training_dataset_from_db(s, mois=24)
    X, y3, yw = build_training_dataset(feats, res)
    print(f"[edge-truth] dataset: {len(X)} lignes, {X['course_id'].nunique()} courses", flush=True)
    groups = X["course_id"]
    all_feat = [c for c in X.columns if c not in META_COLS]
    dedup_feat = [c for c in all_feat if c not in DUP_ODDS]
    pure_feat = [c for c in all_feat if c not in MARKET_ALL]
    noseason_feat = [c for c in all_feat if c not in SEASON_STATS]
    print(f"[edge-truth] full={len(all_feat)} dedup={len(dedup_feat)} pureform={len(pure_feat)} noseason={len(noseason_feat)}", flush=True)
    run_variant("A_FULL (baseline)", X, y3, yw, groups, all_feat)
    run_variant("B_DEDUP (sans cotes dupliquees)", X, y3, yw, groups, dedup_feat)
    run_variant("D_NOSEASON (sans stats-saison J/E = test FUITE)", X, y3, yw, groups, noseason_feat)
    run_variant("C_PUREFORM (zero marche)", X, y3, yw, groups, pure_feat)
    print("\n[edge-truth] LECTURE:", flush=True)
    print("  Q1: B_DEDUP AUC ~= A_FULL -> cotes dupliquees = phantom, dedup SUR.", flush=True)
    print("  FUITE: si D_NOSEASON AUC/ROI << A_FULL -> stats-saison fuitent (recompute a leake).", flush=True)
    print("  Q2: C_PUREFORM ROI-DEVIGGE > 0 -> edge reel hors marche.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
