"""
profil_learning.py — Apprentissage sur les PRONOSTICS RÉELLEMENT ÉMIS par profil.

Différence fondamentale avec profil_backtest (rejeu nightly a posteriori) :
ici, chaque prédiction de course FIGE le plan de mise des 3 profils
(conservateur / équilibré / agressif) AVANT la course (table profil_run_log),
puis le règlement post-course (vrais rapports PMU) écrit le résultat sur CES
pronos figés. L'algorithme apprend donc de SES propres recommandations émises,
pas du top-3 du modèle ni d'une reconstruction.

Intégrité : pari gagnant sans rapport publié → statut "en_attente" (run
"partial", re-réglable) — jamais de gain estimé. Poids sans échantillon
suffisant → neutre 1.0 (aucune invention).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.prediction_evaluation import MIN_PROFIL_WEIGHTS_RUNS
from services.pmu_paris_reference import prelevement

log = structlog.get_logger()

PROFILS = ("conservateur", "equilibre", "agressif")
MISE_REF = 10            # € fixes par run (comparabilité inter-profils)
MIN_RUNS_FOR_WEIGHTS = 10   # en-dessous, poids neutres (pas d'invention)
MIN_RUNS_FOR_WEIGHTS_CTX = 12   # seuil par bucket CONTEXTE (plus haut : plus granulaire)
MIN_RUNS_FOR_SUPPRESS = 25   # preuve solide avant de COUPER un (type×contexte)
ROI_SUPPRESS = -0.40         # ROI réel ≤ -40% sur n≥seuil → suppression dure (poids 0)
# ── SUPPRESSION GLOBALE « 0 GAIN » (audit ROI 2026-07-02) ────────────────────
# La suppression contextuelle (25 runs PAR bucket discipline×peloton) ne coupait
# jamais les types gros-lot : leurs tickets s'éparpillent sur plein de buckets.
# Mesuré en prod : Tiercé/Quarté+/Quinté+ Désordre, Super 4, Pick5, Multi en 4/5
# = 0 gain sur ~91 tickets (−100%). Deux règles GLOBALES par profil, sur les BRUTS :
#   1. type à 0 gain sur n ≥ ZERO_WIN_SUPPRESS_N → poids 0 ;
#   2. famille JACKPOT poolée (types tout-ou-rien ci-dessous) : si le pool a
#      n ≥ JACKPOT_POOL_SUPPRESS_N tickets et AUCUN gain, chaque membre 0-gain
#      (n ≥ 3) est coupé — le pool fournit la preuve que chaque petit n n'a pas.
# RÉHABILITATION AUTOMATIQUE : dès qu'un type gagne UNE fois, il sort de la règle.
ZERO_WIN_SUPPRESS_N = 15
JACKPOT_POOL_SUPPRESS_N = 25
JACKPOT_TYPES = {"Tiercé Désordre", "Tiercé Ordre", "Quarté+ Désordre",
                 "Quinté+ Désordre", "Super 4", "Pick5", "Multi en 4", "Multi en 5"}


def _is_jackpot_type(t: str) -> bool:
    return (t or "").replace("Mini Multi", "Multi") in JACKPOT_TYPES


def zero_win_suppression(types_agg: dict) -> set[str]:
    """Types à couper (poids 0) pour un profil — fonction PURE (testable sans DB).
    `types_agg` : {type: {"n": int, "win": int, ...}} (agrégats BRUTS du profil)."""
    jn = sum(ts.get("n", 0) for t, ts in types_agg.items() if _is_jackpot_type(t))
    jw = sum(ts.get("win", 0) for t, ts in types_agg.items() if _is_jackpot_type(t))
    out: set[str] = set()
    for t, ts in types_agg.items():
        if ts.get("win", 0) > 0:
            continue                                  # a déjà gagné → jamais coupé ici
        if ts.get("n", 0) >= ZERO_WIN_SUPPRESS_N:
            out.add(t)
        elif (_is_jackpot_type(t) and ts.get("n", 0) >= 3
                and jn >= JACKPOT_POOL_SUPPRESS_N and jw == 0):
            out.add(t)
    return out
SHRINK_K = 20            # shrinkage du ROI vers 0 (anti sur-réaction petit n ; 15→20
                         # après audit : 3-4 paris perdants ne doivent pas basculer un poids)
W_MIN, W_MAX = 0.5, 1.6
# DECAY TEMPOREL des runs (demi-vie en jours) : un run d'il y a 45j pèse moitié moins
# qu'un run d'hier → les poids SUIVENT le régime actuel du modèle/marché au lieu de
# moyenner 2024 avec aujourd'hui. La SUPPRESSION dure reste sur les totaux BRUTS
# (une preuve de perte n'expire pas à la légère). Decay appliqué aux POIDS uniquement.
DECAY_HALF_LIFE_DAYS = 45.0

# ── WINSORISATION DES GAINS QUI PILOTENT LES POIDS (audit 2026-08-31) ────────
# Mesure qui impose cette correction, sur 81 jours et 4 039 courses rejouables :
#     Trio, 1 653 paris — ROI BRUT +51,0 %, ROI WINSORISÉ p99 −75,7 %
# Un UNIQUE ticket (19072026R3C7, 10 € misés, 4 526 € rendus) portait 49,8 % de
# tous les gains Trio de la période ; les trois plus gros en portaient 74,7 %.
# Sans ce ticket, le Trio retombait à −24,1 %. `shrunk_weight` travaillant sur
# `net / mise` en sommes BRUTES, l'état appris affichait `Trio roi: 62,8 %` et lui
# donnait le poids MAXIMUM (1,6 = W_MAX) — l'apprentissage poussait donc
# activement le pari qui détruisait le plus d'argent. Seul un gate appliqué EN AVAL
# (`apply_type_gates`) l'empêchait de sortir dans les plans : le produit ne tenait
# que par un correctif posé après coup sur un apprentissage inversé.
#
# Ce qui est winsorisé et ce qui ne l'est PAS — la distinction est délibérée :
#   - les POIDS appris (`shrunk_weight`) partent des gains PLAFONNÉS : un poids
#     doit refléter ce qui se reproduit, pas ce qui est arrivé une fois ;
#   - `mise`, `gain`, `win`, `roi` restent BRUTS : ce sont des diagnostics et
#     l'argent réellement rendu. Un montant en euros affiché quelque part ne doit
#     jamais être une valeur winsorisée.
# Les gates de suppression dure (`zero_win_suppression`, seuil `ROI_SUPPRESS`)
# continuent de lire les champs bruts : ils comptent des VICTOIRES, pas des
# montants, et un plafond ne peut pas transformer un perdant en gagnant.
#
# Plafond calculé PAR TYPE sur l'ensemble des profils (n plus grand, donc plafond
# plus stable) et sur TOUS les tickets, gagnants et perdants — même définition que
# `percentile_cont(0.99)` de PostgreSQL, pour que la mesure d'audit reste
# reproductible telle quelle en SQL.
WINSOR_QUANTILE = 0.99


def plafond_gain(gains: list[float]) -> Optional[float]:
    """Quantile `WINSOR_QUANTILE` d'une liste de gains — fonction PURE (testable
    sans DB). Interpolation linéaire, identique à `percentile_cont` de PostgreSQL.
    Liste vide → None (aucun plafond : on n'invente pas de borne sans données)."""
    if not gains:
        return None
    s = sorted(float(g) for g in gains)
    if len(s) == 1:
        return s[0]
    pos = WINSOR_QUANTILE * (len(s) - 1)
    bas = int(pos)
    haut = min(bas + 1, len(s) - 1)
    return s[bas] + (s[haut] - s[bas]) * (pos - bas)


def ctx_key(discipline, nb_partants) -> str:
    """Clé de contexte d'une course : discipline + bande de taille de peloton.
    Permet d'apprendre des poids par (profil × type × contexte) — ex. « Couplé au
    trot, grand peloton » ≠ « Couplé au plat, petit peloton ». Gardé GROSSIER
    (3 disciplines × 3 bandes = 9 buckets) pour que chaque bucket se remplisse vite."""
    d = (discipline or "?").lower()
    if "trot" in d or "attel" in d or "mont" in d:
        disc = "trot"
    elif "haies" in d or "steeple" in d or "obstacle" in d:
        disc = "obstacle"
    elif "plat" in d:
        disc = "plat"
    else:
        disc = "autre"
    n = int(nb_partants or 0)
    band = "p" if n <= 8 else ("m" if n <= 12 else "g")   # petit / moyen / grand
    return f"{disc}|{band}"


# ─────────────────────────────────────────────────────────────
# Schéma (pattern maison : inline CREATE IF NOT EXISTS, cf. signal_performance)
# ─────────────────────────────────────────────────────────────
async def ensure_tables(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS profil_run_log (
            log_id VARCHAR(36) PRIMARY KEY,
            course_id VARCHAR(36) NOT NULL,
            profil VARCHAR(20) NOT NULL,
            model_version_id VARCHAR(36),
            plan JSONB NOT NULL,
            resultat JSONB,
            roi_reel FLOAT,
            nb_paris INTEGER NOT NULL DEFAULT 0,
            statut VARCHAR(20) NOT NULL DEFAULT 'pending',
            meta JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            settled_at TIMESTAMPTZ,
            UNIQUE (course_id, profil)
        )
    """))
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_profil_run_log_course ON profil_run_log (course_id)"
    ))
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_profil_run_log_statut ON profil_run_log (statut)"
    ))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS profil_learning_state (
            id INTEGER PRIMARY KEY,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.commit()


# ─────────────────────────────────────────────────────────────
# 1. FIGER les pronos par profil au moment de la prédiction
# ─────────────────────────────────────────────────────────────
async def record_profil_runs(session: AsyncSession, course_id: str,
                             model_version_id: Optional[str] = None) -> int:
    """Génère + fige le plan 10€ des 3 profils pour une course À VENIR.

    Mêmes entrées que la route /mise-plan (heat réel, ROI weights réels,
    signal_mults par profil) → ce qui est journalisé = ce que l'utilisateur
    aurait vu. Re-prédiction avant course → écrase (le DERNIER prono avant
    départ fait foi). Course déjà réglée → intouchée.
    """
    from services.mise_calculator import generer_plan, plan_to_dict

    await ensure_tables(session)

    rows = (await session.execute(text("""
        SELECT p.numero, ch.nom, pr.proba_top1, pr.proba_top3,
               COALESCE(pr.cote_figee, p.cote_pmu) AS cote_pmu,
               p.non_partant, f.features
        FROM predictions pr
        JOIN participations p ON p.participation_id = pr.participation_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN features_ml f ON f.participation_id = pr.participation_id
        WHERE p.course_id = :cid
        ORDER BY pr.rang_predit
    """), {"cid": course_id})).all()
    if not rows:
        return 0

    # `h.pays` sert au CONSTAT (zone de marché de la réunion, cf. services/hippodromes) ;
    # il n'entre PAS dans la génération du plan — l'hypothèse a été mesurée et écartée,
    # cf. la note « CALIBRAGE PAR ZONE » dans ml/signal_performance.
    course = (await session.execute(text("""
        SELECT c.statut, c.nb_partants, c.est_quinte, c.est_quarte, c.est_tierce, c.est_2sur4,
               c.paris_disponibles, c.discipline, c.date_heure, h.pays
        FROM courses c
        LEFT JOIN hippodromes h ON h.nom = c.hippodrome_nom
        WHERE c.course_id = :cid
    """), {"cid": course_id})).first()
    if not course or course[0] not in ("a_venir", "en_cours"):
        return 0
    _discipline = course[7]   # contexte d'apprentissage (discipline × peloton)
    # Ne (re)figer QUE strictement AVANT le départ. Une re-prédiction post-départ
    # (régénération EV-live / non-partant, course encore 'en_cours') ne doit PAS
    # réécrire le prono figé ni repousser created_at après le départ → sinon le bilan
    # afficherait un plan différent de celui vu avant la course. Le DERNIER prono
    # émis avant le départ fait foi.
    _date_heure = course[8]
    if _date_heure is not None:
        from datetime import datetime as _dt, timezone as _tz
        _now = _dt.now(_tz.utc) if _date_heure.tzinfo else _dt.now()
        if _now >= _date_heure:
            return 0

    preds = []
    feats_by_num: dict[int, dict] = {}
    for numero, nom, p1, p3, cote, np_, feats in rows:
        preds.append({
            "numero": numero, "nom_cheval": nom,
            "proba_top1": p1, "proba_top3": p3,
            "cote_pmu": cote, "non_partant": np_,
        })
        feats_by_num[int(numero)] = feats or {}

    from services.bet_catalog import derive_bet_flags
    course_info = derive_bet_flags(
        course[6],  # paris_disponibles (liste codePari) — vérité PMU si présente
        est_tierce=bool(course[4]), est_quarte=bool(course[3]),
        est_quinte=bool(course[2]), est_2sur4=bool(course[5]),
    )
    course_info["nb_partants"] = course[1]

    # Contexte d'apprentissage réel (mêmes sources que /mise-plan)
    try:
        from ml.bet_performance import get_model_heat
        heat = await get_model_heat(session)
    except Exception:
        heat = 0.0
    try:
        from ml.signal_performance import load_signal_performance, signal_multiplier
        sig_perf = await load_signal_performance(session)
    except Exception:
        sig_perf = None
    # Calibration estimé→réel (par profil × type) : MÊME entrée que /mise-plan → le plan
    # figé applique les rapports corrigés, donc identique à ce que l'utilisateur voit.
    try:
        from ml.signal_performance import load_rapport_calibration
        rapport_calib = await load_rapport_calibration(session)
    except Exception:
        rapport_calib = None
    try:
        from ml.signal_performance import load_ev_band_performance
        ev_band_perf = await load_ev_band_performance(session)
    except Exception:
        ev_band_perf = None

    n_written = 0
    for profil in PROFILS:
        try:
            from ml.bet_performance import get_learned_type_weights
            roi_weights = await get_learned_type_weights(
                session, profil=profil,
                discipline=_discipline, nb_partants=course[1],
            )
        except Exception:
            roi_weights = {}
        sig_mults = {}
        if sig_perf:
            try:
                from ml.signal_performance import signal_multiplier as _sm
                sig_mults = {n: _sm(f, sig_perf, profil) for n, f in feats_by_num.items()}
            except Exception:
                sig_mults = {}
        try:
            # respect_montant=True : MÊME méthode que le calculateur live (mise du
            # montant complet + concentration gain_target) → le plan FIGÉ est identique
            # à ce que l'utilisateur voit, donc identique au bilan affiché après course.
            plan = generer_plan(MISE_REF, profil, preds, course_info,
                                None, roi_weights, heat, sig_mults, respect_montant=True,
                                rapport_calib=rapport_calib, ev_band_perf=ev_band_perf)
            plan_d = plan_to_dict(plan)
        except Exception as e:
            log.warning("profil_learning.plan_failed", course_id=course_id,
                        profil=profil, err=str(e)[:140])
            continue
        nb_paris = sum(len(n.get("paris", [])) for n in plan_d.get("niveaux", []))
        if nb_paris == 0:
            continue
        # Upsert idempotent — n'écrase JAMAIS un run déjà réglé.
        await session.execute(text("""
            INSERT INTO profil_run_log
                (log_id, course_id, profil, model_version_id, plan, nb_paris, statut, meta)
            VALUES (:id, :cid, :prof, :mv, CAST(:plan AS jsonb), :nb, 'pending',
                    CAST(:meta AS jsonb))
            ON CONFLICT (course_id, profil) DO UPDATE SET
                plan = EXCLUDED.plan,
                nb_paris = EXCLUDED.nb_paris,
                model_version_id = EXCLUDED.model_version_id,
                meta = EXCLUDED.meta,
                created_at = now()
            WHERE profil_run_log.statut = 'pending'
        """), {
            "id": str(uuid.uuid4()), "cid": course_id, "prof": profil,
            "mv": model_version_id, "plan": json.dumps(plan_d),
            "nb": nb_paris,
            # pre_course=true : marqueur explicite « prono figé AVANT le départ »
            # (preuve d'intégrité pour le palmarès, en plus de created_at < date_heure).
            "meta": json.dumps({"heat": round(float(heat), 3), "mise": MISE_REF,
                                "pre_course": True}),
        })
        # Même conseil, journalisé aussi dans le registre append-only commun aux
        # plans utilisateurs : profil_run_log est upserté (le dernier prono
        # pré-départ écrase le précédent), donc il ne conserve PAS l'historique
        # des états successifs. bet_plan_snapshots, lui, ne perd rien.
        await _record_system_plan_snapshot(
            session, course_id=course_id, plan_d=plan_d, profil=profil,
            heat=heat, model_version_id=model_version_id,
            preds=preds, course_start_at=_date_heure,
        )
        n_written += 1
    await session.commit()
    if n_written:
        log.info("profil_learning.runs_recorded", course_id=course_id, n=n_written)
    return n_written


async def _record_system_plan_snapshot(
    session, *, course_id: str, plan_d: dict, profil: str, heat: float,
    model_version_id, preds: list[dict], course_start_at,
) -> None:
    """Fige un plan émis par le job interne (origin='profil_run', sujet 'system')."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        from services.bet_plan_snapshots import (
            latest_prediction_run_id, record_plan_snapshot,
        )
        from services.mise_calculator import _effective_config, _palier

        cotes = {int(p["numero"]): float(p["cote_pmu"]) for p in preds
                 if p.get("cote_pmu")}
        await record_plan_snapshot(
            session,
            course_id=course_id,
            plan=plan_d,
            profil=profil,
            montant_demande=float(MISE_REF),
            bankroll=None,
            cotes_utilisees=cotes,
            algo_config={
                "profil": profil,
                "heat": round(float(heat or 0.0), 4),
                "cfg": _effective_config(profil, float(heat or 0.0)),
                "palier": _palier(int(MISE_REF)),
                "respect_montant": False,
                "origin": "profil_run",
            },
            emitted_at=_dt.now(_tz.utc),
            course_start_at=course_start_at,
            model_version_id=model_version_id,
            prediction_run_id=await latest_prediction_run_id(session, course_id),
            origin="profil_run",
        )
    except Exception as e:
        log.warning("profil_learning.plan_snapshot_skip",
                    course_id=course_id, profil=profil, err=str(e)[:140])


# ─────────────────────────────────────────────────────────────
# 2. RÉGLER les runs à la fin de course (vrais rapports PMU)
# ─────────────────────────────────────────────────────────────
async def settle_profil_runs(session: AsyncSession, course_id: str) -> int:
    """Règle les runs pending/partial de la course contre l'arrivée officielle.
    Idempotent ; gagnant sans rapport publié → 'partial' (re-tenté plus tard)."""
    from services.bet_settlement import settle_plan

    await ensure_tables(session)

    res = (await session.execute(text("""
        SELECT r.classement, r.rapports, c.nb_partants, r.rapports_detail
        FROM resultats r JOIN courses c ON c.course_id = r.course_id
        WHERE r.course_id = :cid
    """), {"cid": course_id})).first()
    if not res or not res[0]:
        return 0
    classement = res[0] if isinstance(res[0], list) else []
    rapports = res[1] or {}
    nb_partants = res[2] or len(classement)
    rapports_detail = res[3] or None

    # Non-partants déclarés → paris remboursés (pas comptés perdants).
    np_rows = (await session.execute(text("""
        SELECT numero FROM participations
        WHERE course_id = :cid AND non_partant = true
    """), {"cid": course_id})).all()
    non_partants = {int(r[0]) for r in np_rows if r[0] is not None}

    runs = (await session.execute(text("""
        SELECT log_id, plan FROM profil_run_log
        WHERE course_id = :cid AND statut IN ('pending', 'partial')
    """), {"cid": course_id})).all()

    n_settled = 0
    for log_id, plan in runs:
        plan_d = plan if isinstance(plan, dict) else json.loads(plan)
        bilan = settle_plan(plan_d, classement, rapports, nb_partants, rapports_detail, non_partants)
        statut = "partial" if bilan.get("en_attente") else "settled"
        roi = bilan.get("roi")
        await session.execute(text("""
            UPDATE profil_run_log
            SET resultat = CAST(:res AS jsonb), roi_reel = :roi, statut = :st,
                settled_at = now()
            WHERE log_id = :id
        """), {
            "res": json.dumps(bilan), "roi": (roi / 100.0) if roi is not None else None,
            "st": statut, "id": log_id,
        })
        n_settled += 1
    await session.commit()
    if n_settled:
        log.info("profil_learning.runs_settled", course_id=course_id, n=n_settled)
    return n_settled


# ─────────────────────────────────────────────────────────────
# 2b. RATTRAPAGE du règlement (audit ROI 2026-07-02)
# ─────────────────────────────────────────────────────────────
# Constat prod : 114 runs 'pending' + 173 'partial' bloqués depuis des semaines —
# le règlement inline de run_post_course a été manqué (worker down, résultat scrapé
# en retard) et n'était JAMAIS retenté → poids/bandes/calibrations apprises sur un
# échantillon amputé (pertes non comptées → ROI appris surestimé).
CATCHUP_TIMEOUT_DAYS = 7


async def settle_catchup(session: AsyncSession, timeout_days: int = CATCHUP_TIMEOUT_DAYS) -> dict:
    """Rattrapage périodique (nightly + CLI) du règlement des runs profils.

    1. RE-RÈGLE tous les runs pending/partial dont la course est terminée : le
       règlement inline a pu être manqué, et un rapport absent au premier passage
       a pu être scrapé depuis (les 'partial' n'étaient sinon JAMAIS retentés).
    2. EXPIRE (statut 'expired') les runs encore pending/partial au-delà de
       `timeout_days` : rapport jamais publié ou course jamais réglée. On ne
       fabrique JAMAIS un gain — le run sort explicitement du pool d'apprentissage
       (toutes les agrégations filtrent statut='settled') au lieu de traîner
       indéfiniment en faux 'en attente'. Motif conservé dans meta.expired_reason.

    Retourne {"resettled": n, "expired": n, "remaining": n}."""
    await ensure_tables(session)
    course_ids = [r[0] for r in (await session.execute(text("""
        SELECT DISTINCT r.course_id
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut IN ('pending', 'partial') AND c.statut = 'termine'
    """))).all()]
    resettled = 0
    for cid in course_ids:
        try:
            resettled += await settle_profil_runs(session, cid)
        except Exception as e:                    # une course cassée ne bloque pas le lot
            log.warning("profil_learning.catchup_course_failed",
                        course_id=cid, err=str(e)[:120])
    expired = (await session.execute(text("""
        UPDATE profil_run_log
        SET statut = 'expired',
            meta = COALESCE(meta, '{}'::jsonb)
                   || jsonb_build_object('expired_reason', 'timeout_' || statut),
            settled_at = COALESCE(settled_at, now())
        WHERE statut IN ('pending', 'partial')
          AND created_at < now() - make_interval(days => :d)
    """), {"d": int(timeout_days)})).rowcount or 0
    remaining = (await session.execute(text(
        "SELECT count(*) FROM profil_run_log WHERE statut IN ('pending','partial')"
    ))).scalar() or 0
    await session.commit()
    log.info("profil_learning.settle_catchup",
             resettled=resettled, expired=expired, remaining=remaining)
    return {"resettled": resettled, "expired": expired, "remaining": remaining}


# ─────────────────────────────────────────────────────────────
# 3. POIDS D'APPRENTISSAGE depuis les pronos émis réglés
# ─────────────────────────────────────────────────────────────
def shrunk_weight(net: float, mise: float, n: float,
                  k: int = SHRINK_K, w_min: float = W_MIN, w_max: float = W_MAX,
                  roi_reference: float = 0.0) -> float:
    """Multiplicateur appris : 1 + AVANTAGE shrinké vers 0 (n/(n+k)), borné.

    `roi_reference` = rendement d'un joueur SANS COMPÉTENCE sur ce pari, c'est-à-dire
    −prélèvement du pool. Comparer à 0 revient à croire qu'un pari devrait rendre son
    prix : le PMU garde ~15,5 % sur un simple mais ~23 % sur un couplé et ~30 % sur un
    Multi, donc à ROI égal ces paris ne disent PAS la même chose. Sans cette référence,
    un Couplé Placé à −30 % (soit −7 points sur son pool) sortait derrière un Simple
    Gagnant à −25 % (soit −9,5 points sur le sien) — l'inverse de ce que mesure la
    performance réelle.

    Fonction PURE (testable sans DB). n ou mise nuls → neutre 1.0.
    `n` accepte un flottant (n EFFECTIF pondéré par la récence, cf. DECAY_HALF_LIFE_DAYS).
    """
    if mise <= 0 or n <= 0:
        return 1.0
    avantage = net / mise - roi_reference
    eff = avantage * (n / (n + k))
    return max(w_min, min(w_max, 1.0 + eff))


async def compute_profil_weights(session: AsyncSession) -> dict:
    """Agrège les runs RÉGLÉS par profil × type de pari → multiplicateurs appris.
    Persiste dans profil_learning_state (singleton JSONB). Recalculé nightly +
    purgeable à chaque fin de course (peu coûteux)."""
    await ensure_tables(session)

    # Intégrité inconditionnelle : seuls les plans réellement émis avant départ et
    # non backfillés peuvent apprendre des poids. Aucun flag de rollback ne peut
    # réintroduire les runs reconstruits après résultat.
    rows = (await session.execute(text("""
        SELECT r.profil, r.resultat, r.roi_reel, c.discipline, c.nb_partants,
               r.created_at
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND r.created_at < c.date_heure
          AND COALESCE(r.meta->>'backfill', '') <> 'true'
    """))).all()

    # Cold start / cohorte amputée : sous ce volume, l'agrégat ne peut produire que
    # des poids neutres et perdrait les suppressions déjà prouvées (types 0-gain,
    # buckets à ROI ≤ -40 %). On PRÉSERVE l'état appris : rien n'est réécrit, la
    # nuit suivante réessaiera. L'état existant est renvoyé tel quel pour que les
    # lecteurs en mémoire continuent d'appliquer la même chose qu'avant.
    if len(rows) < MIN_PROFIL_WEIGHTS_RUNS:
        log.warning(
            "profil_learning.skipped_insufficient_replayable_data",
            n_runs=len(rows), min_runs=MIN_PROFIL_WEIGHTS_RUNS,
        )
        existing = await load_profil_weights(session) or {}
        # "profils" toujours présent : les scripts de diagnostic l'indexent
        # directement, un cold start total ne doit pas les faire planter.
        return {"profils": {}, **existing,
                "n_observed_runs": len(rows),
                "status": "skipped_insufficient_replayable_data",
                "min_runs": MIN_PROFIL_WEIGHTS_RUNS}

    # ── PRÉ-PASSE : plafond de winsorisation par TYPE ────────────────────────
    # Deux passes sont nécessaires : un quantile ne se calcule pas en flux. La
    # première ne fait que collecter les gains (0 inclus pour les perdants, comme
    # la requête SQL de référence), la seconde accumule en plafonnant.
    _gains_par_type: dict[str, list[float]] = {}
    _gains_par_plan: dict[str, list[float]] = {}
    for _profil, _resultat, _r, _d, _np, _ca in rows:
        if _profil not in PROFILS:
            continue
        _res = _resultat if isinstance(_resultat, dict) else json.loads(_resultat)
        _gains_par_plan.setdefault(_profil, []).append(float(_res.get("total_gain") or 0))
        for _pari in _res.get("paris", []):
            _t = _pari.get("type")
            if not _t:
                continue
            _gains_par_type.setdefault(_t, []).append(
                float(_pari.get("gain") or 0) if _pari.get("statut") == "gagne" else 0.0)
    plafonds: dict[str, float] = {t: p for t, p in
                                  ((t, plafond_gain(g)) for t, g in _gains_par_type.items())
                                  if p is not None}
    # Plafond au niveau du PLAN, par profil : sert au seul `roi_global_winsorise`,
    # publié à côté du ROI brut. C'est le chiffre qui a révélé l'ampleur du défaut
    # (profil agressif : −5,08 % brut contre −30,64 % winsorisé sur 4 033 courses) ;
    # le laisser invisible, c'est laisser croire que le profil perd 5 % quand il en
    # perd 30. Ce champ ne pilote AUCUNE décision — il est là pour être lu.
    plafonds_plan: dict[str, float] = {p: c for p, c in
                                       ((p, plafond_gain(g)) for p, g in _gains_par_plan.items())
                                       if c is not None}
    gain_plan_winsor: dict[str, float] = {
        p: sum(min(g, plafonds_plan[p]) for g in gs)
        for p, gs in _gains_par_plan.items() if p in plafonds_plan}

    def _new_agg():
        return {"types": {}, "n_runs": 0, "mise": 0.0, "gain": 0.0, "runs_benef": 0}

    def _accumulate(agg, res, decay: float = 1.0):
        """Accumule un run réglé. Champs BRUTS (n/mise/gain/win : diagnostics + gate de
        suppression, une preuve de perte n'expire pas) ET champs EFFECTIFS pondérés par
        `decay` (récence) — les POIDS appris se calculent sur l'effectif → ils suivent
        le régime récent du modèle/marché au lieu de moyenner tout l'historique à plat.

        `gain_ew` = le même effectif mais sur les gains PLAFONNÉS au p99 du type
        (cf. `plafond_gain`). C'est LUI qui pilote `shrunk_weight` : un poids doit
        refléter ce qui se reproduit, pas un jackpot unique. `gain`/`gain_e`
        restent bruts pour les diagnostics et l'argent réellement rendu."""
        agg["n_runs"] += 1
        agg["mise"] += float(res.get("total_mise") or 0)
        agg["gain"] += float(res.get("total_gain") or 0)
        if float(res.get("net") or 0) > 0:
            agg["runs_benef"] += 1
        for pari in res.get("paris", []):
            t = pari.get("type")
            if not t:
                continue
            ts = agg["types"].setdefault(t, {"n": 0, "mise": 0.0, "gain": 0.0, "win": 0,
                                             "n_e": 0.0, "mise_e": 0.0, "gain_e": 0.0,
                                             "gain_w": 0.0, "gain_ew": 0.0})
            mise = float(pari.get("mise") or 0)
            ts["n"] += 1
            ts["mise"] += mise
            ts["n_e"] += decay
            ts["mise_e"] += mise * decay
            if pari.get("statut") == "gagne":
                gain = float(pari.get("gain") or 0)
                cap = plafonds.get(t)
                gain_w = min(gain, cap) if cap is not None else gain
                ts["win"] += 1
                ts["gain"] += gain
                ts["gain_e"] += gain * decay
                ts["gain_w"] += gain_w
                ts["gain_ew"] += gain_w * decay

    _now = datetime.now(timezone.utc)

    def _decay_of(created_at) -> float:
        """Poids de récence exponentiel (demi-vie DECAY_HALF_LIFE_DAYS)."""
        if created_at is None:
            return 1.0
        try:
            ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (_now - ts).total_seconds() / 86400.0)
            return 0.5 ** (age_days / DECAY_HALF_LIFE_DAYS)
        except Exception:
            return 1.0

    by_profil: dict[str, dict] = {p: _new_agg() for p in PROFILS}
    # buckets contextuels : by_ctx[profil][ctx_key] = agg
    by_ctx: dict[str, dict] = {p: {} for p in PROFILS}
    for profil, resultat, _roi, discipline, nb_partants, created_at in rows:
        if profil not in by_profil:
            continue
        res = resultat if isinstance(resultat, dict) else json.loads(resultat)
        d = _decay_of(created_at)
        _accumulate(by_profil[profil], res, decay=d)
        ck = ctx_key(discipline, nb_partants)
        _accumulate(by_ctx[profil].setdefault(ck, _new_agg()), res, decay=d)

    out = {"profils": {}, "n_total_runs": sum(a["n_runs"] for a in by_profil.values())}
    for profil, agg in by_profil.items():
        weights = {}
        detail = {}
        for t, ts in agg["types"].items():
            if ts["n"] >= MIN_RUNS_FOR_WEIGHTS:
                # Poids sur les agrégats EFFECTIFS (récence) ET WINSORISÉS : le ROI
                # récent pilote, l'ancien s'estompe (demi-vie DECAY_HALF_LIFE_DAYS),
                # et un jackpot unique ne fixe plus le poids d'un type (cf. plafond_gain).
                # Seuil d'activation sur le n BRUT (préserve « pas d'invention sous 10 runs »).
                w = shrunk_weight(ts["gain_ew"] - ts["mise_e"], ts["mise_e"], ts["n_e"],
                                  roi_reference=-prelevement(t))
            else:
                w = 1.0          # échantillon insuffisant → neutre, pas d'invention
            weights[t] = round(w, 3)
            detail[t] = {
                "n": ts["n"], "win_rate": round(ts["win"] / ts["n"] * 100, 1) if ts["n"] else None,
                # `roi` reste BRUT : c'est l'argent réellement rendu. `roi_winsorise`
                # est celui qui a décidé du poids. Publier les DEUX est le seul moyen
                # de voir d'un coup d'œil qu'un type ne tient que par un gros lot —
                # c'est cet écart (Trio : +51,0 % contre −75,7 %) qui a fait découvrir
                # le défaut, et il ne doit plus jamais être invisible.
                "roi": round((ts["gain"] - ts["mise"]) / ts["mise"] * 100, 1) if ts["mise"] > 0 else None,
                "roi_winsorise": round((ts["gain_w"] - ts["mise"]) / ts["mise"] * 100, 1) if ts["mise"] > 0 else None,
                "poids": round(w, 3),
            }
        # SUPPRESSION GLOBALE « 0 GAIN » (cf. zero_win_suppression) : coupe les types
        # jamais gagnants (solo n≥15, ou famille jackpot poolée sans aucun gain). Le
        # gate dur roi_weights ≤ 0.001 de mise_calculator les écarte alors de la
        # sélection ; le filet « chaque course jouée » reste hors gates.
        for t in zero_win_suppression(agg["types"]):
            weights[t] = 0.0
            if t in detail:
                detail[t]["poids"] = 0.0
                detail[t]["suppressed"] = "zero_win"
        # ── Poids CONTEXTUELS : {ctx_key: {type: poids}} ────────────────────
        # Un bucket (discipline×peloton) n'émet un poids que s'il a ≥ seuil runs ;
        # sinon absent → la conso retombe sur le poids type global (puis 1.0).
        # Additif et sûr : zéro effet tant que les buckets ne sont pas remplis.
        ctx_weights: dict[str, dict] = {}
        suppressed: list[str] = []
        for ck, cagg in by_ctx.get(profil, {}).items():
            cw = {}
            for t, ts in cagg["types"].items():
                n, mise, gain = ts["n"], ts["mise"], ts["gain"]
                roi = (gain - mise) / mise if mise > 0 else 0.0
                if n >= MIN_RUNS_FOR_SUPPRESS and roi <= ROI_SUPPRESS:
                    # GATE DUR : type prouvé perdant DANS CE CONTEXTE → poids 0 = jamais
                    # proposé. Contextuel (pas global) : le même type reste jouable là où
                    # il gagne (ex. Couplé nul au plat, +660% au trot → seul le plat coupé).
                    # RÉHABILITATION par la récence : si le ROI EFFECTIF (récent) est
                    # redevenu ≥ -15%, on ne coupe plus (le régime a changé) — on
                    # sous-pondère seulement. Une suppression ne doit pas être éternelle.
                    # Ce ROI de réhabilitation est WINSORISÉ : sinon un seul gros lot
                    # tombé dans ce bucket suffisait à ressusciter un type prouvé
                    # perdant sur des dizaines de courses. C'est exactement ce qui
                    # avait porté `ctx_weights["plat|g"]["Trio"]` à 1,6.
                    roi_e = ((ts["gain_ew"] - ts["mise_e"]) / ts["mise_e"]
                             if ts.get("mise_e", 0) > 0 else roi)
                    if roi_e <= -0.15:
                        cw[t] = 0.0
                        suppressed.append(f"{ck}:{t} (roi={round(roi*100)}% n={n})")
                    else:
                        cw[t] = round(shrunk_weight(ts["gain_ew"] - ts["mise_e"],
                                                    ts["mise_e"], ts["n_e"],
                                                    roi_reference=-prelevement(t)), 3)
                elif n >= MIN_RUNS_FOR_WEIGHTS_CTX:
                    cw[t] = round(shrunk_weight(ts["gain_ew"] - ts["mise_e"],
                                                ts["mise_e"], ts["n_e"],
                                                roi_reference=-prelevement(t)), 3)
            if cw:
                ctx_weights[ck] = cw
        if suppressed:
            log.info("profil_learning.suppressed", profil=profil, buckets=suppressed)

        mise, gain = agg["mise"], agg["gain"]
        out["profils"][profil] = {
            "n_runs": agg["n_runs"],
            "roi_global": round((gain - mise) / mise * 100, 1) if mise > 0 else None,
            # Diagnostic pur, ne pilote rien : l'écart entre les deux dit si le profil
            # tient par sa méthode ou par un gros lot (cf. `plafonds_plan`).
            "roi_global_winsorise": (
                round((gain_plan_winsor[profil] - mise) / mise * 100, 1)
                if mise > 0 and profil in gain_plan_winsor else None),
            "taux_runs_beneficiaires": round(agg["runs_benef"] / agg["n_runs"] * 100, 1) if agg["n_runs"] else None,
            "type_weights": weights,
            "type_detail": detail,
            "ctx_weights": ctx_weights,
            "suppressed": suppressed,
        }

    await session.execute(text("""
        INSERT INTO profil_learning_state (id, data, updated_at)
        VALUES (1, CAST(:d AS jsonb), now())
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
    """), {"d": json.dumps(out)})
    await session.commit()
    log.info("profil_learning.weights_computed", n_runs=out["n_total_runs"])
    return out


async def load_profil_weights(session: AsyncSession) -> dict | None:
    """Charge l'état appris (None si jamais calculé)."""
    try:
        await ensure_tables(session)
        r = (await session.execute(text(
            "SELECT data FROM profil_learning_state WHERE id = 1"
        ))).first()
        if not r:
            return None
        return r[0] if isinstance(r[0], dict) else json.loads(r[0])
    except Exception as e:
        log.warning("profil_learning.load_failed", err=str(e)[:140])
        return None


def effective_type_weights(pdata: dict, discipline=None, nb_partants=None) -> dict:
    """Poids effectifs {type: w} pour CE contexte de course.

    Part du poids type GLOBAL appris, puis le raffine par le poids CONTEXTUEL
    (discipline × bande de peloton) quand ce bucket a suffisamment appris. Blend
    60% contexte / 40% global : le contexte est plus pertinent mais sur moins de
    runs → on amortit son bruit avec le global. Fonction PURE (testable sans DB).
    Sans contexte ou bucket vide → poids global inchangé (comportement historique)."""
    base = dict(pdata.get("type_weights") or {})
    if discipline is None and nb_partants is None:
        return base
    cw = (pdata.get("ctx_weights") or {}).get(ctx_key(discipline, nb_partants)) or {}
    out = dict(base)
    for t, wc in cw.items():
        wc = float(wc)
        if wc <= 0.001:
            out[t] = 0.0            # bucket SUPPRIMÉ (prouvé perdant) → jamais proposé,
            continue                # pas de blend avec le global (la suppression prime)
        wg = base.get(t, 1.0)
        out[t] = round(0.6 * wc + 0.4 * float(wg), 3)
    return out
