"""
Pipeline ML BlackTurf — Auto-amélioration continue.
Adapté de BlackTurf_learning_pipeline.py pour PostgreSQL + RQ.

Flux :
  post_course()     → ELO + features + mini-retraining si N%20=0
  nightly()         → retraining complet 2h UTC
  predict_course()  → prédictions + value bets + recommandations
"""
import asyncio
import uuid
import structlog
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.database import AsyncSessionLocal
from db.models import (
    Course, Resultat, Participation, Prediction as PredictionModel,
    ValueBet as ValueBetModel, Recommandation, ModelVersion, FeatureML,
    Cheval, Jockey, Entraineur
)
from ml.elo import update_elo_after_race
from ml.features import compute_all_features_for_course
from ml.models import BlackTurfEnsemble, build_training_dataset
from ml.valuebets import detect_value_bet, save_value_bet, calculer_mise_kelly
from ml.recommendations import generer_recommandations_course, formater_fiche_recommandation
from ml.post_race_analyzer import PostRaceAnalyzer
from ml.adaptive_learning import get_adaptive_learning, initialize_adaptive_learning
from ml.drift_detector import get_drift_detector, initialize_drift_detector
from ml.meta_learner import get_meta_learner, get_contextual_corrector
from ml.narrative import generate_full_course_analysis, explain_prediction
from ml.portfolio import get_markowitz_optimizer, kelly_fraction_adaptatif, dutching_calculator
from api.config import get_settings

log = structlog.get_logger()
settings = get_settings()


# ─────────────────────────────────────────────
# Post-course pipeline
# ─────────────────────────────────────────────
async def run_post_course(course_id: str) -> None:
    """
    Exécuté immédiatement après la fin d'une course.
    Étapes : ELO → features → mini-retraining conditionnel.
    """
    log.info("pipeline.post_course.start", course_id=course_id)
    t0 = datetime.now()

    async with AsyncSessionLocal() as session:
        # Récupérer la course
        course = await session.get(Course, course_id)
        if not course:
            log.error("pipeline.post_course.course_not_found", course_id=course_id)
            return

        # Récupérer le résultat
        resultat = await session.get(Resultat, course_id)
        if not resultat:
            log.warning("pipeline.post_course.no_result", course_id=course_id)
            return

        # 1. Mise à jour ELO
        classement = [
            {
                "cheval_id": _get_cheval_id_from_resultat(r, resultat),
                "position": r.get("position"),
                "incident": r.get("incident"),
            }
            for r in resultat.classement
        ]
        classement_with_ids = await _enrich_classement_with_ids(session, course_id, resultat.classement)

        await update_elo_after_race(
            session=session,
            course_id=course_id,
            discipline=course.discipline,
            niveau_course=course.niveau_course,
            dotation=course.allocation,
            classement=classement_with_ids,
        )
        log.info("pipeline.post_course.elo_updated", course_id=course_id)

        # 2. Mise à jour stats jockey/entraîneur (cache simplifié)
        await _update_jockey_stats_cache(session, course_id, resultat.classement)

        # 3. Mise à jour features ML pour les futures courses
        await _save_historical_course(session, course, resultat)

        # 4. Log prédiction vs réalité
        await _log_prediction_accuracy(session, course_id, resultat.classement)

        # 5. Alertes résultats utilisateurs (via RQ)
        await _notify_result_subscribers(course_id)

        # 5b. Feature attribution — apprentissage contrastif gagnant vs perdants
        try:
            gagnant_num = None
            if resultat.classement:
                gagnant_entry = min(resultat.classement, key=lambda x: x.get("position") or 999)
                gagnant_num = gagnant_entry.get("numero")

            if gagnant_num is not None:
                from sqlalchemy import select as _sel
                # Features du gagnant
                gagnant_pid_r = await session.execute(_sel(Participation.participation_id).where(
                    Participation.course_id == course_id,
                    Participation.numero == int(gagnant_num),
                ))
                gagnant_pid = gagnant_pid_r.scalar_one_or_none()

                if gagnant_pid:
                    gagnant_feat_r = await session.execute(_sel(FeatureML.features).where(
                        FeatureML.participation_id == gagnant_pid
                    ))
                    gagnant_features = gagnant_feat_r.scalar_one_or_none() or {}

                    # Moyenne des features des perdants
                    all_feat_r = await session.execute(
                        _sel(FeatureML.features).join(
                            Participation, Participation.participation_id == FeatureML.participation_id
                        ).where(
                            Participation.course_id == course_id,
                            Participation.participation_id != gagnant_pid,
                        )
                    )
                    all_feats = [r[0] or {} for r in all_feat_r.fetchall()]

                    if all_feats and gagnant_features:
                        import pandas as _pd
                        # numeric_only : éviter de moyenner course_id/participation_id (str)
                        loser_avg = _pd.DataFrame(all_feats).mean(numeric_only=True).to_dict()

                        # Vérifier si modèle avait prédit le gagnant
                        was_correct = False
                        pred_r = await session.execute(_sel(PredictionModel).where(
                            PredictionModel.participation_id == gagnant_pid
                        ))
                        pred_obj = pred_r.scalar_one_or_none()
                        if pred_obj:
                            was_correct = pred_obj.rang_predit <= 3

                        al = get_adaptive_learning()
                        updates = al.update_from_feature_attribution(
                            winner_features=gagnant_features,
                            loser_features_avg=loser_avg,
                            was_correct=was_correct,
                        )
                        if updates:
                            log.info("pipeline.feature_attribution", updates=updates, was_correct=was_correct)

        except Exception as e:
            log.warning("pipeline.feature_attribution.failed", error=str(e))

        await session.commit()

    # ── 6. Apprentissage adaptatif post-course ───────────────────────────
    # PostRaceAnalyzer analyse le résultat, fait l'autopsie des features
    # manquées, met à jour la matrice de biais et envoie le signal
    # d'apprentissage à AdaptiveLearning (calibration température + poids).
    try:
        async with AsyncSessionLocal() as al_session:
            # ── Init paresseuse : le worker RQ n'a PAS de hook de démarrage,
            # donc DriftDetector / AdaptiveLearning ne sont jamais initialisés et
            # analyze_race échouait → commit sauté → race_learning_log vide.
            # On RECHARGE TOUJOURS l'état depuis la DB avant d'apprendre : le worker
            # RQ fork un process par job, donc le singleton mémoire repart à zéro à
            # chaque course. Sans load_state, n_races/temperature/brier_ema seraient
            # remis à 0 et écraseraient l'historique réel (bug : "1 course analysée").
            from ml.drift_detector import initialize_drift_detector
            from ml.adaptive_learning import initialize_adaptive_learning as _init_al
            await initialize_drift_detector(al_session)
            await _init_al(al_session)

            # ── Idempotence : une course déjà apprise ne doit JAMAIS être
            # ré-injectée dans le drift detector / l'état adaptatif. Sinon le
            # re-polling des résultats fait gonfler n_updates (ex: 2331 pour 78
            # courses) et déclenche de fausses "dérives critiques".
            already_learned = (await al_session.execute(
                text("SELECT 1 FROM race_learning_log WHERE course_id = :cid LIMIT 1"),
                {"cid": course_id},
            )).first() is not None

            if already_learned:
                log.info("pipeline.post_course.skip_already_learned", course_id=course_id)
                pred_rows = []
            else:
                # Charger les prédictions sauvegardées pour cette course
                pred_result = await al_session.execute(text("""
                    SELECT p.participation_id, p.proba_top3, p.proba_top1,
                           p.confidence_score, pa.numero
                    FROM predictions p
                    JOIN participations pa ON p.participation_id = pa.participation_id
                    WHERE p.course_id = :cid
                """), {"cid": course_id})
                pred_rows = pred_result.fetchall()

            if pred_rows:
                predictions_for_analysis = [
                    {
                        "participation_id": r[0],
                        "proba_top3": float(r[1] or 0),
                        "proba_top1": float(r[2] or 0),
                        "confidence_score": float(r[3] or 0),
                        "numero": r[4],
                    }
                    for r in pred_rows
                ]

                # Résultat officiel
                resultat_obj = await al_session.get(Resultat, course_id)
                resultat_for_analysis = {
                    "classement": resultat_obj.classement if resultat_obj else [],
                    "rapports": resultat_obj.rapports if resultat_obj else {},
                }

                analyzer = PostRaceAnalyzer()
                analyzer.adaptive_learning = get_adaptive_learning()  # câbler le signal d'apprentissage
                adaptive_learning_result = await analyzer.analyze_race(
                    session=al_session,
                    course_id=course_id,
                    predictions=predictions_for_analysis,
                    resultat=resultat_for_analysis,
                )

                # COMMIT IMMÉDIAT : persiste race_learning_log + bias_matrix AVANT
                # les étapes suivantes. Sinon une erreur d'un step ultérieur
                # empoisonne la transaction → le commit final devient un rollback
                # silencieux et race_learning_log reste vide.
                await al_session.commit()

                # ── État adaptatif (commit séparé, isolé) ──────────────────
                brier_val = float(adaptive_learning_result.get("brier_score") or 0.20)
                was_surp = bool(adaptive_learning_result.get("was_surprise", False))
                try:
                    al = get_adaptive_learning()
                    await al.save_state(al_session)
                    await al_session.commit()
                except Exception as e:
                    await al_session.rollback()
                    log.warning("pipeline.adaptive_save_skip", course_id=course_id, err=str(e)[:140])

                # ── Drift detection (commit séparé, isolé) ─────────────────
                drift_result = {}
                try:
                    drift_det = get_drift_detector()
                    drift_result = drift_det.update(
                        brier_score=brier_val,
                        was_surprise=was_surp,
                        prediction_confidence=float(adaptive_learning_result.get("gagnant_proba_ia") or 0.3),
                    )
                    await drift_det.save_state(al_session)
                    await al_session.commit()
                except Exception as e:
                    await al_session.rollback()
                    log.warning("pipeline.drift_save_skip", course_id=course_id, err=str(e)[:140])

                # Si drift critique → déclencher retraining immédiat
                if drift_result.get("severity") == "critical":
                    active_signals = [k for k, v in drift_result.get("signals", {}).items() if v]
                    log.warning(
                        "pipeline.drift.critical_detected",
                        course_id=course_id,
                        active_signals=active_signals,
                        triggering_retrain=True,
                    )
                    asyncio.create_task(_async_retrain_wrapper())

                log.info(
                    "pipeline.adaptive_learning.updated",
                    course_id=course_id,
                    temperature=adaptive_learning_result.get("adaptive_updates", {}).get("temperature"),
                    was_surprise=was_surp,
                    brier=brier_val,
                    drift_severity=drift_result.get("severity", "none"),
                )
    except Exception as e:
        log.error("pipeline.adaptive_learning.error", course_id=course_id, err=str(e))

    # 7. Mini-retraining si nb_resultats_depuis_dernier_retrain % 20 == 0
    nb_new = await _count_recent_results()
    if nb_new % settings.retrain_every_n_results == 0:
        log.info("pipeline.mini_retrain.triggered", nb_resultats=nb_new)
        await run_incremental_retraining()

    elapsed = (datetime.now() - t0).total_seconds()
    log.info("pipeline.post_course.done", course_id=course_id, elapsed_s=round(elapsed, 2))


async def run_incremental_retraining() -> None:
    """
    Retraining léger sur les 500 dernières courses.
    Plus rapide que le nightly complet.
    """
    log.info("pipeline.incremental_retrain.start")
    await _do_retraining(mois=3, label="incremental")


async def run_nightly_retraining() -> None:
    """
    Retraining complet nightly à 2h UTC.
    18 mois de données, validation, déploiement conditionnel.
    """
    log.info("pipeline.nightly_retrain.start")
    await _do_retraining(mois=18, label="nightly")


async def _do_retraining(mois: int, label: str) -> None:
    """Pipeline de retraining commun."""
    t0 = datetime.now()
    async with AsyncSessionLocal() as session:
        # Construire le dataset
        features_rows, resultats_dict = await _build_training_dataset_from_db(session, mois)
        # Seuil abaissé à 300 : amorçage sur vraies courses (le synthétique sert de
        # prior tant qu'on a peu de données réelles ; il sera remplacé dès qu'on a
        # un vrai modèle, cf. override est_synthetique ci-dessous).
        if len(features_rows) < 300:
            log.warning("pipeline.retrain.insufficient_data", nb_rows=len(features_rows))
            return

        X, y = build_training_dataset(features_rows, resultats_dict)
        if X.empty:
            log.error("pipeline.retrain.empty_dataset")
            return

        log.info("pipeline.retrain.dataset_ready", n=len(X), pos_rate=float(y.mean()))

        # Entraîner l'ensemble
        model = BlackTurfEnsemble()
        metrics = model.train(X, y)

        # Récupérer le modèle actuel pour comparaison
        current = BlackTurfEnsemble.load_current()
        current_auc = current.auc_roc if current else 0.0

        # Le modèle actif est-il synthétique ? (prior cold-start). Si oui, le 1er vrai
        # modèle le remplace inconditionnellement : son AUC synthétique est gonflé
        # (labels = fonction déterministe des features) et bloquerait sinon tout
        # apprentissage réel.
        current_is_synth = await session.scalar(text(
            "SELECT est_synthetique FROM model_versions WHERE est_actif = true "
            "ORDER BY version_num DESC LIMIT 1"
        ))

        # Déployer si : remplace un prior synthétique, OU pas de modèle, OU meilleur.
        seuil_regression = 0.005  # Tolérance 0.5%
        if current_is_synth or current is None or metrics["auc_roc"] >= current_auc - seuil_regression:
            version_num = await _get_next_version_num(session)
            model.deploy(version_num)

            # Enregistrer en DB
            mv = ModelVersion(
                version_id=str(uuid.uuid4()),
                version_num=version_num,
                nom_fichier=f"model_v{version_num:04d}.pkl",
                auc_roc=metrics["auc_roc"],
                brier_score=metrics["brier_score"],
                precision_top3=metrics["precision_top3"],
                roi_simule=metrics["roi_simule"],
                walk_forward_auc=metrics.get("walk_forward_auc"),
                walk_forward_variance=metrics.get("walk_forward_variance"),
                nb_courses_train=len(X),
                est_actif=True,
                est_synthetique=False,  # entraîné sur de vraies courses
                feature_importance=model.feature_importance,
            )
            session.add(mv)

            # Désactiver les anciennes versions
            await session.execute(
                update(ModelVersion)
                .where(ModelVersion.version_num < version_num)
                .values(est_actif=False)
            )

            log.info(
                "pipeline.retrain.deployed",
                version=version_num,
                auc=round(metrics["auc_roc"], 4),
                prev_auc=round(current_auc, 4),
            )
        else:
            log.warning(
                "pipeline.retrain.rollback",
                new_auc=round(metrics["auc_roc"], 4),
                current_auc=round(current_auc, 4),
            )

        await session.commit()

    elapsed = (datetime.now() - t0).total_seconds()
    log.info(f"pipeline.retrain.{label}.done", elapsed_min=round(elapsed / 60, 1))


# ─────────────────────────────────────────────
# Prédictions
# ─────────────────────────────────────────────
async def predict_course(course_id: str, user_bankroll: float = 100.0) -> Optional[dict]:
    """
    Génère les prédictions + recommandations pour une course à venir.
    """
    model = BlackTurfEnsemble.load_current()
    if not model:
        log.warning("pipeline.predict.no_model")
        return None

    async with AsyncSessionLocal() as session:
        course = await session.get(Course, course_id)
        if not course:
            return None

        # Calculer les features
        features_list = await compute_all_features_for_course(session, course_id)
        if not features_list:
            log.warning("pipeline.predict.no_features", course_id=course_id)
            return None

        # Sauvegarder les features en DB
        for feat in features_list:
            pid = feat.get("participation_id")
            if pid:
                stmt = pg_insert(FeatureML).values(
                    participation_id=pid,
                    features=feat,
                    computed_at=datetime.now(),
                ).on_conflict_do_update(
                    index_elements=["participation_id"],
                    set_={"features": feat, "computed_at": datetime.now()},
                )
                await session.execute(stmt)

        # Prédictions avec confiance (accord entre les 3 modèles)
        X = pd.DataFrame(features_list)
        probas_top3_raw, confidence_scores = model.predict_with_confidence(X)

        # ── Calibration adaptative (temperature scaling + biais contextuel) ──
        al = get_adaptive_learning()
        bias_correction = await al.get_bias_correction(
            session=session,
            discipline=course.discipline or "",
            terrain=course.terrain_officiel or "",
            hippodrome=course.hippodrome_nom or "",
        )
        # Temperature scaling + biais contextuel (AdaptiveLearning)
        probas_calibrated = al.apply_calibration(
            probas_top3_raw,
            context={
                "discipline": course.discipline,
                "terrain": course.terrain_officiel,
                "hippodrome": course.hippodrome_nom,
            },
            bias_correction=bias_correction,
        )

        # ── Meta-learner correction (Layer 3) ────────────────────────────
        # Applique le meta-learner ou le correcteur contextuel pour affiner
        # les probas en tenant compte des biais systématiques appris
        meta = get_meta_learner()
        corrector = get_contextual_corrector()
        probas_top3 = probas_calibrated.copy()

        if meta.is_trained:
            try:
                # Construire les contextes pour chaque partant
                contexts = []
                for feat in features_list:
                    contexts.append({
                        "discipline": course.discipline,
                        "terrain": course.terrain_officiel,
                        "hippodrome": course.hippodrome_nom,
                        "nb_partants": course.nb_partants or len(features_list),
                        "hour_of_day": course.date_heure.hour if course.date_heure else 14,
                        "est_quinte": int(course.est_quinte or False),
                        "jours_repos": feat.get("jours_repos", 30),
                        "cote_pmu": feat.get("cote_pmu", 5.0),
                        "rang_cote": feat.get("rang_cote", 5),
                        "elo_vs_moyenne": feat.get("elo_vs_moyenne", 0.0),
                        "forme_5_courses": feat.get("forme_5_courses", 0.5),
                        "spi_score": feat.get("spi_score", 0.0),
                        "season_month": feat.get("mois_course", 6),
                        "distance": course.distance or 2000,
                    })
                corrected = meta.predict_corrections_batch(
                    list(probas_calibrated), contexts
                )
                probas_top3 = np.array(corrected)
            except Exception as e:
                log.warning("pipeline.meta_learner.failed", err=str(e))
                # Fallback : correcteur contextuel simple
                for i, feat in enumerate(features_list):
                    ctx = {
                        "nb_partants": course.nb_partants or len(features_list),
                        "hour_of_day": course.date_heure.hour if course.date_heure else 14,
                        "discipline": course.discipline,
                        "distance": course.distance or 2000,
                    }
                    corrected_p = corrector.get_correction(
                        float(probas_calibrated[i]), ctx, bias_correction
                    )
                    probas_top3[i] = corrected_p
        else:
            # Pas encore entraîné → correction contextuelle simple
            for i, feat in enumerate(features_list):
                ctx = {
                    "nb_partants": course.nb_partants or len(features_list),
                    "hour_of_day": course.date_heure.hour if course.date_heure else 14,
                    "discipline": course.discipline,
                    "distance": course.distance or 2000,
                }
                probas_top3[i] = corrector.get_correction(
                    float(probas_calibrated[i]), ctx, bias_correction
                )

        # ── Normalisation probabiliste PAR COURSE (cohérence) ───────────────────
        # Sans ça, le modèle peut donner P(top3)~0.7 à plusieurs chevaux (dont des
        # outsiders) → P(top1) absurde (ex. 0.20 sur un 219/1) → faux value bets.
        # Contraintes réelles : exactement 1 gagnant (Σ P(top1)=1) et 3 placés
        # (Σ P(top3)=min(3, nb_partants)). On renormalise donc le champ.
        nb_partants = max(course.nb_partants or len(features_list), 3)
        p3_arr = np.clip(np.asarray(probas_top3, dtype=float), 1e-4, 0.999)
        n = len(p3_arr)

        # P(top1) ∝ P(top3)^gamma (γ>1 : les favoris concentrent davantage la victoire)
        raw_p1 = p3_arr ** 1.6
        s1 = float(raw_p1.sum())
        probas_top1 = (raw_p1 / s1) if s1 > 0 else np.full(n, 1.0 / n)

        # P(top3) renormalisé pour sommer à min(3, nb_partants), borné à 0.99
        target_sum3 = float(min(3.0, nb_partants))
        s3 = float(p3_arr.sum())
        probas_top3 = np.clip(p3_arr * (target_sum3 / s3), 0.0, 0.99) if s3 > 0 else p3_arr

        # ── Calibration par le marché (blend modèle × proba implicite PMU) ───────
        # Le marché PMU est un prior fort et bien calibré. On mélange la proba
        # modèle avec la proba implicite (1/cote, overround retiré). Ça calibre les
        # probas ET empêche un modèle imparfait d'attribuer 13% de victoire à un
        # 239/1 (proba implicite ~0.4%). ALPHA = confiance accordée au modèle.
        #
        # ALPHA ADAPTATIF (calibration empirique scripts/calibration_longshots.py) :
        # le modèle est bien calibré jusqu'à cote ~12 (ratio proba/réel 0.7-1.0) puis
        # sur-évalue les outsiders (ratio 1.76 sur cote 20-40) et "plafonne" ~0.043
        # quand le marché continue de décroître. On dégrade donc ALPHA avec la cote :
        # au-delà du seuil, le marché (mieux calibré) domine progressivement.
        ALPHA_MAX = 0.55          # confiance modèle sur favoris (cote ≤ ALPHA_FULL_COTE)
        ALPHA_MIN = 0.15          # plancher : sur gros outsiders le marché domine
        ALPHA_FULL_COTE = 12.0    # en-deçà : modèle de confiance
        ALPHA_DECAY = 0.022       # pente de décroissance par unité de cote au-delà du seuil
        cotes_pmu = np.array([float(f.get("cote_pmu") or 0.0) for f in features_list])
        alpha = np.clip(
            ALPHA_MAX - ALPHA_DECAY * np.maximum(cotes_pmu - ALPHA_FULL_COTE, 0.0),
            ALPHA_MIN, ALPHA_MAX,
        )
        implied = np.where(cotes_pmu > 1.0, 1.0 / cotes_pmu, 0.0)
        si = float(implied.sum())
        if si > 0:
            implied_norm = implied / si  # overround retiré, Σ=1
            # si une cote manque (implied=0), on garde la proba modèle pour ce cheval
            blend = np.where(
                implied > 0,
                alpha * probas_top1 + (1.0 - alpha) * implied_norm,
                probas_top1,
            )
            bs = float(blend.sum())
            if bs > 0:
                probas_top1 = blend / bs

        # Purge des value bets de la course avant recalcul : un partant qui n'est
        # PLUS un value bet (recalibré) doit disparaître, sinon des paris obsolètes
        # (ex. ancien EV gonflé) restent affichés. save_value_bet ne fait qu'upsert.
        await session.execute(
            text("DELETE FROM value_bets WHERE course_id = :cid"), {"cid": course_id}
        )

        # Récupérer version modèle active
        mv_result = await session.execute(
            select(ModelVersion).where(ModelVersion.est_actif == True)
        )
        mv = mv_result.scalars().first()
        mv_id = mv.version_id if mv else None

        # Rang prédit = ordre par PROBABILITÉ finale (proba_top1 desc, tiebreak top3).
        # Doit être cohérent avec les probas affichées + le plan de mise. Calculé ICI
        # sur les probas définitives (post calibration + blend marché), pas sur l'ordre
        # d'itération des features.
        _p1_arr = np.asarray(probas_top1, dtype=float)
        _p3_arr = np.asarray(probas_top3, dtype=float)
        _order = np.lexsort((-_p3_arr, -_p1_arr))  # primaire: -proba_top1, secondaire: -proba_top3
        _rang_by_index = np.empty(len(_order), dtype=int)
        for _k, _idx in enumerate(_order):
            _rang_by_index[int(_idx)] = _k + 1

        predictions = []
        for i, feat in enumerate(features_list):
            pid = feat.get("participation_id")
            proba_t3 = float(probas_top3[i])
            proba_t1 = float(probas_top1[i])

            # Rang prédit cohérent avec la proba finale
            rang = int(_rang_by_index[i])

            # Sauvegarder prédiction
            confidence = float(confidence_scores[i])
            pred_id = str(uuid.uuid4())
            stmt = pg_insert(PredictionModel).values(
                prediction_id=pred_id,
                participation_id=pid,
                course_id=course_id,
                model_version_id=mv_id,
                proba_top1=proba_t1,
                proba_top3=proba_t3,
                rang_predit=rang,
                confidence_score=round(confidence * 100, 2),  # accord des 3 modèles
                created_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=["participation_id"],
                set_={
                    "proba_top1": proba_t1,
                    "proba_top3": proba_t3,
                    "rang_predit": rang,
                    "confidence_score": round(confidence * 100, 2),
                },
            ).returning(PredictionModel.prediction_id)
            result = await session.execute(stmt)
            pred_id = result.scalar_one_or_none() or pred_id

            # Value bet — tous les bookmakers + suspension check
            cote_pmu     = feat.get("cote_pmu")
            cote_geny    = feat.get("cote_geny")
            cote_bzh     = feat.get("cote_bzh")
            cote_winamax = feat.get("cote_winamax")
            cote_betclic = feat.get("cote_betclic")
            cote_unibet  = feat.get("cote_unibet")
            cote_betfair = feat.get("cote_betfair_exchange")
            steam_betclic_pct = feat.get("steam_move_betclic", 0.0)
            if steam_betclic_pct:
                steam_betclic_pct = steam_betclic_pct * 100  # normalize back to %
            changement_j = bool(feat.get("changement_jockey", False))

            # Vérifier suspensions actives
            jockey_susp = False
            entraineur_susp = False
            if pid:
                from db.models import SuspensionProfessionnel
                from datetime import date as _date
                from sqlalchemy import select as _sel
                susp_q = await session.execute(_sel(
                    SuspensionProfessionnel.type_pro
                ).join(
                    Participation, Participation.participation_id == pid
                ).join(
                    Jockey, Jockey.jockey_id == Participation.jockey_id, isouter=True
                ).where(
                    SuspensionProfessionnel.est_active.is_(True),
                    SuspensionProfessionnel.date_debut <= _date.today(),
                ).limit(1))
                # Simplified check — use names from features
                jockey_nom = feat.get("jockey_nom", "")
                entraineur_nom = feat.get("entraineur_nom", "")
                if jockey_nom or entraineur_nom:
                    from sqlalchemy import text as _t
                    susp_r = await session.execute(_t("""
                        SELECT nom, type_pro FROM suspensions_professionnels
                        WHERE est_active = true AND nom = ANY(:noms)
                    """), {"noms": [n for n in [jockey_nom, entraineur_nom] if n]})
                    for s_nom, s_type in susp_r.fetchall():
                        if s_type == "jockey": jockey_susp = True
                        if s_type == "entraineur": entraineur_susp = True

            # Fetch cote history for SPI
            cotes_history = await _get_cotes_history(session, pid) if pid else None

            # Value bet GAGNANT : EV = cote_gagnant × P(victoire). On passe proba_t1
            # (proba de victoire normalisée), pas proba_t3 (placé) — sinon EV gonflé.
            vb = detect_value_bet(
                proba_t1,
                cote_pmu=cote_pmu,
                cote_geny=cote_geny,
                cote_bzh=cote_bzh,
                cote_winamax=cote_winamax,
                cote_betclic=cote_betclic,
                cote_unibet=cote_unibet,
                cote_betfair=cote_betfair,
                cotes_history=cotes_history,
                steam_move_betclic_pct=steam_betclic_pct,
                jockey_suspendu=jockey_susp,
                entraineur_suspendu=entraineur_susp,
            )
            niveau_vb = 0
            ev_max = 0.0
            if vb:
                await save_value_bet(session, pred_id, course_id, pid, vb)
                niveau_vb = vb["niveau"]
                ev_max = vb["ev_max"]

                # Alerte push si VB fort (niveau ≥ 2)
                if niveau_vb >= 2:
                    asyncio.create_task(_broadcast_value_bet_alert(
                        course_id=course_id,
                        nom_cheval=feat.get("nom", ""),
                        hippodrome=course.hippodrome_nom or "",
                        heure=course.date_heure.strftime("%H:%M") if course.date_heure else "",
                        vb=vb,
                        cote=cote_pmu,
                    ))

            predictions.append({
                "participation_id": pid,
                "numero": feat.get("rang_cote", i + 1),  # Approximation
                "nom": feat.get("nom", ""),
                "proba_top3": proba_t3,
                "proba_top1": proba_t1,
                "cote_pmu": cote_pmu,
                "cote_geny": cote_geny,
                "ev_max": ev_max,
                "niveau_vb": niveau_vb,
                "prediction_id": pred_id,
            })

        # Trier par proba de VICTOIRE décroissante (tiebreak top-3) et assigner les
        # rangs — même base que le rang_predit sauvegardé en DB (cohérence totale).
        predictions.sort(key=lambda x: (x["proba_top1"], x["proba_top3"]), reverse=True)
        for i, p in enumerate(predictions):
            p["rang_predit"] = i + 1

        # Alertes équipement et marché
        alertes_equip = await _get_alertes_equipement(session, course_id)
        alertes_marche = []  # Rempli par WebSocket live

        # Recommandations
        course_info = {
            "course_id": course_id,
            "hippodrome": course.hippodrome_nom,
            "heure": str(course.date_heure.time()) if course.date_heure else "",
            "discipline": course.discipline,
            "distance": course.distance,
            "terrain": course.terrain_officiel,
            "nb_partants": course.nb_partants,
            "est_quinte": course.est_quinte,
            "est_quarte": course.est_quarte,
            "est_tierce": course.est_tierce,
        }
        recos = generer_recommandations_course(predictions, course_info, bankroll=user_bankroll)

        # ── Remplacer les EV/probas HARDCODÉS des paris combinés par les valeurs
        # RÉELLES du moteur Plackett-Luce (intégrité : aucune valeur inventée). ──
        try:
            from ml.combo_bets import build_combo_proposals
            combo = build_combo_proposals(predictions, course_info, bankroll=user_bankroll)
            props = combo.get("proposals", [])
            combo_full = {c["type_pari"].lower(): c for c in props}            # ex "couplé placé"
            combo_cat = {}
            for c in props:                                                     # 1er par catégorie
                combo_cat.setdefault(c["type_pari"].split()[0].lower(), c)
            for reco in recos:
                t = reco["type_pari"]
                if t in ("Simple Gagnant", "Simple Placé"):
                    continue  # paris simples : EV déjà réel (ev_max du value bet)
                cp = combo_full.get(t.lower()) or combo_cat.get(t.split()[0].lower())
                if cp:
                    reco["ev_calcule"] = cp["ev"]            # EV réelle (P × rapport − 1)
                    reco["confidence"] = cp["proba_gain"]    # proba simulée
                    if cp.get("cout_total"):
                        reco["cout_total"] = cp["cout_total"]
        except Exception as e:
            log.warning("pipeline.combo_ev_override_failed", course_id=course_id, err=str(e)[:140])

        # Purge des anciennes recommandations de la course avant recalcul
        # (sinon doublons + vieilles EV obsolètes s'accumulent à chaque re-prédiction).
        await session.execute(
            text("DELETE FROM recommandations WHERE course_id = :cid"), {"cid": course_id}
        )

        # Sauvegarder recommandations en DB
        for reco in recos:
            r = Recommandation(
                reco_id=str(uuid.uuid4()),
                course_id=course_id,
                model_version_id=mv_id,
                niveau=reco["niveau"],
                type_pari=reco["type_pari"],
                chevaux_selectionnes=reco["chevaux"],
                mise_suggeree=reco.get("mise_suggeree"),
                ev_calcule=reco.get("ev_calcule"),
                confidence=reco.get("confidence"),
                texte_explication=reco.get("texte_explication"),
                nb_combinaisons=reco.get("nb_combinaisons"),
                cout_total=reco.get("cout_total"),
            )
            session.add(r)

        await session.commit()

        # Confiance globale = accord moyen des 3 modèles sur le top-3 prédit
        top3_indices = [i for i, p in enumerate(predictions) if p["rang_predit"] <= 3]
        if top3_indices:
            confidence_globale = float(np.mean([confidence_scores[i] for i in top3_indices[:3]]))
        else:
            confidence_globale = float(predictions[0]["proba_top3"]) if predictions else 0.5
        auc_modele = model.auc_roc if model else 0.65

        fiche = formater_fiche_recommandation(
            course_info=course_info,
            predictions=predictions,
            recos=recos,
            alertes_equipement=alertes_equip,
            alertes_marche=alertes_marche,
            confidence_globale=confidence_globale,
            auc_modele=auc_modele,
        )

        # ── Narrative IA (explication + analyse langage naturel) ─────────────
        try:
            features_by_pid = {f["participation_id"]: f for f in features_list if f.get("participation_id")}
            course_info_narrative = {**course_info,
                                     "penetrometre_coef": getattr(course, "penetrometre_coef", None)}
            # Ajouter VB dans predictions pour narrative
            preds_for_narrative = []
            for pred in predictions:
                pid = pred.get("participation_id")
                vb_for_pred = None
                if pid:
                    from sqlalchemy import select as _sel
                    from db.models import ValueBet as VBModel
                    vb_r = await session.execute(
                        _sel(VBModel).where(VBModel.participation_id == pid, VBModel.actif.is_(True))
                    )
                    vb_obj = vb_r.scalar_one_or_none()
                    if vb_obj:
                        vb_for_pred = {"ev_max": vb_obj.ev_max, "niveau": vb_obj.niveau,
                                       "spi_detected": vb_obj.spi_detected}
                preds_for_narrative.append({**pred, "vb": vb_for_pred})

            narrative_result = await generate_full_course_analysis(
                session=session,
                course_id=course_id,
                course_info=course_info_narrative,
                predictions=preds_for_narrative,
                features_by_pid=features_by_pid,
            )

            # Ajouter les explanations à la fiche
            if isinstance(fiche, dict):
                fiche["narrative"] = narrative_result.get("narrative", "")
                fiche["market_signals"] = narrative_result.get("market_signals", [])
                fiche["field_confidence"] = narrative_result.get("field_confidence", 0.5)
                # Merge explanations dans predictions de la fiche
                expl_by_num = {p.get("numero"): p.get("explanation") for p in narrative_result.get("predictions", [])}
                for pred_in_fiche in fiche.get("predictions", []):
                    num = pred_in_fiche.get("numero")
                    if num in expl_by_num:
                        pred_in_fiche["explanation"] = expl_by_num[num]

        except Exception as e:
            log.warning("pipeline.narrative.failed", error=str(e))

        # ── Markowitz mise optimale (en complément du Kelly standard) ────────
        try:
            markowitz = get_markowitz_optimizer()
            al_state = al.get_state_summary() if al else {}
            # Kelly adaptatif avec brier_ema et température
            for pred in predictions:
                ev = pred.get("ev_max", 0)
                cote = pred.get("cote_pmu", 5.0)
                if ev > 0.05 and cote and cote > 1.0:
                    mise_kelly_adapt = kelly_fraction_adaptatif(
                        ev=ev, cote=cote, bankroll=user_bankroll,
                        roi_recent=0.0,
                        brier_ema=al_state.get("brier_ema", 0.18),
                        temperature=al_state.get("temperature", 1.0),
                    )
                    pred["mise_kelly_adaptatif"] = mise_kelly_adapt

            # Dutch bet si ≥ 2 VBs dans la course avec EV positif
            vb_preds = [p for p in predictions if p.get("ev_max", 0) > 0.05 and p.get("cote_pmu")]
            if len(vb_preds) >= 2:
                dutch = dutching_calculator(
                    selections=[{"numero": p["numero"], "nom": p.get("nom", ""), "cote": p["cote_pmu"],
                                  "proba": p.get("proba_top1", 0.1)}
                                for p in vb_preds[:4]],
                    budget=min(user_bankroll * 0.05, 20.0),
                )
                if isinstance(fiche, dict) and dutch.get("is_profitable"):
                    fiche["dutch_bet"] = dutch

        except Exception as e:
            log.warning("pipeline.markowitz.failed", error=str(e))

        log.info("pipeline.predict.done", course_id=course_id, nb_predictions=len(predictions))
        return fiche


async def _async_retrain_wrapper() -> None:
    """Lance un retraining incrémental en tâche de fond (déclenché par drift critique)."""
    try:
        log.warning("pipeline.drift.retrain_triggered")
        await run_incremental_retraining()
    except Exception as e:
        log.error("pipeline.drift.retrain_failed", err=str(e))


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
async def _enrich_classement_with_ids(session: AsyncSession, course_id: str, classement: list) -> list:
    """Enrichit le classement avec les cheval_id depuis la DB."""
    result = await session.execute(text("""
        SELECT p.participation_id, p.cheval_id, p.numero
        FROM participations p
        WHERE p.course_id = :cid
    """), {"cid": course_id})
    part_map = {r[2]: r[1] for r in result.fetchall()}  # numero → cheval_id

    enriched = []
    for entry in classement:
        numero = entry.get("numero")
        cheval_id = part_map.get(numero)
        if cheval_id:
            enriched.append({
                "cheval_id": cheval_id,
                "position": entry.get("position"),
                "incident": entry.get("incident"),
            })
    return enriched


async def _get_alertes_equipement(session: AsyncSession, course_id: str) -> list[str]:
    """Récupère les alertes équipement pour une course."""
    result = await session.execute(text("""
        SELECT ch.nom, p.numero, e.premier_deferre, e.premieres_oeilleres, e.deferre_change
        FROM equipements e
        JOIN participations p ON e.participation_id = p.participation_id
        JOIN chevaux ch ON e.cheval_id = ch.cheval_id
        WHERE e.course_id = :cid AND (e.equipement_nouveau = true OR e.premier_deferre = true)
    """), {"cid": course_id})

    alertes = []
    for nom, numero, prem_def, prem_oeil, def_change in result.fetchall():
        if prem_def:
            alertes.append(f"🔔 N°{numero} {nom} — DÉFERRÉ POUR LA 1ÈRE FOIS — signal positif fort")
        elif def_change:
            alertes.append(f"🔔 N°{numero} {nom} — Changement de ferrage")
        if prem_oeil:
            alertes.append(f"🔔 N°{numero} {nom} — Nouvelles oeillères pour la 1ère fois")
    return alertes


async def _build_training_dataset_from_db(
    session: AsyncSession, mois: int
) -> tuple[list[dict], dict]:
    """Construit le dataset d'entraînement depuis PostgreSQL."""
    date_limite = datetime.now() - timedelta(days=mois * 30)

    # Récupérer les features sauvegardées avec leurs labels
    result = await session.execute(text("""
        SELECT
            fm.features,
            h.position_arrivee,
            h.cheval_id,
            p.course_id
        FROM features_ml fm
        JOIN participations p ON fm.participation_id = p.participation_id
        JOIN historique_courses h ON h.cheval_id = p.cheval_id AND h.course_id = p.course_id
        JOIN courses c ON p.course_id = c.course_id
        WHERE c.date_heure > :date_limite
          AND c.statut = 'termine'
          AND h.position_arrivee IS NOT NULL
          AND h.position_arrivee < 99
        ORDER BY c.date_heure
    """), {"date_limite": date_limite})

    rows = result.fetchall()
    features_list = []
    resultats_dict: dict[str, dict] = {}

    for feat_json, position, cheval_id, course_id in rows:
        feat = dict(feat_json)
        feat["cheval_id"] = cheval_id
        features_list.append(feat)

        if course_id not in resultats_dict:
            resultats_dict[course_id] = {}
        resultats_dict[course_id][cheval_id] = int(position)

    return features_list, resultats_dict


async def _get_next_version_num(session: AsyncSession) -> int:
    result = await session.execute(text("SELECT COALESCE(MAX(version_num), 0) + 1 FROM model_versions"))
    return result.scalar()


async def _get_cotes_history(session: AsyncSession, participation_id: str) -> list[float]:
    """Fetch chronological PMU cote history (cotes_historique hypertable) for SPI."""
    result = await session.execute(text("""
        SELECT cote FROM cotes_historique
        WHERE participation_id = :pid AND source = 'pmu' AND cote > 1.0
        ORDER BY time ASC
    """), {"pid": participation_id})
    rows = result.fetchall()
    return [float(r[0]) for r in rows]


async def _count_recent_results() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT COUNT(*) FROM resultats
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """))
        return result.scalar() or 0


async def _update_jockey_stats_cache(session: AsyncSession, course_id: str, classement: list) -> None:
    """
    Mise à jour incrémentale stats jockey/entraîneur post-course.
    UPSERT dans stats_jockeys / stats_entraineurs pour la saison courante.
    Le nightly recalcule taux_victoire_global / taux_place_global / ROI.
    """
    saison = date.today().year

    for entry in classement:
        pos = entry.get("position")
        if not pos or entry.get("incident"):
            continue

        part_result = await session.execute(text("""
            SELECT p.jockey_id, p.entraineur_id
            FROM participations p
            WHERE p.course_id = :cid AND p.numero = :num
        """), {"cid": course_id, "num": entry.get("numero")})
        part = part_result.fetchone()
        if not part:
            continue
        jockey_id, entraineur_id = part

        victoire = 1 if pos == 1 else 0
        place = 1 if pos <= 3 else 0

        # UPSERT stats_jockeys
        if jockey_id:
            await session.execute(text("""
                INSERT INTO stats_jockeys (stat_id, jockey_id, saison, victoires_saison, places_saison, courses_saison)
                VALUES (gen_random_uuid()::text, :jid, :saison, :v, :pl, 1)
                ON CONFLICT (jockey_id, saison) DO UPDATE SET
                    victoires_saison = stats_jockeys.victoires_saison + EXCLUDED.victoires_saison,
                    places_saison    = stats_jockeys.places_saison + EXCLUDED.places_saison,
                    courses_saison   = stats_jockeys.courses_saison + 1,
                    updated_at       = NOW()
            """), {"jid": jockey_id, "saison": saison, "v": victoire, "pl": place})

        # UPSERT stats_entraineurs
        if entraineur_id:
            await session.execute(text("""
                INSERT INTO stats_entraineurs (stat_id, entraineur_id, saison, victoires_saison, places_saison, courses_saison)
                VALUES (gen_random_uuid()::text, :eid, :saison, :v, :pl, 1)
                ON CONFLICT (entraineur_id, saison) DO UPDATE SET
                    victoires_saison = stats_entraineurs.victoires_saison + EXCLUDED.victoires_saison,
                    places_saison    = stats_entraineurs.places_saison + EXCLUDED.places_saison,
                    courses_saison   = stats_entraineurs.courses_saison + 1,
                    updated_at       = NOW()
            """), {"eid": entraineur_id, "saison": saison, "v": victoire, "pl": place})


async def _save_historical_course(session: AsyncSession, course: Course, resultat: Resultat) -> None:
    """Sauvegarde le résultat dans historique_courses pour enrichir l'historique."""
    from db.models import HistoriqueCourse
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for entry in resultat.classement:
        # Trouver le cheval_id
        part_result = await session.execute(text("""
            SELECT cheval_id, jockey_id FROM participations
            WHERE course_id = :cid AND numero = :num
        """), {"cid": course.course_id, "num": entry.get("numero")})
        part = part_result.fetchone()
        if not part:
            continue

        cheval_id, jockey_id = part
        jockey_nom = None
        if jockey_id:
            j = await session.get(Jockey, jockey_id)
            if j:
                jockey_nom = j.nom

        # ── Dynamique de course : réduction km + accélération finale ──────────
        # Dérivé du temps individuel + dernier 400 m (TempsPassage).
        # NULL si données absentes ou aberrantes — jamais fabriqué.
        from ml.race_dynamics import compute_reduction_km, compute_acceleration
        temps_indiv = entry.get("temps")
        reduction_km = compute_reduction_km(temps_indiv, course.distance)
        accel_idx = accel_label = None
        tp_row = await session.execute(text("""
            SELECT passage_dernier_400m FROM temps_passage
            WHERE course_id = :cid AND numero = :num
        """), {"cid": course.course_id, "num": entry.get("numero")})
        tp = tp_row.fetchone()
        if tp and tp[0]:
            accel = compute_acceleration(tp[0], temps_indiv, course.distance)
            if accel:
                accel_idx = accel["acceleration_index"]
                accel_label = accel["acceleration_label"]

        stmt = pg_insert(HistoriqueCourse).values(
            historique_id=str(uuid.uuid4()),
            cheval_id=cheval_id,
            course_id=course.course_id,
            date_course=course.date_heure.date() if course.date_heure else date.today(),
            hippodrome=course.hippodrome_nom,
            pays="FR",
            discipline=course.discipline,
            distance=course.distance,
            terrain=course.terrain_officiel,
            nb_partants=course.nb_partants,
            position_arrivee=entry.get("position"),
            incident=entry.get("incident"),
            temps_officiel=(str(entry.get("temps")) if entry.get("temps") is not None else None),
            allocation=course.allocation,
            niveau_course=course.niveau_course,
            jockey_course=jockey_nom,
            gains_rapportes=entry.get("gains"),
            reduction_km=reduction_km,
            acceleration_index=accel_idx,
            acceleration_label=accel_label,
        ).on_conflict_do_update(
            # index unique partiel (cheval_id, course_id) WHERE course_id IS NOT NULL
            # → un seul historique par cheval & course interne (pas de doublon au re-run)
            index_elements=["cheval_id", "course_id"],
            index_where=text("course_id IS NOT NULL"),
            set_={
                "position_arrivee": entry.get("position"),
                "incident": entry.get("incident"),
                "temps_officiel": (str(entry.get("temps")) if entry.get("temps") is not None else None),
                "reduction_km": reduction_km,
                "acceleration_index": accel_idx,
                "acceleration_label": accel_label,
            },
        )
        await session.execute(stmt)


async def _log_prediction_accuracy(session: AsyncSession, course_id: str, classement: list) -> None:
    """Log la précision des prédictions vs le résultat réel."""
    # Récupérer les prédictions existantes
    result = await session.execute(text("""
        SELECT pr.prediction_id, pr.rang_predit, pr.proba_top3,
               p.cheval_id
        FROM predictions pr
        JOIN participations p ON pr.participation_id = p.participation_id
        WHERE pr.course_id = :cid
    """), {"cid": course_id})
    predictions = result.fetchall()

    # Map cheval_id → position réelle
    pos_reelle = {}
    for entry in classement:
        # On cherche le cheval_id via le numero
        pr = await session.execute(text("""
            SELECT cheval_id FROM participations WHERE course_id = :cid AND numero = :num
        """), {"cid": course_id, "num": entry.get("numero")})
        row = pr.fetchone()
        if row:
            pos_reelle[row[0]] = entry.get("position")

    # Simple log — pas de mise à jour en DB pour ne pas perdre l'historique
    nb_top3_correct = 0
    for pred_id, rang_predit, proba, cheval_id in predictions:
        pos_real = pos_reelle.get(cheval_id)
        if pos_real is not None and pos_real <= 3 and rang_predit <= 3:
            nb_top3_correct += 1

    log.info(
        "pipeline.accuracy_log",
        course_id=course_id,
        nb_predictions=len(predictions),
        nb_top3_correct=nb_top3_correct,
    )


async def _notify_result_subscribers(course_id: str) -> None:
    """Envoie les alertes résultats aux utilisateurs abonnés."""
    # Délégué au worker via RQ (sync wrapper)
    try:
        import redis as redis_sync
        from rq import Queue
        r = redis_sync.from_url(settings.redis_url)
        q = Queue(connection=r)
        q.enqueue("ml.pipeline.post_course_sync", course_id)
    except Exception as e:
        log.warning("pipeline.notify_subscribers.failed", error=str(e))


def _get_cheval_id_from_resultat(entry: dict, resultat: Resultat) -> str:
    return entry.get("cheval_id", "")


async def _broadcast_value_bet_alert(
    course_id: str,
    nom_cheval: str,
    hippodrome: str,
    heure: str,
    vb: dict,
    cote: Optional[float],
) -> None:
    """
    Diffuse un value bet via :
    - Redis pub/sub → tous les WS connectés
    - Push notifications → utilisateurs abonnés avec push_subscription
    """
    try:
        from api.routes.ws import broadcast_alert
        from services.alerts import send_web_push, send_inapp
        from db.database import AsyncSessionLocal

        etoiles = "⭐" * vb["niveau"]
        payload = {
            "type": "value_bet",
            "vb_id": None,
            "course_id": course_id,
            "nom_cheval": nom_cheval,
            "hippodrome": hippodrome,
            "heure": heure,
            "cote": cote,
            "ev": round(vb["ev_max"], 4),
            "niveau": vb["niveau"],
            "spi_detected": vb.get("spi_detected", False),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # Broadcast WebSocket (tous les users connectés)
        await broadcast_alert(payload)

        # Push notifications aux users abonnés standard+
        if vb["niveau"] >= 2:
            async with AsyncSessionLocal() as session:
                from db.models import User
                from sqlalchemy import select
                users_res = await session.execute(
                    select(User).where(
                        User.push_subscription.isnot(None),
                        User.is_active == True,
                        User.plan.in_(["starter", "standard", "pro", "expert"]),
                    )
                )
                users = users_res.scalars().all()
                for user in users:
                    await send_web_push(
                        subscription=user.push_subscription,
                        title=f"Value Bet {etoiles} — {nom_cheval}",
                        body=f"{hippodrome} {heure} · EV +{round(vb['ev_max']*100, 1)}%",
                        data=payload,
                    )

    except Exception as e:
        log.error("pipeline.broadcast_vb.failed", error=str(e))


# ─────────────────────────────────────────────
# RQ-callable wrapper (sync, runs in worker)
# ─────────────────────────────────────────────
def retrain_if_needed() -> None:
    """Sync wrapper for RQ — runs nightly retraining in the worker process."""
    import asyncio
    asyncio.run(run_nightly_retraining())


def post_course_sync(course_id: str) -> None:
    """Sync wrapper for RQ — post-course pipeline (ELO, features, notifications)."""
    import asyncio
    asyncio.run(run_post_course(course_id))
