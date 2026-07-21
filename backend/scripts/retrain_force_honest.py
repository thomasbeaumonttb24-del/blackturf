"""retrain_force_honest.py — Entraîne v(N+1) sur les features LEAK-FREE (recompute
point-in-time) et le déploie INCONDITIONNELLEMENT, en bypassant la comparaison
walk-forward vs modèle actif.

POURQUOI bypasser le gate : le modèle actif (v494) a un walk-forward AUC GONFLÉ par
la fuite stats-saison (mesuré : +0.05 win-AUC, ROI +79 vs +29). Le gate wf
préférerait donc à tort le modèle leaké au modèle honnête (wf plus bas mais HONNÊTE
= meilleur en live). On force le honnête APRÈS garde-fous de SANTÉ absolus (pas de
modèle cassé) : walk-forward >= 0.6 et brier <= 0.20. Sinon ABORT (rien déployé).

À lancer APRÈS recompute_features_prerace.py (sinon entraîne sur l'ancien builder)
ET avec le builder leak-free déployé dans le worker (sinon train/serve skew).
"""
import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select, update

from db.database import AsyncSessionLocal
from db.models import ModelVersion
from ml.models import BlackTurfEnsemble, build_training_dataset
from ml.pipeline import _build_training_dataset_from_db, _get_next_version_num

MOIS = 60
WF_FLOOR = 0.60       # walk-forward minimum (sinon modèle ~aléatoire)
BRIER_CEIL = 0.20     # brier maximum (sinon mal calibré)


async def main() -> int:
    t0 = datetime.now()
    async with AsyncSessionLocal() as session:
        feats, res = await _build_training_dataset_from_db(session, MOIS)
        print(f"[force] dataset {len(feats)} lignes", flush=True)
        if len(feats) < 300:
            print("[force] ABORT insufficient data", flush=True)
            return 1
        X, y, y_win = build_training_dataset(feats, res)
        if X.empty:
            print("[force] ABORT empty", flush=True)
            return 1
        n_rows = len(X)
        print(f"[force] training on {n_rows} rows, {len([c for c in X.columns])} cols...", flush=True)
        import gc
        del feats, res
        gc.collect()

        model = BlackTurfEnsemble()
        metrics = model.train(X, y, y_win)
        del X, y, y_win
        gc.collect()

        wf = float(metrics.get("walk_forward_auc") or metrics["auc_roc"])
        brier = float(metrics["brier_score"])
        win_auc = float(getattr(model, "win_auc", 0.0) or 0.0)
        print(f"[force] METRICS auc={metrics['auc_roc']:.4f} wf={wf:.4f} win_auc={win_auc:.4f} "
              f"brier={brier:.4f} prec_top3={metrics['precision_top3']:.4f} "
              f"roi_sim={metrics['roi_simule']:.3f} n_feat={len(model.feature_names)}", flush=True)

        # ── Garde-fous de SANTÉ (on force le honnête, pas un cassé) ──
        if wf < WF_FLOOR:
            print(f"[force] ABORT wf {wf:.4f} < {WF_FLOOR} (modèle non fiable)", flush=True)
            return 1
        if brier > BRIER_CEIL:
            print(f"[force] ABORT brier {brier:.4f} > {BRIER_CEIL} (mal calibré)", flush=True)
            return 1

        version_num = await _get_next_version_num(session)
        model.deploy(version_num)   # écrit current_model.pkl (= modèle servi)
        mv = ModelVersion(
            version_id=str(uuid.uuid4()),
            version_num=version_num,
            nom_fichier=f"model_v{version_num:04d}.pkl",
            auc_roc=metrics["auc_roc"],
            brier_score=brier,
            precision_top3=metrics["precision_top3"],
            roi_simule=metrics["roi_simule"],
            walk_forward_auc=metrics.get("walk_forward_auc"),
            walk_forward_variance=metrics.get("walk_forward_variance"),
            nb_courses_train=n_rows,
            est_actif=True,
            est_synthetique=False,
            feature_importance=model.feature_importance,
        )
        session.add(mv)
        await session.execute(
            update(ModelVersion).where(ModelVersion.version_num < version_num).values(est_actif=False)
        )
        await session.commit()
        dt = (datetime.now() - t0).total_seconds()
        print(f"[force] DEPLOYED v{version_num} (forced honest) in {dt:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
