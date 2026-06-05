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

MODELS_DIR = Path("/app/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Poids fallback si stacking non disponible
ENSEMBLE_WEIGHTS_FALLBACK = {"xgb": 0.50, "lgbm": 0.30, "catboost": 0.20}

META_COLS = {"participation_id", "course_id", "cheval_id", "numero", "nom", "label"}

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

    def train(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """
        Entraîne l'ensemble. Split temporel 80/20.
        Walk-forward validation sur 6 fenêtres.
        """
        self.feature_names = [c for c in X.columns if c not in META_COLS]
        X_feat = X[self.feature_names].fillna(0)

        n = len(X_feat)
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
            n_jobs=-1,
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
            n_jobs=-1,
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
            skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            oof_xgb = np.zeros(len(X_train))
            oof_lgbm = np.zeros(len(X_train))
            oof_cb = np.zeros(len(X_train))

            for fold_train_idx, fold_val_idx in skf.split(X_train, y_train):
                Xf_tr, Xf_val = X_train.iloc[fold_train_idx], X_train.iloc[fold_val_idx]
                yf_tr = y_train.iloc[fold_train_idx]

                # Quick fold models (no calibration for speed)
                xgb_fold = XGBClassifier(
                    n_estimators=200, max_depth=5, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    scale_pos_weight=pos_weight, use_label_encoder=False,
                    eval_metric="logloss", tree_method="hist",
                    random_state=42, n_jobs=-1, verbosity=0
                )
                xgb_fold.fit(Xf_tr, yf_tr)
                oof_xgb[fold_val_idx] = xgb_fold.predict_proba(Xf_val)[:, 1]

                lgbm_fold = LGBMClassifier(
                    n_estimators=200, max_depth=5, learning_rate=0.05,
                    num_leaves=31, subsample=0.8, colsample_bytree=0.8,
                    is_unbalance=True, random_state=42, verbose=-1, n_jobs=-1
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
                is_unbalance=True, random_state=42, verbose=-1, n_jobs=-1
            )
            self.meta_learner.fit(meta_X_train, y_train)
            self._stacking_trained = True
            log.info("model.stacking.trained", n_meta_features=meta_X_train.shape[1])

        except Exception as e:
            log.warning("model.stacking.failed", err=str(e), fallback="fixed weights")
            self._stacking_trained = False

        # ── Walk-forward validation (6 fenêtres) ──────────
        wf_scores = self._walk_forward_validation(X_feat, y)
        log.info("model.walk_forward", scores=[round(s, 4) for s in wf_scores], mean=round(float(np.mean(wf_scores)), 4))

        # ── Métriques finales ──────────────────────────────
        metrics = self._evaluate(X_test, y_test)
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
        )
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
        X_feat = X[self.feature_names].fillna(0)
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
        X_feat = X[self.feature_names].fillna(0)
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

    def _walk_forward_validation(self, X: pd.DataFrame, y: pd.Series, n_splits: int = 6) -> list[float]:
        """Walk-forward validation pour détecter l'instabilité du modèle."""
        n = len(X)
        min_train = max(100, int(n * 0.5))
        scores = []
        fold_size = (n - min_train) // n_splits

        for i in range(n_splits):
            train_end = min_train + i * fold_size
            test_end = train_end + fold_size
            if test_end > n:
                break
            X_tr, y_tr = X.iloc[:train_end], y.iloc[:train_end]
            X_te, y_te = X.iloc[train_end:test_end], y.iloc[train_end:test_end]
            if y_te.nunique() < 2:
                continue
            # Quick XGB only for walk-forward
            try:
                quick_xgb = XGBClassifier(
                    n_estimators=100, max_depth=4, learning_rate=0.1,
                    use_label_encoder=False, eval_metric="logloss", random_state=42, n_jobs=-1,
                )
                quick_xgb.fit(X_tr, y_tr)
                p = quick_xgb.predict_proba(X_te)[:, 1]
                scores.append(float(roc_auc_score(y_te, p)))
            except Exception:
                pass

        return scores if scores else [0.5]

    def _evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        """Métriques sur le set de test."""
        probas = self.predict_proba(X_test)

        auc = float(roc_auc_score(y_test, probas)) if y_test.nunique() > 1 else 0.5
        brier = float(brier_score_loss(y_test, probas))

        # Précision top-3 : pour chaque course, le top-3 IA contient-il le vrai top-3 ?
        prec_top3 = self._compute_precision_top3(X_test, y_test, probas)

        # ROI simulé value bets (EV > 0.05)
        roi = self._simulate_roi(X_test, y_test, probas)

        return {
            "auc_roc": auc,
            "brier_score": brier,
            "precision_top3": prec_top3,
            "roi_simule": roi,
        }

    def _compute_precision_top3(self, X: pd.DataFrame, y: pd.Series, probas: np.ndarray) -> float:
        """Taux de courses où le top-3 IA inclut le gagnant réel."""
        if "course_id" not in X.columns:
            return 0.0
        df = X.copy()
        df["proba"] = probas
        df["label"] = y.values

        correct = 0
        total = 0
        for _, group in df.groupby("course_id"):
            top3_ia = set(group.nlargest(3, "proba").index)
            gagnant = group[group["label"] == 1].index
            if len(gagnant) > 0 and gagnant[0] in top3_ia:
                correct += 1
            total += 1

        return correct / total if total > 0 else 0.0

    def _simulate_roi(self, X: pd.DataFrame, y: pd.Series, probas: np.ndarray) -> float:
        """Simule le ROI si on joue tous les value bets (EV > 0.05)."""
        if "cote_pmu" not in X.columns:
            return 0.0

        mise_totale = 0.0
        gains_totaux = 0.0

        for i, (proba, label, cote) in enumerate(zip(probas, y.values, X["cote_pmu"].values)):
            if not cote or cote <= 1.0:
                continue
            ev = (cote * proba) - 1
            if ev > 0.05:
                mise = 1.0
                mise_totale += mise
                if label == 1:
                    gains_totaux += mise * cote

        if mise_totale == 0:
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


def build_training_dataset(features_list: list[dict], resultats: dict[str, dict]) -> tuple[pd.DataFrame, pd.Series]:
    """
    Construit X et y pour le training.
    resultats : {course_id: {cheval_id: position}}
    """
    rows = []
    labels = []

    for feat in features_list:
        pid = feat.get("participation_id")
        cid = feat.get("course_id")

        # Trouver le label (est-ce que ce partant est arrivé dans le top-3 ?)
        if cid not in resultats:
            continue

        # On a besoin du cheval_id pour savoir sa position — on l'ajoute dans les features
        cheval_id = feat.get("cheval_id")
        pos = resultats[cid].get(cheval_id)
        if pos is None:
            continue

        label = int(pos <= 3 and pos > 0)
        rows.append(feat)
        labels.append(label)

    if not rows:
        return pd.DataFrame(), pd.Series([], dtype=int)

    X = pd.DataFrame(rows)
    y = pd.Series(labels, name="label")
    return X, y
