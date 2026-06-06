"""
AdaptiveLearning — Calibration adaptative et apprentissage continu.

Après chaque course, ce module :
  1. Met à jour la calibration du modèle (temperature scaling)
  2. Adapte les poids des features selon leur utilité récente
  3. Détecte les dérives de distribution (concept drift)
  4. Entraîne un méta-modèle de correction des biais
  5. Propose des ajustements de probabilité contextuels

Méthode : Online Learning + Temperature Scaling + Bias Correction Matrix.

Temperature Scaling :
  P_calibrée = sigmoid(logit(P_brute) / T)
  T > 1 → modèle trop confiant → étale les probas
  T < 1 → modèle trop incertain → concentre les probas

Correction contextuelle :
  P_finale = P_calibrée × (1 + correction_facteur_contexte)
  correction_facteur_contexte ← matrice bias_matrix par (discipline × terrain × hippodrome)
"""
import json
import math
import uuid
import numpy as np
import structlog
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

log = structlog.get_logger(module="adaptive_learning")

# Température initiale
T_INITIAL = 1.0
# Learning rate pour la mise à jour de température
T_LEARNING_RATE = 0.02
# Fenêtre glissante pour la température (pondération exponentielle)
T_DECAY = 0.95
# Borne temperature
T_MIN, T_MAX = 0.6, 2.0

# Poids des features adaptatifs — groupe → poids relatif
DEFAULT_FEATURE_WEIGHTS = {
    "elo": 1.0,
    "forme": 1.0,
    "repos": 0.8,
    "distance": 0.9,
    "terrain": 0.9,
    "hippodrome": 0.8,
    "cotes": 1.2,    # Les cotes intègrent l'info marché — fort prédicteur
    "equip": 0.6,
    "jockey": 1.0,
    "entraineur": 0.8,
    "cheval": 0.9,
    "signaux_avances": 1.1,   # SPI, momentum — souvent sous-estimés
    "fingerprint": 0.9,
    "synergy": 0.8,
    # Nouvelles features
    "classe": 1.0,   # class_drop_ratio, class_jump_score
    "bounce": 0.7,   # bounce_score
    "draw": 0.6,     # draw_bias_score
    "career": 0.9,   # career_momentum, form_vs_career
    "dynamique": 0.9,      # dyn_finit_fort, accélération finale, réduction km (Phase 1)
    "confrontation": 0.8,  # conf_bilan_net, head-to-head (Phase 1.3)
}

# Mapping feature key → feature group
FEATURE_TO_GROUP: dict[str, str] = {
    # ELO
    "elo_global": "elo", "elo_discipline": "elo", "elo_vs_moyenne": "elo",
    "delta_elo_5courses": "elo", "velocity_elo": "elo", "elo_trend_30j": "elo",
    # Forme
    "forme_1_course": "forme", "forme_5_courses": "forme", "forme_tendance": "forme",
    "regularite": "forme", "taux_top3": "forme", "taux_victoire_5c": "forme",
    "time_decay_form": "forme",
    # Repos
    "jours_repos": "repos", "fraicheur_score": "repos", "surmenage_score": "repos",
    "jours_depuis_derniere_db": "repos",
    # Distance
    "pref_distance_actuelle": "distance", "delta_dist_prefere": "distance",
    "stamina_index": "distance",
    # Terrain
    "pref_terrain_actuel": "terrain", "humidite_piste": "terrain",
    "penetrometre_coef": "terrain", "running_style_terrain_fit": "terrain",
    "pace_conflict_score": "terrain",
    # Hippodrome
    "pref_hippodrome": "hippodrome", "record_hippodrome": "hippodrome",
    "corde_preference": "hippodrome", "draw_bias_score": "draw",
    # Cotes marché
    "cote_pmu": "cotes", "cote_betfair_exchange": "cotes", "spread_bookmakers": "cotes",
    "gap_pmu_betfair": "cotes", "steam_move_betclic": "cotes", "spi_score": "signaux_avances",
    "mouvement_30min": "signaux_avances", "pool_gagnant_ratio": "signaux_avances",
    "valeur_latente": "signaux_avances", "decote_detectee": "signaux_avances",
    # Équipement
    "premier_deferre": "equip", "premieres_oeilleres": "equip",
    "changement_equipement": "equip", "equipement_score": "equip",
    # Jockey
    "jockey_taux_victoire_global": "jockey", "jockey_forme_30j": "jockey",
    "jockey_roi": "jockey", "asso_jockey_entraineur_taux": "jockey",
    "changement_jockey": "jockey",
    # Entraîneur
    "entraineur_taux_global": "entraineur", "combo_jockey_entraineur": "entraineur",
    "trainer_return_bonus": "entraineur",
    # Cheval
    "running_style_code": "cheval", "prix_vente_log": "cheval",
    "career_win_rate": "cheval", "age": "cheval",
    # Fingerprint / synergy
    "course_fingerprint_score": "fingerprint", "jockey_cheval_synergy_score": "synergy",
    # Classe
    "class_drop_ratio": "classe", "class_jump_score": "classe",
    # Bounce
    "bounce_score": "bounce", "form_vs_career_rate": "bounce",
    # Career
    "career_momentum": "career", "form_vs_career_rate": "career",
    # Dynamique de course (Phase 1)
    "dyn_finit_fort": "dynamique", "dyn_taux_accelere": "dynamique",
    "dyn_taux_faiblit": "dynamique", "dyn_reduction_km_best": "dynamique",
    "dyn_reduction_km_moy": "dynamique",
    # Confrontations directes (Phase 1.3)
    "conf_bilan_net": "confrontation", "conf_taux_victoire": "confrontation",
    "conf_nb_rivaux_battus": "confrontation",
}

# Ajustement max par feature en une seule update (évite l'instabilité)
WEIGHT_CLIP = 0.05

# Tags causaux (PostRaceAnalyzer) → groupes de features sous-pondérés à renforcer.
# Quand une cause récurrente révèle un angle mort du modèle, on booste le groupe.
CAUSAL_TAG_TO_GROUPS = {
    "gagnant_finit_fort":          [("dynamique", 1.0)],
    "train_lent_sprint_final":     [("dynamique", 0.8)],
    "favori_faiblit":              [("dynamique", 0.6), ("confrontation", 0.4)],
    "favori_jamais_dans_le_coup":  [("confrontation", 0.8), ("forme", 0.4)],
    "surprise_outsider":           [("signaux_avances", 0.8), ("cotes", 0.4)],
    "train_rapide_usure":          [("dynamique", 0.5)],
}


def causal_weight_nudges(causal_tags: list) -> dict:
    """
    Convertit des tags causaux en deltas de poids par groupe (pur, testable).

    causal_tags : [{tag, description}, ...]. Retourne {group: delta} agrégé,
    chaque delta borné par WEIGHT_CLIP. Tag inconnu ignoré (aucun effet inventé).
    """
    nudges: dict[str, float] = {}
    for t in causal_tags or []:
        tag = t.get("tag") if isinstance(t, dict) else t
        for group, intensite in CAUSAL_TAG_TO_GROUPS.get(tag, []):
            nudges[group] = nudges.get(group, 0.0) + WEIGHT_CLIP * intensite
    # Borne chaque groupe à WEIGHT_CLIP (un seul boost max par update)
    return {g: round(min(d, WEIGHT_CLIP), 4) for g, d in nudges.items()}


class AdaptiveLearning:
    """
    Moteur d'apprentissage adaptatif continu.

    Persisté partiellement en DB (temperature, feature_weights).
    Instance en mémoire pour les updates rapides.
    """

    def __init__(self):
        self.temperature: float = T_INITIAL
        self.feature_weights: dict[str, float] = DEFAULT_FEATURE_WEIGHTS.copy()
        self.n_races_processed: int = 0
        self.brier_ema: float = 0.20        # Brier score exponential moving average
        self.surprise_rate_ema: float = 0.3
        self._recent_signals: list[dict] = []
        self._max_recent = 100

    async def load_state(self, session: AsyncSession) -> None:
        """Charge l'état depuis la DB au démarrage."""
        try:
            r = await session.execute(text("""
                SELECT temperature, feature_weights_json, n_races, brier_ema, surprise_ema
                FROM adaptive_learning_state
                ORDER BY updated_at DESC LIMIT 1
            """))
            row = r.fetchone()
            if row:
                self.temperature = float(row[0] or T_INITIAL)
                fw = row[1]
                if fw:
                    fw_dict = fw if isinstance(fw, dict) else json.loads(fw)
                    for k, v in fw_dict.items():
                        self.feature_weights[k] = float(v)
                self.n_races_processed = int(row[2] or 0)
                self.brier_ema = float(row[3] or 0.20)
                self.surprise_rate_ema = float(row[4] or 0.3)
                log.info(
                    "adaptive.state_loaded",
                    T=round(self.temperature, 4),
                    n_races=self.n_races_processed,
                    brier_ema=round(self.brier_ema, 4),
                )
        except Exception as e:
            log.warning("adaptive.state_load_failed", err=str(e))

    async def save_state(self, session: AsyncSession) -> None:
        """Sauvegarde l'état en DB."""
        try:
            await session.execute(text("""
                INSERT INTO adaptive_learning_state
                    (state_id, temperature, feature_weights_json, n_races,
                     brier_ema, surprise_ema, updated_at)
                VALUES
                    (:sid, :temp, CAST(:fw AS JSONB), :n, :brier, :surp, NOW())
                ON CONFLICT (state_id) DO UPDATE SET
                    temperature = EXCLUDED.temperature,
                    feature_weights_json = EXCLUDED.feature_weights_json,
                    n_races = EXCLUDED.n_races,
                    brier_ema = EXCLUDED.brier_ema,
                    surprise_ema = EXCLUDED.surprise_ema,
                    updated_at = NOW()
            """), {
                "sid": "singleton",
                "temp": round(self.temperature, 6),
                "fw": json.dumps({k: round(v, 4) for k, v in self.feature_weights.items()}),
                "n": self.n_races_processed,
                "brier": round(self.brier_ema, 6),
                "surp": round(self.surprise_rate_ema, 4),
            })
            await session.flush()
        except Exception as e:
            log.error("adaptive.save_state_error", err=str(e))

    async def process_race_signal(self, signal: dict) -> dict:
        """
        Traite le signal d'apprentissage d'une course.
        Met à jour temperature, feature_weights, biais.

        signal : voir PostRaceAnalyzer.analyze_race retour learning_signal
        """
        brier = float(signal.get("brier_course", 0.20))
        was_surprise = bool(signal.get("was_surprise", False))
        gagnant_proba = float(signal.get("gagnant_proba_ia", 0.3))
        autopsy = signal.get("feature_autopsy", {})

        self.n_races_processed += 1

        # ── 1. Mise à jour EMA des métriques ────────────────────────────
        self.brier_ema = 0.9 * self.brier_ema + 0.1 * brier
        self.surprise_rate_ema = 0.95 * self.surprise_rate_ema + 0.05 * (1.0 if was_surprise else 0.0)

        # ── 2. Ajustement de température (calibration) ───────────────────
        temperature_update = self._update_temperature(gagnant_proba, was_surprise, brier)

        # ── 3. Mise à jour des poids features via autopsie ───────────────
        weight_updates = self._update_feature_weights(autopsy, was_surprise)

        # ── 4. Mémoriser le signal récent ────────────────────────────────
        self._recent_signals.append(signal)
        if len(self._recent_signals) > self._max_recent:
            self._recent_signals.pop(0)

        return {
            "n_races": self.n_races_processed,
            "temperature": round(self.temperature, 4),
            "brier_ema": round(self.brier_ema, 4),
            "surprise_rate_ema": round(self.surprise_rate_ema, 3),
            "temperature_update": round(temperature_update, 6),
            "weight_updates": weight_updates,
        }

    def _update_temperature(
        self,
        gagnant_proba: float,
        was_surprise: bool,
        brier: float,
    ) -> float:
        """
        Mise à jour de temperature T par gradient stochastique.

        Principe :
        - Si le gagnant était un surprise (proba basse) et le brier est élevé,
          le modèle est TROP CONFIANT sur les favoris → augmenter T
        - Si le brier est bas (bonnes prédictions), stable ou légère réduction T
        """
        old_T = self.temperature

        if was_surprise and gagnant_proba < 0.15:
            # Très forte surprise → modèle trop confiant → +T
            delta = T_LEARNING_RATE * (1.0 - gagnant_proba)
            self.temperature = min(self.temperature + delta, T_MAX)
        elif brier > 0.22:
            # Brier élevé → calibration à ajuster → légère +T
            delta = T_LEARNING_RATE * 0.5 * (brier - 0.18)
            self.temperature = min(self.temperature + delta * 0.5, T_MAX)
        elif brier < 0.14 and not was_surprise:
            # Très bonne prédiction → on peut concentrer légèrement
            self.temperature = max(self.temperature - T_LEARNING_RATE * 0.3, T_MIN)
        else:
            # Decay vers T=1.0 (stabilisation)
            self.temperature += (T_INITIAL - self.temperature) * (T_LEARNING_RATE * 0.1)

        return self.temperature - old_T

    def update_from_feature_attribution(
        self,
        winner_features: dict,
        loser_features_avg: dict,
        was_correct: bool,
    ) -> dict:
        """
        Met à jour les poids features en comparant les features du gagnant
        vs la moyenne des perdants.

        Principe :
        Si le gagnant a une valeur feature F significativement plus haute
        que les perdants ET que le modèle avait correctement prédit →
        augmenter légèrement le poids de ce groupe (renforcement).

        Si le modèle s'est trompé ET que le gagnant avait une valeur
        feature forte ignorée → augmenter le poids (correction).

        Apprentissage contrastif simplifié.
        """
        updates = {}
        lr = WEIGHT_CLIP * (0.5 if was_correct else 1.0)

        for feat_key, group in FEATURE_TO_GROUP.items():
            winner_val = winner_features.get(feat_key)
            loser_val = loser_features_avg.get(feat_key)

            if winner_val is None or loser_val is None:
                continue

            try:
                w_val = float(winner_val)
                l_val = float(loser_val)
            except (TypeError, ValueError):
                continue

            # Différence normalisée
            diff = w_val - l_val
            if abs(diff) < 0.01:
                continue

            current_w = self.feature_weights.get(group, 1.0)

            if not was_correct and diff > 0.10:
                # Modèle raté le gagnant qui était meilleur sur ce signal → augmenter poids
                delta = lr * min(abs(diff), 1.0)
                new_w = min(current_w + delta, 2.0)
                if new_w != current_w:
                    self.feature_weights[group] = round(new_w, 4)
                    updates[f"{group}+"] = round(delta, 4)

            elif was_correct and diff > 0.15:
                # Modèle correct ET signal fort du gagnant → très légère augmentation (renforcement)
                delta = lr * 0.3 * min(abs(diff), 1.0)
                self.feature_weights[group] = round(min(current_w + delta, 2.0), 4)

        # Decay vers défaut
        for group in list(self.feature_weights.keys()):
            default_w = DEFAULT_FEATURE_WEIGHTS.get(group, 1.0)
            current_w = self.feature_weights[group]
            self.feature_weights[group] = round(current_w + (default_w - current_w) * 0.01, 4)

        return updates

    def get_feature_importance_ranking(self) -> list[dict]:
        """Retourne les groupes de features triés par poids décroissant."""
        return [
            {"group": k, "weight": round(v, 3), "vs_default": round(v - DEFAULT_FEATURE_WEIGHTS.get(k, 1.0), 3)}
            for k, v in sorted(self.feature_weights.items(), key=lambda x: -x[1])
        ]

    def _update_feature_weights(self, autopsy: dict, was_surprise: bool) -> dict:
        """
        Ajuste les poids des groupes de features selon l'autopsie.

        Si un signal d'un groupe était présent MAIS non exploité par le modèle
        (= on a raté le gagnant), on AUGMENTE le poids de ce groupe.

        Si le modèle était correct (pas de surprise), on stabilise les poids.
        """
        updates = {}

        # ── Nudges causaux (Phase 3) — actifs même hors surprise ─────────
        # Une cause physique récurrente (favori qui faiblit, gagnant qui finit
        # fort…) révèle un angle mort : on renforce le groupe de features associé.
        causal_tags = autopsy.get("causal_tags", []) if isinstance(autopsy, dict) else []
        for group, delta in causal_weight_nudges(causal_tags).items():
            old_w = self.feature_weights.get(group, 1.0)
            new_w = min(old_w + delta, 2.0)
            self.feature_weights[group] = round(new_w, 4)
            updates[group] = {"ancien": round(old_w, 4), "nouveau": round(new_w, 4),
                              "delta": round(delta, 4), "cause": "causal"}

        if not was_surprise:
            return updates  # Hors surprise : seuls les nudges causaux s'appliquent

        # Mapping autopsie → groupe de features
        autopsy_to_group = {
            "spi_manque": "signaux_avances",
            "mouvement_cote_manque": "cotes",
            "valeur_latente_manque": "cotes",
            "forme_montante": "forme",
            "repos_optimal": "repos",
            "equipement_nouveau": "equip",
            "elo_sous_estime": "elo",
            "fingerprint_fort": "fingerprint",
            "synergy_jockey_cheval": "synergy",
        }

        for signal_key, group in autopsy_to_group.items():
            if signal_key in autopsy and not signal_key.startswith("_"):
                # Augmenter le poids de ce groupe
                old_w = self.feature_weights.get(group, 1.0)
                delta = WEIGHT_CLIP * float(autopsy[signal_key].get("valeur", 0.5))
                new_w = min(old_w + delta, 2.0)  # Plafond à 2.0
                self.feature_weights[group] = round(new_w, 4)
                updates[group] = {"ancien": round(old_w, 4), "nouveau": round(new_w, 4), "delta": round(delta, 4)}

        # Décroissance lente vers les poids par défaut pour éviter l'explosion
        for group in self.feature_weights:
            default_w = DEFAULT_FEATURE_WEIGHTS.get(group, 1.0)
            current_w = self.feature_weights[group]
            self.feature_weights[group] = round(
                current_w + (default_w - current_w) * 0.02,  # 2% de retour vers défaut
                4
            )

        return updates

    def apply_calibration(
        self,
        probas: np.ndarray,
        context: Optional[dict] = None,
        bias_correction: float = 0.0,
    ) -> np.ndarray:
        """
        Applique la calibration adaptative aux probabilités brutes.

        probas : array de probas brutes du modèle (une par partant)
        context : dict avec discipline, terrain, hippodrome pour correction contextuelle
        bias_correction : facteur de correction issu de bias_matrix (-0.1 à +0.1)

        Retourne les probas calibrées et normalisées.
        """
        # ── Temperature scaling ──────────────────────────────────────────
        # logit puis division par T, puis sigmoid
        eps = 1e-7
        p_clipped = np.clip(probas, eps, 1 - eps)
        logits = np.log(p_clipped / (1 - p_clipped))
        scaled_logits = logits / max(self.temperature, 0.1)
        p_calibrated = 1.0 / (1.0 + np.exp(-scaled_logits))

        # ── Correction contextuelle biais ────────────────────────────────
        if bias_correction != 0.0:
            p_calibrated = p_calibrated * (1.0 + bias_correction)
            p_calibrated = np.clip(p_calibrated, 0.01, 0.99)

        # ── Normalisation pour que la somme soit cohérente ───────────────
        # Les probas top-3 ne doivent pas toutes être très hautes
        # On garde les probabilités relatives mais on les plafonne
        p_calibrated = np.clip(p_calibrated, 0.01, 0.95)

        return p_calibrated

    async def get_bias_correction(
        self, session: AsyncSession, discipline: str, terrain: str, hippodrome: str
    ) -> float:
        """
        Récupère le facteur de correction de biais pour un contexte donné.
        Retourne 0.0 si pas de biais connu ou pas assez de données.
        """
        try:
            r = await session.execute(text("""
                SELECT correction_factor, nb_courses
                FROM bias_matrix
                WHERE bias_key = :key AND nb_courses >= 8
            """), {"key": f"{discipline}|{terrain}|{hippodrome}"})
            row = r.fetchone()
            if row:
                return float(row[0] or 0.0)
        except Exception:
            pass
        return 0.0

    def get_adjusted_probas_for_display(
        self,
        base_probas: list[float],
        feature_groups: Optional[list[dict]] = None,
    ) -> list[float]:
        """
        Applique les poids adaptatifs aux probabilités pour l'affichage.
        Utile pour ajuster légèrement les probas selon les signaux du jour.

        feature_groups : [{groupe: str, score: float}] par partant
        """
        if not feature_groups:
            return base_probas

        adjusted = []
        for i, proba in enumerate(base_probas):
            p = proba
            if i < len(feature_groups):
                fg = feature_groups[i]
                for groupe, score in fg.items():
                    w = self.feature_weights.get(groupe, 1.0)
                    # Ajustement marginal pondéré par le score du signal
                    bonus = (w - 1.0) * score * 0.02
                    p = p + bonus
            adjusted.append(float(np.clip(p, 0.01, 0.99)))

        return adjusted

    def get_state_summary(self) -> dict:
        """Retourne un résumé de l'état actuel pour l'admin."""
        top_features = sorted(
            self.feature_weights.items(),
            key=lambda x: abs(x[1] - DEFAULT_FEATURE_WEIGHTS.get(x[0], 1.0)),
            reverse=True
        )
        return {
            "temperature": round(self.temperature, 4),
            "brier_ema": round(self.brier_ema, 4),
            "surprise_rate_ema": round(self.surprise_rate_ema, 3),
            "n_races_processed": self.n_races_processed,
            "calibration_status": (
                "sur-confiant" if self.temperature > 1.15
                else "sous-confiant" if self.temperature < 0.90
                else "calibré"
            ),
            "top_feature_drifts": [
                {
                    "groupe": k,
                    "poids_actuel": round(v, 3),
                    "poids_défaut": round(DEFAULT_FEATURE_WEIGHTS.get(k, 1.0), 3),
                    "drift": round(v - DEFAULT_FEATURE_WEIGHTS.get(k, 1.0), 3),
                }
                for k, v in top_features[:5]
            ],
            "alerte_calibration": self.brier_ema > 0.22 or self.surprise_rate_ema > 0.45,
        }


# ── Instance globale (singleton) ────────────────────────────────────────────
_adaptive_learning_instance: Optional[AdaptiveLearning] = None


def get_adaptive_learning() -> AdaptiveLearning:
    """Retourne l'instance singleton de AdaptiveLearning."""
    global _adaptive_learning_instance
    if _adaptive_learning_instance is None:
        _adaptive_learning_instance = AdaptiveLearning()
    return _adaptive_learning_instance


async def initialize_adaptive_learning(session: AsyncSession) -> AdaptiveLearning:
    """Initialise et charge l'état depuis DB. À appeler au démarrage."""
    al = get_adaptive_learning()
    await al.load_state(session)
    return al
