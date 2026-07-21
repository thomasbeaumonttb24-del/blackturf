"""
Modèle ML BlackTurf — Ensemble XGBoost + LightGBM + CatBoost + Stacking.
v4 — Stacking meta-learner appris (LightGBM L2) remplace les poids fixes.
     SHAP feature importance. Brier < 0.18 avant déploiement.
     Walk-forward validation 6 fenêtres glissantes.

Architecture :
  Level 0 : XGBoost + LightGBM + CatBoost (calibrés isotonique)
  Level 1 : LightGBM meta-learner sur les 3 prédictions L0 + features clés
             → apprend QUAND faire confiance à chaque modèle de base

SHAP :
  Calculé sur XGBoost (meilleure compatibilité).
  Valeurs SHAP stockées dans feature_importance + disponibles par partant.
"""
import os
import pickle
import json
import structlog
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional

from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

log = structlog.get_logger()

MODELS_DIR = Path(os.getenv("BT_MODELS_DIR", "/app/models"))
try:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    # Environnements sans /app en écriture (CI, tests) : ne pas casser l'import.
    # Les tests qui écrivent des modèles doivent passer BT_MODELS_DIR (ex. tmpdir).
    log.warning("models.dir.not_writable", path=str(MODELS_DIR))

# Parallélisme d'entraînement — capé pour éviter l'OOM sur petit VPS (7,6 Gio).
# n_jobs=_N_JOBS prenait tous les cœurs + pic RAM ~4,6 Go → OOM-kill du retrain nocturne.
_N_JOBS = int(os.getenv("BT_TRAIN_NJOBS", "2"))

# Poids fallback si stacking non disponible
ENSEMBLE_WEIGHTS_FALLBACK = {"xgb": 0.50, "lgbm": 0.30, "catboost": 0.20}

META_COLS = {"participation_id", "course_id", "cheval_id", "numero", "nom", "label",
             # champs TEXTE d'affichage/narratif (ajoutés au batch features) — jamais
             # des features ML : exclure sinon XGBoost rejette les dtypes object.
             "jockey_nom", "entraineur_nom", "cheval_nom",
             # ── Exclus du MODÈLE (audit edge 2026-06-17) — restent dans le dict pour
             #    narrative/valuebets, mais pas appris : ────────────────────────────
             # (a) COTES DUPLIQUÉES : en live geny/bzh/unibet/winamax/betclic/betfair
             #     valent cote_pmu (sources mortes, geny 403) → phantom + train/serve
             #     skew. Ablation prouvée NEUTRE sur l'AUC (A_FULL≈B_DEDUP). On garde
             #     cote_pmu + les dérivées pmu (prob_implicite, rang_cote, est_favori).
             "cote_geny", "cote_bzh", "cote_unibet", "cote_winamax", "cote_betclic",
             "cote_betfair_exchange", "cote_marche_min", "ratio_pmu_geny",
             "gap_pmu_betfair", "spread_bookmakers", "decote_detectee", "valeur_latente",
             "steam_move_betclic",
             # (b) STATS SAISON BRUTES (compteurs/ROI cumulés saison) = FUITE au recompute
             #     d'une course passée (la saison entière inclut le futur). Les TAUX
             #     jockey/entraîneur/asso sont, eux, recalculés point-in-time (trailing
             #     365j, date<départ) dans features.py et CONSERVÉS.
             "jockey_victoires_saison", "entraineur_victoires_saison",
             "jockey_montes_30j", "jockey_roi", "entraineur_roi"}

# Brier score minimum requis avant déploiement
BRIER_THRESHOLD = 0.18

# Features passées au meta-learner (en plus des 3 probas L0)
STACKING_FEATURES = [
    "cote_pmu", "rang_cote", "prob_implicite",
    "elo_vs_moyenne", "forme_5_courses", "spi_score",
    "nb_partants", "field_hhi", "jours_repos",
]


def _try_import_catboost():
    try:
        from catboost import CatBoostClassifier
        return CatBoostClassifier
    except ImportError:
        log.warning("catboost.not_installed", fallback="using LogisticRegression")
        return None


class BlackTurfEnsemble:
    """
    Ensemble calibré XGBoost + LightGBM + CatBoost.
    CatBoost excelle sur variables catégorielles (hippodrome, jockey, terrain).
    Fallback sur LogisticRegression si CatBoost non installé.
    """

    def __init__(self):
        self.xgb: Optional[CalibratedClassifierCV] = None
        self.lgbm: Optional[CalibratedClassifierCV] = None
        self.catboost: Optional[CalibratedClassifierCV] = None
        # Level-2 stacking meta-learner (LightGBM)
        # Input: [p_xgb, p_lgbm, p_cb, + STACKING_FEATURES]
        self.meta_learner: Optional[LGBMClassifier] = None
        self._stacking_trained: bool = False
        # Modèle de VICTOIRE dédié (label = arrivé 1er) — donne une P(top1) APPRISE
        # au lieu de la dériver de P(top3) par un exposant heuristique (p3**1.6).
        self.win_model: Optional[CalibratedClassifierCV] = None
        self.win_auc: float = 0.0
        self.win_brier: float = 1.0
        self.feature_names: list[str] = []
        self.stacking_feature_names: list[str] = []
        self.scaler = StandardScaler()
        self.version_num: int = 0
        self.auc_roc: float = 0.0
        self.brier_score: float = 1.0
        self.precision_top3: float = 0.0
        self.roi_simule: float = 0.0
        self.feature_importance: dict = {}
        self.shap_importance: dict = {}
        self.trained_at: Optional[datetime] = None
        self._catboost_available: bool = False
        # Modèle de RANKING (LGBMRanker lambdarank, groupé par course) — sert
        # UNIQUEMENT à ordonner le classement affiché (rang_predit), jamais les
        # probas/EV. None si non entraîné / LightGBM indispo.
        self.ranker = None

    def train(self, X: pd.DataFrame, y: pd.Series, y_win: Optional[pd.Series] = None) -> dict:
        """
        Entraîne l'ensemble (top-3). Split temporel 80/20.
        Walk-forward validation sur 6 fenêtres.
        Si y_win fourni, entraîne aussi le modèle de VICTOIRE dédié (P(top1) apprise).
        """
        self.feature_names = [c for c in X.columns if c not in META_COLS]
        X_feat = X[self.feature_names].fillna(0)

        n = len(X_feat)
        # FLAG group_split : split PAR COURSE (course_id), pas par cheval. Sans ça,
        # des chevaux de la MÊME course tombent à cheval sur train/test → le modèle
        # mémorise la course via les features de champ (field_hhi, elo_vs_moyenne…)
        # → AUC/Brier gonflés, modèle overfit promu, -52% live (cf. audit edge).
        # Flag off → split positionnel historique inchangé.
        from ml.algo_flags import FLAGS as _AF
        if _AF.group_split and "course_id" in X.columns:
            courses_ordered = list(dict.fromkeys(X["course_id"].tolist()))  # chrono (ORDER BY date_heure)
            cut = int(len(courses_ordered) * 0.8)
            train_courses = set(courses_ordered[:cut])
            train_mask = X["course_id"].isin(train_courses).to_numpy()
            X_train, X_test = X_feat[train_mask], X_feat[~train_mask]
            y_train, y_test = y[train_mask], y[~train_mask]
        else:
            split = int(n * 0.8)
            X_train, X_test = X_feat.iloc[:split], X_feat.iloc[split:]
            y_train, y_test = y.iloc[:split], y.iloc[split:]

        log.info("model.training", n_train=len(X_train), n_test=len(X_test), pos_rate=float(y_train.mean()))

        pos_weight = float((y_train == 0).sum()) / max(float((y_train == 1).sum()), 1)

        # ── XGBoost 50% ──────────────────────────────────
        xgb_base = XGBClassifier(
            n_estimators=600,
            max_depth=6,
            learning_rate=0.04,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            scale_pos_weight=pos_weight,
            use_label_encoder=False,
            eval_metric="logloss",
            tree_method="hist",
            random_state=42,
            n_jobs=_N_JOBS,
        )
        self.xgb = CalibratedClassifierCV(xgb_base, method="isotonic", cv=3)
        self.xgb.fit(X_train, y_train)
        log.info("model.xgb_trained")

        # ── LightGBM 30% ──────────────────────────────────
        lgbm_base = LGBMClassifier(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.04,
            num_leaves=40,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=15,
            is_unbalance=True,
            random_state=42,
            verbose=-1,
            n_jobs=_N_JOBS,
        )
        self.lgbm = CalibratedClassifierCV(lgbm_base, method="isotonic", cv=3)
        self.lgbm.fit(X_train, y_train)
        log.info("model.lgbm_trained")

        # ── CatBoost 20% (ou Logistic fallback) ───────────
        CatBoostCls = _try_import_catboost()
        if CatBoostCls is not None:
            cb_base = CatBoostCls(
                iterations=400,
                depth=6,
                learning_rate=0.05,
                loss_function="Logloss",
                eval_metric="AUC",
                class_weights=[1.0, pos_weight],
                random_seed=42,
                verbose=0,
            )
            self.catboost = CalibratedClassifierCV(cb_base, method="isotonic", cv=3)
            self.catboost.fit(X_train, y_train)
            self._catboost_available = True
            log.info("model.catboost_trained")
        else:
            X_scaled = self.scaler.fit_transform(X_train)
            logistic_base = LogisticRegression(max_iter=1000, C=0.1, random_state=42)
            self.catboost = CalibratedClassifierCV(logistic_base, method="isotonic", cv=3)
            self.catboost.fit(X_scaled, y_train)
            self._catboost_available = False
            log.info("model.logistic_fallback")

        # ── Stacking Level-2 via out-of-fold predictions ──────────────────
        # Use StratifiedKFold to generate OOF predictions for meta-learner training
        # This prevents data leakage from L0 → L1
        log.info("model.stacking.start")
        try:
            # FLAG group_split : OOF par groupe de course → aucun frère de course ne
            # fuit dans le fold d'entraînement de ses voisins (sinon le méta-learner
            # apprend sur des probas OOF malhonnêtes = sur-confiant en prod).
            if _AF.group_split and "course_id" in X.columns:
                from sklearn.model_selection import StratifiedGroupKFold
                _groups_tr = X.loc[X_train.index, "course_id"].to_numpy()
                _fold_iter = StratifiedGroupKFold(n_splits=5).split(X_train, y_train, groups=_groups_tr)
            else:
                skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
                _fold_iter = skf.split(X_train, y_train)
            oof_xgb = np.zeros(len(X_train))
            oof_lgbm = np.zeros(len(X_train))
            oof_cb = np.zeros(len(X_train))

            for fold_train_idx, fold_val_idx in _fold_iter:
                Xf_tr, Xf_val = X_train.iloc[fold_train_idx], X_train.iloc[fold_val_idx]
                yf_tr = y_train.iloc[fold_train_idx]

                # Quick fold models (no calibration for speed)
                xgb_fold = XGBClassifier(
                    n_estimators=200, max_depth=5, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    scale_pos_weight=pos_weight, use_label_encoder=False,
                    eval_metric="logloss", tree_method="hist",
                    random_state=42, n_jobs=_N_JOBS, verbosity=0
                )
                xgb_fold.fit(Xf_tr, yf_tr)
                oof_xgb[fold_val_idx] = xgb_fold.predict_proba(Xf_val)[:, 1]

                lgbm_fold = LGBMClassifier(
                    n_estimators=200, max_depth=5, learning_rate=0.05,
                    num_leaves=31, subsample=0.8, colsample_bytree=0.8,
                    is_unbalance=True, random_state=42, verbose=-1, n_jobs=_N_JOBS
                )
                lgbm_fold.fit(Xf_tr, yf_tr)
                oof_lgbm[fold_val_idx] = lgbm_fold.predict_proba(Xf_val)[:, 1]

                # CatBoost fold
                CatBoostCls_fold = _try_import_catboost()
                if CatBoostCls_fold:
                    cb_fold = CatBoostCls_fold(
                        iterations=150, depth=5, learning_rate=0.06,
                        loss_function="Logloss", class_weights=[1.0, pos_weight],
                        random_seed=42, verbose=0
                    )
                    cb_fold.fit(Xf_tr, yf_tr)
                    oof_cb[fold_val_idx] = cb_fold.predict_proba(Xf_val)[:, 1]
                else:
                    oof_cb[fold_val_idx] = oof_xgb[fold_val_idx]

            # Build stacking features for meta-learner
            stacking_feat_cols = [f for f in STACKING_FEATURES if f in X_train.columns]
            self.stacking_feature_names = stacking_feat_cols

            meta_X_train = np.column_stack(
                [oof_xgb, oof_lgbm, oof_cb]
                + [X_train[c].fillna(0).values for c in stacking_feat_cols]
            )

            # Train meta-learner LightGBM
            self.meta_learner = LGBMClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.03,
                num_leaves=15, subsample=0.8, colsample_bytree=0.7,
                is_unbalance=True, random_state=42, verbose=-1, n_jobs=_N_JOBS
            )
            self.meta_learner.fit(meta_X_train, y_train)
            self._stacking_trained = True
            log.info("model.stacking.trained", n_meta_features=meta_X_train.shape[1])

        except Exception as e:
            log.warning("model.stacking.failed", err=str(e), fallback="fixed weights")
            self._stacking_trained = False

        # ── Walk-forward validation (6 fenêtres) ──────────
        _wf_groups = X["course_id"] if (_AF.group_split and "course_id" in X.columns) else None
        wf_scores = self._walk_forward_validation(X_feat, y, groups=_wf_groups)
        log.info("model.walk_forward", scores=[round(s, 4) for s in wf_scores], mean=round(float(np.mean(wf_scores)), 4))

        # ── Métriques finales ──────────────────────────────
        # course_id est une colonne META (retirée de X_feat) → on la repasse alignée sur
        # l'index de X_test pour que la précision top-3 puisse grouper PAR COURSE (sinon 0).
        _test_cid = X.loc[X_test.index, "course_id"] if "course_id" in X.columns else None
        metrics = self._evaluate(X_test, y_test, _test_cid)
        metrics["walk_forward_auc"] = float(np.mean(wf_scores))
        metrics["walk_forward_variance"] = float(np.var(wf_scores))

        self.auc_roc = metrics["auc_roc"]
        self.brier_score = metrics["brier_score"]
        self.precision_top3 = metrics["precision_top3"]
        self.roi_simule = metrics.get("roi_simule", 0.0)
        self.trained_at = datetime.now()

        # ── Feature importance (XGBoost gain-based) ───────
        try:
            xgb_inner = self.xgb.calibrated_classifiers_[0].estimator
            if hasattr(xgb_inner, "feature_importances_"):
                self.feature_importance = {
                    name: float(imp)
                    for name, imp in zip(self.feature_names, xgb_inner.feature_importances_)
                }
        except Exception:
            pass

        # ── SHAP values (approximation via XGBoost built-in) ──────────────
        try:
            import shap
            xgb_inner_shap = self.xgb.calibrated_classifiers_[0].estimator
            explainer = shap.TreeExplainer(xgb_inner_shap)
            shap_sample = X_test.iloc[:min(500, len(X_test))]
            shap_vals = explainer.shap_values(shap_sample)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1]  # classe 1
            mean_abs_shap = np.abs(shap_vals).mean(axis=0)
            self.shap_importance = {
                name: float(val)
                for name, val in zip(self.feature_names, mean_abs_shap)
            }
            # Merge SHAP into feature_importance
            self.feature_importance.update(
                {f"shap_{k}": v for k, v in self.shap_importance.items()}
            )
            log.info("model.shap.computed", top_feature=max(self.shap_importance, key=self.shap_importance.get))
        except Exception:
            pass  # SHAP optional (requires shap package)

        # ── Modèle de VICTOIRE dédié (label = arrivé 1er) ─────────────────
        # Donne une P(top1) APPRISE (vs heuristique p3**1.6). Fortement déséquilibré
        # (~1 gagnant / nb_partants) → scale_pos_weight + calibration isotonique.
        if y_win is not None and len(y_win) == n:
            try:
                # Aligner sur l'index de X_train/X_test → cohérent ET robuste aux DEUX
                # modes de split (group_split par course = masque, sinon positionnel).
                # Avant : iloc[:split] plantait sous group_split (`split` non défini).
                yw_train, yw_test = y_win.loc[X_train.index], y_win.loc[X_test.index]
                if yw_train.nunique() > 1:
                    pos_w_win = float((yw_train == 0).sum()) / max(float((yw_train == 1).sum()), 1)
                    win_base = XGBClassifier(
                        n_estimators=500, max_depth=5, learning_rate=0.04,
                        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                        scale_pos_weight=pos_w_win, use_label_encoder=False,
                        eval_metric="logloss", tree_method="hist",
                        random_state=42, n_jobs=_N_JOBS,
                    )
                    self.win_model = CalibratedClassifierCV(win_base, method="isotonic", cv=3)
                    self.win_model.fit(X_train, yw_train)
                    if yw_test.nunique() > 1:
                        p_win_test = self.win_model.predict_proba(X_test)[:, 1]
                        self.win_auc = float(roc_auc_score(yw_test, p_win_test))
                        self.win_brier = float(brier_score_loss(yw_test, p_win_test))
                    log.info("model.win_model_trained",
                             win_auc=round(self.win_auc, 4), win_brier=round(self.win_brier, 4),
                             pos_rate=round(float(yw_train.mean()), 4))
            except Exception as e:
                log.warning("model.win_model_failed", err=str(e)[:160])
                self.win_model = None

        # ── Modèle de RANKING (LambdaRank, groupé par course) ─────────────────
        # Optimise directement l'ORDRE d'arrivée intra-course (vs la classif top3
        # binaire). Score utilisé seulement pour le classement affiché (blend côté
        # predict, flag BT_RANKER_BLEND) — jamais pour les probas/EV calibrées.
        self.ranker = None
        if _AF.group_split and "course_id" in X.columns and y_win is not None and len(y_win) == n:
            try:
                import itertools
                from lightgbm import LGBMRanker
                _grp_src = X.loc[X_train.index, "course_id"].tolist()
                _grp = [sum(1 for _ in g) for _, g in itertools.groupby(_grp_src)]
                _yw = y_win.loc[X_train.index].to_numpy()
                _y3 = y_train.to_numpy()
                # relevance : gagnant=2, placé(top3)=1, autre=0 (label_gain associé)
                _rel = np.where(_yw == 1, 2, np.where(_y3 == 1, 1, 0)).astype(int)
                if sum(_grp) == len(X_train) and len(_grp) >= 2:
                    _rk = LGBMRanker(
                        objective="lambdarank", n_estimators=400, max_depth=6,
                        learning_rate=0.05, num_leaves=40, subsample=0.8,
                        colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=_N_JOBS,
                        label_gain=[0, 1, 3],
                    )
                    _rk.fit(X_train, _rel, group=_grp)
                    self.ranker = _rk
                    log.info("model.ranker_trained", n_groups=len(_grp))
            except Exception as e:
                log.warning("model.ranker_failed", err=str(e)[:160])
                self.ranker = None

        # Brier threshold check
        if self.brier_score > BRIER_THRESHOLD:
            log.warning("model.brier_too_high", brier=self.brier_score, threshold=BRIER_THRESHOLD)

        log.info(
            "model.trained",
            auc=round(self.auc_roc, 4),
            brier=round(self.brier_score, 4),
            prec_top3=round(self.precision_top3, 4),
            roi=round(self.roi_simule, 4),
            stacking=self._stacking_trained,
            catboost=self._catboost_available,
            win_model=self.win_model is not None,
            win_auc=round(self.win_auc, 4),
        )
        metrics["win_auc"] = self.win_auc
        metrics["win_brier"] = self.win_brier
        return metrics

    def _get_l0_predictions(self, X_feat: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Retourne les 3 prédictions L0 : (p_xgb, p_lgbm, p_cb)."""
        p_xgb = self.xgb.predict_proba(X_feat)[:, 1]
        p_lgbm = self.lgbm.predict_proba(X_feat)[:, 1]
        if self._catboost_available:
            p_cb = self.catboost.predict_proba(X_feat)[:, 1]
        else:
            X_scaled = self.scaler.transform(X_feat)
            p_cb = self.catboost.predict_proba(X_scaled)[:, 1]
        return p_xgb, p_lgbm, p_cb

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Prédictions ensemblées.
        Si stacking entraîné : meta-learner L2 (LightGBM sur OOF L0 + features contextuelles).
        Sinon : fallback poids fixes 50/30/20.
        """
        X_feat = X.reindex(columns=self.feature_names, fill_value=0).fillna(0)
        p_xgb, p_lgbm, p_cb = self._get_l0_predictions(X_feat)

        if self._stacking_trained and self.meta_learner is not None:
            try:
                stacking_cols = [c for c in self.stacking_feature_names if c in X_feat.columns]
                meta_X = np.column_stack(
                    [p_xgb, p_lgbm, p_cb]
                    + [X_feat[c].fillna(0).values for c in stacking_cols]
                )
                return self.meta_learner.predict_proba(meta_X)[:, 1]
            except Exception as e:
                log.warning("model.stacking.predict_failed", err=str(e), fallback="fixed_weights")

        # Fallback : poids fixes
        return (
            ENSEMBLE_WEIGHTS_FALLBACK["xgb"] * p_xgb
            + ENSEMBLE_WEIGHTS_FALLBACK["lgbm"] * p_lgbm
            + ENSEMBLE_WEIGHTS_FALLBACK["catboost"] * p_cb
        )

    def predict_with_confidence(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """
        Retourne (probas, confidence_scores).

        Confidence améliorée :
          1. Accord L0 : 1 - std(p_xgb, p_lgbm, p_cb) / mean  (désaccord entre modèles)
          2. Plausibilité marché : 1 - |proba - prob_implicite_cote|  (écart au marché)
          3. Score final = 0.6 × accord_L0 + 0.4 × plausibilité_marché

        Plus un modèle est en accord AVEC lui-même (les 3 modèles convergent)
        ET avec le marché, plus la confidence est élevée.
        """
        X_feat = X.reindex(columns=self.feature_names, fill_value=0).fillna(0)
        p_xgb, p_lgbm, p_cb = self._get_l0_predictions(X_feat)

        probas = self.predict_proba(X)

        # ── Accord L0 ────────────────────────────────────────────────────
        stack = np.stack([p_xgb, p_lgbm, p_cb], axis=1)
        std_l0 = stack.std(axis=1)
        mean_l0 = stack.mean(axis=1) + 1e-8
        accord_l0 = np.clip(1.0 - std_l0 / mean_l0, 0.0, 1.0)

        # ── Plausibilité marché ───────────────────────────────────────────
        market_confidence = np.ones(len(probas))
        if "prob_implicite" in X_feat.columns:
            prob_market = X_feat["prob_implicite"].values.astype(float)
            ecart = np.abs(probas - prob_market)
            market_confidence = np.clip(1.0 - ecart * 2, 0.0, 1.0)

        confidence = 0.6 * accord_l0 + 0.4 * market_confidence
        return probas, confidence

    def predict_with_uncertainty(
        self, X: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Retourne (probas, confidence, incertitude_relative).

        incertitude_relative = std(p_xgb, p_lgbm, p_cb) / mean  ∈ [0, 1] : c'est le
        DÉSACCORD entre les 3 modèles de base (incertitude épistémique). Sert à
        construire un intervalle de confiance autour de la proba finale : plus les
        modèles divergent sur un partant, plus la bande est large. Honnête : mesure
        un vrai désaccord, pas une marge inventée.
        """
        X_feat = X.reindex(columns=self.feature_names, fill_value=0).fillna(0)
        p_xgb, p_lgbm, p_cb = self._get_l0_predictions(X_feat)
        probas, confidence = self.predict_with_confidence(X)

        stack = np.stack([p_xgb, p_lgbm, p_cb], axis=1)
        std_l0 = stack.std(axis=1)
        mean_l0 = stack.mean(axis=1) + 1e-8
        rel_unc = np.clip(std_l0 / mean_l0, 0.0, 1.0)
        return probas, confidence, rel_unc

    def predict_win_proba(self, X: pd.DataFrame) -> Optional[np.ndarray]:
        """
        P(victoire) APPRISE par le modèle de victoire dédié (brute, non normalisée).
        Retourne None si le modèle de victoire n'est pas disponible (anciens pickles)
        → l'appelant retombe alors sur l'heuristique p3**gamma.
        """
        if self.win_model is None:
            return None
        X_feat = X.reindex(columns=self.feature_names, fill_value=0).fillna(0)
        try:
            return self.win_model.predict_proba(X_feat)[:, 1]
        except Exception as e:
            log.warning("model.predict_win_failed", err=str(e)[:140])
            return None

    def predict_rank_score(self, X: pd.DataFrame) -> Optional[np.ndarray]:
        """Score de ranking LambdaRank (plus haut = mieux classé). None si pas de
        ranker (vieux modèle / LightGBM indispo). Sert UNIQUEMENT au classement.
        """
        rk = getattr(self, "ranker", None)
        if rk is None:
            return None
        try:
            X_feat = X.reindex(columns=self.feature_names, fill_value=0).fillna(0)
            return np.asarray(rk.predict(X_feat), dtype=float)
        except Exception as e:
            log.warning("model.ranker.predict_failed", err=str(e)[:120])
            return None

    def _walk_forward_validation(self, X: pd.DataFrame, y: pd.Series, n_splits: int = 6,
                                 groups: Optional[pd.Series] = None) -> list[float]:
        """Walk-forward validation pour détecter l'instabilité du modèle.

        Si `groups` (course_id) fourni (FLAG group_split), les fenêtres expandantes
        sont découpées sur des COURSES entières — aucun cheval d'une course ne tombe
        à cheval sur train/test (sinon AUC walk-forward gonflé = gate de déploiement
        trop laxiste, cf. audit edge). Sans groups → découpage positionnel historique.
        """
        n = len(X)
        scores = []

        def _eval(tr_mask, te_mask) -> None:
            X_tr, y_tr = X[tr_mask], y[tr_mask]
            X_te, y_te = X[te_mask], y[te_mask]
            if y_te.nunique() < 2:
                return
            try:
                quick_xgb = XGBClassifier(
                    n_estimators=100, max_depth=4, learning_rate=0.1,
                    use_label_encoder=False, eval_metric="logloss", random_state=42, n_jobs=_N_JOBS,
                )
                quick_xgb.fit(X_tr, y_tr)
                p = quick_xgb.predict_proba(X_te)[:, 1]
                scores.append(float(roc_auc_score(y_te, p)))
            except Exception:
                pass

        if groups is not None:
            g = groups.to_numpy() if hasattr(groups, "to_numpy") else np.asarray(groups)
            courses_ordered = list(dict.fromkeys(g.tolist()))  # chrono
            nc = len(courses_ordered)
            if nc < 4:
                return [0.5]
            min_train_c = max(2, int(nc * 0.5))
            fold_c = max(1, (nc - min_train_c) // n_splits)
            for i in range(n_splits):
                tr_end = min_train_c + i * fold_c
                te_end = tr_end + fold_c
                if te_end > nc:
                    break
                tr_mask = np.isin(g, courses_ordered[:tr_end])
                te_mask = np.isin(g, courses_ordered[tr_end:te_end])
                _eval(tr_mask, te_mask)
            return scores if scores else [0.5]

        # Découpage positionnel historique (flag off)
        min_train = max(100, int(n * 0.5))
        fold_size = (n - min_train) // n_splits
        for i in range(n_splits):
            train_end = min_train + i * fold_size
            test_end = train_end + fold_size
            if test_end > n:
                break
            tr_mask = np.zeros(n, dtype=bool); tr_mask[:train_end] = True
            te_mask = np.zeros(n, dtype=bool); te_mask[train_end:test_end] = True
            _eval(tr_mask, te_mask)

        return scores if scores else [0.5]

    def _evaluate(self, X_test: pd.DataFrame, y_test: pd.Series,
                  course_ids: "pd.Series | None" = None) -> dict:
        """Métriques sur le set de test."""
        probas = self.predict_proba(X_test)

        auc = float(roc_auc_score(y_test, probas)) if y_test.nunique() > 1 else 0.5
        brier = float(brier_score_loss(y_test, probas))

        # Précision top-3 : pour chaque course, le top-3 IA contient-il le vrai gagnant ?
        prec_top3 = self._compute_precision_top3(X_test, y_test, probas, course_ids)

        # ROI simulé value bets (EV > 0.05)
        roi = self._simulate_roi(X_test, y_test, probas)

        return {
            "auc_roc": auc,
            "brier_score": brier,
            "precision_top3": prec_top3,
            "roi_simule": roi,
        }

    def _compute_precision_top3(self, X: pd.DataFrame, y: pd.Series, probas: np.ndarray,
                                course_ids: "pd.Series | None" = None) -> float:
        """Taux de courses où le top-3 IA inclut le gagnant réel.

        `course_id` est une colonne META retirée des features → la passer explicitement
        (sinon, absente de X, la fonction renvoyait toujours 0)."""
        cid = course_ids
        if cid is None and "course_id" in X.columns:
            cid = X["course_id"]
        if cid is None:
            return 0.0
        df = pd.DataFrame({
            "proba": np.asarray(probas),
            "label": np.asarray(y.values if hasattr(y, "values") else y),
            "course_id": np.asarray(cid),
        })

        correct = 0
        total = 0
        for _, group in df.groupby("course_id"):
            top3_ia = set(group.nlargest(3, "proba").index)
            gagnant = group.index[group["label"] == 1]
            if len(gagnant) > 0 and gagnant[0] in top3_ia:
                correct += 1
            total += 1

        return correct / total if total > 0 else 0.0

    # ROI sim : garde-fous anti-aberration (un seul outsider gagnant à grosse cote
    # sur un petit set faisait exploser le ROI ex. +602%, métadonnée non crédible).
    _ROI_MAX_COTE = 30.0   # au-delà : pari non réaliste en flat-stake, ignoré
    _ROI_MIN_BETS = 20     # sous ce nombre de value bets, ROI non significatif

    def _simulate_roi(self, X: pd.DataFrame, y: pd.Series, probas: np.ndarray) -> float:
        """
        Simule le ROI si on joue tous les value bets (EV > 0.05), en flat-stake.

        Garde-fous : on ignore les cotes > _ROI_MAX_COTE (bruit non tradeable) et on
        exige au moins _ROI_MIN_BETS paris, sinon le ROI n'est pas significatif et
        on renvoie 0.0 — on ne stocke jamais une valeur aberrante.
        """
        if "cote_pmu" not in X.columns:
            return 0.0

        mise_totale = 0.0
        gains_totaux = 0.0
        nb_bets = 0

        for proba, label, cote in zip(probas, y.values, X["cote_pmu"].values):
            if not cote or cote <= 1.0 or cote > self._ROI_MAX_COTE:
                continue
            ev = (cote * proba) - 1
            if ev > 0.05:
                mise = 1.0
                mise_totale += mise
                nb_bets += 1
                if label == 1:
                    gains_totaux += mise * cote

        if mise_totale == 0 or nb_bets < self._ROI_MIN_BETS:
            return 0.0
        return float((gains_totaux - mise_totale) / mise_totale)

    def save(self, version_num: int) -> Path:
        """Sauvegarde le modèle avec son numéro de version."""
        path = MODELS_DIR / f"model_v{version_num:04d}.pkl"
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

        with open(MODELS_DIR / "feature_names.json", "w") as f:
            json.dump(self.feature_names, f)

        log.info("model.saved", path=str(path))
        return path

    @classmethod
    def load(cls, path: Path) -> "BlackTurfEnsemble":
        with open(path, "rb") as f:
            model = pickle.load(f)
        log.info("model.loaded", path=str(path))
        return model

    @classmethod
    def load_current(cls) -> Optional["BlackTurfEnsemble"]:
        """Charge le modèle actif (pointeur current_model.pkl)."""
        current = MODELS_DIR / "current_model.pkl"
        if not current.exists():
            log.warning("model.no_current_model")
            return None
        return cls.load(current)

    def deploy(self, version_num: int) -> None:
        """Déploie ce modèle comme modèle actif."""
        import shutil
        path = self.save(version_num)
        current = MODELS_DIR / "current_model.pkl"
        shutil.copy2(path, current)
        log.info("model.deployed", version=version_num)


def build_training_dataset(
    features_list: list[dict], resultats: dict[str, dict]
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Construit X, y_top3 et y_win pour le training.
    resultats : {course_id: {cheval_id: position}}

    Retourne (X, y_top3, y_win) :
      - y_top3 = arrivé dans les 3 premiers (label historique de l'ensemble)
      - y_win  = arrivé 1er (label du modèle de VICTOIRE dédié)
    """
    rows = []
    labels_top3 = []
    labels_win = []

    for feat in features_list:
        cid = feat.get("course_id")
        if cid not in resultats:
            continue
        cheval_id = feat.get("cheval_id")
        pos = resultats[cid].get(cheval_id)
        if pos is None:
            continue

        rows.append(feat)
        labels_top3.append(int(pos <= 3 and pos > 0))
        labels_win.append(int(pos == 1))

    if not rows:
        empty = pd.Series([], dtype=int)
        return pd.DataFrame(), empty, empty

    X = pd.DataFrame(rows)
    return X, pd.Series(labels_top3, name="label"), pd.Series(labels_win, name="win")
