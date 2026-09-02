"""
bet_performance.py — Auto-amélioration de la sélection par le ROI RÉEL observé.

Lit les paris ENREGISTRÉS et RÉGLÉS (bankroll_entries : resultat gagne/perd,
gain_perte net réel issu des vrais rapports PMU) et calcule, par TYPE de pari,
le ROI net réellement réalisé. On en déduit un multiplicateur de conviction
borné, appliqué à la sélection future : on pondère vers les types qui ont
VRAIMENT rapporté, on réduit ceux qui perdent.

Intégrité : 100% données réelles. Un type sans historique suffisant reçoit un
poids NEUTRE (1.0) — aucune invention. Shrinkage vers 1.0 quand l'échantillon
est faible (peu de paris = peu de signal).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# En-deçà de MIN_SAMPLE paris réglés, le ROI d'un type est fortement ramené vers
# le neutre (peu de signal). Bornes du multiplicateur de conviction.
MIN_SAMPLE = 12
WEIGHT_LO, WEIGHT_HI = 0.5, 1.6

_CACHE_KEY = "bet_roi_weights:v1"
_CACHE_TTL = 3600  # 1h — recalcul à la volée sur données réelles à jour


async def compute_type_roi_weights(session: AsyncSession, only_ia: bool = True) -> dict[str, float]:
    """ROI net réel par type_pari → multiplicateur de conviction borné.

    only_ia : ne compter que les paris issus des plans IA (suivi_reco_ia) — c'est
    le track-record du système sur ses propres recommandations.
    """
    where_ia = "AND suivi_reco_ia = true" if only_ia else ""
    rows = (await session.execute(text(f"""
        SELECT type_pari,
               COUNT(*)                       AS n,
               COALESCE(SUM(mise), 0)         AS somme_mise,
               COALESCE(SUM(gain_perte), 0)   AS somme_net
        FROM bankroll_entries
        WHERE resultat IN ('gagne', 'perd')
          AND gain_perte IS NOT NULL
          AND mise > 0
          {where_ia}
        GROUP BY type_pari
    """))).fetchall()

    weights: dict[str, float] = {}
    for type_pari, n, somme_mise, somme_net in rows:
        n = int(n or 0)
        somme_mise = float(somme_mise or 0.0)
        somme_net = float(somme_net or 0.0)
        if n <= 0 or somme_mise <= 0:
            continue
        roi = somme_net / somme_mise            # gain_perte = net → ROI net réel
        shrink = n / (n + MIN_SAMPLE)           # 0 (peu de data) → 1 (beaucoup)
        eff_roi = roi * shrink
        w = max(WEIGHT_LO, min(WEIGHT_HI, 1.0 + eff_roi))
        weights[type_pari] = round(w, 3)

    if weights:
        log.info("bet_performance.roi_weights", weights=weights)
    return weights


async def get_learned_type_weights(session: AsyncSession,
                                   profil: str | None = None,
                                   discipline: str | None = None,
                                   nb_partants: int | None = None) -> dict[str, float]:
    """Poids appris par type, plafonnés par les gates automatiques (Point 11)."""
    weights = await _get_learned_type_weights_raw(session, profil, discipline, nb_partants)
    try:
        from ml.bet_plan_performance import apply_type_gates
        weights = await apply_type_gates(session, weights)
    except Exception:
        pass
    if profil:
        try:
            weights = await _garantir_catalogue_profil(session, profil, weights)
        except Exception:
            pass
    return weights


# Un poids ≤ 0.001 est un gate DUR dans mise_calculator : le type n'est plus jamais
# propose. Le seuil de suspension est ABSOLU (-20 % de ROI) alors que le prelevement
# PMU vaut deja ~20 % : presque tous les types finissent donc sous la barre. Mesure du
# 2026-08-20 : sur les 13 types autorises au profil RISQUE, les 13 etaient suspendus —
# le profil n'avait plus AUCUN pari eligible et retombait sur le filet « une course =
# un pari de secours » a chaque course (2 plans gagnants sur 46 dans la journee).
#
# Garde-fou : un profil conserve TOUJOURS ses meilleurs types, a conviction fortement
# reduite. Le signal d'apprentissage est preserve (mise plus petite, conviction basse)
# sans detruire l'identite du profil. On ne reanime que les MOINS MAUVAIS, classes par
# ROI reel mesure.
PLANCHER_TYPE_REANIME = 0.25
# 4 et non 3 : a 3, le MODERE ne gardait que Simple Place, Couple Place et Simple
# Gagnant — trois types a FAIBLE rapport. Or sa bande x4-15 mesuree sur la mise totale
# exige de gros rapports pour financer plusieurs tickets (besoin = ceil(cible/rapport)).
# Le 4e type reanime est le Couple Ordre : un duo, donc de vrais gros rapports.
# Mesure du 2026-08-20 sur 144 courses (plan 10 EUR) : 47,2 % -> 45,1 % de plans a un
# seul pari, pour 0,3 point de ROI mesure. Aller plus loin (6 types = + Couple Gagnant,
# 8 = + Trio) gagne 0,15 ticket mais fait passer le ROI moyen des types joues de
# -20,6 % a -33,0 % : ce compromis-la n'est PAS pris ici.
MIN_TYPES_PAR_PROFIL = 4
# Un type n'est compté comme « encore jouable » que s'il a un vrai historique de paris.
# Sans ce filtre, le profil MODÉRÉ paraissait servi par Multi en 5/6/7 et Mini Multi
# (4 à 18 paris joués en tout, contre 612 pour le Couplé Placé) : des paris que le PMU
# n'offre presque jamais. Le catalogue semblait plein et le plan restait vide.
MIN_PARIS_TYPE_COURANT = 50


async def _garantir_catalogue_profil(session: AsyncSession, profil: str,
                                     weights: dict[str, float]) -> dict[str, float]:
    """Empêche les gates d'éteindre TOUT le catalogue d'un profil.

    Si moins de `MIN_TYPES_PAR_PROFIL` types autorisés par le profil survivent, on
    réanime les moins mauvais (meilleur ROI mesuré d'abord) au poids plancher. Ne
    touche à rien quand le profil a déjà de quoi jouer.
    """
    if not weights:
        return weights
    from services.mise_calculator import PROFIL_CONFIG
    autorises = (PROFIL_CONFIG.get(profil) or {}).get("types")
    candidats = [t for t in weights if autorises is None or t in autorises]
    if not candidats:
        return weights

    from ml.bet_plan_performance import load_segment_gates
    gates = await load_segment_gates(session, "type_pari")

    def _courant(t: str) -> bool:
        """Type réellement offert par le PMU, jugé sur son historique de paris joués."""
        n = (gates.get(t) or {}).get("n_paris")
        return n is not None and int(n) >= MIN_PARIS_TYPE_COURANT

    vivants = [t for t in candidats if weights[t] > 0.001 and _courant(t)]
    manquants = MIN_TYPES_PAR_PROFIL - len(vivants)
    if manquants <= 0:
        return weights

    def _rang(t: str) -> tuple[int, float]:
        """Classe d'abord les types dont le rendement est MESURÉ, du meilleur au pire.

        Tenter l'inverse (« pas de mesure = pas de preuve qu'il est mauvais ») réanimait
        des paris quasi jamais offerts par le PMU (Pick5, Multi en 4) au lieu des paris
        de travail du profil : le catalogue restait vide en pratique. Un type mesuré à
        −25 % qu'on peut jouer sur chaque course vaut mieux qu'un type inconnu absent
        de 95 % des programmes.

        Le classement se fait sur l'AVANTAGE (ROI + prélèvement du pool), pas sur le ROI
        brut : réanimer « le moins mauvais en absolu » revient à toujours choisir les
        pools bon marché (simples) et à écarter les couplés, alors que c'est là que
        l'avantage mesuré du système est le plus fort. Un Couplé Placé à −30 % sur un
        pool qui prélève 23 % vaut mieux qu'un Simple Gagnant à −25 % sur un pool qui
        n'en prélève que 15,5 %.
        """
        from services.pmu_paris_reference import prelevement
        g = gates.get(t) or {}
        r = g.get("roi_pct")
        return (1, float(r) + prelevement(t) * 100.0) if r is not None else (0, 0.0)

    morts = sorted((t for t in candidats if weights[t] <= 0.001), key=_rang, reverse=True)
    if not morts:
        return weights
    out = dict(weights)
    reanimes = []
    for t in morts[:manquants]:
        out[t] = PLANCHER_TYPE_REANIME
        reanimes.append(t)
    log.info("bet_performance.catalogue_reanime", profil=profil,
             types=reanimes, restants_vivants=len(vivants))
    return out


async def _get_learned_type_weights_raw(session: AsyncSession,
                                        profil: str | None = None,
                                        discipline: str | None = None,
                                        nb_partants: int | None = None) -> dict[str, float]:
    """Poids de conviction APPRIS par type — c'est le cœur de l'auto-amélioration.

    Source PRIORITAIRE (si `profil` fourni et historique suffisant) : ROI réel des
    PRONOS ÉMIS par CE profil (profil_run_log : plans figés avant course, réglés aux
    vrais rapports PMU). C'est l'apprentissage sur les recommandations réellement
    faites — pas sur le top-3 du modèle ni un rejeu.

    Si `discipline`/`nb_partants` sont fournis, les poids sont RAFFINÉS par contexte
    (discipline × bande de peloton) via effective_type_weights — quand ce bucket a
    suffisamment appris ; sinon on garde le poids type global (zéro effet sinon).

    Source suivante : ROI RÉEL winsorisé par type mesuré sur l'historique réglé
    (backtest profils, cache `stats:profils`, recalculé à chaque fin de course et la
    nuit) → un type qui perd (Simple Gagnant) descend, un type qui rapporte (placé à
    valeur) monte. L'algo « apprend le pourquoi » et adapte les futurs paris.

    Repli : si le cache n'est pas encore peuplé, on utilise le ROI des paris
    utilisateur réglés (bankroll). Jamais d'invention : défaut neutre 1.0 par type.
    """
    # 1. Pronos émis par profil (le plus fidèle à ce que l'utilisateur a vu).
    if profil:
        try:
            from ml.profil_learning import (
                load_profil_weights, effective_type_weights, MIN_RUNS_FOR_WEIGHTS,
            )
            state = await load_profil_weights(session)
            if state:
                pdata = (state.get("profils") or {}).get(profil) or {}
                if (pdata.get("n_runs") or 0) >= MIN_RUNS_FOR_WEIGHTS and pdata.get("type_weights"):
                    # raffinage contextuel (additif : retombe sur le global si bucket vide)
                    return effective_type_weights(pdata, discipline, nb_partants)
        except Exception:
            pass

    learned: dict = {}
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get("stats:profils")
        if cached:
            data = json.loads(cached)
            learned = data.get("type_weights") or {}
    except Exception:
        learned = {}

    if learned:
        return learned
    # Repli : ROI réel des paris joués (échantillon souvent faible) → neutre sinon.
    return await get_type_roi_weights(session)


async def get_type_roi_weights(session: AsyncSession) -> dict[str, float]:
    """Poids ROI par type avec cache Redis (best-effort). Renvoie {} si rien."""
    redis = None
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        redis = None

    weights = await compute_type_roi_weights(session)

    try:
        if redis is not None:
            await redis.set(_CACHE_KEY, json.dumps(weights), ex=_CACHE_TTL)
    except Exception:
        pass
    return weights


# ─────────────────────────────────────────────────────────────
# Thermostat adaptatif "heat" ∈ [-1, +1]
#   Relie APPRENTISSAGE (calibration du modèle, race_learning_log.brier_score) et
#   RÉSULTATS (ROI net récent des paris IA réglés). Sert à durcir/assouplir TOUS
#   les profils de mise : froid (modèle mal calibré OU série perdante) → prudence ;
#   chaud (bien calibré + gagnant) → audace mesurée. 100% données réelles.
# ─────────────────────────────────────────────────────────────
_HEAT_CACHE_KEY = "bet_heat:v1"
_HEAT_TTL = 1800           # 30 min
_RECENT_RACES = 60         # fenêtre brier
_RECENT_BETS = 80          # fenêtre ROI récent
_BRIER_GOOD = 0.16         # brier ≤ → modèle bien calibré
_BRIER_BAD = 0.26          # brier ≥ → mal calibré
# Fenêtre du terme « résultats » : les PLANS réellement émis et réglés.
_HEAT_ROI_JOURS = 7
_MIN_PLANS_FOR_ROI = 100
# Un plan ne peut pas rendre plus de 50× sa mise dans ce calcul : le thermostat
# décide d'un comportement, il ne doit jamais basculer sur un coup isolé (même
# plafond que le ROI par tranche de rapport).
_HEAT_GAIN_CAP = 50.0
# Prélèvement PMU moyen du système, pondéré par la mise — MESURÉ le 2026-08-23 sur
# 29 672 paris réglés : 20,08 %. Il sert de zéro au terme « résultats » : un plan à
# −20 % sur des pools qui prennent 20 % n'est pas une série perdante, c'est le tarif
# de la maison. À re-mesurer (`compute_forward_performance` → global.prelevement_pct)
# si le catalogue de types joués change nettement.
PRELEVEMENT_MOYEN_SYSTEME_PCT = 20.0


async def compute_model_heat(session: AsyncSession) -> dict:
    """Calcule le thermostat adaptatif depuis les données RÉELLES.

    heat = 0.5 × terme_calibration + 0.5 × terme_roi_récent, borné [-1, +1].
      - terme_calibration : brier moyen des dernières courses apprises (mappé
        [_BRIER_GOOD, _BRIER_BAD] → [+1, -1]).
      - terme_résultats : AVANTAGE des plans émis et réglés sur les 7 derniers
        jours (ROI winsorisé + prélèvement du pool, mappé ±30% → ±1) ; ignoré sous
        _MIN_PLANS_FOR_ROI plans. Un système à −20 % sur des pools qui prennent
        20 % est à l'équilibre, pas en série perdante.
    Renvoie {heat, brier, roi_recent, n_races, n_bets} (tout réel ; None si absent).
    """
    # ── Calibration : brier moyen récent (race_learning_log) ──
    brier = None
    n_races = 0
    try:
        row = (await session.execute(text("""
            SELECT AVG(brier_score), COUNT(*) FROM (
                SELECT brier_score FROM race_learning_log
                WHERE brier_score IS NOT NULL
                ORDER BY analyzed_at DESC LIMIT :lim
            ) q
        """), {"lim": _RECENT_RACES})).first()
        if row and row[0] is not None:
            brier = float(row[0])
            n_races = int(row[1] or 0)
    except Exception:
        brier = None

    # ── Résultats : AVANTAGE récent des PLANS réellement émis et réglés ─────────
    #
    # Cette mesure lisait `bankroll_entries` — les paris que des utilisateurs ont
    # saisis à la main en cochant « suivi reco IA ». Constat du 2026-08-23 : 80
    # lignes étalées sur DEUX MOIS (12/06 → 20/08), 388 € misés, +849 € nets, soit
    # un ROI de +218,8 % dont +578 € portés par deux tickets (un Mini Multi à ×120,
    # un Couplé Gagnant à ×111). Le terme était donc collé à son maximum (+1) et le
    # thermostat annonçait heat = 0,748 — audace maximale sur TOUS les profils —
    # pendant que les plans du système mesuraient −6 % à −27 %.
    #
    # Un échantillon saisi à la main est auto-sélectionné (on note ses gains), vieux,
    # minuscule, et sans rapport avec ce que le moteur conseille aujourd'hui. On lit
    # désormais les PLANS ÉMIS ET RÉGLÉS, la même source que tout le reste de
    # l'apprentissage — dédupliqués sur le dernier règlement, gains plafonnés.
    #
    # Et on ne juge pas le ROI BRUT mais l'AVANTAGE (ROI + prélèvement du pool) : un
    # système à −20 % sur des pools qui prennent 20 % ne traverse pas une série
    # perdante, il paie le tarif. Sans cela le thermostat resterait au plancher en
    # permanence et ne thermostaterait plus rien.
    roi_recent = None
    n_bets = 0
    try:
        since = datetime.now(timezone.utc) - timedelta(days=_HEAT_ROI_JOURS)
        # DEUX déduplications, comme dans `ml.bet_plan_performance` :
        #   `rn`      = dernier RÈGLEMENT de chaque plan (append-only) ;
        #   `rn_plan` = dernier CONSEIL de chaque (course × profil × montant ×
        #               bankroll). Le même plan est ré-émis à chaque mouvement de
        #               cote (~33 fois par course) : sans cette seconde dédup, le
        #               thermostat pondérait les courses par leur nombre de
        #               ré-émissions — donc par leur liquidité, pas par leur
        #               résultat — et atteignait son seuil de 100 plans avec trois
        #               courses.
        row = (await session.execute(text("""
            SELECT COALESCE(SUM(mise), 0), COALESCE(SUM(retour), 0), COUNT(*)
            FROM (
                SELECT montant_mise AS mise,
                       CASE WHEN montant_retour < montant_mise * :cap
                            THEN montant_retour ELSE montant_mise * :cap END AS retour
                FROM (
                    SELECT montant_mise, montant_retour,
                           ROW_NUMBER() OVER (
                               PARTITION BY course_id, profil, montant_demande, bankroll
                               ORDER BY emitted_at DESC, plan_snapshot_id DESC
                           ) AS rn_plan
                    FROM (
                        SELECT t.montant_mise, t.montant_retour,
                               s.course_id, s.profil, s.montant_demande, s.bankroll,
                               s.emitted_at, s.plan_snapshot_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY t.plan_snapshot_id
                                   ORDER BY t.settled_at DESC, t.settlement_id DESC
                               ) AS rn
                        FROM bet_plan_settlements t
                        JOIN bet_plan_snapshots s
                          ON s.plan_snapshot_id = t.plan_snapshot_id
                        WHERE t.statut = 'settled' AND s.is_pre_course = true
                          AND t.settled_at >= :since AND t.montant_mise > 0
                    ) dernier_reglement
                    WHERE rn = 1
                ) dernier_plan
                WHERE rn_plan = 1
            ) q
        """), {"since": since, "cap": _HEAT_GAIN_CAP})).first()
        if row and float(row[0] or 0) > 0 and int(row[2] or 0) >= _MIN_PLANS_FOR_ROI:
            n_bets = int(row[2] or 0)
            roi = (float(row[1]) - float(row[0])) / float(row[0])
            roi_recent = roi + PRELEVEMENT_MOYEN_SYSTEME_PCT / 100.0
    except Exception:
        roi_recent = None

    # ── Termes ──
    terms = []
    if brier is not None:
        # brier _BRIER_GOOD → +1, _BRIER_BAD → -1 (linéaire borné)
        cal = (_BRIER_BAD - brier) / (_BRIER_BAD - _BRIER_GOOD) * 2.0 - 1.0
        terms.append(max(-1.0, min(1.0, cal)))
    if roi_recent is not None and n_bets >= _MIN_PLANS_FOR_ROI:
        terms.append(max(-1.0, min(1.0, roi_recent / 0.30)))

    heat = round(sum(terms) / len(terms), 3) if terms else 0.0

    # GEL OFFENSIF EN DÉRIVE (2026-07-02) : quand le drift detector est en severity
    # 'critical', le modèle dérive MAINTENANT — un heat > 0 (calé sur le brier/ROI
    # d'AVANT la dérive) assouplirait les gates au pire moment. On cape à ≤ 0
    # (mode prudent/normal) jusqu'à ce que le retrain ramène la severity sous critical.
    drift_freeze = False
    try:
        row = (await session.execute(text(
            "SELECT severity FROM drift_detector_state LIMIT 1"))).first()
        if row and row[0] == "critical" and heat > 0:
            heat = 0.0
            drift_freeze = True
    except Exception:
        pass

    return {
        "heat": heat,
        "brier": round(brier, 4) if brier is not None else None,
        "roi_recent": round(roi_recent, 4) if roi_recent is not None else None,
        "n_races": n_races,
        "n_bets": n_bets,
        "drift_freeze": drift_freeze,
    }


async def get_model_heat(session: AsyncSession) -> float:
    """heat ∈ [-1,+1] avec cache Redis (best-effort). 0.0 si aucun signal."""
    redis = None
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(_HEAT_CACHE_KEY)
        if cached is not None:
            return float(cached)
    except Exception:
        redis = None

    ctx = await compute_model_heat(session)
    heat = float(ctx.get("heat", 0.0))
    try:
        if redis is not None:
            await redis.set(_HEAT_CACHE_KEY, str(heat), ex=_HEAT_TTL)
    except Exception:
        pass
    return heat
