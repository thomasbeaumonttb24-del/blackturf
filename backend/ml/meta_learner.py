"""
MetaLearner — Modèle de méta-apprentissage pour la correction des prédictions BlackTurf.

Ce module implémente un méta-apprenant LightGBM qui apprend les biais systématiques
du modèle de base et corrige ses prédictions de probabilité.

Architecture :
  - MetaLearner : LightGBM entraîné sur l'historique des prédictions vs résultats réels.
    Prend en entrée la proba du modèle de base + features contextuelles.
    Retourne une proba corrigée dans [0, 1].

  - ContextualCorrector : Correcteur plus simple basé sur des lookup tables.
    Utilisé comme fallback quand MetaLearner n'a pas assez de données.

Flux d'entraînement :
  1. Requête sur race_learning_log (6 derniers mois) + predictions + courses
  2. Construction des features : proba_base + contexte (discipline, terrain, etc.)
  3. Label = top3_precision (le modèle a-t-il placé le gagnant dans son top-3 ?)
  4. Entraînement LightGBM avec validation croisée
  5. Persistance pickle sur /app/models/meta_learner.pkl

Persistance :
  - save(path) / load(path) via pickle
  - Singleton global via get_meta_learner() / initialize_meta_learner(session)
"""
from __future__ import annotations

import math
import pickle
import structlog
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="meta_learner")

# ── Constantes ──────────────────────────────────────────────────────────────
META_LEARNER_PATH = Path("/app/models/meta_learner.pkl")
MIN_SAMPLES_TO_TRAIN = 200
TRAINING_WINDOW_MONTHS = 6

# Encodages catégoriels déterministes (hash stable) pour éviter une dépendance
# sklearn LabelEncoder au moment de l'inférence.
_DISCIPLINE_MAP: dict[str, int] = {
    "Plat": 0,
    "Haies": 1,
    "Steeple": 2,
    "Attelé": 3,
    "Monté": 4,
}
_TERRAIN_MAP: dict[str, int] = {
    "Bon": 0,
    "Bon souple": 1,
    "Souple": 2,
    "Très souple": 3,
    "Lourd": 4,
    "Collant": 5,
    "Ferme": 6,
    "Bon ferme": 7,
    "Très bon": 8,
}

# Heures de la journée buckétisées
_MORNING_HOURS = set(range(6, 12))    # 6h–11h
_AFTERNOON_HOURS = set(range(12, 18))  # 12h–17h
_EVENING_HOURS = set(range(18, 24))   # 18h–23h

# Distances typiques par discipline (en mètres) : [min_normal, max_normal]
_DISCIPLINE_DIST_NORMAL: dict[str, tuple[int, int]] = {
    "Plat": (1000, 3200),
    "Haies": (2700, 4500),
    "Steeple": (3500, 6000),
    "Attelé": (1700, 3200),
    "Monté": (1700, 3200),
}


def _encode_discipline(discipline: Optional[str]) -> int:
    """Encode la discipline en entier. Retourne -1 si inconnue."""
    if not discipline:
        return -1
    return _DISCIPLINE_MAP.get(discipline.strip(), -1)


def _encode_terrain(terrain: Optional[str]) -> int:
    """Encode le terrain en entier. Retourne -1 si inconnu."""
    if not terrain:
        return -1
    return _TERRAIN_MAP.get(terrain.strip(), -1)


def _encode_hippodrome(hippodrome: Optional[str]) -> int:
    """Encode le nom d'hippodrome en hash entier stable [0, 999]."""
    if not hippodrome:
        return -1
    return hash(hippodrome.strip().lower()) % 1000


def _build_feature_vector(base_proba: float, context: dict) -> list[float]:
    """
    Construit le vecteur de features pour le méta-apprenant.

    Parameters
    ----------
    base_proba:
        Probabilité brute du modèle de base (float dans [0, 1]).
    context:
        Dictionnaire avec les clés contextuelles suivantes (toutes optionnelles) :
          - discipline (str)
          - terrain (str)
          - hippodrome (str)
          - nb_partants (int)
          - hour_of_day (int, 0–23)
          - est_quinte (bool/int)
          - jours_repos (int)
          - cote_pmu (float)
          - rang_cote (int)
          - elo_vs_moyenne (float)
          - forme_5_courses (float)
          - spi_score (float)
          - season_month (int, 1–12)

    Returns
    -------
    list[float]
        Vecteur de 14 features numériques.
    """
    discipline_enc = float(_encode_discipline(context.get("discipline")))
    terrain_enc = float(_encode_terrain(context.get("terrain")))
    hippodrome_enc = float(_encode_hippodrome(context.get("hippodrome")))

    nb_partants = float(context.get("nb_partants") or 8)
    hour_of_day = float(context.get("hour_of_day") or 14)
    est_quinte = float(1 if context.get("est_quinte") else 0)
    jours_repos = float(context.get("jours_repos") or 30)
    cote_pmu = float(context.get("cote_pmu") or 5.0)
    rang_cote = float(context.get("rang_cote") or 5)
    elo_vs_moyenne = float(context.get("elo_vs_moyenne") or 0.0)
    forme_5_courses = float(context.get("forme_5_courses") or 0.5)
    spi_score = float(context.get("spi_score") or 0.0)
    season_month = float(context.get("season_month") or 6)

    return [
        float(base_proba),
        discipline_enc,
        terrain_enc,
        hippodrome_enc,
        nb_partants,
        hour_of_day,
        est_quinte,
        jours_repos,
        cote_pmu,
        rang_cote,
        elo_vs_moyenne,
        forme_5_courses,
        spi_score,
        season_month,
    ]


FEATURE_NAMES = [
    "base_proba",
    "discipline_enc",
    "terrain_enc",
    "hippodrome_enc",
    "nb_partants",
    "hour_of_day",
    "est_quinte",
    "jours_repos",
    "cote_pmu",
    "rang_cote",
    "elo_vs_moyenne",
    "forme_5_courses",
    "spi_score",
    "season_month",
]


# ── MetaLearner ──────────────────────────────────────────────────────────────

class MetaLearner:
    """
    Méta-apprenant LightGBM pour la correction des probabilités du modèle de base.

    Apprend les biais systématiques (par discipline, terrain, hippodrome, heure, etc.)
    et retourne des probabilités corrigées.

    Attributs
    ---------
    _model :
        Instance LGBMClassifier entraînée (None tant que non entraîné).
    _trained_at :
        Datetime du dernier entraînement.
    _n_samples :
        Nombre d'exemples utilisés lors du dernier entraînement.
    _metrics :
        Métriques du dernier entraînement (auc, logloss, n_samples).
    """

    def __init__(self) -> None:
        self._model = None
        self._trained_at: Optional[datetime] = None
        self._n_samples: int = 0
        self._metrics: dict = {}

    @property
    def is_trained(self) -> bool:
        """Retourne True si le modèle a été entraîné et est prêt à faire des prédictions."""
        return self._model is not None

    async def train(self, session: AsyncSession) -> dict:
        """
        Entraîne le méta-apprenant sur les 6 derniers mois de données.

        Requête sur race_learning_log JOIN predictions JOIN courses JOIN participations
        pour construire les features contextuelles + proba de base.

        Le label est top3_precision (booléen : le vrai gagnant était-il dans le top-3
        prédit par le modèle de base ?).

        Parameters
        ----------
        session :
            Session SQLAlchemy asyncrone.

        Returns
        -------
        dict
            Métriques du training : n_samples, auc_roc, logloss, trained_at.
            Si moins de MIN_SAMPLES_TO_TRAIN exemples disponibles, retourne
            {"status": "insufficient_data", "n_samples": <n>}.
        """
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            log.error("meta_learner.lgbm_not_installed")
            return {"status": "error", "message": "lightgbm not installed"}

        cutoff = datetime.utcnow() - timedelta(days=30 * TRAINING_WINDOW_MONTHS)

        log.info("meta_learner.train_start", cutoff=cutoff.isoformat())

        # ── Requête principale ───────────────────────────────────────────────
        # On joint race_learning_log (contexte + label top3_precision)
        # avec predictions (proba de base)
        # et courses (date_heure pour heure_of_day + est_quinte + distance)
        # et participations (cote_pmu, rang_pronostic_pmu)
        # et elo_history pour elo_vs_moyenne via la snapshot dans feature_autopsy
        # (ou on se contente des colonnes disponibles dans rll + pred)
        try:
            result = await session.execute(text("""
                SELECT
                    rll.course_id,
                    (rll.gagnant_rang_predit <= 3)  AS top3_precision,
                    rll.gagnant_proba_ia            AS base_proba,
                    rll.discipline,
                    rll.terrain,
                    rll.hippodrome,
                    rll.nb_partants,
                    rll.brier_score                 AS brier_course,
                    rll.was_surprise,
                    c.date_heure,
                    c.est_quinte,
                    c.distance,
                    -- Features agrégées au niveau course (moyennes / médianes partants)
                    AVG(p.cote_pmu)              AS avg_cote_pmu,
                    MIN(p.cote_pmu)              AS min_cote_pmu,
                    AVG(p.rang_pronostic_pmu)    AS avg_rang_cote,
                    -- Proba min cote = favori (rang=1) → approximation rang_cote pour le gagnant
                    (SELECT pr2.cote_pmu
                     FROM participations pr2
                     WHERE pr2.course_id = rll.course_id
                       AND pr2.rang_pronostic_pmu = 1
                     LIMIT 1)                   AS favori_cote
                FROM race_learning_log rll
                JOIN courses c ON c.course_id = rll.course_id
                JOIN participations p ON p.course_id = rll.course_id
                WHERE rll.analyzed_at >= :cutoff
                  AND rll.gagnant_rang_predit IS NOT NULL
                  AND rll.gagnant_proba_ia IS NOT NULL
                GROUP BY
                    rll.course_id,
                    rll.gagnant_rang_predit,
                    rll.gagnant_proba_ia,
                    rll.discipline,
                    rll.terrain,
                    rll.hippodrome,
                    rll.nb_partants,
                    rll.brier_score,
                    rll.was_surprise,
                    c.date_heure,
                    c.est_quinte,
                    c.distance
                ORDER BY c.date_heure ASC
            """), {"cutoff": cutoff})
            rows = result.fetchall()
        except Exception as e:
            log.error("meta_learner.train_query_error", err=str(e))
            return {"status": "error", "message": str(e)}

        n_samples = len(rows)
        log.info("meta_learner.train_data_fetched", n_samples=n_samples)

        if n_samples < MIN_SAMPLES_TO_TRAIN:
            log.warning(
                "meta_learner.insufficient_data",
                n_samples=n_samples,
                min_required=MIN_SAMPLES_TO_TRAIN,
            )
            return {
                "status": "insufficient_data",
                "n_samples": n_samples,
                "min_required": MIN_SAMPLES_TO_TRAIN,
            }

        # ── Construction de X et y ───────────────────────────────────────────
        X_list: list[list[float]] = []
        y_list: list[int] = []

        for row in rows:
            (
                _course_id,
                top3_precision,
                base_proba,
                discipline,
                terrain,
                hippodrome,
                nb_partants,
                _brier,
                _was_surprise,
                date_heure,
                est_quinte,
                distance,
                _avg_cote,
                _min_cote,
                _avg_rang,
                _favori_cote,
            ) = row

            if base_proba is None:
                continue

            # Heure de la journée
            hour_of_day = date_heure.hour if date_heure else 14

            # Mois de la saison
            season_month = date_heure.month if date_heure else 6

            # Rang de cote : on approxime avec rang_pronostic moyen → non dispo ici
            # On utilise une estimation : si proba_base est haute → petit rang
            rang_cote = max(1, round(1.0 / max(float(base_proba), 0.01) * 0.5))
            rang_cote = min(rang_cote, 20)

            # Mismatch distance/discipline
            dist_ok = _distance_normal_for_discipline(discipline, distance)
            spi_score = 0.0  # Non disponible à ce niveau agrégé

            context = {
                "discipline": discipline,
                "terrain": terrain,
                "hippodrome": hippodrome,
                "nb_partants": nb_partants or 8,
                "hour_of_day": hour_of_day,
                "est_quinte": bool(est_quinte),
                "jours_repos": 20,  # Non disponible au niveau course → valeur neutre
                "cote_pmu": _min_cote or 5.0,  # cote du favori ≈ min cote
                "rang_cote": rang_cote,
                "elo_vs_moyenne": 0.0,  # Non disponible ici
                "forme_5_courses": 0.5,
                "spi_score": spi_score,
                "season_month": season_month,
                # extra feature pour distance mismatch
                "_distance_mismatch": float(not dist_ok),
            }

            feat = _build_feature_vector(float(base_proba), context)
            # Ajouter distance_mismatch comme 15e feature
            feat.append(float(not dist_ok))

            X_list.append(feat)
            y_list.append(int(bool(top3_precision)))

        if len(X_list) < MIN_SAMPLES_TO_TRAIN:
            return {
                "status": "insufficient_data",
                "n_samples": len(X_list),
                "min_required": MIN_SAMPLES_TO_TRAIN,
            }

        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list, dtype=np.int32)

        # ── Split temporel 80/20 ─────────────────────────────────────────────
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        pos_rate = float(y_train.mean()) if len(y_train) > 0 else 0.5
        scale_pos_weight = (1.0 - pos_rate) / max(pos_rate, 1e-6)

        log.info(
            "meta_learner.train_split",
            n_train=len(X_train),
            n_val=len(X_val),
            pos_rate=round(pos_rate, 3),
        )

        # ── Entraînement LightGBM ────────────────────────────────────────────
        feature_names_ext = FEATURE_NAMES + ["distance_mismatch"]

        model = LGBMClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=10,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            verbose=-1,
            n_jobs=-1,
        )

        try:
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                feature_name=feature_names_ext,
                callbacks=[],
            )
        except TypeError:
            # Ancienne API LightGBM sans feature_name dans fit
            model.fit(X_train, y_train)

        # ── Métriques de validation ──────────────────────────────────────────
        metrics = _compute_validation_metrics(model, X_val, y_val)
        metrics["n_samples"] = len(X)
        metrics["n_train"] = len(X_train)
        metrics["n_val"] = len(X_val)
        metrics["pos_rate"] = round(pos_rate, 4)
        metrics["trained_at"] = datetime.utcnow().isoformat()

        self._model = model
        self._trained_at = datetime.utcnow()
        self._n_samples = len(X)
        self._metrics = metrics

        log.info(
            "meta_learner.train_complete",
            n_samples=len(X),
            auc=metrics.get("auc_roc"),
            logloss=metrics.get("log_loss"),
        )

        return {"status": "ok", **metrics}

    def predict_correction(self, base_proba: float, context: dict) -> float:
        """
        Retourne la probabilité corrigée par le méta-apprenant.

        Si le modèle n'est pas entraîné, retourne base_proba tel quel.

        Parameters
        ----------
        base_proba :
            Probabilité brute du modèle de base (float dans [0, 1]).
        context :
            Dictionnaire de features contextuelles (voir _build_feature_vector).

        Returns
        -------
        float
            Probabilité corrigée dans [0.01, 0.99].
        """
        if not self.is_trained:
            return float(base_proba)

        try:
            feat = _build_feature_vector(base_proba, context)
            feat.append(float(context.get("_distance_mismatch", 0.0)))
            X = np.array([feat], dtype=np.float32)
            proba_corrected = float(self._model.predict_proba(X)[0, 1])
            # Blend correction : moyenne pondérée entre base et meta
            # (évite les sauts brutaux en cas d'extrapolation)
            blended = 0.4 * float(base_proba) + 0.6 * proba_corrected
            return float(np.clip(blended, 0.01, 0.99))
        except Exception as e:
            log.warning("meta_learner.predict_error", err=str(e))
            return float(base_proba)

    def predict_corrections_batch(
        self,
        base_probas: list[float],
        contexts: list[dict],
    ) -> list[float]:
        """
        Applique la correction à une liste de probabilités et contextes.

        Parameters
        ----------
        base_probas :
            Liste de probabilités brutes du modèle de base.
        contexts :
            Liste de dictionnaires contextuels (un par proba).

        Returns
        -------
        list[float]
            Liste de probabilités corrigées dans [0.01, 0.99].
        """
        if not self.is_trained:
            return [float(p) for p in base_probas]

        if len(base_probas) != len(contexts):
            log.error(
                "meta_learner.batch_size_mismatch",
                n_probas=len(base_probas),
                n_contexts=len(contexts),
            )
            return [float(p) for p in base_probas]

        if not base_probas:
            return []

        try:
            X_list = []
            for proba, ctx in zip(base_probas, contexts):
                feat = _build_feature_vector(proba, ctx)
                feat.append(float(ctx.get("_distance_mismatch", 0.0)))
                X_list.append(feat)

            X = np.array(X_list, dtype=np.float32)
            probas_corrected = self._model.predict_proba(X)[:, 1]

            results = []
            for base_p, corr_p in zip(base_probas, probas_corrected):
                blended = 0.4 * float(base_p) + 0.6 * float(corr_p)
                results.append(float(np.clip(blended, 0.01, 0.99)))
            return results
        except Exception as e:
            log.warning("meta_learner.batch_predict_error", err=str(e))
            return [float(p) for p in base_probas]

    def save(self, path: Optional[Path] = None) -> Path:
        """
        Sérialise le méta-apprenant avec pickle.

        Parameters
        ----------
        path :
            Chemin de sauvegarde. Utilise META_LEARNER_PATH si None.

        Returns
        -------
        Path
            Chemin effectif de sauvegarde.
        """
        save_path = Path(path) if path else META_LEARNER_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("meta_learner.saved", path=str(save_path), n_samples=self._n_samples)
        return save_path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "MetaLearner":
        """
        Désérialise un MetaLearner depuis un fichier pickle.

        Parameters
        ----------
        path :
            Chemin du fichier pickle. Utilise META_LEARNER_PATH si None.

        Returns
        -------
        MetaLearner
            Instance chargée.

        Raises
        ------
        FileNotFoundError
            Si le fichier n'existe pas.
        """
        load_path = Path(path) if path else META_LEARNER_PATH
        with open(load_path, "rb") as f:
            instance = pickle.load(f)
        log.info(
            "meta_learner.loaded",
            path=str(load_path),
            trained_at=instance._trained_at,
            n_samples=instance._n_samples,
        )
        return instance

    def get_summary(self) -> dict:
        """Retourne un résumé de l'état du méta-apprenant."""
        return {
            "is_trained": self.is_trained,
            "trained_at": self._trained_at.isoformat() if self._trained_at else None,
            "n_samples": self._n_samples,
            "metrics": self._metrics,
        }


# ── ContextualCorrector ──────────────────────────────────────────────────────

class ContextualCorrector:
    """
    Correcteur contextuel simplifié — fallback quand MetaLearner manque de données.

    Combine trois corrections additives :
      1. Biais de la bias_matrix DB (contexte discipline × terrain × hippodrome).
      2. Correction heure de la journée (matin → favoris sous-performent).
      3. Correction taille du champ (> 16 partants → favoris surcotés).

    Ces corrections sont additives (multipliées à la proba de base) et plafonnées
    pour rester dans [0.01, 0.99].

    Lookup tables
    -------------
    TIME_CORRECTIONS :
        Matin (< 12h) : -0.04 pour les favoris (proba > 0.35), 0 sinon.
        Après-midi : neutre.
        Soir : légèrement positif pour les longshots (proba < 0.10).

    FIELD_SIZE_CORRECTIONS :
        nb_partants > 16 → favoris (proba > 0.40) : -0.05 (cotes gonflées).
        nb_partants > 16 → outsiders (proba < 0.10) : +0.02 (plus d'opportunités).
        nb_partants <= 8 → favoris : +0.02 (domination renforcée en petit champ).

    DISTANCE_MISMATCH_CORRECTIONS :
        distance inhabituelle pour la discipline → -0.03 sur toute proba > 0.20.
    """

    # ── Lookup table 1 : heure de la journée ────────────────────────────────
    # Format : (heure_min_inclusif, heure_max_exclusif, proba_seuil_favori, correction)
    TIME_CORRECTIONS: list[tuple[int, int, float, float]] = [
        # Matin : favoris sous-performent
        (6, 12, 0.35, -0.04),
        # Soirée : longshots légèrement avantagés (favoris sous pression)
        (18, 24, 0.10, +0.015),
    ]

    # ── Lookup table 2 : taille du champ ────────────────────────────────────
    # Format : (nb_partants_min, nb_partants_max, condition, proba_seuil, correction)
    # condition : "gt" (proba > seuil) ou "lt" (proba < seuil)
    FIELD_CORRECTIONS: list[tuple[int, int, str, float, float]] = [
        # Grand champ (> 16) : favoris surcotés → correction négative
        (17, 999, "gt", 0.40, -0.05),
        # Grand champ : outsiders légèrement favorisés
        (17, 999, "lt", 0.10, +0.02),
        # Petit champ (<= 8) : favoris renforcés
        (0, 8, "gt", 0.35, +0.02),
    ]

    def get_correction(
        self,
        base_proba: float,
        context: dict,
        bias_correction: float,
    ) -> float:
        """
        Retourne la probabilité corrigée par les lookup tables + biais DB.

        Parameters
        ----------
        base_proba :
            Probabilité brute du modèle de base (float dans [0, 1]).
        context :
            Dictionnaire contextuel avec au minimum :
              - hour_of_day (int)
              - nb_partants (int)
              - discipline (str)
              - distance (int, optionnel)
        bias_correction :
            Facteur de correction issu de bias_matrix DB (-0.15 à +0.15).

        Returns
        -------
        float
            Probabilité corrigée dans [0.01, 0.99].
        """
        p = float(base_proba)
        hour = int(context.get("hour_of_day") or 14)
        nb_partants = int(context.get("nb_partants") or 8)
        discipline = context.get("discipline", "")
        distance = int(context.get("distance") or 0)

        # ── 1. Correction bias_matrix ────────────────────────────────────────
        if bias_correction != 0.0:
            p = p * (1.0 + bias_correction)

        # ── 2. Correction heure de la journée ────────────────────────────────
        time_delta = self._time_of_day_correction(hour, p)
        p = p + time_delta

        # ── 3. Correction taille du champ ────────────────────────────────────
        field_delta = self._field_size_correction(nb_partants, p)
        p = p + field_delta

        # ── 4. Correction mismatch distance/discipline ────────────────────────
        if distance and discipline:
            dist_delta = self._distance_mismatch_correction(discipline, distance, p)
            p = p + dist_delta

        return float(np.clip(p, 0.01, 0.99))

    def _time_of_day_correction(self, hour: int, proba: float) -> float:
        """
        Applique la correction heure de la journée.

        Les courses du matin voient les favoris (proba > 0.35) systématiquement
        sous-performer par rapport à l'après-midi : biais de "morning wobble"
        (moins de liquidité, cotes moins représentatives).
        """
        for h_min, h_max, seuil, correction in self.TIME_CORRECTIONS:
            if h_min <= hour < h_max:
                # correction négative pour les favoris en cas de heure_min=6
                if correction < 0 and proba > seuil:
                    return correction
                # correction positive pour les longshots en soirée
                elif correction > 0 and proba < seuil:
                    return correction
        return 0.0

    def _field_size_correction(self, nb_partants: int, proba: float) -> float:
        """
        Applique la correction taille du champ.

        Dans les grands champs (> 16), les probabilités des favoris sont
        systématiquement surestimées car les modèles entraînés sur des courses
        moyennes (8-12 partants) n'extrapolent pas bien.
        """
        for n_min, n_max, condition, seuil, correction in self.FIELD_CORRECTIONS:
            if n_min <= nb_partants <= n_max:
                if condition == "gt" and proba > seuil:
                    return correction
                elif condition == "lt" and proba < seuil:
                    return correction
        return 0.0

    def _distance_mismatch_correction(
        self, discipline: str, distance: int, proba: float
    ) -> float:
        """
        Pénalise les chevaux à proba élevée courant une distance inhabituelle
        pour leur discipline (ex: Plat sur 4000m, Steeple sur 2000m).
        """
        if proba <= 0.20:
            return 0.0
        if not _distance_normal_for_discipline(discipline, distance):
            return -0.03
        return 0.0


# ── Helpers privés ───────────────────────────────────────────────────────────

def _distance_normal_for_discipline(
    discipline: Optional[str], distance: Optional[int]
) -> bool:
    """
    Retourne True si la distance est normale pour la discipline donnée.

    Parameters
    ----------
    discipline :
        Nom de la discipline (Plat, Haies, Steeple, Attelé, Monté).
    distance :
        Distance en mètres.

    Returns
    -------
    bool
        True si la distance est dans la plage normale.
    """
    if not discipline or not distance:
        return True
    bounds = _DISCIPLINE_DIST_NORMAL.get(discipline.strip())
    if not bounds:
        return True
    return bounds[0] <= distance <= bounds[1]


def _compute_validation_metrics(model, X_val: np.ndarray, y_val: np.ndarray) -> dict:
    """
    Calcule AUC-ROC et log-loss sur le set de validation.

    Parameters
    ----------
    model :
        Modèle LightGBM entraîné.
    X_val :
        Features de validation.
    y_val :
        Labels de validation.

    Returns
    -------
    dict
        {"auc_roc": float, "log_loss": float}
    """
    if len(X_val) == 0 or len(np.unique(y_val)) < 2:
        return {"auc_roc": None, "log_loss": None}

    try:
        from sklearn.metrics import roc_auc_score, log_loss
        probas = model.predict_proba(X_val)[:, 1]
        auc = float(roc_auc_score(y_val, probas))
        ll = float(log_loss(y_val, probas))
        return {"auc_roc": round(auc, 4), "log_loss": round(ll, 4)}
    except Exception as e:
        log.warning("meta_learner.metrics_error", err=str(e))
        return {"auc_roc": None, "log_loss": None}


# ── Singleton ────────────────────────────────────────────────────────────────

_meta_learner_instance: Optional[MetaLearner] = None
_contextual_corrector_instance: Optional[ContextualCorrector] = None


def get_meta_learner() -> MetaLearner:
    """
    Retourne l'instance singleton de MetaLearner.

    Crée l'instance si elle n'existe pas encore.
    Tente de charger le modèle depuis META_LEARNER_PATH si disponible.

    Returns
    -------
    MetaLearner
        Instance singleton.
    """
    global _meta_learner_instance
    if _meta_learner_instance is None:
        _meta_learner_instance = MetaLearner()
        # Tentative de chargement automatique depuis le disque
        if META_LEARNER_PATH.exists():
            try:
                _meta_learner_instance = MetaLearner.load(META_LEARNER_PATH)
                log.info("meta_learner.auto_loaded", path=str(META_LEARNER_PATH))
            except Exception as e:
                log.warning("meta_learner.auto_load_failed", err=str(e))
    return _meta_learner_instance


def get_contextual_corrector() -> ContextualCorrector:
    """
    Retourne l'instance singleton de ContextualCorrector.

    Returns
    -------
    ContextualCorrector
        Instance singleton.
    """
    global _contextual_corrector_instance
    if _contextual_corrector_instance is None:
        _contextual_corrector_instance = ContextualCorrector()
    return _contextual_corrector_instance


async def initialize_meta_learner(session: AsyncSession) -> MetaLearner:
    """
    Initialise le MetaLearner au démarrage de l'application.

    Tente d'abord de charger le modèle depuis le disque. Si absent ou corrompu,
    lance un entraînement immédiat. Si insuffisamment de données, retourne
    un MetaLearner vide (non entraîné).

    Parameters
    ----------
    session :
        Session SQLAlchemy asyncrone.

    Returns
    -------
    MetaLearner
        Instance initialisée (potentiellement non entraînée).
    """
    global _meta_learner_instance
    ml = get_meta_learner()

    if ml.is_trained:
        log.info(
            "meta_learner.already_initialized",
            trained_at=ml._trained_at,
            n_samples=ml._n_samples,
        )
        return ml

    # Pas de modèle chargé → tenter un entraînement à froid
    log.info("meta_learner.cold_start_training")
    result = await ml.train(session)

    if result.get("status") == "ok":
        try:
            ml.save()
        except Exception as e:
            log.warning("meta_learner.save_failed_on_init", err=str(e))

    _meta_learner_instance = ml
    return ml
