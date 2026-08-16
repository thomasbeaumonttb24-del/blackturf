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

# Plancher de qualité absolu pour la mise en production d'un modèle. Un walk-forward
# AUC sous ce seuil = modèle au mieux aléatoire (0.5) / au pire inversé → JAMAIS déployé.
# 0.52 laisse une petite marge au-dessus du hasard pur tout en bloquant les runs cassés.
MIN_DEPLOYABLE_AUC = 0.52


def _should_deploy(
    new_wf: float,
    current_wf: float,
    *,
    current_is_synth: bool,
    no_current: bool,
    current_unreliable: bool,
    data_jump: bool,
    seuil_regression: float = 0.005,
    min_auc: float = MIN_DEPLOYABLE_AUC,
    roi_gate_enabled: bool = False,
    betting_edge_ok: bool = True,
    h2h_delta: Optional[float] = None,
    h2h_tolerance: float = 0.002,
) -> bool:
    """Décide si un nouveau modèle doit être promu en production (logique pure, testable).

    GARDE-FOU ABSOLU d'abord : sous `min_auc` (walk-forward), on ne déploie JAMAIS, quelle
    que soit la situation de l'actif. C'est ce plancher qui manquait et qui a laissé un
    modèle à AUC 0.06 passer en prod (l'actif "non fiable" déployait n'importe quoi).

    ARBITRE DE RANKING — `h2h_delta` (AUC_challenger − AUC_champion, mesurés sur le MÊME
    hold-out hors-échantillon pour les deux) quand il est disponible, sinon repli sur la
    comparaison des walk-forward.

    Pourquoi : le walk-forward RÉ-ENTRAÎNE un XGB rapide sur des folds du dataset
    COURANT — c'est une mesure du DATASET, pas du modèle. Comparer le wf d'un challenger
    au wf STOCKÉ d'un champion entraîné sur une autre génération de données revient à
    comparer deux datasets, et le champion gagne mécaniquement. Constat 2026-08-16 :
    référence figée à 0.8104 (juin, 151k lignes) vs challengers stables à 0.794
    (août, 168k lignes) → 14 rejets d'affilée, modèle gelé 48 jours. `h2h_delta` est la
    seule comparaison honnête entre deux modèles.

    FLAG roi_deploy_gate : si `roi_gate_enabled`, la couche PARIS doit prouver un edge
    hors-échantillon (`betting_edge_ok`, ex. edge_monitor edge_ok). MAIS cette gate ne
    bloque QUE la promotion d'un modèle SANS mérite de ranking. Un meilleur CLASSEUR est
    toujours promu : il améliore les pronostics affichés, sans placer d'argent. Le ROI/edge
    est une couche distincte (staking, BT_STAKING_SAFE) gérée à part. Sans ce dégel, un
    edge durablement négatif (audit -52%) figerait le modèle À VIE — exactement le blocage
    du 2026-06-19 (wf 0.8165>0.8141 rejeté à tort en `worse_wf`).

    Ensuite seulement : on déploie si l'actif est synthétique / absent / non fiable, OU
    saut de données massif, OU mérite de ranking (tolérance régression).
    """
    if new_wf < min_auc:
        return False
    # Remplacement STRUCTUREL de l'actif : actif synthetique / absent / non fiable
    # (trop peu de courses) / saut de donnees massif (nouveau modele entraine sur
    # >=1.5x plus de donnees). Ces cas justifient la promotion independamment du
    # walk-forward (cf data_jump : le wf est optimiste sur peu de donnees).
    structural_replace = (
        current_is_synth or no_current or current_unreliable or data_jump
    )
    # Mérite de ranking : head-to-head si mesuré, sinon walk-forward (repli).
    if h2h_delta is not None:
        ranking_improvement = h2h_delta >= 0.0
        ranking_acceptable = h2h_delta >= -h2h_tolerance
    else:
        ranking_improvement = new_wf >= current_wf
        ranking_acceptable = new_wf >= current_wf - seuil_regression
    # Gate ROI : ne fige PAS un mérite de ranking NI un remplacement structurel (ex.
    # modele 18 mois remplacant un modele a fenetre courte sur-ajuste dont le wf gonfle
    # bloquait tout -- bug 2026-06-29 : roi_gate court-circuitait avant data_jump).
    if (roi_gate_enabled and not betting_edge_ok
            and not ranking_improvement and not structural_replace):
        return False
    return structural_replace or ranking_acceptable


def _edge_undecidable(em: dict) -> bool:
    """L'edge_monitor a-t-il assez de matière pour CONCLURE quoi que ce soit ?

    `compute_edge_monitor` signale l'insuffisance par DEUX clés distinctes :
      - `insufficient` : dataset global < 500 lignes (cas d'amorçage, quasi jamais) ;
      - `enough_filt`  : moins de `min_filt` paris retenus par le filtre de conviction
                         — LE cas courant en régime normal.
    Dans les deux cas `edge_ok` vaut False PAR CONSTRUCTION, ce qui ne veut pas dire
    « edge prouvé mauvais » mais « indécidable ».

    Régression protégée (2026-08-16) : le pipeline ne testait que `insufficient`, une
    clé qui n'apparaît jamais en régime normal. En prod, `n_filt=25 < min_filt=50`
    donnait donc edge_ok=False lu au premier degré → roi_gate bloquait → 14 rejets
    consécutifs, modèle gelé 48 jours.
    """
    return bool(em.get("insufficient")) or not em.get("enough_filt", True)


def _edge_gate_ok(em: dict) -> bool:
    """Valeur à passer à `_should_deploy(betting_edge_ok=…)`.

    Indécidable → True (on ne bloque pas sur du bruit). Sinon on lit `edge_ok`.
    """
    if _edge_undecidable(em):
        return True
    return bool(em.get("edge_ok", True))


# Taille minimale de l'échantillon d'arbitrage. Sous ce seuil l'AUC est du bruit :
# on préfère « indécidable » (repli walk-forward) à une promotion sur 200 lignes.
H2H_MIN_ROWS = 2000


async def _head_to_head_auc(
    session: AsyncSession,
    challenger: BlackTurfEnsemble,
    X_hold: pd.DataFrame,
    y_hold: pd.Series,
    current_mv: Optional[ModelVersion],
) -> Optional[dict]:
    """AUC du champion ET du challenger sur EXACTEMENT le même échantillon.

    L'échantillon = le hold-out temporel du challenger (courses qu'il n'a pas vues),
    RESTREINT aux courses postérieures à la création du champion — donc hors-échantillon
    pour les DEUX modèles. Sans cette restriction le champion aurait un avantage
    mécanique : il a été entraîné sur une partie de ce hold-out.

    Coût : de l'inférence pure, pas de ré-entraînement. Le champion est chargé puis
    libéré immédiatement (le garder en RAM à côté du challenger ET du dataset était la
    cause de l'OOM en phase de promotion, cf. commentaire de _do_retraining).

    Retourne None quand la comparaison n'est pas fiable (pas de champion, échantillon
    trop mince, features incompatibles) → l'appelant retombe sur le walk-forward.
    """
    if current_mv is None or getattr(current_mv, "created_at", None) is None:
        return None
    if "course_id" not in X_hold.columns or len(X_hold) == 0:
        return None

    try:
        rows = await session.execute(
            text("SELECT course_id FROM courses WHERE date_heure > :cutoff"),
            {"cutoff": current_mv.created_at},
        )
        oos_courses = {r[0] for r in rows}
    except Exception as e:
        log.warning("pipeline.h2h.courses_query_failed", err=str(e)[:160])
        return None

    mask = X_hold["course_id"].isin(oos_courses).to_numpy()
    n_rows = int(mask.sum())
    if n_rows < H2H_MIN_ROWS:
        log.info("pipeline.h2h.sample_too_small", n_rows=n_rows, min_rows=H2H_MIN_ROWS)
        return None

    X_oos, y_oos = X_hold[mask], y_hold[mask]
    if y_oos.nunique() < 2:
        return None

    import gc
    from sklearn.metrics import roc_auc_score

    try:
        champion = BlackTurfEnsemble.load_current()
        if champion is None:
            return None
        # predict_proba reindexe sur ses propres feature_names → tolère une dérive
        # du schéma de features entre les deux générations.
        auc_champion = float(roc_auc_score(y_oos, champion.predict_proba(X_oos)))
    except Exception as e:
        log.warning("pipeline.h2h.champion_scoring_failed", err=str(e)[:160])
        return None
    finally:
        champion = None
        gc.collect()

    try:
        auc_challenger = float(roc_auc_score(y_oos, challenger.predict_proba(X_oos)))
    except Exception as e:
        log.warning("pipeline.h2h.challenger_scoring_failed", err=str(e)[:160])
        return None

    delta = auc_challenger - auc_champion
    n_courses = int(X_oos["course_id"].nunique())
    log.info("pipeline.h2h.measured",
             auc_challenger=round(auc_challenger, 4), auc_champion=round(auc_champion, 4),
             delta=round(delta, 4), n_rows=n_rows, n_courses=n_courses)
    return {
        "auc_challenger": auc_challenger,
        "auc_champion": auc_champion,
        "delta": delta,
        "n_rows": n_rows,
        "n_courses": n_courses,
    }


# Part minimale du champ devant avoir une cote réelle pour que l'overround calculé
# soit fiable. Sous ce seuil, la somme des probas implicites SOUS-COMPTE l'overround
# réel (des partants pesants manquent) et peut tomber près de 0.
MIN_OVERROUND_COVERAGE = 0.70


def compute_field_overround(features_list: list[dict]) -> Optional[float]:
    """Overround du champ = Σ probas implicites marché pondérées (cf. cote_marche_ponderee).

    Sert à dé-vigger les gates value bet (`ml.valuebets.detect_value_bet`) : la
    proba implicite brute 1/cote contient la marge bookmaker (~12-20% overround)
    → comparaison biaisée sans correction.

    GARDE-FOU COUVERTURE (2026-08-16, audit "value bets en extinction", 27/mois en
    août contre 1170/mois en juin). Si seule une minorité des partants a une cote,
    la somme sous-compte l'overround réel et peut tomber près de 0.
    `implied_marche / field_overround` DIVISE alors par ce quasi-zéro → explose
    vers l'infini → le gate anti-longshot (`proba_top1 > MAX_MODEL_MARKET_RATIO *
    implied_marche`) ne se déclenche PLUS JAMAIS (rien ne peut dépasser l'infini) :
    une couverture cotes faible désactivait silencieusement le garde-fou au lieu de
    le renforcer — l'inverse de l'effet recherché. En pratique la couverture PMU du
    jour est bonne (~85-100%), donc rarement déclenché, mais le défaut était réel
    (champ clairsemé, réunion étrangère mal couverte, panne de scraping) et sans
    filet. On n'utilise donc l'overround QUE si au moins MIN_OVERROUND_COVERAGE du
    champ a une cote réelle ; sinon None, qui fait tourner le gate SANS dé-vig
    (comparaison au marché brut, plus prudente — cf. detect_value_bet) plutôt que
    de le neutraliser.
    """
    from ml.valuebets import cote_marche_ponderee

    if not features_list:
        return None

    total_implied = 0.0
    n_priced = 0
    for f in features_list:
        cote = cote_marche_ponderee({
            "pmu": f.get("cote_pmu"), "geny": f.get("cote_geny"),
            "bzh": f.get("cote_bzh"), "winamax": f.get("cote_winamax"),
            "betclic": f.get("cote_betclic"), "unibet": f.get("cote_unibet"),
            "betfair": f.get("cote_betfair_exchange"),
        })
        if cote and cote > 1.0:
            total_implied += 1.0 / cote
            n_priced += 1

    coverage = n_priced / len(features_list)
    if total_implied <= 0 or coverage < MIN_OVERROUND_COVERAGE:
        return None
    return total_implied


# ─────────────────────────────────────────────
# Capture cote de clôture (fondation CLV)
# ─────────────────────────────────────────────
async def _capture_closing_cotes(course_id: str) -> None:
    """Fige la cote PMU de CLÔTURE (dernière scrapée ~départ) + la cote_figee (T-10) de
    chaque partant dans cote_cloture_log. Base de la métrique CLV (bat-on la ligne de
    clôture ?). Idempotent (ON CONFLICT DO NOTHING : la 1re capture après l'off gagne).
    Best-effort : tout échec est avalé, n'interrompt jamais l'apprentissage post-course.

    NB : tant que le scraper ne rafraîchit pas les cotes dans les dernières minutes,
    cote_cloture ≈ cote_figee (la cote PMU se fige ~T-10). L'étape suivante = scrape
    haute fréquence near-off pour capturer le vrai mouvement de clôture."""
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("""
                CREATE TABLE IF NOT EXISTS cote_cloture_log (
                    participation_id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    numero INT,
                    cote_cloture DOUBLE PRECISION,
                    cote_figee DOUBLE PRECISION,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            await s.execute(text("""
                INSERT INTO cote_cloture_log (participation_id, course_id, numero, cote_cloture, cote_figee)
                SELECT pa.participation_id, pa.course_id, pa.numero, pa.cote_pmu, pr.cote_figee
                FROM participations pa
                LEFT JOIN predictions pr ON pr.participation_id = pa.participation_id
                WHERE pa.course_id = :cid AND pa.non_partant = false AND pa.cote_pmu > 1
                ON CONFLICT (participation_id) DO NOTHING
            """), {"cid": course_id})
            await s.commit()
        log.info("pipeline.closing_cotes_captured", course_id=course_id)
    except Exception as e:
        log.warning("pipeline.closing_cotes_skip", course_id=course_id, err=str(e)[:140])


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

        # 0. Snapshot cote de CLÔTURE (fondation CLV). La course vient de finir → la cote
        # PMU a cessé d'évoluer ; pa.cote_pmu = dernière scrapée ≈ ligne de clôture. On la
        # fige (+ cote_figee T-10) une fois pour mesurer plus tard si on bat la clôture.
        await _capture_closing_cotes(course_id)

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
                           p.confidence_score, pa.numero, p.rang_predit
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
                        "rang_predit": int(r[5]) if r[5] is not None else None,
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

    # ── 6b. Invalider les caches stats : à CHAQUE fin de course, les chiffres
    # (performance IA, précision Top-3, équity, track-record) doivent refléter le
    # résultat tout juste tombé — sinon ils restent figés jusqu'à expiration TTL
    # (2-30 min). On purge les clés → recalcul à la volée sur données RÉELLES.
    await _invalidate_stats_caches(course_id)

    # ── 6c. Régler les paris enregistrés (TOUS les utilisateurs) de la course qui
    # vient de finir → bankroll + back-office admin à jour immédiatement, sans
    # attendre que chaque utilisateur consulte son compte. Vrais rapports PMU.
    try:
        from api.routes.bankroll import settle_pending_bets
        async with AsyncSessionLocal() as settle_session:
            await settle_pending_bets(settle_session, None)  # None = tous les users
    except Exception as e:
        log.warning("pipeline.settle_all_skip", course_id=course_id, err=str(e)[:140])

    # ── 6d. Régler les PRONOS ÉMIS PAR PROFIL (profil_run_log) sur cette course :
    # l'apprentissage se fait sur les recommandations réellement émises (figées
    # avant course), réglées aux vrais rapports PMU — pas sur le top-3 du modèle.
    try:
        from ml.profil_learning import settle_profil_runs, compute_profil_weights
        async with AsyncSessionLocal() as pl_session:
            n_pl = await settle_profil_runs(pl_session, course_id)
            if n_pl:
                # Recalcul léger des poids appris → la prochaine sélection en profite.
                await compute_profil_weights(pl_session)
                # Recalcul de la calibration estimé→réel du rapport (par profil × type) :
                # les bandes de cote restent fidèles aux paiements PMU réels les plus récents.
                try:
                    from ml.signal_performance import (
                        compute_rapport_calibration, persist_rapport_calibration)
                    _rc = await compute_rapport_calibration(pl_session)
                    await persist_rapport_calibration(pl_session, _rc)
                except Exception as e:
                    log.warning("pipeline.rapport_calib_skip", course_id=course_id, err=str(e)[:140])
    except Exception as e:
        log.warning("pipeline.profil_learning_settle_skip", course_id=course_id, err=str(e)[:140])

    # 7. Mini-retraining si nb_resultats_depuis_dernier_retrain % 20 == 0
    # COOLDOWN (anti-flood) : _count_recent_results() reste à un multiple du seuil sur une
    # fenêtre → SANS cooldown, CHAQUE post-course re-déclenchait un retrain complet (47k
    # lignes, ~2 min, lourd) toutes les 2-4 min, surtout au reboot quand le backlog de
    # résultats se règle → pic mémoire/CPU permanent (cause d'OOM sur 8 Go). Le cooldown
    # Redis (clé auto-expirante) borne à 1 retrain incrémental / RETRAIN_COOLDOWN_S. Le
    # nightly complet (scheduler 02:00) reste indépendant.
    nb_new = await _count_recent_results()
    if nb_new % settings.retrain_every_n_results == 0:
        if await _incr_retrain_cooldown_active():
            log.info("pipeline.mini_retrain.cooldown_skip", nb_resultats=nb_new)
        else:
            await _set_incr_retrain_cooldown(RETRAIN_COOLDOWN_S)
            log.info("pipeline.mini_retrain.triggered", nb_resultats=nb_new)
            await run_incremental_retraining()

    elapsed = (datetime.now() - t0).total_seconds()
    log.info("pipeline.post_course.done", course_id=course_id, elapsed_s=round(elapsed, 2))


async def _invalidate_stats_caches(course_id: str) -> None:
    """Purge les caches de stats agrégées + la fiche de la course finie, pour que le
    dashboard/track-record reflètent immédiatement le nouveau résultat (données réelles
    recalculées au prochain appel). Best-effort : un échec Redis n'interrompt rien."""
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        keys = [
            "stats:public", "stats:equity-curve", "stats:ml-status",
            "stats:dashboard-summary",
            # NB: stats:track-record + stats:profils retires de la purge immediate
            # (recalcul froid ~2s). Geres par TTL 1h + job warm_caches /30min.
            f"course_detail:{course_id}", f"analyse:{course_id}",
        ]
        await redis.delete(*keys)
        log.info("pipeline.stats_cache_invalidated", course_id=course_id, n_keys=len(keys))
    except Exception as e:
        log.warning("pipeline.stats_cache_invalidate_skip", err=str(e)[:140])


# Délai minimal entre deux retrains INCRÉMENTAUX (post-course). 6 h → au plus 4/jour,
# au lieu d'un toutes les 2-4 min. Les nouveaux résultats restent appris (au prochain
# créneau), mais on supprime le pic mémoire/CPU permanent qui saturait le VPS 8 Go.
RETRAIN_COOLDOWN_S = 6 * 3600
_INCR_RETRAIN_COOLDOWN_KEY = "ml:incr_retrain_cooldown"


async def _incr_retrain_cooldown_active() -> bool:
    """True si un retrain incrémental a tourné récemment (clé Redis non expirée)."""
    try:
        from db.redis_client import get_redis
        r = await get_redis()
        return bool(await r.exists(_INCR_RETRAIN_COOLDOWN_KEY))
    except Exception:
        return False        # Redis indispo → ne pas bloquer le retrain


async def _set_incr_retrain_cooldown(seconds: int) -> None:
    try:
        from db.redis_client import get_redis
        r = await get_redis()
        await r.set(_INCR_RETRAIN_COOLDOWN_KEY, "1", ex=int(seconds))
    except Exception:
        pass


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
    # Recalcule la calibration longshots sur toutes les données réelles à jour
    try:
        from ml.longshot_calibration import compute_and_store
        async with AsyncSessionLocal() as cal_session:
            await compute_and_store(cal_session)
    except Exception as e:
        log.warning("pipeline.nightly_calibration_skip", err=str(e)[:140])
    # Recalcule la calibration isotonique (proba_top1 finale → fréquence réelle)
    try:
        from ml.isotonic_calibration import compute_and_store as _iso_compute
        async with AsyncSessionLocal() as iso_session:
            await _iso_compute(iso_session)
    except Exception as e:
        log.warning("pipeline.nightly_isotonic_skip", err=str(e)[:140])
    # Recalcule la calibration isotonique du proba_top3 (placé → fréquence réelle)
    try:
        from ml.isotonic_calibration_top3 import compute_and_store as _iso3_compute
        async with AsyncSessionLocal() as iso3_session:
            await _iso3_compute(iso3_session)
    except Exception as e:
        log.warning("pipeline.nightly_isotonic_top3_skip", err=str(e)[:140])
    # Recalcule la calibration par tranche de cote (corrige favori/longshot dans l'EV
    # des value bets) — auto-apprentissage : s'affine à chaque nuit avec les résultats.
    try:
        from ml.cote_calibration import compute_cote_calibration, persist_cote_calibration
        async with AsyncSessionLocal() as cc_session:
            _cc = await compute_cote_calibration(cc_session)
            await persist_cote_calibration(cc_session, _cc)
            log.info("pipeline.cote_calibration_done", n=_cc.get("n_total"))
    except Exception as e:
        log.warning("pipeline.nightly_cote_calib_skip", err=str(e)[:140])
    # RATTRAPAGE du règlement des runs profils (audit ROI 2026-07-02 : 287 runs
    # pending/partial bloqués = apprentissage sur échantillon amputé). AVANT les
    # apprentissages ci-dessous pour qu'ils agrègent des données complètes.
    try:
        from ml.profil_learning import settle_catchup
        async with AsyncSessionLocal() as sc_session:
            _sc = await settle_catchup(sc_session)
            log.info("pipeline.settle_catchup_done", **_sc)
    except Exception as e:
        log.warning("pipeline.nightly_settle_catchup_skip", err=str(e)[:140])
    # Ré-apprend le ROI réel PAR SIGNAL (duo J/E, ELO, pedigree, forme-piège…) →
    # module la sélection des value bets vers ce qui rapporte. Auto-amélioration.
    try:
        from ml.signal_performance import (
            compute_signal_performance, compute_signal_performance_by_profile,
            persist_signal_performance,
        )
        async with AsyncSessionLocal() as sp_session:
            _sp = await compute_signal_performance(sp_session)            # global
            _spp = await compute_signal_performance_by_profile(sp_session)  # par profil
            _sp["profils"] = _spp.get("profils", {})                      # fusion
            await persist_signal_performance(sp_session, _sp)
            log.info("pipeline.signal_performance_done", n=_sp.get("n_total"))
    except Exception as e:
        log.warning("pipeline.nightly_signal_perf_skip", err=str(e)[:140])
    # Ré-apprend le ROI réel PAR BANDE D'EV → rétrograde les bandes perdantes (zone
    # toxique) au lieu d'un couperet dur. La sélection s'adapte au ROI mesuré.
    try:
        from ml.signal_performance import (
            compute_ev_band_performance, persist_ev_band_performance,
        )
        async with AsyncSessionLocal() as evb_session:
            _evb = await compute_ev_band_performance(evb_session)
            await persist_ev_band_performance(evb_session, _evb)
            log.info("pipeline.ev_band_performance_done", n=_evb.get("n_total"))
    except Exception as e:
        log.warning("pipeline.nightly_ev_band_perf_skip", err=str(e)[:140])
    # Ré-apprend les poids PAR PROFIL depuis les PRONOS ÉMIS réglés (profil_run_log) :
    # l'algo apprend de SES recommandations réelles par profil, pas du top-3.
    try:
        from ml.profil_learning import compute_profil_weights
        async with AsyncSessionLocal() as plw_session:
            _plw = await compute_profil_weights(plw_session)
            log.info("pipeline.profil_weights_done", n_runs=_plw.get("n_total_runs"))
    except Exception as e:
        log.warning("pipeline.nightly_profil_weights_skip", err=str(e)[:140])
    # Ré-apprend la calibration estimé→réel du RAPPORT par (profil × type) depuis les
    # pronos figés réglés → le gate de bande s'applique au rapport RÉELLEMENT attendu :
    # un type qui paie sous la tranche de son profil (ex. Placé favori ×1.3 en prudent)
    # est écarté. C'est l'apprentissage qui fait respecter les tranches sur le réel.
    try:
        from ml.signal_performance import (
            compute_rapport_calibration, persist_rapport_calibration)
        async with AsyncSessionLocal() as rc_session:
            _rc = await compute_rapport_calibration(rc_session)
            await persist_rapport_calibration(rc_session, _rc)
            log.info("pipeline.rapport_calibration_done", n_runs=_rc.get("n_runs"))
    except Exception as e:
        log.warning("pipeline.nightly_rapport_calib_skip", err=str(e)[:140])
    # Surveillance HONNÊTE de l'edge : test hors-échantillon (le filtre conviction≥1.1
    # bat-il encore le marché ?) journalisé → on détecte une dégradation de l'edge.
    try:
        from ml.edge_monitor import compute_edge_monitor, persist_edge_monitor
        async with AsyncSessionLocal() as em_session:
            _em = await compute_edge_monitor(em_session)
            await persist_edge_monitor(em_session, _em)
            log.info("pipeline.edge_monitor_done", edge_ok=_em.get("edge_ok"),
                     win_filt=_em.get("win_filt"), roi_cap=_em.get("roi_cap"))
    except Exception as e:
        log.warning("pipeline.nightly_edge_monitor_skip", err=str(e)[:140])
    # Santé des FEATURES : détecte les features mortes/constantes (scraper cassé →
    # valeur défaut figée). Le drift_detector ne surveille que la perf, pas la
    # distribution des features. On LOGGE + persiste (pas d'exclusion auto = pas de
    # surprise silencieuse sur le modèle ; la liste sert d'alerte/diagnostic).
    try:
        from ml.feature_health import compute_feature_health, persist_feature_health
        async with AsyncSessionLocal() as fh_session:
            _fh = await compute_feature_health(fh_session)
            await persist_feature_health(fh_session, _fh)
            log.info("pipeline.feature_health_done", n_dead=_fh.get("n_dead"),
                     dead=(_fh.get("dead") or [])[:15])
    except Exception as e:
        log.warning("pipeline.nightly_feature_health_skip", err=str(e)[:140])
    # CLV (Closing Line Value) : nos choix battent-ils la ligne de clôture PMU ? Proxy
    # d'edge le plus robuste à la variance. On suit la CLV des top picks modèle vs marché
    # → si > 0 et > moyenne, le modèle anticipe le marché (signal d'edge non-circulaire).
    try:
        from ml.clv_monitor import compute_clv_monitor, persist_clv_monitor
        async with AsyncSessionLocal() as clv_session:
            _clv = await compute_clv_monitor(clv_session)
            await persist_clv_monitor(clv_session, _clv)
            log.info("pipeline.clv_monitor_done", n_top1=_clv.get("n_top1"),
                     clv_top1=_clv.get("clv_top1"), edge_signal=_clv.get("edge_signal"))
    except Exception as e:
        log.warning("pipeline.nightly_clv_monitor_skip", err=str(e)[:140])
    # Ré-apprend les POIDS PAR TYPE (ROI réel winsorisé) + perf par profil et met en
    # cache → la sélection future est pondérée par ce qui a VRAIMENT rapporté.
    try:
        import json as _json
        from api.profil_backtest import backtest_profils
        from db.redis_client import get_redis
        async with AsyncSessionLocal() as bt_session:
            data = await backtest_profils(bt_session, limit=300, n_sims=4000)
        redis = await get_redis()
        await redis.set("stats:profils", _json.dumps(data), ex=86400)
        log.info("pipeline.nightly_learned_weights", type_weights=data.get("type_weights"))
    except Exception as e:
        log.warning("pipeline.nightly_learned_weights_skip", err=str(e)[:140])
    # Garde-fou intégrité : nos données collent-elles à PMU ? (logge toute dérive)
    try:
        from datetime import date as _date
        from scripts.validate_pmu_integrity import validate as _validate_pmu
        res = await _validate_pmu(_date.today().strftime("%d%m%Y"))
        if res.get("mismatches"):
            log.error("pipeline.nightly_pmu_drift", n=len(res["mismatches"]), sample=res["mismatches"][:5])
    except Exception as e:
        log.warning("pipeline.nightly_pmu_integrity_skip", err=str(e)[:140])


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

        X, y, y_win = build_training_dataset(features_rows, resultats_dict)
        if X.empty:
            log.error("pipeline.retrain.empty_dataset")
            return

        log.info("pipeline.retrain.dataset_ready", n=len(X),
                 pos_rate=float(y.mean()), win_rate=float(y_win.mean()) if len(y_win) else 0.0)

        # Libérer la liste brute (144k dicts × 173 clés ≈ 2-3 Go) : inutile une fois X
        # construit. Réduit le pic RAM (serveur 8 Go → OOM à la phase promotion sinon).
        import gc
        del features_rows, resultats_dict
        gc.collect()

        # Entraîner l'ensemble (top-3) + le modèle de victoire dédié (top-1)
        model = BlackTurfEnsemble()
        metrics = model.train(X, y, y_win)
        # Hold-out temporel (MÊME découpage que train()) conservé pour l'arbitrage
        # champion/challenger. ~20% des lignes en float32 = quelques dizaines de Mo :
        # négligeable face aux Go du dataset complet qu'on libère juste après.
        from ml.models import temporal_holdout_mask
        _hm = temporal_holdout_mask(X)
        X_hold, y_hold = X[_hm].copy(), y[_hm].copy()
        # X/y/y_win ne servent plus à la décision de promotion (métriques déjà calculées)
        # → on libère avant la phase métriques/edge_monitor pour ne pas cumuler le pic RAM.
        n_train_rows = len(X)
        del X, y, y_win, _hm
        gc.collect()

        # Récupérer le modèle actif EN BASE pour une comparaison HONNÊTE.
        current_mv = (await session.execute(
            select(ModelVersion).where(ModelVersion.est_actif == True)
            .order_by(ModelVersion.version_num.desc())
        )).scalars().first()
        # NE PAS recharger l'ensemble actif en mémoire ici : il ne sert qu'à tester
        # "existe-t-il un modèle actif" → current_mv (ligne DB) suffit. Le charger
        # (~1-2 Go) PAR-DESSUS le modèle fraîchement entraîné + le dataset 144k faisait
        # exploser la RAM (OOM à ~5 Go pendant la promotion). Économie directe.

        current_is_synth = bool(current_mv.est_synthetique) if current_mv else False
        current_train_n = int(current_mv.nb_courses_train or 0) if current_mv else 0

        # ── Métrique de décision = WALK-FORWARD AUC (généralisation), PAS l'AUC test ──
        # L'AUC test est sur-apprenable : un modèle entraîné sur peu de courses peut
        # afficher un AUC test gonflé (ex. v2 : 399 courses → AUC 0.985 = sur-apprentissage)
        # tout en généralisant mal. Le walk-forward (6 fenêtres glissantes) est l'estimation
        # honnête de la perf future. On compare donc les walk-forward (fallback AUC si absent).
        new_wf = float(metrics.get("walk_forward_auc") or metrics["auc_roc"])
        current_wf = float(
            (current_mv.walk_forward_auc if current_mv and current_mv.walk_forward_auc
             else (current_mv.auc_roc if current_mv else 0.0)) or 0.0
        )

        # Un modèle actif entraîné sur trop peu de courses est NON FIABLE (sur-apprentissage
        # probable) → il doit pouvoir être remplacé par un vrai modèle même à walk-forward
        # inférieur. Seuil : MIN_RELIABLE_TRAIN courses réelles.
        MIN_RELIABLE_TRAIN = 800
        current_unreliable = (not current_is_synth) and current_train_n < MIN_RELIABLE_TRAIN
        new_train_n = n_train_rows

        # ── Saut de DONNÉES : le walk-forward n'est comparable qu'à taille d'entraînement
        # comparable. Sur peu de données il est OPTIMISTE (folds petits/faciles → ex. v7 :
        # 2054 lignes → wf 0.826). Un modèle entraîné sur BEAUCOUP plus de données (≥1.5×)
        # généralise mieux : on le déploie même si son wf (mesuré sur des folds plus durs)
        # est légèrement inférieur, tant qu'il reste sain (tolérance élargie 8%).
        data_jump = (new_train_n >= 1.5 * max(current_train_n, 1)
                     and new_wf >= current_wf - 0.08 and new_wf >= 0.6)

        # FLAG roi_deploy_gate : edge hors-échantillon de la couche PARIS (edge_monitor).
        # Calculé seulement si le flag est actif (sinon edge_ok=True = no-op).
        from ml.algo_flags import FLAGS as _AF
        _betting_edge_ok = True
        if _AF.roi_deploy_gate:
            try:
                from ml.edge_monitor import compute_edge_monitor
                _em = await compute_edge_monitor(session)
                _betting_edge_ok = _edge_gate_ok(_em)
                if _edge_undecidable(_em):
                    log.info("pipeline.retrain.edge_undecidable",
                             n_filt=_em.get("n_filt"), min_filt=_em.get("min_filt"))
            except Exception as _e:
                log.warning("pipeline.retrain.edge_gate_skip", err=str(_e)[:120])
                _betting_edge_ok = True

        # Arbitrage champion/challenger sur un hold-out commun (cf. _head_to_head_auc).
        _h2h = await _head_to_head_auc(session, model, X_hold, y_hold, current_mv)
        del X_hold, y_hold
        gc.collect()
        _h2h_delta = _h2h["delta"] if _h2h else None

        # Décision de promotion (garde-fou absolu MIN_DEPLOYABLE_AUC inclus, cf _should_deploy).
        if _should_deploy(
            new_wf, current_wf,
            current_is_synth=current_is_synth,
            no_current=(current_mv is None),
            current_unreliable=current_unreliable,
            data_jump=data_jump,
            roi_gate_enabled=_AF.roi_deploy_gate,
            betting_edge_ok=_betting_edge_ok,
            h2h_delta=_h2h_delta,
        ):
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
                nb_courses_train=n_train_rows,
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
                wf_auc=round(new_wf, 4),
                prev_wf_auc=round(current_wf, 4),
                reason=("synth" if current_is_synth else "unreliable_active" if current_unreliable
                        else "data_jump" if data_jump
                        else "better_h2h" if _h2h_delta is not None else "better_wf"),
                h2h_delta=round(_h2h_delta, 4) if _h2h_delta is not None else None,
                h2h_n_courses=_h2h["n_courses"] if _h2h else None,
                train_n=new_train_n,
            )

            # AUTO-PURGE : garder seulement les N derniers .pkl archivés (model_v*.pkl
            # ~18 Mo chacun) pour que models/ ne grossisse pas indéfiniment (était 7,1 Go
            # / 493 fichiers). current_model.pkl / meta_learner.pkl ne matchent pas le
            # motif → jamais touchés. Les lignes DB model_versions sont conservées (FK
            # recommandations + taille négligeable), seules les archives disque sont purgées.
            try:
                from ml.models import MODELS_DIR
                _KEEP = 5
                archives = sorted(MODELS_DIR.glob("model_v*.pkl"))
                for _old in archives[:-_KEEP]:
                    _old.unlink(missing_ok=True)
                log.info("pipeline.retrain.pruned_archives",
                         kept=min(_KEEP, len(archives)),
                         removed=max(0, len(archives) - _KEEP))
            except Exception as _e:  # purge best-effort : ne jamais faire échouer un deploy
                log.warning("pipeline.retrain.prune_failed", err=str(_e)[:120])
        else:
            log.warning(
                "pipeline.retrain.rollback",
                new_wf_auc=round(new_wf, 4),
                current_wf_auc=round(current_wf, 4),
                # Le head-to-head est l'arbitre quand il a pu être mesuré : le tracer
                # ici évite de re-diagnostiquer un rejet à partir des seuls wf (qui,
                # eux, ne sont PAS comparables d'une génération à l'autre).
                h2h_delta=round(_h2h_delta, 4) if _h2h_delta is not None else None,
                h2h_auc_challenger=round(_h2h["auc_challenger"], 4) if _h2h else None,
                h2h_auc_champion=round(_h2h["auc_champion"], 4) if _h2h else None,
                reason=(
                    "below_min_auc" if new_wf < MIN_DEPLOYABLE_AUC
                    else "roi_gate" if (_AF.roi_deploy_gate and not _betting_edge_ok
                                        and not (_h2h_delta is not None and _h2h_delta >= 0)
                                        and new_wf < current_wf)
                    else "worse_h2h" if _h2h_delta is not None
                    else "worse_wf"
                ),
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

        # Prédictions avec confiance (accord entre les 3 modèles) + incertitude
        # relative (désaccord L0) pour l'intervalle de confiance sur la proba.
        X = pd.DataFrame(features_list)
        probas_top3_raw, confidence_scores, rel_uncertainty = model.predict_with_uncertainty(X)
        # FLAG calib_on_raw : snapshot de la proba MODÈLE BRUTE top3 (avant toute
        # correction post-hoc) → persistée pour fitter les calibrations sur brut→réel
        # et casser la boucle fermée (cf. audit edge). Aligné à features_list.
        _raw_p3_snap = np.clip(np.asarray(probas_top3_raw, dtype=float), 1e-6, 0.999)

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

        # ── Feature-weight tilt : applique les POIDS APPRIS des groupes de features
        # sur la proba finale (les poids adaptatifs étaient appris mais jamais utilisés
        # à l'inférence — un modèle à arbres est invariant à l'échelle des features).
        # Marginal, borné, inactif tant que < TILT_MIN_RACES courses apprises.
        try:
            probas_top3 = al.apply_feature_weight_tilt(probas_top3, features_list)
        except Exception as e:
            log.warning("pipeline.feature_weight_tilt_skip", err=str(e)[:140])

        # ── Normalisation probabiliste PAR COURSE (cohérence) ───────────────────
        # Sans ça, le modèle peut donner P(top3)~0.7 à plusieurs chevaux (dont des
        # outsiders) → P(top1) absurde (ex. 0.20 sur un 219/1) → faux value bets.
        # Contraintes réelles : exactement 1 gagnant (Σ P(top1)=1) et 3 placés
        # (Σ P(top3)=min(3, nb_partants)). On renormalise donc le champ.
        nb_partants = max(course.nb_partants or len(features_list), 3)
        p3_arr = np.clip(np.asarray(probas_top3, dtype=float), 1e-4, 0.999)
        n = len(p3_arr)

        # P(top1) : modèle de VICTOIRE dédié (APPRIS sur label arrivé-1er) si dispo,
        # sinon fallback heuristique P(top3)^gamma. Le modèle appris capte des
        # signaux propres à la victoire (vs simple placement), bien plus fiable que
        # l'exposant fixe. Normalisé Σ=1 par course (1 seul gagnant).
        p_win_raw = None
        try:
            p_win_raw = model.predict_win_proba(X)
        except Exception as e:
            log.warning("pipeline.win_model_skip", err=str(e)[:140])
        if p_win_raw is not None and len(p_win_raw) == n and float(np.sum(p_win_raw)) > 0:
            raw_p1 = np.clip(np.asarray(p_win_raw, dtype=float), 1e-6, 0.999)
            log.info("pipeline.win_model_used", course_id=course_id)
        else:
            # Fallback : P(top1) ∝ P(top3)^gamma (favoris concentrent la victoire)
            raw_p1 = p3_arr ** 1.6
        s1 = float(raw_p1.sum())
        probas_top1 = (raw_p1 / s1) if s1 > 0 else np.full(n, 1.0 / n)
        # FLAG calib_on_raw : snapshot proba victoire BRUTE (normalisée Σ=1) AVANT
        # blend marché / longshot / isotonic. Base honnête de calibration brut→réel.
        _raw_p1_snap = np.asarray(probas_top1, dtype=float).copy()

        # P(top3) renormalisé pour sommer à min(3, nb_partants), borné à 0.99
        target_sum3 = float(min(3.0, nb_partants))
        s3 = float(p3_arr.sum())
        probas_top3 = np.clip(p3_arr * (target_sum3 / s3), 0.0, 0.99) if s3 > 0 else p3_arr

        # ── Calibration isotonique du proba_top3 (placé) ─────────────────────────
        # Corrige la sur-confiance milieu de gamme du placé (mesurée : prédit 0.5
        # → réel ~0.40) → EV/proba des paris PLACÉ honnêtes (cœur prudent/modéré).
        # Régression monotone apprise sur les vraies arrivées, recalc nightly.
        try:
            from ml.isotonic_calibration_top3 import load_curve as _t3_load, apply_calibration as _t3_apply
            _t3_curve = await _t3_load(session)
            if _t3_curve:
                probas_top3 = _t3_apply(probas_top3, _t3_curve, nb_partants)
        except Exception as e:
            log.warning("pipeline.isotonic_top3_skip", err=str(e)[:140])

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
        # RECENTRAGE MARCHÉ (2026-07-02, priorité ROI) : le marché PMU agrège l'info de
        # milliers de parieurs + pros ; un modèle ne le bat que là où il a un signal
        # PROUVÉ. ALPHA_MAX 0.55→0.42 : même sur les favoris le marché garde la majorité
        # — l'edge doit venir d'un vrai désaccord persistant, pas d'une sur-confiance.
        # ALPHA_DECAY 0.022→0.030 : au-delà de cote 12 la confiance modèle tombe plus
        # vite (ratio proba/réel 1.76 mesuré sur cote 20-40 = sur-évaluation avérée).
        ALPHA_MAX = 0.42          # confiance modèle sur favoris (cote ≤ ALPHA_FULL_COTE)
        ALPHA_MIN = 0.12          # plancher : sur gros outsiders le marché domine
        ALPHA_FULL_COTE = 12.0    # en-deçà : modèle de confiance
        ALPHA_DECAY = 0.030       # pente de décroissance par unité de cote au-delà du seuil
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

        # ── Calibration longshots : corrige le sur-fit sur grosses cotes en
        # ramenant la proba vers la fréquence RÉELLE observée par bucket de cote,
        # puis renormalise. Facteurs appris sur données réelles (recalc nightly).
        # FLAG collapse_longshot : on saute cette étape pour ne PAS empiler une 3e
        # correction favori-longshot (le blend marché ci-dessus + l'isotonic résiduel
        # ci-dessous suffisent). L'empilement écrasait l'edge quand le modèle a raison
        # (cf. audit edge : triple-comptage du biais). Flag off → comportement d'avant.
        try:
            from ml.algo_flags import FLAGS as _AF3
            _skip_longshot = _AF3.collapse_longshot
        except Exception:
            _skip_longshot = False
        if not _skip_longshot:
            try:
                from ml.longshot_calibration import load_factors, apply_calibration
                _cal_factors = await load_factors(session)
                if _cal_factors:
                    probas_top1 = apply_calibration(probas_top1, cotes_pmu, _cal_factors)
            except Exception as e:
                log.warning("pipeline.longshot_calibration_skip", err=str(e)[:140])

        # ── Calibration isotonique RÉSIDUELLE : ajuste la proba_top1 finale pour
        # qu'elle colle à la fréquence de victoire réelle (régression monotone apprise
        # sur les vraies courses, recalc nightly). Dernière étape de calibration —
        # ferme la boucle après temperature/blend marché/longshots. Identité si peu
        # de données. Renormalise Σ=1.
        try:
            from ml.isotonic_calibration import load_curve, apply_calibration as _iso_apply, seg_key as _iso_seg
            _iso_curve = await load_curve(session)
            if _iso_curve:
                # Calibration PAR SEGMENT (discipline × tranche de partants) si dispo,
                # sinon courbe globale (fallback). nb_partants = nb de lignes scorées.
                _seg = _iso_seg(course.discipline, len(features_list))
                probas_top1 = _iso_apply(probas_top1, _iso_curve, seg=_seg)
        except Exception as e:
            log.warning("pipeline.isotonic_calibration_skip", err=str(e)[:140])

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
        # FLAG ranker_blend : mélange le score LambdaRank (ordre intra-course) avec
        # la proba_top1 (z-scores) pour CLASSER — sans toucher proba/EV. Réversible.
        _ord_key = _p1_arr
        try:
            from ml.algo_flags import FLAGS as _AFrk
            if getattr(_AFrk, "ranker_blend", False):
                _rs = model.predict_rank_score(X)
                if _rs is not None and len(_rs) == len(_p1_arr) and float(np.std(_rs)) > 0:
                    def _z(a):
                        a = np.asarray(a, dtype=float)
                        return (a - a.mean()) / (a.std() + 1e-9)
                    _w = float(getattr(_AFrk, "ranker_blend_weight", 1.0))
                    _ord_key = _z(_p1_arr) + _w * _z(_rs)
                    log.info("pipeline.ranker_blend_applied", course_id=course_id)
        except Exception as _e:
            log.warning("pipeline.ranker_blend_skip", err=str(_e)[:120])
        _order = np.lexsort((-_p3_arr, -_ord_key))  # primaire: -ord_key, secondaire: -proba_top3
        _rang_by_index = np.empty(len(_order), dtype=int)
        for _k, _idx in enumerate(_order):
            _rang_by_index[int(_idx)] = _k + 1

        # ── Intervalle de confiance sur proba_top1 ───────────────────────────────
        # Bande = proba × (1 ± K × incertitude_relative), où l'incertitude relative
        # est le désaccord entre les 3 modèles de base (std/mean). Bornes par cheval
        # (pas une distribution → pas de renormalisation). Plus les modèles divergent,
        # plus l'intervalle est large. K_CI borné pour rester lisible.
        K_CI = 0.6
        _ru = np.asarray(rel_uncertainty, dtype=float)
        _ci_low = np.clip(_p1_arr * (1.0 - K_CI * _ru), 1e-4, 0.999)
        _ci_high = np.clip(_p1_arr * (1.0 + K_CI * _ru), 1e-4, 0.999)

        # Calibration par tranche de cote (apprise nightly des résultats réels) —
        # chargée une fois, appliquée à l'EV des value bets (corrige favori/longshot).
        try:
            from ml.cote_calibration import load_cote_calibration
            _cote_calib = await load_cote_calibration(session)
        except Exception:
            _cote_calib = None
        # Apprentissage par signal (ROI réel par signal, recalc nightly) — module
        # le niveau des value bets vers les signaux historiquement gagnants.
        _sig_mult = None
        try:
            from ml.signal_performance import load_signal_performance, signal_multiplier as _sig_mult_fn
            _signal_perf = await load_signal_performance(session)
            _sig_mult = _sig_mult_fn
        except Exception:
            _signal_perf = None
        # ROI réel par BANDE D'EV (recalc nightly) — gate d'ÉMISSION des value bets
        # (bande au ROI shrinké négatif → pas de VB, cf. flag ev_band_gate). Était
        # calculé nightly mais JAMAIS passé à l'émission live (trou audit 2026-07-02) :
        # 59% des paris sortaient dans des bandes prouvées perdantes.
        try:
            from ml.signal_performance import load_ev_band_performance
            _ev_band_perf = await load_ev_band_performance(session)
        except Exception:
            _ev_band_perf = None

        # FLAG devig_gates : overround du champ. Calculé une fois par course.
        # None si flag off, ou couverture cotes insuffisante → detect_value_bet
        # inchangé (cf. compute_field_overround).
        _field_overround = None
        try:
            from ml.algo_flags import FLAGS as _AF
            if _AF.devig_gates:
                _field_overround = compute_field_overround(features_list)
        except Exception:
            _field_overround = None

        predictions = []
        for i, feat in enumerate(features_list):
            pid = feat.get("participation_id")
            proba_t3 = float(probas_top3[i])
            proba_t1 = float(probas_top1[i])

            # Rang prédit cohérent avec la proba finale
            rang = int(_rang_by_index[i])

            # Sauvegarder prédiction
            confidence = float(confidence_scores[i])
            ci_low = float(_ci_low[i])
            ci_high = float(_ci_high[i])
            pred_id = str(uuid.uuid4())
            # FLAG calib_on_raw : écrit aussi la proba modèle BRUTE (nécessite migration
            # 0024). Vide sinon → colonnes NULL, calibrateurs retombent sur proba_top1/3.
            _raw_vals = {}
            try:
                from ml.algo_flags import FLAGS as _AF2
                if _AF2.calib_on_raw:
                    _raw_vals = {
                        "proba_top1_raw": float(_raw_p1_snap[i]),
                        "proba_top3_raw": float(_raw_p3_snap[i]),
                    }
            except Exception:
                _raw_vals = {}
            stmt = pg_insert(PredictionModel).values(
                prediction_id=pred_id,
                participation_id=pid,
                course_id=course_id,
                model_version_id=mv_id,
                proba_top1=proba_t1,
                proba_top3=proba_t3,
                proba_top1_low=ci_low,
                proba_top1_high=ci_high,
                rang_predit=rang,
                confidence_score=round(confidence * 100, 2),  # accord des 3 modèles
                # Snapshot de la cote PMU servant de base au plan de mise. Recalculée
                # à chaque cycle TANT que la course est > 10 min du départ ; figée dès
                # que le cycle s'arrête (T-10 min) → plan stable, cotes affichées libres.
                cote_figee=feat.get("cote_pmu"),
                created_at=datetime.now(),
                **_raw_vals,
            ).on_conflict_do_update(
                index_elements=["participation_id"],
                set_={
                    # Attribution : la ligne re-prédite doit porter le modèle QUI a
                    # produit les probas courantes (sinon stamp figé au 1er cycle du
                    # jour → fausse la traçabilité / le monitoring / la CLV par modèle).
                    # created_at NON touché : reste l'heure du 1er prono (intégrité
                    # palmarès : prono émis avant départ).
                    "model_version_id": mv_id,
                    "proba_top1": proba_t1,
                    "proba_top3": proba_t3,
                    "proba_top1_low": ci_low,
                    "proba_top1_high": ci_high,
                    "rang_predit": rang,
                    "confidence_score": round(confidence * 100, 2),
                    "cote_figee": feat.get("cote_pmu"),
                    **_raw_vals,
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
                cote_calib=_cote_calib,
                signal_mult=(_sig_mult(feat, _signal_perf) if (_sig_mult and _signal_perf) else None),
                field_overround=_field_overround,
                ev_band_perf=_ev_band_perf,
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
                "numero": feat.get("numero") if feat.get("numero") is not None else feat.get("rang_cote", i + 1),
                "nom": feat.get("nom", ""),
                "proba_top3": proba_t3,
                "proba_top1": proba_t1,
                "proba_top1_low": ci_low,
                "proba_top1_high": ci_high,
                "cote_pmu": cote_pmu,
                "cote_geny": cote_geny,
                "ev_max": ev_max,
                "niveau_vb": niveau_vb,
                "prediction_id": pred_id,
                "_ord": float(_ord_key[int(i)]),
            })

        # Trier par proba de VICTOIRE décroissante (tiebreak top-3) et assigner les
        # rangs — même base que le rang_predit sauvegardé en DB (cohérence totale).
        predictions.sort(key=lambda x: (x.get("_ord", x["proba_top1"]), x["proba_top3"]), reverse=True)
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
            "est_2sur4": course.est_2sur4,
        }
        recos = generer_recommandations_course(predictions, course_info, bankroll=user_bankroll)

        # ── Remplacer les EV/probas HARDCODÉS des paris combinés par les valeurs
        # RÉELLES du moteur Plackett-Luce (intégrité : aucune valeur inventée). ──
        coverage_result = {"proposals": [], "coup_a_tenter": None}
        try:
            from ml.combo_bets import build_combo_proposals, build_coverage_bets
            combo = build_combo_proposals(predictions, course_info, bankroll=user_bankroll)
            props = combo.get("proposals", [])
            combo_full = {c["type_pari"].lower(): c for c in props}            # ex "couplé placé"
            combo_cat = {}
            for c in props:                                                     # 1er par catégorie
                combo_cat.setdefault(c["type_pari"].split()[0].lower(), c)

            # Couverture jackpot (base+champ) — proba/coût/EV réels par catégorie.
            coverage_result = build_coverage_bets(predictions, course_info, bankroll=user_bankroll)
            cov_props = coverage_result.get("proposals", [])
            cov_best = {}  # 1ère catégorie = meilleure (déjà triée jackpot→EV)
            for c in cov_props:
                cov_best.setdefault(c["type_pari"].split()[0].lower(), c)

            for reco in recos:
                t = reco["type_pari"]
                if t in ("Simple Gagnant", "Simple Placé"):
                    continue  # paris simples : EV déjà réel (ev_max du value bet)
                cat = t.split()[0].lower()
                # Jackpots (Tiercé/Quarté+/Quinté+) : valeurs RÉELLES du moteur de
                # couverture (proba/coût/combinaisons cohérents avec un vrai ticket).
                cv = cov_best.get(cat) if cat in ("tiercé", "quarté+", "quinté+") else None
                if cv:
                    reco["ev_calcule"] = cv["ev"]
                    reco["confidence"] = cv["proba_gain"]
                    reco["cout_total"] = cv["cout_total"]
                    reco["mise_suggeree"] = cv["cout_total"]
                    reco["nb_combinaisons"] = cv["nb_combinaisons"]
                    reco["texte_explication"] = cv["texte_explication"]
                    continue
                cp = combo_full.get(t.lower()) or combo_cat.get(cat)
                if cp:
                    reco["ev_calcule"] = cp["ev"]            # EV réelle (P × rapport − 1)
                    reco["confidence"] = cp["proba_gain"]    # proba simulée
                    if cp.get("cout_total"):
                        reco["cout_total"] = cp["cout_total"]
        except Exception as e:
            log.warning("pipeline.combo_ev_override_failed", course_id=course_id, err=str(e)[:140])

        # ── Ajouter le « coup à tenter » + 1 couverture élargie comme recos ──────
        # (persistées → visibles via /courses/{id}/predictions). Valeurs 100% réelles
        # issues du moteur de couverture ; aucune si non crédible.
        try:
            coup = coverage_result.get("coup_a_tenter")
            if coup:
                recos.append({
                    "niveau": "coup",
                    "type_pari": coup["type_pari"],
                    "chevaux": [{"numero": h["numero"], "nom": h["nom"]} for h in coup["chevaux"]],
                    "mise_suggeree": round(min(max(user_bankroll * 0.02, 1.5), 10.0), 2),
                    "ev_calcule": coup["ev"],
                    "confidence": coup["proba_gain"],
                    "cout_total": round(min(max(user_bankroll * 0.02, 1.5), 10.0), 2),
                    "nb_combinaisons": 1,
                    "texte_explication": coup["texte_explication"],
                })
            # 1 meilleure couverture élargie (niveau "couverture") non déjà couverte
            cov_extra = next(
                (c for c in coverage_result.get("proposals", [])
                 if c.get("niveau") == "couverture" and c.get("ev", -9) > -0.5),
                None,
            )
            if cov_extra:
                recos.append({
                    "niveau": "couverture",
                    "type_pari": cov_extra["type_pari"],
                    "chevaux": [{"numero": h["numero"], "nom": h["nom"]} for h in cov_extra["chevaux"]],
                    "mise_suggeree": cov_extra["cout_total"],
                    "ev_calcule": cov_extra["ev"],
                    "confidence": cov_extra["proba_gain"],
                    "cout_total": cov_extra["cout_total"],
                    "nb_combinaisons": cov_extra["nb_combinaisons"],
                    "texte_explication": cov_extra["texte_explication"],
                })
        except Exception as e:
            log.warning("pipeline.coup_reco_failed", course_id=course_id, err=str(e)[:140])

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

        # ── FIGER les pronos par profil (profil_run_log) : le plan 10€ des 3
        # profils est journalisé AVANT la course → c'est sur CES pronos émis que
        # l'algorithme apprendra (règlement post-course aux vrais rapports PMU).
        try:
            from ml.profil_learning import record_profil_runs
            await record_profil_runs(session, course_id, model_version_id=mv_id)
        except Exception as e:
            log.warning("pipeline.profil_runs_record_skip", course_id=course_id, err=str(e)[:140])

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

        # ── Couverture jackpot + « coup à tenter » (gros gains) ──────────────
        if isinstance(fiche, dict):
            fiche["coverage_jackpot"] = coverage_result.get("proposals", [])
            fiche["coup_a_tenter"] = coverage_result.get("coup_a_tenter")

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

    # FLAG train_prerace_only : n'entraîne que sur features FIGÉES AVANT le départ
    # (fm.computed_at < c.date_heure), comme meta_learner.py. Sans ça, les features
    # recomputées/backfillées APRÈS la course (cotes de clôture, stats J/E incluant
    # cette course, ELO backfillé) fuient avec hindsight → gros lift in-sample qui
    # s'évapore en live (cf. audit edge -52%). Flag off → comportement historique.
    from ml.algo_flags import FLAGS as _AF
    _prerace_clause = (
        "AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure"
        if _AF.train_prerace_only else ""
    )

    # Récupérer les features sauvegardées avec leurs labels
    result = await session.execute(text(f"""
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
          {_prerace_clause}
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
    """No-op : le push d'alertes RÉSULTAT n'est pas implémenté.

    BUG CORRIGÉ 2026-06-29 — BOUCLE INFINIE : cette fonction est appelée DEPUIS
    `run_post_course` (étape 5) et ré-enqueuait `post_course_sync` (= run_post_course),
    donc chaque course se ré-injectait sans fin dans la file RQ `default`. Résultat :
    ~5900 jobs en backlog permanent, worker à 100 % 24/7, `skip_already_learned` à
    chaque tour, et risque d'affamer la file `ml` (retrain).

    Le 1er (et seul) traitement légitime d'une course est déclenché par l'orchestrator
    (`scraper/orchestrator.py` poll_resultats) quand l'arrivée est publiée. On ne
    ré-enqueue donc RIEN ici. Si un jour on veut notifier les abonnés du résultat,
    le faire DIRECTEMENT (services.alerts.send_web_push), JAMAIS via post_course_sync.
    """
    return None


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


def run_incremental_retraining_sync() -> None:
    """Sync wrapper for RQ — retraining incrémental (drift) dans le worker.
    RQ ne peut pas exécuter une coroutine ; ce wrapper l'enveloppe dans asyncio.run."""
    import asyncio
    asyncio.run(run_incremental_retraining())


def post_course_sync(course_id: str) -> None:
    """Sync wrapper for RQ — post-course pipeline (ELO, features, notifications)."""
    import asyncio
    asyncio.run(run_post_course(course_id))
