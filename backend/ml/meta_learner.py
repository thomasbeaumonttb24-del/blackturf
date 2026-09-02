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

import hashlib
import json
import math
import pickle
import structlog
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.models import _N_JOBS

log = structlog.get_logger(module="meta_learner")

# ── Constantes ──────────────────────────────────────────────────────────────
META_LEARNER_PATH = Path("/app/models/meta_learner.pkl")
# Le méta-apprenant s'entraîne sur des PARTANTS, pas sur des courses : ~10 lignes
# par course, donc 200 exemples valaient une vingtaine de courses. Trop peu pour
# qu'un correcteur contextuel signifie quoi que ce soit — le seuil porte désormais
# sur la bonne unité.
MIN_SAMPLES_TO_TRAIN = 2000
TRAINING_WINDOW_MONTHS = 6
# Poids de la proba de BASE dans le mélange final. Le méta-apprenant est un
# correcteur, pas un second modèle : il ne remplace jamais la proba, il l'infléchit.
# Nommé ici parce que le gate d'utilité DOIT juger le mélange réellement servi, et
# non la sortie brute du correcteur.
META_BLEND_BASE = 0.4
# CONTRAT D'ENTRAÎNEMENT — identifie CE QUE le modèle a appris, pas sa version de
# code. Il est écrit dans le pickle et vérifié au chargement.
#
# Sans lui, le déploiement de cette correction aurait été inopérant : le pickle
# resté sur disque a été entraîné par PARTANT ? Non — par COURSE, avec un autre
# label, une autre entrée et six features constantes. `get_meta_learner()` le
# recharge au démarrage de l'API ; il aurait donc continué à corriger les probas
# exactement comme avant, silencieusement, jusqu'au premier retrain réussi — et
# indéfiniment si le gate d'utilité le rejette.
#
# À incrémenter à CHAQUE changement de la nature des exemples (label, entrée,
# vecteur de features). Pas pour un simple réglage d'hyperparamètre.
TRAINING_CONTRACT = "partant/top3/base=isotone+temperature/v1"

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


# Lookup INSENSIBLE À LA CASSE : race_learning_log stocke discipline/terrain en
# minuscules (post_race fait .lower()) alors que les maps sont capitalisées. Sans
# normalisation, _encode_* renvoyait -1 pour TOUTES les lignes → discipline/terrain
# = features constantes → le méta-modèle n'apprenait rien de ces dimensions.
_DISCIPLINE_MAP_NORM: dict[str, int] = {k.lower(): v for k, v in _DISCIPLINE_MAP.items()}
_TERRAIN_MAP_NORM: dict[str, int] = {k.lower(): v for k, v in _TERRAIN_MAP.items()}


def _encode_discipline(discipline: Optional[str]) -> int:
    """Encode la discipline en entier. Retourne -1 si inconnue."""
    if not discipline:
        return -1
    return _DISCIPLINE_MAP_NORM.get(discipline.strip().lower(), -1)


def _encode_terrain(terrain: Optional[str]) -> int:
    """Encode le terrain en entier. Retourne -1 si inconnu."""
    if not terrain:
        return -1
    return _TERRAIN_MAP_NORM.get(terrain.strip().lower(), -1)


def _encode_hippodrome(hippodrome: Optional[str]) -> int:
    """Encode le nom d'hippodrome en hash entier stable [0, 999].

    hashlib (pas hash() built-in) : hash() est randomisé par PYTHONHASHSEED →
    valeur différente entre le process d'entraînement et celui d'inférence pour
    le même hippodrome. md5 est déterministe entre process.
    """
    if not hippodrome:
        return -1
    digest = hashlib.md5(hippodrome.strip().lower().encode("utf-8")).hexdigest()
    return int(digest, 16) % 1000


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
        # Nature des exemples sur lesquels ce modèle a été entraîné (cf.
        # TRAINING_CONTRACT). Persisté dans le pickle, vérifié au chargement.
        self._contract: str = TRAINING_CONTRACT

    @property
    def is_trained(self) -> bool:
        """Retourne True si le modèle a été entraîné et est prêt à faire des prédictions."""
        return self._model is not None

    async def train(self, session: AsyncSession) -> dict:
        """Entraîne le méta-apprenant PAR PARTANT sur les conseils réellement émis.

        Ce que corrigeait la version précédente, et pourquoi elle ne le pouvait pas
        ─────────────────────────────────────────────────────────────────────────
        Elle s'entraînait sur ``race_learning_log``, à raison d'UNE ligne par COURSE :

          - le label était « le vrai gagnant est-il dans le top-3 prédit ? », une
            propriété de la COURSE, alors que la sortie est appliquée à la proba de
            CHAQUE partant ;
          - ``base_proba`` était ``gagnant_proba_ia``, la proba du GAGNANT — une
            quantité connue seulement après l'arrivée — alors qu'à l'inférence elle
            reçoit la proba de tous les partants ;
          - six des quinze features (``jours_repos``, ``elo_vs_moyenne``,
            ``forme_5_courses``, ``spi_score``…) étaient des CONSTANTES à
            l'entraînement et de vraies valeurs au service ;
          - ``rang_cote`` était fabriqué depuis ``base_proba``, et ``cote_pmu``
            valait le MIN du champ.

        Le taux de base différait d'un facteur deux (0,617 par course contre ~0,27
        par partant) et la sortie remplaçait ``probas_top3`` pour tout le monde.

        Ce que fait cette version
        ─────────────────────────
        Une ligne par PARTANT, depuis ``prediction_evaluation`` — la vue qui expose
        les prédictions FIGÉES avant le départ avec leurs features gelées (mêmes
        gardes anti-fuite que les calibrations isotones : ``is_replayable``,
        ``created_at < date_heure``). Le label est « CE cheval est arrivé dans les
        trois premiers », c'est-à-dire exactement ce que la sortie corrige.

        L'entrée ``base_proba`` est reconstruite comme à l'inférence : la proba
        BRUTE du modèle passée dans la courbe isotone top3 puis dans le température
        scaling, par COURSE. Fit et service voient donc la même grandeur. Il n'y a
        pas de boucle fermée : tout est dérivé de ``proba_top3_raw``, jamais de la
        sortie du méta-apprenant de la veille.

        GATE DE VALIDATION — un correcteur non prouvé ne corrige rien
        ────────────────────────────────────────────────────────────
        Le modèle n'est retenu que s'il fait MIEUX, en log-loss, que l'absence de
        correction sur un hold-out découpé PAR COURSE et postérieur à tout ce qu'il
        a vu. Sinon ``is_trained`` reste faux et la chaîne applique l'identité.
        C'est le contrôle qui manquait : rien ne vérifiait que la correction
        apportait quoi que ce soit, et son AUC de validation flattait parce qu'elle
        était mesurée sur SA tâche à elle, pas sur celle qu'on lui faisait faire.
        """
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            log.error("meta_learner.lgbm_not_installed")
            return {"status": "error", "message": "lightgbm not installed"}

        cutoff = datetime.now(timezone.utc) - timedelta(days=30 * TRAINING_WINDOW_MONTHS)
        log.info("meta_learner.train_start", cutoff=cutoff.isoformat())

        try:
            result = await session.execute(text("""
                SELECT pe.course_id,
                       pa.numero,
                       pe.proba_top3_raw,
                       pe.features,
                       c.discipline,
                       c.terrain_officiel,
                       c.hippodrome_nom,
                       c.nb_partants,
                       c.date_heure,
                       c.est_quinte,
                       c.distance,
                       r.classement
                FROM prediction_evaluation pe
                JOIN participations pa ON pa.participation_id = pe.participation_id
                JOIN courses c         ON c.course_id         = pe.course_id
                JOIN resultats r       ON r.course_id         = pe.course_id
                WHERE pe.is_replayable = true
                  AND pe.proba_top3_raw IS NOT NULL
                  AND pe.features IS NOT NULL
                  AND r.classement IS NOT NULL
                  AND c.date_heure IS NOT NULL
                  AND c.date_heure >= :cutoff
                  AND pe.created_at IS NOT NULL
                  AND pe.created_at < c.date_heure
                ORDER BY c.date_heure ASC, pe.course_id ASC
            """), {"cutoff": cutoff})
            rows = result.fetchall()
        except Exception as e:
            log.error("meta_learner.train_query_error", err=str(e))
            return {"status": "error", "message": str(e)}

        log.info("meta_learner.train_data_fetched", n_lignes=len(rows))

        # La courbe isotone top3 est celle que l'inférence appliquera cette nuit :
        # le job tourne à 03:00, après son recalcul par le retrain de 02:00.
        try:
            from ml.isotonic_calibration_top3 import load_curve as _t3_load
            courbe_t3 = await _t3_load(session)
        except Exception as e:
            log.warning("meta_learner.isotone_indisponible", err=str(e)[:140])
            courbe_t3 = None

        courses = _grouper_par_course(rows)
        X_list, y_list, groupes = [], [], []
        for course_id, lignes in courses:
            echantillons = _echantillons_de_course(lignes, courbe_t3)
            for feat, label in echantillons:
                X_list.append(feat)
                y_list.append(label)
                groupes.append(course_id)

        if len(X_list) < MIN_SAMPLES_TO_TRAIN:
            log.warning("meta_learner.insufficient_data", n_samples=len(X_list),
                        min_required=MIN_SAMPLES_TO_TRAIN)
            return {"status": "insufficient_data", "n_samples": len(X_list),
                    "min_required": MIN_SAMPLES_TO_TRAIN}

        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list, dtype=np.int32)

        # Découpage temporel PAR COURSE : aucun frère de course ne peut se trouver
        # des deux côtés (les features de champ les rendraient reconnaissables).
        masque_val = _masque_holdout_par_course(groupes, frac_train=0.8)
        X_train, X_val = X[~masque_val], X[masque_val]
        y_train, y_val = y[~masque_val], y[masque_val]
        if len(X_val) == 0 or len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
            log.warning("meta_learner.holdout_inexploitable",
                        n_train=len(X_train), n_val=len(X_val))
            return {"status": "insufficient_data", "n_samples": len(X),
                    "min_required": MIN_SAMPLES_TO_TRAIN}

        pos_rate = float(y_train.mean())
        log.info("meta_learner.train_split", n_train=len(X_train), n_val=len(X_val),
                 pos_rate=round(pos_rate, 4))

        model = LGBMClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05, num_leaves=31,
            subsample=0.8, colsample_bytree=0.8, min_child_samples=30,
            random_state=42, verbose=-1,
            # Aligné sur BT_TRAIN_NJOBS comme ml/models.py. `-1` prenait tous les
            # cœurs, et chaque thread LightGBM porte ses propres tampons : sur ce
            # VPS 4 vCPU / 7,6 Gio partagés, le gain de temps ne vaut pas le pic.
            n_jobs=_N_JOBS,
        )
        # PAS de `scale_pos_weight` : il DÉCALIBRE volontairement les probabilités
        # pour équilibrer les classes. Or ce modèle ne classe pas, il produit une
        # probabilité qui doit être juste — le rééquilibrage aurait gonflé toutes
        # les sorties et le gate de log-loss l'aurait rejeté à chaque fois.
        try:
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
                      feature_name=FEATURE_NAMES + ["distance_mismatch"], callbacks=[])
        except TypeError:
            model.fit(X_train, y_train)   # ancienne API LightGBM

        metrics = _compute_validation_metrics(model, X_val, y_val)
        verdict = _verdict_utilite(model, X_val, y_val)
        metrics.update(verdict)
        metrics.update({
            "n_samples": len(X), "n_train": len(X_train), "n_val": len(X_val),
            "n_courses": len(courses), "pos_rate": round(pos_rate, 4),
            "trained_at": datetime.now(timezone.utc).isoformat(),
        })

        if not verdict["utile"]:
            # Un correcteur qui n'améliore rien ne doit pas être appliqué. On ne
            # garde PAS le modèle : `is_trained` reste faux et la chaîne applique
            # l'identité, ce qui est la bonne réponse quand la mesure ne conclut pas.
            self._model = None
            self._metrics = metrics
            log.warning("meta_learner.rejete_inutile",
                        logloss_meta=verdict["logloss_meta"],
                        logloss_sans_correction=verdict["logloss_sans_correction"])
            return {"status": "rejected_not_useful", **metrics}

        self._model = model
        self._trained_at = datetime.now(timezone.utc)
        self._contract = TRAINING_CONTRACT
        self._n_samples = len(X)
        self._metrics = metrics
        log.info("meta_learner.train_complete", n_samples=len(X),
                 n_courses=len(courses), auc=metrics.get("auc_roc"),
                 logloss=metrics.get("log_loss"),
                 gain_logloss=verdict["gain_logloss"])
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
            blended = (META_BLEND_BASE * float(base_proba)
                       + (1.0 - META_BLEND_BASE) * proba_corrected)
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
                blended = (META_BLEND_BASE * float(base_p)
                           + (1.0 - META_BLEND_BASE) * float(corr_p))
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
        # Un modèle entraîné sous un AUTRE contrat n'est pas un modèle périmé, c'est
        # un modèle qui a appris autre chose. Le servir reviendrait à appliquer la
        # correction qu'on vient précisément de corriger. On le neutralise plutôt
        # que de le refuser : l'appelant reçoit une instance saine, non entraînée,
        # et la chaîne applique l'identité jusqu'au prochain retrain.
        contrat = getattr(instance, "_contract", None)
        if contrat != TRAINING_CONTRACT:
            log.warning("meta_learner.contrat_perime", path=str(load_path),
                        contrat_du_pickle=contrat, contrat_attendu=TRAINING_CONTRACT)
            neuf = cls()
            neuf._metrics = {"status": "contrat_perime", "contrat_du_pickle": contrat}
            return neuf
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


def _grouper_par_course(rows) -> list[tuple[str, list]]:
    """Regroupe les lignes (déjà triées chronologiquement) par course, en préservant
    l'ordre. Le champ ENTIER est nécessaire : la température est centrée sur la
    moyenne des logits de la course, et la courbe isotone top3 renormalise à
    Σ = min(3, nb_partants). Une ligne isolée ne permet ni l'une ni l'autre."""
    courses: list[tuple[str, list]] = []
    courant, lignes = None, []
    for r in rows:
        cid = r[0]
        if cid != courant:
            if lignes:
                courses.append((courant, lignes))
            courant, lignes = cid, []
        lignes.append(r)
    if lignes:
        courses.append((courant, lignes))
    return courses


def _top3_du_classement(classement) -> set:
    """Numéros arrivés dans les trois premiers. Ensemble vide si illisible — une
    course sans arrivée exploitable ne doit produire aucun exemple, jamais un label
    par défaut."""
    if not classement:
        return set()
    if isinstance(classement, str):
        try:
            classement = json.loads(classement)
        except (ValueError, TypeError):
            return set()
    top3 = set()
    for e in classement or []:
        try:
            if int(e.get("position")) in (1, 2, 3):
                top3.add(int(e.get("numero")))
        except (TypeError, ValueError, AttributeError):
            continue
    return top3


def base_proba_de_course(raw_top3, courbe_t3, nb_partants: int,
                         temperature: float = 1.0) -> np.ndarray:
    """Reconstruit EXACTEMENT l'entrée que le méta-apprenant reçoit à l'inférence :
    la proba brute du modèle, passée dans la courbe isotone top3 puis dans le
    température scaling centré sur la course.

    Fonction pure, testable sans base. Elle DOIT rester le miroir de
    ``ml.pipeline.predict_course`` : si les deux divergent, le méta-apprenant est de
    nouveau ajusté sur une grandeur et appliqué à une autre — le défaut même qu'il
    s'agit de corriger.

    Pas de boucle fermée : tout dérive de ``proba_top3_raw``, jamais d'une sortie de
    méta-apprenant.
    """
    p = np.clip(np.asarray(raw_top3, dtype=float), 1e-6, 0.999)
    if courbe_t3:
        try:
            from ml.isotonic_calibration_top3 import apply_calibration as _t3_apply
            p = np.asarray(_t3_apply(p, courbe_t3, nb_partants), dtype=float)
        except Exception as e:
            log.warning("meta_learner.isotone_application_echec", err=str(e)[:140])
    p = np.clip(p, 1e-7, 1 - 1e-7)
    logits = np.log(p / (1 - p))
    T = max(float(temperature or 1.0), 0.1)
    moyenne = float(logits.mean()) if logits.size else 0.0
    return 1.0 / (1.0 + np.exp(-(moyenne + (logits - moyenne) / T)))


def _normaliser_datetime(valeur):
    """Normalise une colonne DateTime lue par ``text()``.

    asyncpg (PostgreSQL) rend déjà un ``datetime`` ; le driver SQLite des tests rend
    une chaîne ISO pour une requête brute non-ORM — même précédent que
    ``ml.bet_plan_performance._as_dt`` et ``ml.features`` pour ``last_date``.
    """
    if valeur is None or isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, str):
        try:
            return datetime.fromisoformat(valeur)
        except ValueError:
            return None
    return None


def _echantillons_de_course(lignes, courbe_t3, temperature: float = 1.0):
    """(vecteur de features, label) pour chaque PARTANT d'une course.

    Label = ce cheval est arrivé dans les trois premiers. C'est exactement ce que la
    sortie du méta-apprenant corrige — l'ancienne version apprenait « le vrai gagnant
    est-il dans le top-3 prédit ? », une propriété de la COURSE, et l'appliquait
    ensuite partant par partant.
    """
    top3 = _top3_du_classement(lignes[0][11])
    if not top3:
        return []
    raw = [float(r[2]) for r in lignes]
    nb_partants = int(lignes[0][7] or len(lignes))
    base = base_proba_de_course(raw, courbe_t3, nb_partants, temperature)

    date_heure = _normaliser_datetime(lignes[0][8])
    discipline, terrain, hippodrome = lignes[0][4], lignes[0][5], lignes[0][6]
    est_quinte, distance = lignes[0][9], lignes[0][10]
    dist_ok = _distance_normal_for_discipline(discipline, distance)

    out = []
    for i, r in enumerate(lignes):
        feats = r[3]
        if isinstance(feats, str):
            try:
                feats = json.loads(feats)
            except (ValueError, TypeError):
                feats = {}
        feats = feats or {}
        try:
            numero = int(r[1])
        except (TypeError, ValueError):
            continue
        contexte = {
            "discipline": discipline,
            "terrain": terrain,
            "hippodrome": hippodrome,
            "nb_partants": nb_partants,
            "hour_of_day": date_heure.hour if date_heure is not None else 14,
            "est_quinte": bool(est_quinte),
            "distance": distance,
            # Vraies valeurs du PARTANT, prises dans ses features figées. C'est ici
            # que l'ancienne version mettait des constantes (jours_repos=20,
            # elo_vs_moyenne=0.0, forme_5_courses=0.5, spi_score=0.0) tandis que
            # l'inférence lui passait les vraies : six features sur quinze étaient
            # muettes à l'entraînement et parlantes au service.
            "jours_repos": feats.get("jours_repos"),
            "cote_pmu": feats.get("cote_pmu"),
            "rang_cote": feats.get("rang_cote"),
            "elo_vs_moyenne": feats.get("elo_vs_moyenne"),
            "forme_5_courses": feats.get("forme_5_courses"),
            "spi_score": feats.get("spi_score"),
            "season_month": date_heure.month if date_heure is not None else 6,
        }
        vecteur = _build_feature_vector(float(base[i]), contexte)
        vecteur.append(float(not dist_ok))
        out.append((vecteur, int(numero in top3)))
    return out


def _masque_holdout_par_course(groupes: list, frac_train: float = 0.8) -> np.ndarray:
    """Masque booléen du hold-out : True = courses les plus RÉCENTES.

    Découpage PAR COURSE et non par ligne : les partants d'une même course partagent
    leurs features de champ (nb_partants, hippodrome, heure…) et se reconnaissent
    entre eux. Un découpage par ligne laisserait donc chaque course fuir dans son
    propre hold-out, et le gate d'utilité validerait n'importe quoi.
    """
    ordre = list(dict.fromkeys(groupes))          # chronologique, sans doublon
    coupe = int(len(ordre) * frac_train)
    train = set(ordre[:coupe])
    return np.array([g not in train for g in groupes], dtype=bool)


# Gain minimal de log-loss exigé pour qu'une correction soit appliquée. Strictement
# positif : un modèle qui fait « aussi bien » que l'absence de correction ne doit pas
# être appliqué — il ajouterait de la variance sans rien apporter.
MIN_GAIN_LOGLOSS = 1e-4


def _verdict_utilite(model, X_val: np.ndarray, y_val: np.ndarray) -> dict:
    """Le correcteur fait-il MIEUX que l'absence de correction ?

    Comparaison sur le hold-out, en log-loss, entre :
      - la proba de base seule (colonne 0 de X, c'est-à-dire ne rien corriger) ;
      - la proba mélangée exactement comme au service (cf. `predict_correction`).

    Rien ne vérifiait cela. L'AUC de validation publiée mesurait la performance du
    méta-apprenant SUR SA PROPRE TÂCHE, jamais le fait que l'appliquer améliore la
    probabilité servie. Un correcteur non prouvé ne corrige rien : `train` le jette.
    """
    try:
        from sklearn.metrics import log_loss
    except ImportError:
        return {"utile": False, "logloss_meta": None,
                "logloss_sans_correction": None, "gain_logloss": None}
    if len(X_val) == 0 or len(np.unique(y_val)) < 2:
        return {"utile": False, "logloss_meta": None,
                "logloss_sans_correction": None, "gain_logloss": None}
    try:
        base = np.clip(X_val[:, 0].astype(float), 1e-6, 1 - 1e-6)
        corrige = model.predict_proba(X_val)[:, 1]
        melange = np.clip(META_BLEND_BASE * base + (1.0 - META_BLEND_BASE) * corrige,
                          0.01, 0.99)
        ll_sans = float(log_loss(y_val, base, labels=[0, 1]))
        ll_meta = float(log_loss(y_val, melange, labels=[0, 1]))
    except Exception as e:
        log.warning("meta_learner.verdict_utilite_echec", err=str(e)[:140])
        return {"utile": False, "logloss_meta": None,
                "logloss_sans_correction": None, "gain_logloss": None}
    gain = ll_sans - ll_meta
    return {"utile": bool(gain > MIN_GAIN_LOGLOSS),
            "logloss_meta": round(ll_meta, 6),
            "logloss_sans_correction": round(ll_sans, 6),
            "gain_logloss": round(gain, 6)}


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
