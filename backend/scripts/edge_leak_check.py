"""edge_leak_check.py — READ-ONLY, rapide. 1 split temporel 75/25 par course.
Teste : fuite stats-saison (D) + edge hors-marché (C) + confirme dédup (B).
Logge progressif (flush) → tailable."""
import asyncio
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score

from db.database import AsyncSessionLocal
from ml.pipeline import _build_training_dataset_from_db
from ml.models import build_training_dataset, META_COLS

DUP_ODDS = ["cote_geny","cote_bzh","cote_unibet","cote_winamax","cote_betclic",
    "cote_betfair_exchange","cote_marche_min","ratio_pmu_geny","gap_pmu_betfair",
    "spread_bookmakers","decote_detectee","valeur_latente","steam_move_betclic"]
MARKET_ALL = DUP_ODDS + ["cote_pmu","prob_implicite","rang_cote","rang_cote_relatif",
    "est_favori","variance_cotes_7j","momentum_3j","mouvement_30min","mouvement_bm_pct",
    "spi_score","market_timing_score","pool_gagnant_ratio","tendance_force",
    "rang_popularite","rang_pronostic_geny","pronostic_expert_rang","sagesse_foules_score",
    "consensus_sources","nb_experts_presse","nb_premier_presse","presse_consensus_score"]
SEASON_STATS = ["jockey_taux_victoire_global","jockey_taux_place_global","jockey_roi",
    "jockey_victoires_saison","jockey_montes_30j","jockey_forme_30j","entraineur_taux_global",
    "entraineur_taux_place","entraineur_roi","entraineur_victoires_saison","entraineur_forme_30j",
    "asso_jockey_entraineur_taux","asso_jockey_entraineur_nb","asso_jockey_entraineur_fiable",
    "combo_jockey_entraineur"]
KW = dict(n_estimators=120, max_depth=4, learning_rate=0.08, subsample=0.85,
          colsample_bytree=0.85, eval_metric="logloss", random_state=42, n_jobs=-1)


def roi(d, mask):
    g = int(mask.sum())
    if g == 0: return float("nan"), 0
    net = (d.loc[mask, "cote"] * (d.loc[mask, "won"] == 1)).sum()
    return 100.0 * (net - g) / g, g


async def main():
    print("[leak] loading...", flush=True)
    async with AsyncSessionLocal() as s:
        feats, res = await _build_training_dataset_from_db(s, mois=24)
    X, y3, yw = build_training_dataset(feats, res)
    print(f"[leak] {len(X)} lignes / {X['course_id'].nunique()} courses", flush=True)
    co = list(dict.fromkeys(X["course_id"].tolist()))
    cut = int(len(co) * 0.75)
    trc = set(co[:cut]); tem = X["course_id"].isin(set(co[cut:])).to_numpy()
    trm = X["course_id"].isin(trc).to_numpy()
    yw_te = yw[tem]; y3_te = y3[tem]
    # ROI base frame (test)
    base = pd.DataFrame({"cid": X["course_id"].to_numpy()[tem], "cote": X["cote_pmu"].to_numpy()[tem],
                         "won": yw.to_numpy()[tem]})
    base = base[(base["cote"] > 1.0) & (base["cote"] <= 30.0)].copy()
    base["inv"] = 1.0 / base["cote"]
    base["fair"] = base["inv"] / base.groupby("cid")["inv"].transform("sum")

    allf = [c for c in X.columns if c not in META_COLS]
    variants = {
        "A_FULL": allf,
        "B_DEDUP": [c for c in allf if c not in DUP_ODDS],
        "D_NOSEASON": [c for c in allf if c not in SEASON_STATS],
        "C_PUREFORM": [c for c in allf if c not in MARKET_ALL],
    }
    for name, cols in variants.items():
        Xf = X[cols].fillna(0)
        m3 = XGBClassifier(**KW); m3.fit(Xf[trm], y3[trm])
        a3 = roc_auc_score(y3_te, m3.predict_proba(Xf[tem])[:, 1]) if y3_te.nunique() > 1 else 0.5
        mw = XGBClassifier(**KW); mw.fit(Xf[trm], yw[trm])
        pw = mw.predict_proba(Xf[tem])[:, 1]
        aw = roc_auc_score(yw_te, pw) if yw_te.nunique() > 1 else 0.5
        b = base.copy(); b["pw"] = pw[(X["cote_pmu"].to_numpy()[tem] > 1.0) & (X["cote_pmu"].to_numpy()[tem] <= 30.0)]
        r_raw, n_raw = roi(b, (b["pw"] * b["cote"] - 1.0) > 0.05)
        r_dv, n_dv = roi(b, b["pw"] > b["fair"] * 1.05)
        print(f"=== {name} (n_feat={len(cols)}) AUC top3={a3:.4f} win={aw:.4f} | "
              f"ROI brute={r_raw:+.1f}%(n{n_raw}) devig={r_dv:+.1f}%(n{n_dv})", flush=True)
    print("[leak] LECTURE: D<<A => stats-saison fuitent ; C ROI-devig>0 => edge reel", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
