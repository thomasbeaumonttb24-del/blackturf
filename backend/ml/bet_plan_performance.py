"""Rentabilité FORWARD des plans réellement émis (`bet_plan_snapshots`).

Source unique de vérité : les conseils réellement émis avant le départ
(`bet_plan_evaluation`, cf. migration 0031), réglés sur les vrais rapports PMU.
Aucune reconstruction après coup — un plan jamais figé n'entre jamais dans une
mesure de rentabilité.

Deux niveaux de mesure :

- **Par PARI** (mise/retour/hit-rate/tranches) : le seul niveau où « tranche de
  cote », « type de pari » ou « simple vs combinaison » ont un sens.
- **Par PLAN** (drawdown, série de pertes, volatilité, IC bootstrap) : un plan
  entier est l'unité de décision d'un utilisateur un jour donné ; c'est la série
  temporelle des plans, pas des paris individuels, qui mesure le risque vécu.

Intégrité : sous ``MIN_SEGMENT_OBS``, un segment reste ``status="observed"``,
jamais ``"profitable"``/``"losing"`` — un petit échantillon ou un gros gain
isolé ne doit jamais faire déclarer une stratégie rentable.
"""
from __future__ import annotations

import json
import random
import statistics
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.cote_calibration import COTE_EDGES, bucket_index
from ml.isotonic_calibration import _nb_bucket
from ml.profil_learning import JACKPOT_TYPES, _is_jackpot_type
from ml.signal_performance import EV_BANDS, _ev_band_key

log = structlog.get_logger(module="bet_plan_performance")

# En dessous, un segment reste "observed" : jamais promu "profitable"/"losing".
# Le run des value bets a montré qu'un ROI sur < 30 paris est dominé par la
# variance (cf. Point 9 : mêmes ordres de grandeur que les autres seuils
# cold-start). Documenté ici plutôt que dupliqué à chaque appelant.
MIN_SEGMENT_OBS = 30
# Nombre minimal de PLANS (pas de paris) avant de mesurer un drawdown ou une
# série de pertes : sous ce seuil la série temporelle est trop courte pour que
# ces statistiques signifient autre chose que du bruit.
MIN_PLANS_FOR_SERIES = 10
BOOTSTRAP_ITER = 2000
BOOTSTRAP_SEED = 20260818  # figé : deux appels sur les mêmes données → même IC

# Ancienneté du snapshot au moment de l'émission (délai avant le départ).
SNAPSHOT_AGE_BUCKETS = [
    (0, 600, "0-10min"),
    (600, 3600, "10-60min"),
    (3600, 86400, "1-24h"),
    (86400, 10 ** 9, ">24h"),
]
# Bornes de bankroll — alignées sur les paliers produit (mise_calculator).
BANKROLL_BUCKETS = [
    (0, 30, "micro"), (30, 100, "petit"), (100, 1000, "moyen"), (1000, 10 ** 9, "gros"),
]

DIMENSIONS = (
    "profil", "type_pari", "cote_band", "ev_band", "discipline", "hippodrome",
    "peloton", "model_version", "snapshot_age", "bankroll", "combo",
)


def _as_dt(value) -> Optional[datetime]:
    """Normalise une colonne DateTime lue par ``text()``.

    asyncpg (PostgreSQL) renvoie déjà des ``datetime`` ; SQLite (tests, driver
    aiosqlite) renvoie une chaîne ISO pour une requête brute non-ORM — même
    précédent que ``ml/features.py`` pour ``last_date``.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _bucket(value: float, edges: list[tuple[float, float, str]]) -> str:
    for lo, hi, label in edges:
        if lo <= value < hi:
            return label
    return edges[-1][2]


def _flatten_plan_bets(plan: dict) -> list[dict]:
    """Aplatit les paris du plan dans le MÊME ORDRE que ``settle_plan`` (double
    boucle niveaux → paris) : c'est ce qui permet de les recaler par index sur
    ``bilan["paris"]`` sans avoir à ré-identifier un pari par (type, chevaux)."""
    out = []
    for niveau in plan.get("niveaux") or []:
        for pari in niveau.get("paris") or []:
            out.append({
                "type": pari.get("type"),
                "chevaux": [int(c["numero"]) for c in (pari.get("chevaux") or [])
                           if c.get("numero") is not None],
                "ev_estime": pari.get("ev_estime"),
                "probabilite": pari.get("probabilite"),
            })
    return out


def _segment_key(dimension: str, bet_row: dict) -> Optional[str]:
    if dimension == "profil":
        return bet_row["profil"]
    if dimension == "type_pari":
        return bet_row["type"]
    if dimension == "cote_band":
        cote = bet_row.get("cote_moyenne")
        if cote is None or cote <= 1:
            return None
        i = bucket_index(float(cote))
        lo, hi = COTE_EDGES[i], COTE_EDGES[i + 1]
        return f"[{lo:g}-{hi:g})" if hi < 1e8 else f"[{lo:g}+)"
    if dimension == "ev_band":
        ev = bet_row.get("ev_estime")
        return _ev_band_key(float(ev)) if ev is not None else None
    if dimension == "discipline":
        return bet_row.get("discipline") or "inconnu"
    if dimension == "hippodrome":
        return bet_row.get("hippodrome") or "inconnu"
    if dimension == "peloton":
        return _nb_bucket(int(bet_row.get("nb_partants") or 0))
    if dimension == "model_version":
        return bet_row.get("model_version_id") or "inconnu"
    if dimension == "snapshot_age":
        age_s = bet_row.get("snapshot_age_s")
        return _bucket(float(age_s), SNAPSHOT_AGE_BUCKETS) if age_s is not None else None
    if dimension == "bankroll":
        bk = bet_row.get("bankroll")
        return _bucket(float(bk), BANKROLL_BUCKETS) if bk is not None else "inconnu"
    if dimension == "combo":
        return "combinaison" if bet_row.get("is_combo") else "simple"
    return None


def _drawdown_and_streak(net_series: list[float]) -> tuple[float, int]:
    """Drawdown max (perte cumulée depuis le pic, en €) + plus longue série de
    plans consécutifs en perte, sur la série ORDONNÉE DANS LE TEMPS des nets
    par plan (chronologie d'émission — pas de résultat trié a posteriori)."""
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = 0
    max_streak = 0
    for net in net_series:
        cum += net
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        if net < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return round(max_dd, 2), max_streak


def _bootstrap_ci(values: list[float], iters: int = BOOTSTRAP_ITER) -> Optional[tuple[float, float]]:
    """IC 90% (percentile bootstrap) sur la moyenne. None si trop peu de points
    pour qu'un ré-échantillonnage signifie quoi que ce soit."""
    n = len(values)
    if n < 10:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(iters):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.05 * iters)]
    hi = means[min(iters - 1, int(0.95 * iters))]
    return round(lo, 4), round(hi, 4)


def _metrics_for_group(bet_rows: list[dict], plan_rows: list[dict]) -> dict:
    """Métriques agrégées sur un groupe de paris + les plans qui les contiennent.

    ``plan_rows`` doit être trié par ``emitted_at`` croissant AVANT l'appel : le
    drawdown/la série de pertes n'ont de sens que dans l'ordre d'émission réel.
    """
    n_paris = len(bet_rows)
    mise = round(sum(b["mise"] for b in bet_rows), 2)
    retour = round(sum(b["gain"] or 0.0 for b in bet_rows), 2)
    net = round(retour - mise, 2)
    hit = sum(1 for b in bet_rows if b["statut"] == "gagne")
    hit_rate = round(hit / n_paris, 4) if n_paris else None
    roi = round(net / mise * 100, 2) if mise > 0 else None

    n_plans = len(plan_rows)
    plan_nets = [p["net"] for p in plan_rows]
    courses_benef = len({p["course_id"] for p in plan_rows if p["net"] > 0})
    courses_total = len({p["course_id"] for p in plan_rows})
    taux_courses_benef = round(courses_benef / courses_total * 100, 1) if courses_total else None

    if n_plans >= MIN_PLANS_FOR_SERIES:
        drawdown_max, losing_streak_max = _drawdown_and_streak(plan_nets)
        volatilite = round(statistics.pstdev(plan_nets), 2) if n_plans > 1 else 0.0
        mediane = round(statistics.median(plan_nets), 2)
        ci = _bootstrap_ci(plan_nets)
    else:
        drawdown_max = losing_streak_max = volatilite = mediane = None
        ci = None

    reliable = n_paris >= MIN_SEGMENT_OBS
    return {
        "n_plans": n_plans,
        "n_paris": n_paris,
        "n_courses": courses_total,
        "montant_mise": mise,
        "montant_retour": retour,
        "net_profit": net,
        "roi_pct": roi if reliable else None,
        "roi_pct_raw": roi,
        "hit_rate": hit_rate,
        "taux_courses_beneficiaires": taux_courses_benef,
        "drawdown_max": drawdown_max,
        "losing_streak_max": losing_streak_max,
        "volatilite": volatilite,
        "mediane_resultat_plan": mediane,
        "ic90_moyenne_plan": ci,
        "reliable": reliable,
        "min_obs": MIN_SEGMENT_OBS,
        # status jamais tranché sous le seuil : ni "profitable" ni "losing" ne
        # doit pouvoir sortir d'un échantillon trop petit ou d'un seul gros gain.
        "status": ("profitable" if roi and roi > 0 else "losing") if reliable and roi is not None else "observed",
    }


async def _naive_favorite_roi(session: AsyncSession, course_ids: list[str]) -> Optional[dict]:
    """ROI d'1€ Simple Gagnant flat sur le FAVORI perçu par le système au moment
    de l'émission (cote la plus basse dans ``cotes_utilisees``), sur les mêmes
    courses que le segment — comparateur naïf, pas un signal appris."""
    if not course_ids:
        return None
    # IN (expanding bindparam), pas ANY(:cids) : portable SQLite (tests) + PostgreSQL.
    # Le filtre "classement bien formé" se fait côté Python (isinstance ci-dessous) :
    # jsonb_typeof est PostgreSQL-only, et le classement mal formé reste rare/marginal.
    stmt = text("""
        SELECT s.course_id, s.cotes_utilisees, r.classement
        FROM bet_plan_snapshots s
        JOIN resultats r ON r.course_id = s.course_id
        WHERE s.course_id IN :cids AND s.is_pre_course = true
    """).bindparams(bindparam("cids", expanding=True))
    rows = (await session.execute(stmt, {"cids": list(set(course_ids))})).all()
    seen: set[str] = set()
    mise = gain = 0.0
    n = 0
    for course_id, cotes_raw, classement_raw in rows:
        if course_id in seen:
            continue
        cotes = cotes_raw if isinstance(cotes_raw, dict) else (
            json.loads(cotes_raw) if cotes_raw else None)
        classement = classement_raw if isinstance(classement_raw, list) else (
            json.loads(classement_raw) if classement_raw else None)
        if not cotes or not isinstance(classement, list) or not classement:
            continue
        seen.add(course_id)
        try:
            fav_num = min(cotes, key=lambda k: float(cotes[k]))
            fav_cote = float(cotes[fav_num])
        except (ValueError, TypeError):
            continue
        # Gagnant = entrée à position == 1 (PAS l'index 0 : le classement n'est pas
        # garanti trié — même convention que scripts/calibration_longshots.fetch_winners).
        gagnant = None
        for entry in classement:
            if isinstance(entry, dict):
                try:
                    if int(entry.get("position")) == 1:
                        gagnant = entry.get("numero")
                        break
                except (TypeError, ValueError):
                    continue
        mise += 1.0
        n += 1
        if gagnant is not None and int(gagnant) == int(fav_num):
            gain += fav_cote
    if n == 0:
        return None
    net = round(gain - mise, 2)
    return {"n_courses": n, "montant_mise": round(mise, 2), "montant_retour": round(gain, 2),
            "net_profit": net, "roi_pct": round(net / mise * 100, 2) if mise else None}


async def compute_forward_performance(
    session: AsyncSession, dimension: str, since: Optional[datetime] = None,
) -> dict:
    """Rentabilité forward des plans réglés, segmentée selon ``dimension``.

    Retourne ``{"dimension", "since", "global": {...}, "segments": {clé: {...}},
    "naive_favorite_comparator": {...}}``. Le comparateur favori est calculé sur
    les MÊMES courses que le groupe global (pas par segment — un favori n'a pas
    de « bande d'EV »).
    """
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension inconnue: {dimension}")

    params: dict = {}
    since_clause = ""
    if since is not None:
        since_clause = "AND t.settled_at >= :since"
        params["since"] = since

    # ROW_NUMBER() plutôt que DISTINCT ON : compatible SQLite (tests) ET PostgreSQL
    # (même convention que admin.py / clv_monitor.py). Dernier règlement 'settled'
    # de chaque plan émis avant le départ.
    rows = (await session.execute(text(f"""
        SELECT plan_snapshot_id, course_id, profil, bankroll, model_version_id,
               emitted_at, course_start_at, plan, discipline, hippodrome_nom,
               nb_partants, bilan, net, roi, settled_at
        FROM (
            SELECT s.plan_snapshot_id, s.course_id, s.profil, s.bankroll,
                   s.model_version_id, s.emitted_at, s.course_start_at, s.plan,
                   c.discipline, c.hippodrome_nom, c.nb_partants,
                   t.bilan, t.net, t.roi, t.settled_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.plan_snapshot_id
                       ORDER BY t.settled_at DESC, t.settlement_id DESC
                   ) AS rn
            FROM bet_plan_snapshots s
            JOIN courses c ON c.course_id = s.course_id
            JOIN bet_plan_settlements t
                ON t.plan_snapshot_id = s.plan_snapshot_id AND t.statut = 'settled'
            WHERE s.is_pre_course = true
              {since_clause}
        ) ranked
        WHERE rn = 1
    """), params)).all()

    plan_rows: list[dict] = []
    all_bet_rows: list[dict] = []
    by_segment: dict[str, list[dict]] = {}
    by_segment_plans: dict[str, dict[str, dict]] = {}  # segment -> {plan_snapshot_id: plan_row}

    for (plan_snapshot_id, course_id, profil, bankroll, model_version_id, emitted_at,
         course_start_at, plan, discipline, hippodrome, nb_partants, bilan, net, roi,
         settled_at) in rows:
        emitted_at = _as_dt(emitted_at)
        course_start_at = _as_dt(course_start_at)
        # asyncpg/aiosqlite renvoient parfois du JSON en chaîne pour une requête
        # texte brute (pas de décodage typé hors ORM) — même précédent que
        # profil_learning.settle_profil_runs pour son propre `plan`.
        plan_d = plan if isinstance(plan, dict) else (json.loads(plan) if plan else {})
        bilan_d = bilan if isinstance(bilan, dict) else (json.loads(bilan) if bilan else {})
        plan_row = {"plan_snapshot_id": plan_snapshot_id, "course_id": course_id,
                    "emitted_at": emitted_at, "net": float(net or 0.0)}
        plan_rows.append(plan_row)

        bet_specs = _flatten_plan_bets(plan_d)
        bet_bilans = bilan_d.get("paris") or []
        cotes = plan_d.get("cotes_utilisees") if isinstance(plan_d.get("cotes_utilisees"), dict) else None
        age_s = None
        if emitted_at is not None and course_start_at is not None:
            age_s = (course_start_at - emitted_at).total_seconds()

        for spec, settled_bet in zip(bet_specs, bet_bilans):
            if settled_bet.get("statut") == "rembourse":
                continue  # neutre pour le ROI, comme dans settle_plan
            chevaux = spec.get("chevaux") or []
            cote_moy = None
            if cotes:
                vals = [float(cotes[str(n)]) for n in chevaux if str(n) in cotes]
                if vals:
                    cote_moy = sum(vals) / len(vals)
            bet_row = {
                "plan_snapshot_id": plan_snapshot_id,
                "course_id": course_id,
                "profil": profil,
                "type": spec.get("type") or settled_bet.get("type"),
                "ev_estime": spec.get("ev_estime"),
                "cote_moyenne": cote_moy,
                "discipline": discipline,
                "hippodrome": hippodrome,
                "nb_partants": nb_partants,
                "model_version_id": model_version_id,
                "snapshot_age_s": age_s,
                "bankroll": bankroll,
                "is_combo": len(chevaux) > 1 or _is_jackpot_type(spec.get("type") or ""),
                "mise": float(settled_bet.get("mise") or 0.0),
                "gain": settled_bet.get("gain"),
                "statut": settled_bet.get("statut"),
            }
            all_bet_rows.append(bet_row)
            key = _segment_key(dimension, bet_row)
            if key is None:
                continue
            by_segment.setdefault(key, []).append(bet_row)
            by_segment_plans.setdefault(key, {})[plan_snapshot_id] = plan_row

    plan_rows.sort(key=lambda p: p["emitted_at"] or datetime.min.replace(tzinfo=timezone.utc))
    global_metrics = _metrics_for_group(all_bet_rows, plan_rows)

    segments = {}
    for key, bets in by_segment.items():
        seg_plans = sorted(by_segment_plans[key].values(),
                           key=lambda p: p["emitted_at"] or datetime.min.replace(tzinfo=timezone.utc))
        segments[key] = _metrics_for_group(bets, seg_plans)

    naive = await _naive_favorite_roi(session, [p["course_id"] for p in plan_rows])

    return {
        "dimension": dimension,
        "since": since.isoformat() if since else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global": global_metrics,
        "segments": segments,
        "naive_favorite_comparator": naive,
    }


# ─────────────────────────────────────────────────────────────
# Gates automatiques — segment négatif / drawdown excessif
# ─────────────────────────────────────────────────────────────
# ROI% sous ce seuil, avec assez d'observations, suspend le segment (poids ×0).
# -20% : nettement au-delà du prélèvement PMU moyen (~25-30% brut mais réparti,
# l'edge visé est positif) — un ROI durablement pire que ça n'est pas du bruit.
ROI_SUSPEND_THRESHOLD_PCT = -20.0
# drawdown_max / montant misé du segment ≥ cette fraction → mises réduites de
# moitié plutôt que suspendues (le segment n'est pas prouvé perdant, mais la
# série de pertes vécue dépasse ce qu'un profil normal doit encaisser).
DRAWDOWN_REDUCE_FRACTION = 0.5
REDUCE_FACTOR = 0.5


def evaluate_segment_gates(perf: dict) -> dict[str, dict]:
    """Décision par segment à partir d'un rapport ``compute_forward_performance``.

    Ne tranche JAMAIS sous les seuils de fiabilité déjà appliqués par
    ``_metrics_for_group`` (``status == "observed"``) : un segment encore
    "observed" reste "active" ici, quel que soit son ROI apparent.
    """
    out: dict[str, dict] = {}
    for key, m in (perf.get("segments") or {}).items():
        status, factor, reason = "active", 1.0, None
        if m.get("reliable") and m.get("roi_pct") is not None and m["roi_pct"] <= ROI_SUSPEND_THRESHOLD_PCT:
            status, factor = "suspended", 0.0
            reason = f"roi_pct={m['roi_pct']} <= {ROI_SUSPEND_THRESHOLD_PCT} (n={m['n_paris']})"
        elif (m.get("drawdown_max") is not None and m.get("montant_mise")
              and m["montant_mise"] > 0
              and m["drawdown_max"] / m["montant_mise"] >= DRAWDOWN_REDUCE_FRACTION):
            status, factor = "reduced", REDUCE_FACTOR
            reason = (f"drawdown_max={m['drawdown_max']} >= "
                     f"{DRAWDOWN_REDUCE_FRACTION:.0%} de montant_mise={m['montant_mise']}")
        out[key] = {
            "status": status, "factor": factor, "reason": reason,
            "roi_pct": m.get("roi_pct"), "n_paris": m.get("n_paris"),
            "n_plans": m.get("n_plans"), "drawdown_max": m.get("drawdown_max"),
        }
    return out


async def persist_segment_gates(session: AsyncSession, dimension: str, gates: dict[str, dict]) -> int:
    """Upsert des décisions de gate. Un segment qui redisparaît du rapport (plus
    assez d'observations récentes) n'est PAS supprimé ici : la dernière décision
    connue reste appliquée jusqu'au prochain calcul qui la révise explicitement —
    on ne réactive jamais un segment suspendu par simple absence de données."""
    if not gates:
        return 0
    now = datetime.now(timezone.utc)
    for key, g in gates.items():
        await session.execute(text("""
            INSERT INTO bet_plan_segment_gates
                (dimension, segment_key, status, factor, reason, roi_pct, n_paris, updated_at)
            VALUES (:dim, :key, :status, :factor, :reason, :roi, :n, :now)
            ON CONFLICT (dimension, segment_key) DO UPDATE SET
                status = EXCLUDED.status, factor = EXCLUDED.factor,
                reason = EXCLUDED.reason, roi_pct = EXCLUDED.roi_pct,
                n_paris = EXCLUDED.n_paris, updated_at = EXCLUDED.updated_at
        """), {"dim": dimension, "key": key, "status": g["status"], "factor": g["factor"],
               "reason": g["reason"], "roi": g.get("roi_pct"), "n": g.get("n_paris"), "now": now})
    await session.commit()
    return len(gates)


async def load_segment_gates(session: AsyncSession, dimension: str) -> dict[str, dict]:
    """Charge les gates actives pour une dimension. {} si table absente (avant
    migration 0032) ou vide — jamais une erreur qui casserait l'appelant."""
    try:
        rows = (await session.execute(text("""
            SELECT segment_key, status, factor, reason
            FROM bet_plan_segment_gates WHERE dimension = :dim
        """), {"dim": dimension})).all()
        return {r[0]: {"status": r[1], "factor": float(r[2]), "reason": r[3]} for r in rows}
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        return {}


async def apply_type_gates(session: AsyncSession, type_weights: dict[str, float]) -> dict[str, float]:
    """Applique les gates ``type_pari`` sur des poids déjà appris (multiplicatif).

    Ne peut qu'ABAISSER un poids existant, jamais l'inventer ni le relever au-delà
    de ce que l'apprentissage a déjà produit — le gate est un plafond de sécurité,
    pas une source de conviction.
    """
    if not type_weights:
        return type_weights
    gates = await load_segment_gates(session, "type_pari")
    if not gates:
        return type_weights
    return {t: round(w * gates[t]["factor"], 4) if t in gates else w
            for t, w in type_weights.items()}
