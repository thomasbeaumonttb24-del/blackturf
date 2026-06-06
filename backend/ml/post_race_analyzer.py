"""
PostRaceAnalyzer — Analyse post-course intelligente.

Après chaque fin de course officielle :
  1. Compare prédictions IA vs résultat réel
  2. Calcule Brier / log-loss par course
  3. Identifie les surprises (gagnant sous-évalué par le modèle)
  4. Autopsie des features : quels signaux auraient dû alerter ?
  5. Détecte les biais systémiques accumulés (ex: sous-estimation outsiders lourd)
  6. Envoie le signal d'apprentissage à AdaptiveLearning
  7. Stocke tout dans race_learning_log pour le futur ré-entraînement

Philosophie : le modèle ne se contente pas d'être "précis en moyenne" —
il doit comprendre POURQUOI il a tort pour s'améliorer.
"""
import math
import uuid
import json
import structlog
import numpy as np
from datetime import datetime, date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ml.causal_autopsy import tag_race_causes

log = structlog.get_logger(module="post_race_analyzer")

# Score de surprise : proba < SEUIL_SURPRISE = résultat inattendu
SEUIL_SURPRISE_GAGNANT = 0.20   # proba < 20% pour le gagnant = surprise forte
SEUIL_SURPRISE_MOYEN = 0.35     # proba < 35% = surprise modérée

# Biais accumulés : si on se trompe > N fois dans la même config, correction activée
BIAIS_SEUIL_COURSES = 8         # minimum 8 courses pour détecter un biais
BIAIS_SEUIL_ERREUR = 0.55       # taux d'erreur > 55% dans une config = biais confirmé


class PostRaceAnalyzer:
    """
    Moteur d'analyse post-course.
    Apprend de chaque course et accumule les signaux d'apprentissage.
    """

    def __init__(self, adaptive_learning=None):
        """
        adaptive_learning : instance de AdaptiveLearning (optionnel).
        Si fourni, lui transmet les signaux de correction après chaque course.
        """
        self.adaptive_learning = adaptive_learning

    async def analyze_race(
        self,
        session: AsyncSession,
        course_id: str,
        predictions: list[dict],
        resultat: dict,
    ) -> dict:
        """
        Point d'entrée principal. À appeler après chaque résultat officiel.

        predictions : [{participation_id, numero, nom, proba_top3, proba_top1,
                        cote_pmu, cote_geny, cote_bzh, features_snapshot}]
        resultat    : {ordre_arrivee: [{numero, position, ...}], ...}

        Retourne le rapport d'analyse complet.
        """
        log.info("post_race.analyze_start", course_id=course_id, n_preds=len(predictions))

        if not predictions or not resultat:
            log.warning("post_race.skip_empty", course_id=course_id)
            return {}

        # ── 1. Construire le mapping numéro → résultat réel ──────────────
        # La course en DB stocke l'arrivée sous "classement" ; le scraper sous
        # "ordre_arrivee". On accepte les deux (sinon arrivée vide → pas d'apprentissage).
        arrivee = resultat.get("ordre_arrivee") or resultat.get("classement") or []
        position_reelle: dict[int, int] = {}
        for entry in arrivee:
            num = entry.get("numero")
            pos = entry.get("position")
            if num and pos:
                position_reelle[int(num)] = int(pos)

        if not position_reelle:
            log.warning("post_race.no_arrivee", course_id=course_id)
            return {}

        gagnant_numero = min(position_reelle, key=position_reelle.get) if position_reelle else None
        top3_reels = {num for num, pos in position_reelle.items() if 1 <= pos <= 3}

        # ── 2. Métriques de précision pour cette course ──────────────────
        pred_map: dict[int, dict] = {int(p.get("numero", 0)): p for p in predictions}

        brier_total = 0.0
        log_loss_total = 0.0
        n_valid = 0

        for num, pred in pred_map.items():
            proba = float(pred.get("proba_top3", 0))
            label = 1 if num in top3_reels else 0
            brier_total += (proba - label) ** 2
            log_loss_total -= (
                label * math.log(max(proba, 1e-7)) +
                (1 - label) * math.log(max(1 - proba, 1e-7))
            )
            n_valid += 1

        brier_course = brier_total / n_valid if n_valid > 0 else 1.0
        log_loss_course = log_loss_total / n_valid if n_valid > 0 else 10.0

        # Précision top-3 : notre sélection contient-elle le gagnant ?
        top3_ia = sorted(pred_map.items(), key=lambda x: x[1].get("proba_top3", 0), reverse=True)[:3]
        top3_ia_numeros = {num for num, _ in top3_ia}
        top3_precision = gagnant_numero in top3_ia_numeros if gagnant_numero else False

        # ── 3. Analyse de la surprise ────────────────────────────────────
        winner_pred = pred_map.get(gagnant_numero, {})
        gagnant_proba_ia = float(winner_pred.get("proba_top3", 0))
        gagnant_cote_pmu = float(winner_pred.get("cote_pmu") or 0)

        was_surprise = gagnant_proba_ia < SEUIL_SURPRISE_GAGNANT if gagnant_numero else False
        surprise_score = max(0.0, (SEUIL_SURPRISE_GAGNANT - gagnant_proba_ia) / SEUIL_SURPRISE_GAGNANT) if gagnant_numero else 0.0

        # ── 4. Autopsy des features — signaux manqués / mal interprétés ──
        feature_autopsy = await self._autopsy_features(
            session, course_id, gagnant_numero, pred_map, top3_reels
        )

        # ── 5. Récupérer le contexte course pour les biais ───────────────
        ctx = await self._get_course_context(session, course_id)

        # ── 5b. Autopsie causale — POURQUOI ce résultat (dynamique) ──────
        pos500_by_num = await self._load_pos500(session, course_id)
        proba_by_num = {num: float(p.get("proba_top3", 0)) for num, p in pred_map.items()}
        causal_tags = tag_race_causes(
            winner_num=gagnant_numero,
            position_reelle=position_reelle,
            pos500_by_num=pos500_by_num,
            proba_by_num=proba_by_num,
            nb_partants=ctx.get("nb_partants"),
        )
        if causal_tags:
            feature_autopsy = dict(feature_autopsy or {})
            feature_autopsy["causal_tags"] = causal_tags

        # ── 6. Stocker dans race_learning_log ────────────────────────────
        log_id = await self._save_learning_log(
            session,
            course_id=course_id,
            gagnant_numero=gagnant_numero,
            winner_predicted=top3_ia_numeros,
            gagnant_proba_ia=gagnant_proba_ia,
            gagnant_cote_pmu=gagnant_cote_pmu,
            top3_precision=top3_precision,
            brier_course=brier_course,
            log_loss_course=log_loss_course,
            was_surprise=was_surprise,
            surprise_score=surprise_score,
            feature_autopsy=feature_autopsy,
            ctx=ctx,
        )

        # ── 7. Mettre à jour les biais systémiques ───────────────────────
        await self._update_bias_matrix(session, ctx, top3_precision, was_surprise)

        # ── 8. Transmettre à AdaptiveLearning ────────────────────────────
        learning_signal = {
            "course_id": course_id,
            "brier_course": brier_course,
            "log_loss_course": log_loss_course,
            "was_surprise": was_surprise,
            "surprise_score": surprise_score,
            "gagnant_proba_ia": gagnant_proba_ia,
            "top3_precision": top3_precision,
            "discipline": ctx.get("discipline"),
            "terrain": ctx.get("terrain"),
            "hippodrome": ctx.get("hippodrome"),
            "nb_partants": ctx.get("nb_partants"),
            "feature_autopsy": feature_autopsy,
        }

        if self.adaptive_learning:
            await self.adaptive_learning.process_race_signal(learning_signal)

        rapport = {
            "log_id": log_id,
            "course_id": course_id,
            "gagnant_numero": gagnant_numero,
            "gagnant_proba_ia": round(gagnant_proba_ia * 100, 1),
            "top3_precision": top3_precision,
            "brier_course": round(brier_course, 4),
            "log_loss_course": round(log_loss_course, 4),
            "was_surprise": was_surprise,
            "surprise_score": round(surprise_score, 3),
            "feature_autopsy": feature_autopsy,
            "causal_tags": (feature_autopsy or {}).get("causal_tags", []),
            "learning_signal": learning_signal,
        }

        log.info(
            "post_race.analyzed",
            course_id=course_id,
            gagnant=gagnant_numero,
            proba_ia=f"{gagnant_proba_ia*100:.1f}%",
            top3_ok=top3_precision,
            brier=round(brier_course, 4),
            surprise=was_surprise,
        )
        return rapport

    async def _autopsy_features(
        self,
        session: AsyncSession,
        course_id: str,
        gagnant_numero: Optional[int],
        pred_map: dict[int, dict],
        top3_reels: set[int],
    ) -> dict:
        """
        Autopsie des features du gagnant vs nos prédictions.

        Identifie :
        - Features qui auraient dû signaler le gagnant (hautes valeurs chez lui)
        - Features où le gagnant était sous-estimé (valeur élevée ignorée)
        - Signaux de marché manqués (SPI, mouvement cotes)
        """
        if not gagnant_numero or gagnant_numero not in pred_map:
            return {}

        winner = pred_map[gagnant_numero]

        # Features "surprise indicators" — les signaux que le modèle n'a pas assez valorisé
        snapshot = winner.get("features_snapshot") or {}
        if not snapshot:
            # Lire le snapshot des features depuis features_ml (pas predictions :
            # cette table n'a pas de colonne features_snapshot → l'ancienne requête
            # plantait et empoisonnait toute la transaction d'apprentissage).
            try:
                r = await session.execute(text("""
                    SELECT fm.features FROM features_ml fm
                    JOIN participations pa ON pa.participation_id = fm.participation_id
                    WHERE pa.course_id = :cid AND pa.numero = :num
                    LIMIT 1
                """), {"cid": course_id, "num": gagnant_numero})
                row = r.fetchone()
                if row and row[0]:
                    snapshot = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            except Exception as e:
                log.debug("autopsy.no_snapshot", err=str(e))
                try:
                    await session.rollback()  # désempoisonner la transaction
                except Exception:
                    pass

        autopsy: dict = {}

        # Signaux de marché manqués
        spi_score = float(snapshot.get("spi_score", 0))
        mouvement_30min = float(snapshot.get("mouvement_30min", 0))
        valeur_latente = float(snapshot.get("valeur_latente", 0))
        decote = float(snapshot.get("decote_detectee", 0))

        if spi_score > 0.2:
            autopsy["spi_manque"] = {
                "signal": "SPI élevé non exploité",
                "valeur": round(spi_score, 3),
                "action": "Augmenter poids SPI pour prochaines courses similaires",
            }

        if mouvement_30min > 0.15:
            autopsy["mouvement_cote_manque"] = {
                "signal": "Cote en forte baisse ignorée",
                "valeur": round(mouvement_30min, 3),
                "action": "Le mouvement de cote prédit mieux que prévu",
            }

        if valeur_latente > 0.3:
            autopsy["valeur_latente_manque"] = {
                "signal": "PMU surcotait ce cheval vs le marché",
                "valeur": round(valeur_latente, 3),
                "action": "Valeur latente = indicateur fort de sous-estimation modèle",
            }

        # Forme vs forme attendue
        forme_1 = float(snapshot.get("forme_1_course", 0))
        tendance = float(snapshot.get("forme_tendance", 0))
        fraicheur = float(snapshot.get("fraicheur_score", 0))

        if tendance > 0.3 and forme_1 > 0.5:
            autopsy["forme_montante"] = {
                "signal": "Cheval en progression forte (tendance positive)",
                "valeur": round(tendance, 3),
                "action": "Les chevaux en progression méritent un bonus de proba",
            }

        if fraicheur > 0.9 and float(snapshot.get("jours_repos", 30)) > 45:
            autopsy["repos_optimal"] = {
                "signal": "Long repos suivi d'un retour frais",
                "valeur": round(fraicheur, 3),
                "action": "Les retours après long repos bien préparés sont sous-évalués",
            }

        # Équipement nouveau
        equip_score = float(snapshot.get("equipement_score", 0))
        premier_deferre = float(snapshot.get("premier_deferre", 0))
        if equip_score > 0 or premier_deferre > 0:
            autopsy["equipement_nouveau"] = {
                "signal": "Changement d'équipement significatif",
                "valeur": max(equip_score, premier_deferre),
                "action": "Les équipements nouveaux (déferré, œillères) = signal de préparation",
            }

        # Qualité opposition (cheval meilleur que le niveau moyen)
        opp_quality = float(snapshot.get("opposition_quality", 0))
        elo_vs_moyenne = float(snapshot.get("elo_vs_moyenne", 0))
        if elo_vs_moyenne > 50 and winner.get("proba_top3", 0) < 0.35:
            autopsy["elo_sous_estime"] = {
                "signal": "ELO supérieur à la moyenne mais faible proba",
                "valeur": round(elo_vs_moyenne, 1),
                "action": "ELO discriminant dans ce contexte, augmenter son poids",
            }

        # Fingerprint historique fort (bon palmarès exact sur cette config)
        fp_score = float(snapshot.get("course_fingerprint_score", 0.5))
        fp_nb = int(snapshot.get("course_fingerprint_nb", 0))
        if fp_score > 0.6 and fp_nb >= 3:
            autopsy["fingerprint_fort"] = {
                "signal": f"Excellent bilan historique sur cette config exacte ({fp_nb} courses)",
                "valeur": round(fp_score, 3),
                "action": "Fingerprint de course = prédicteur très fiable à valoriser",
            }

        # Synergy jockey-cheval
        synergy = float(snapshot.get("jockey_cheval_synergy_score", 0))
        synergy_nb = int(snapshot.get("jockey_cheval_synergy_nb", 0))
        if synergy > 0.4 and synergy_nb >= 3:
            autopsy["synergy_jockey_cheval"] = {
                "signal": f"Synergie jockey-cheval forte ({synergy_nb} courses ensemble)",
                "valeur": round(synergy, 3),
                "action": "Ce duo gagne souvent ensemble — augmenter poids synergy",
            }

        # Résumé pédagogique
        autopsy["_resume"] = {
            "nb_signaux_manques": len([k for k in autopsy if not k.startswith("_")]),
            "proba_donnee": round(float(winner.get("proba_top3", 0)) * 100, 1),
            "signal_principal": list(autopsy.keys())[0] if [k for k in autopsy if not k.startswith("_")] else "aucun_signal_clair",
        }

        return autopsy

    async def _get_course_context(self, session: AsyncSession, course_id: str) -> dict:
        """Récupère le contexte de la course pour l'analyse des biais."""
        try:
            r = await session.execute(text("""
                SELECT discipline, terrain_officiel, hippodrome_nom, nb_partants,
                       est_quinte, date_heure, distance
                FROM courses
                WHERE course_id = :cid
            """), {"cid": course_id})
            row = r.fetchone()
            if row:
                return {
                    "discipline": (row[0] or "plat").lower(),
                    "terrain": (row[1] or "bon").lower(),
                    "hippodrome": (row[2] or "inconnu").lower(),
                    "nb_partants": int(row[3] or 10),
                    "est_quinte": bool(row[4]),
                    "date_heure": row[5],
                    "distance": int(row[6] or 2000),
                }
        except Exception as e:
            log.error("post_race.ctx_error", err=str(e))
        return {}

    async def _load_pos500(self, session: AsyncSession, course_id: str) -> dict:
        """Position à 500m du poteau par numéro (temps_passage). {} si indisponible."""
        try:
            r = await session.execute(text("""
                SELECT numero, position_500m FROM temps_passage
                WHERE course_id = :cid AND position_500m IS NOT NULL
            """), {"cid": course_id})
            return {int(row[0]): int(row[1]) for row in r.fetchall()}
        except Exception as e:
            log.warning("post_race.pos500_error", err=str(e))
            return {}

    async def _save_learning_log(
        self,
        session: AsyncSession,
        course_id: str,
        gagnant_numero: Optional[int],
        winner_predicted: set,
        gagnant_proba_ia: float,
        gagnant_cote_pmu: float,
        top3_precision: bool,
        brier_course: float,
        log_loss_course: float,
        was_surprise: bool,
        surprise_score: float,
        feature_autopsy: dict,
        ctx: dict,
    ) -> str:
        """
        Stocke l'analyse dans race_learning_log via l'ORM (aligné au schéma réel,
        migration 0005). Les champs hors schéma (gagnant réel, écart, précision…)
        sont conservés dans feature_autopsy["_meta"] — rien n'est perdu.
        """
        from db.models import RaceLearningLog
        from sqlalchemy import select as sa_select

        log_id = str(uuid.uuid4())
        date_heure = ctx.get("date_heure")
        # Rang prédit du gagnant réel (1/2/3 si dans le top-3 modèle, sinon 99).
        # Alimente accuracy_top1 / accuracy_top3 du palmarès public.
        wp = list(winner_predicted)
        gagnant_rang_predit = (wp.index(gagnant_numero) + 1) if gagnant_numero in wp else 99
        fa = dict(feature_autopsy or {})
        fa["_meta"] = {
            "winner_actual": gagnant_numero,
            "winner_predicted_top3": list(winner_predicted),
            "winner_cote_depart": gagnant_cote_pmu,
            "top3_precision": bool(top3_precision),
            "surprise_score": round(surprise_score, 4),
            "log_loss": round(log_loss_course, 6),
            "date_course": date_heure.isoformat() if hasattr(date_heure, "isoformat") else date_heure,
        }
        try:
            existing = (await session.execute(
                sa_select(RaceLearningLog).where(RaceLearningLog.course_id == course_id)
            )).scalar_one_or_none()

            if existing:
                existing.brier_score = round(brier_course, 6)
                existing.log_loss = round(log_loss_course, 6)
                existing.was_surprise = was_surprise
                existing.gagnant_proba_ia = round(gagnant_proba_ia, 4)
                existing.gagnant_rang_predit = gagnant_rang_predit
                existing.feature_autopsy = fa
                existing.discipline = ctx.get("discipline")
                existing.terrain = ctx.get("terrain")
                existing.hippodrome = ctx.get("hippodrome")
                existing.nb_partants = ctx.get("nb_partants")
                log_id = existing.log_id
            else:
                session.add(RaceLearningLog(
                    log_id=log_id,
                    course_id=course_id,
                    brier_score=round(brier_course, 6),
                    log_loss=round(log_loss_course, 6),
                    was_surprise=was_surprise,
                    gagnant_proba_ia=round(gagnant_proba_ia, 4),
                    gagnant_rang_predit=gagnant_rang_predit,
                    discipline=ctx.get("discipline"),
                    terrain=ctx.get("terrain"),
                    hippodrome=ctx.get("hippodrome"),
                    nb_partants=ctx.get("nb_partants"),
                    feature_autopsy=fa,
                ))
            # COMMIT propre : le log d'apprentissage est la donnée la plus importante,
            # on le persiste immédiatement pour qu'aucune étape ultérieure (biais,
            # adaptatif) ne puisse l'annuler en empoisonnant la transaction.
            await session.commit()
        except Exception as e:
            log.error("post_race.save_log_error", err=str(e))
            try:
                await session.rollback()
            except Exception:
                pass

        return log_id

    async def _update_bias_matrix(
        self,
        session: AsyncSession,
        ctx: dict,
        top3_precision: bool,
        was_surprise: bool,
    ) -> None:
        """
        Met à jour la matrice de biais systémiques.

        Biais détecté si pour une combinaison (discipline × terrain × hippodrome),
        le modèle se trompe significativement plus souvent que la moyenne.
        """
        if not ctx:
            return

        discipline = ctx.get("discipline", "plat")
        terrain = ctx.get("terrain", "bon")
        hippodrome = ctx.get("hippodrome", "inconnu")

        try:
            # Upsert aligné au schéma réel (bias_id, nb_courses, nb_surprises,
            # correction_factor). On suit le taux de surprise par contexte ;
            # si trop élevé sur assez de courses → correction négative de confiance.
            await session.execute(text("""
                INSERT INTO bias_matrix (
                    bias_id, bias_key, discipline, terrain, hippodrome,
                    nb_courses, nb_surprises, correction_factor, updated_at
                ) VALUES (
                    :bid, :key, :discipline, :terrain, :hippodrome,
                    1, :surprise, 0.0, NOW()
                )
                ON CONFLICT (bias_key) DO UPDATE SET
                    nb_courses = bias_matrix.nb_courses + 1,
                    nb_surprises = bias_matrix.nb_surprises + :surprise,
                    correction_factor = CASE
                        WHEN (bias_matrix.nb_courses + 1) >= :seuil_courses
                             AND (bias_matrix.nb_surprises + :surprise)::float /
                                 (bias_matrix.nb_courses + 1) > :seuil_erreur
                        THEN -0.05
                        ELSE 0.0
                    END,
                    updated_at = NOW()
            """), {
                "bid": str(uuid.uuid4()),
                "key": f"{discipline}|{terrain}|{hippodrome}",
                "discipline": discipline,
                "terrain": terrain,
                "hippodrome": hippodrome,
                "surprise": int(was_surprise),
                "seuil_courses": BIAIS_SEUIL_COURSES,
                "seuil_erreur": BIAIS_SEUIL_ERREUR,
            })
            await session.flush()
        except Exception as e:
            log.error("post_race.bias_update_error", err=str(e))
            try:
                await session.rollback()
            except Exception:
                pass

    async def get_performance_summary(
        self,
        session: AsyncSession,
        last_n: int = 50,
    ) -> dict:
        """
        Synthèse des performances récentes du modèle.
        Utilisé pour l'interface admin et pour déclencher le ré-entraînement.
        """
        try:
            r = await session.execute(text("""
                SELECT
                    COUNT(*) as total,
                    AVG(brier_course)::float as brier_moyen,
                    AVG(log_loss_course)::float as logloss_moyen,
                    SUM(CASE WHEN top3_precision THEN 1 ELSE 0 END)::float /
                        NULLIF(COUNT(*), 0) as precision_top3,
                    SUM(CASE WHEN was_surprise THEN 1 ELSE 0 END)::float /
                        NULLIF(COUNT(*), 0) as taux_surprise,
                    AVG(surprise_score)::float as surprise_score_moyen
                FROM race_learning_log
                ORDER BY created_at DESC
                LIMIT :n
            """), {"n": last_n})
            row = r.fetchone()
            if not row:
                return {}

            return {
                "nb_courses_analysees": int(row[0] or 0),
                "brier_moyen": round(float(row[1] or 1.0), 4),
                "logloss_moyen": round(float(row[2] or 10.0), 4),
                "precision_top3": round(float(row[3] or 0.0), 3),
                "taux_surprise": round(float(row[4] or 0.0), 3),
                "surprise_score_moyen": round(float(row[5] or 0.0), 3),
            }
        except Exception as e:
            log.error("post_race.summary_error", err=str(e))
            return {}

    async def get_bias_report(self, session: AsyncSession) -> list[dict]:
        """Retourne les biais systémiques confirmés."""
        try:
            r = await session.execute(text("""
                SELECT discipline, terrain, hippodrome, nb_courses,
                       taux_erreur, correction_factor
                FROM bias_matrix
                WHERE nb_courses >= :seuil AND correction_factor != 0
                ORDER BY taux_erreur DESC
                LIMIT 20
            """), {"seuil": BIAIS_SEUIL_COURSES})
            rows = r.fetchall()
            return [
                {
                    "contexte": f"{r[0]} × {r[1]} @ {r[2]}",
                    "nb_courses": int(r[3]),
                    "taux_erreur": round(float(r[4]), 3),
                    "correction_factor": round(float(r[5]), 3),
                    "alerte": float(r[4]) > 0.70,
                }
                for r in rows
            ]
        except Exception as e:
            log.error("post_race.bias_report_error", err=str(e))
            return []

    async def should_retrain(self, session: AsyncSession) -> tuple[bool, str]:
        """
        Décide si le modèle doit être ré-entraîné.

        Critères de déclenchement :
        - Brier moyen des 20 dernières courses > 0.22 (dégradation)
        - Taux de surprise > 45% (modèle systématiquement surpris)
        - >= 20 nouvelles courses avec résultat depuis le dernier entraînement
        """
        try:
            # Récupérer stats depuis dernier entraînement
            r = await session.execute(text("""
                SELECT
                    COUNT(*) as nb_nouvelles,
                    AVG(brier_course) as brier_recent,
                    SUM(CASE WHEN was_surprise THEN 1 ELSE 0 END)::float /
                        NULLIF(COUNT(*), 0) as taux_surprise
                FROM race_learning_log
                WHERE created_at > (
                    SELECT COALESCE(MAX(trained_at), '2000-01-01'::timestamp)
                    FROM model_versions WHERE is_active = true
                )
            """))
            row = r.fetchone()
            if not row or not row[0]:
                return False, "pas_assez_données"

            nb_nouvelles = int(row[0] or 0)
            brier_recent = float(row[1] or 0)
            taux_surprise = float(row[2] or 0)

            if brier_recent > 0.22:
                return True, f"brier_trop_élevé ({brier_recent:.3f} > 0.22)"
            if taux_surprise > 0.45:
                return True, f"trop_de_surprises ({taux_surprise:.1%} > 45%)"
            if nb_nouvelles >= 20:
                return True, f"{nb_nouvelles} nouvelles_courses_disponibles"

            return False, f"pas_encore ({nb_nouvelles}/20 courses, brier={brier_recent:.3f})"

        except Exception as e:
            log.error("post_race.should_retrain_error", err=str(e))
            return False, "erreur"
