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
import math
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
from services.pmu_paris_reference import prelevement

log = structlog.get_logger(module="bet_plan_performance")

# En dessous, un segment reste "observed" : jamais promu "profitable"/"losing".
# Le run des value bets a montré qu'un ROI sur < 30 paris est dominé par la
# variance (cf. Point 9 : mêmes ordres de grandeur que les autres seuils
# cold-start). Documenté ici plutôt que dupliqué à chaque appelant.
MIN_SEGMENT_OBS = 30
# ── COURSES DISTINCTES, PAS PARIS (audit 2026-08-31) ────────────────────────
# `MIN_SEGMENT_OBS` compte des PARIS, or un même plan est ré-émis à chaque
# mouvement de cote : ~33 snapshots par course en production. Un segment atteint
# donc 30 « observations » avec une seule course. Constat au 2026-08-31 :
#   Mini Multi en 4 : 228 paris mais 17 COURSES, ROI brut +332 % → gate « active »
#   Pick5 : 86 paris / 3 courses · Tiercé Désordre : 35 paris / 1 course
# Le seuil ne peut pas simplement passer en courses : mesuré, cela FAIT REMONTER
# 8 types ruineux (Multi en 4 à −100 % sur 7 courses, Pick5 −100 % sur 3) parce
# qu'un segment redevenu "observed" retombe en "active" par défaut.
#
# La règle est donc ASYMÉTRIQUE, parce que les deux erreurs ne coûtent pas pareil :
#   - SUSPENDRE garde le seuil permissif en paris. Suspendre à tort coûte un type
#     écarté ; ne pas suspendre coûte de l'argent réel, à chaque course.
#   - RESTER ACTIF à plein régime sur un avantage POSITIF exige des courses
#     distinctes. En dessous, le segment est "reduced", jamais "active".
MIN_COURSES_POUR_ACTIF = 30
# Nombre minimal de PLANS (pas de paris) avant de mesurer un drawdown ou une
# série de pertes : sous ce seuil la série temporelle est trop courte pour que
# ces statistiques signifient autre chose que du bruit.
MIN_PLANS_FOR_SERIES = 10
# Quantile de winsorisation des gains. 0.99 et pas moins : on coupe la queue
# extrême, pas la performance. Même définition que `percentile_cont(0.99)` de
# PostgreSQL, pour qu'une mesure faite en SQL et une mesure faite ici coïncident.
WINSOR_QUANTILE = 0.99
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


def _plafond_winsorisation(gains: list[float]) -> Optional[float]:
    """Quantile ``WINSOR_QUANTILE`` d'une liste de gains — fonction PURE.

    Prend TOUS les tickets, gagnants et perdants (les 0 comptent), exactement comme
    ``percentile_cont(0.99) WITHIN GROUP (ORDER BY gain)`` en SQL : c'est ce qui
    permet de rejouer la mesure d'audit à l'identique depuis psql. Liste vide →
    None, c'est-à-dire aucun plafond : on n'invente pas de borne sans données.
    """
    if not gains:
        return None
    s = sorted(float(g or 0.0) for g in gains)
    if len(s) == 1:
        return s[0]
    pos = WINSOR_QUANTILE * (len(s) - 1)
    bas = int(pos)
    haut = min(bas + 1, len(s) - 1)
    return s[bas] + (s[haut] - s[bas]) * (pos - bas)


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


def _prelevement_moyen_pct(bet_rows: list[dict]) -> Optional[float]:
    """Prélèvement PMU du groupe, en %, pondéré par la MISE réellement engagée.

    Le pari mutuel n'a pas un seul « taux de la maison » : le PMU garde ~15,5 % sur
    un simple, ~23 % sur un couplé, ~25 % sur un trio, ~30 % sur un Multi. Un même
    ROI ne dit donc PAS la même chose selon le pool : −20 % sur un Multi, c'est
    +10 points de mieux que le hasard ; −20 % sur un Simple Gagnant, c'est
    −4,5 points de moins. Pondéré par la mise (et non par le nombre de paris) parce
    que c'est l'argent engagé, pas le nombre de tickets, qui subit le prélèvement.
    """
    total = sum(float(b.get("mise") or 0.0) for b in bet_rows)
    if total <= 0:
        return None
    pondere = sum(float(b.get("mise") or 0.0) * prelevement(b.get("type"))
                  for b in bet_rows)
    return round(pondere / total * 100, 2)


def _streak_attendue(hit_rate: Optional[float], n_plans: int) -> Optional[float]:
    """Plus longue série perdante ATTENDUE pour un taux de réussite donné.

    Espérance de la plus longue suite d'échecs sur ``n`` tirages indépendants de
    probabilité de succès ``p`` : ln(n) / ln(1/(1−p)). Un Multi en 4 qui tombe une
    fois sur onze enchaîne NORMALEMENT une trentaine de plans perdants sur 300 —
    ce n'est pas une anomalie de risque, c'est sa loi. Sans cette référence, tout
    pari à faible fréquence et gros rapport se fait signaler « drawdown excessif »
    quel que soit son rendement (constat prod du 2026-08-23 : « Mini Multi en 4 »
    à +332 % de ROI était rétrogradé pour cette seule raison).
    """
    if not hit_rate or hit_rate <= 0 or hit_rate >= 1 or n_plans < 2:
        return None
    return math.log(n_plans) / math.log(1.0 / (1.0 - hit_rate))


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

    # ── ROI WINSORISÉ (audit 2026-08-31) ────────────────────────────────────
    # `retour` est l'argent réellement rendu : il reste brut, on n'affiche jamais
    # un euro winsorisé. Mais un ROI sert à JUGER, et un jugement ne doit pas
    # tenir à un seul ticket. Mesure qui l'impose, sur 4 039 courses rejouables :
    # le Trio ressortait à +51,0 % de ROI alors qu'un unique gain de 4 526 € (sur
    # 6 023 € misés au total) portait 49,8 % de tous ses gains ; winsorisé, il vaut
    # −75,7 %. C'est ce chiffre-là, pas le brut, qui doit décider d'une suspension.
    plafond = _plafond_winsorisation([b["gain"] or 0.0 for b in bet_rows])
    retour_w = (round(sum(min(b["gain"] or 0.0, plafond) for b in bet_rows), 2)
                if plafond is not None else retour)
    roi_winsor = round((retour_w - mise) / mise * 100, 2) if mise > 0 else None

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
    # AVANTAGE RÉEL = ce que le ROI vaut UNE FOIS LE PRÉLÈVEMENT DÉDUIT de la
    # comparaison. Un parieur sans aucune compétence sur un pool qui prélève t %
    # finit à −t % : c'est le zéro. `edge_pct = roi_pct + prelevement_pct` mesure
    # donc la compétence propre du système, la seule grandeur comparable entre un
    # Simple Gagnant (15,5 %) et un Multi (30 %).
    prelev = _prelevement_moyen_pct(bet_rows)
    edge = round(roi + prelev, 2) if (roi is not None and prelev is not None) else None
    edge_w = (round(roi_winsor + prelev, 2)
              if (roi_winsor is not None and prelev is not None) else None)
    streak_attendue = _streak_attendue(hit_rate, n_plans)
    return {
        "n_plans": n_plans,
        "n_paris": n_paris,
        "n_courses": courses_total,
        "montant_mise": mise,
        # `montant_retour` est de l'argent RÉELLEMENT rendu : jamais winsorisé.
        "montant_retour": retour,
        "net_profit": net,
        "roi_pct": roi if reliable else None,
        "roi_pct_raw": roi,
        # ROI/avantage WINSORISÉS : ce sont eux qui décident (cf. evaluate_segment_gates).
        # Les bruts restent publiés à côté — l'écart entre les deux est le signal
        # « ce segment ne tient que par un gros lot », et il doit rester lisible.
        "roi_pct_winsor": roi_winsor if reliable else None,
        "roi_pct_winsor_raw": roi_winsor,
        "plafond_winsorisation": (round(plafond, 2) if plafond is not None else None),
        "prelevement_pct": prelev,
        "edge_pct": edge if reliable else None,
        "edge_pct_raw": edge,
        "edge_pct_winsor": edge_w if reliable else None,
        "edge_pct_winsor_raw": edge_w,
        "hit_rate": hit_rate,
        "taux_courses_beneficiaires": taux_courses_benef,
        "drawdown_max": drawdown_max,
        "losing_streak_max": losing_streak_max,
        # Série perdante NORMALE pour ce taux de réussite — le repère qui dit si
        # `losing_streak_max` est une anomalie ou la loi du pari.
        "losing_streak_attendue": (round(streak_attendue, 1)
                                   if streak_attendue is not None else None),
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
    # ORDER BY s.emitted_at DESC : INDISPENSABLE, et son absence a coûté cher.
    # Il y a ~33 snapshots pré-course par course. Sans tri, la boucle
    # `if course_id in seen: continue` gardait un snapshot ARBITRAIRE — donc le plus
    # souvent un snapshot ancien, dont les cotes ne désignent pas encore le vrai
    # favori. Mesuré le 2026-08-31 sur les mêmes 611 courses :
    #     snapshot le plus ancien   → le favori gagne 11,4 %, ROI −43,00 %
    #     ordre physique (avant fix)→ 12,7 %, ROI −40,93 %   [valeur servie : −44,22 %]
    #     dernier snapshot (ci-dessous) → 26,5 %, ROI −25,85 %
    #     contrôle indépendant sur `predictions.cote_figee` → 26,7 %, ROI −25,68 %
    # Le comparateur annonçait donc un marché à −44 % là où il est à −26 %, et
    # surestimait l'avantage revendiqué par BlackTurf de 17 à 18 points. Un
    # comparateur sans garde de cote figée n'est pas un comparateur.
    stmt = text("""
        SELECT s.course_id, s.cotes_utilisees, r.classement
        FROM bet_plan_snapshots s
        JOIN resultats r ON r.course_id = s.course_id
        WHERE s.course_id IN :cids AND s.is_pre_course = true
        ORDER BY s.course_id, s.emitted_at DESC
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


def _taille_baseline(type_pari: str) -> Optional[int]:
    """Nombre de chevaux que prendrait le MÊME type de pari joué sur le classement.

    « Multi en 6 » → les 6 premiers du classement, « Trio » → les 3 premiers, etc.
    None = type dont on ne sait pas construire la sélection de référence : on
    préfère ne rien comparer plutôt que comparer n'importe quoi.
    """
    if not type_pari:
        return None
    t = str(type_pari)
    if "Multi en " in t:                       # « Multi en 5 », « Mini Multi en 5 »
        try:
            return int(t.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            return None
    return {
        "Simple Gagnant": 1, "Simple Placé": 1,
        "Couplé Gagnant": 2, "Couplé Placé": 2, "Couplé Ordre": 2, "2sur4": 2,
        "Trio": 3, "Trio Ordre": 3, "Tiercé Désordre": 3, "Tiercé Ordre": 3,
        "Super 4": 4, "Quarté+": 4, "Quarté+ Désordre": 4,
        "Quinté+": 5, "Quinté+ Désordre": 5, "Quinté+ Flexi": 5, "Pick5": 5,
    }.get(t)


async def _baseline_classement_par_type(
    session: AsyncSession, course_ids: list[str], types: list[str],
) -> dict[str, dict]:
    """Rendement du MÊME type de pari joué sur les N PREMIERS DU CLASSEMENT.

    C'est le comparateur qui manquait. ``naive_favorite_comparator`` répond à
    « bat-on le favori du marché ? » ; celui-ci répond à la question qui décide de
    l'architecture du moteur : **la sélection apporte-t-elle quelque chose au
    classement, ou lui coûte-t-elle ?** Un type dont le moteur tire −33 % là où
    « les 2 premiers du classement » rend −11 % n'a pas un problème de type de
    pari : il a un problème de choix des chevaux.

    Réglé par ``settle_pari`` — exactement le même code que les vrais conseils,
    donc même traitement des rapports, des ex-æquo et des non-partants. Mise 1 €
    par course. Un pari gagnant dont le rapport n'est pas publié est EXCLU (jamais
    compté 0), même règle d'honnêteté que le règlement des plans.
    """
    if not course_ids or not types:
        return {}
    tailles = {t: _taille_baseline(t) for t in types}
    tailles = {t: n for t, n in tailles.items() if n}
    if not tailles:
        return {}

    stmt = text("""
        SELECT pr.course_id, pr.rang_predit, pa.numero, pa.non_partant,
               c.nb_partants, r.classement, r.rapports, r.rapports_detail
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN courses c ON c.course_id = pr.course_id
        JOIN resultats r ON r.course_id = pr.course_id
        WHERE pr.course_id IN :cids
    """).bindparams(bindparam("cids", expanding=True))
    rows = (await session.execute(stmt, {"cids": list(set(course_ids))})).all()
    if not rows:
        return {}

    par_course: dict[str, dict] = {}
    for course_id, rang, numero, non_partant, nb_partants, cl_raw, rap_raw, det_raw in rows:
        c = par_course.setdefault(course_id, {
            "rangs": {}, "np": set(), "nb_partants": nb_partants,
            "classement": cl_raw, "rapports": rap_raw, "detail": det_raw,
        })
        try:
            num = int(numero)
        except (TypeError, ValueError):
            continue
        if non_partant:
            c["np"].add(num)
            continue                      # un NP n'a pas sa place dans la référence
        if rang is not None:
            c["rangs"][int(rang)] = num

    from services.bet_settlement import settle_pari

    out: dict[str, dict] = {}
    for course_id, c in par_course.items():
        classement = c["classement"] if isinstance(c["classement"], list) else (
            json.loads(c["classement"]) if c["classement"] else None)
        if not classement:
            continue
        rapports = c["rapports"] if isinstance(c["rapports"], dict) else (
            json.loads(c["rapports"]) if c["rapports"] else {})
        detail = c["detail"] if isinstance(c["detail"], dict) else (
            json.loads(c["detail"]) if c["detail"] else None)
        # Rangs RECALCULÉS après retrait des non-partants : « les 2 premiers du
        # classement » doit désigner deux chevaux réellement au départ.
        ordre = [c["rangs"][r] for r in sorted(c["rangs"]) if c["rangs"][r] not in c["np"]]
        for type_pari, n in tailles.items():
            if len(ordre) < n:
                continue
            res = settle_pari(type_pari, ordre[:n], classement, rapports,
                              c["nb_partants"] or len(classement), detail, c["np"])
            if res.get("rembourse"):
                continue
            agg = out.setdefault(type_pari, {"n_courses": 0, "mise": 0.0, "gain": 0.0,
                                             "n_gagnes": 0, "n_rapport_absent": 0})
            if res.get("gagne"):
                if res.get("rapport_reel") is None:
                    agg["n_rapport_absent"] += 1
                    continue              # gain inconnu → hors mesure, jamais 0
                agg["gain"] += float(res["rapport_reel"]) * float(res.get("gain_mult", 1.0))
                agg["n_gagnes"] += 1
            agg["n_courses"] += 1
            agg["mise"] += 1.0

    for type_pari, agg in out.items():
        mise = agg["mise"]
        roi = round((agg["gain"] - mise) / mise * 100, 2) if mise > 0 else None
        agg["roi_pct"] = roi
        agg["hit_rate"] = round(agg["n_gagnes"] / agg["n_courses"], 4) if agg["n_courses"] else None
        agg["prelevement_pct"] = round(prelevement(type_pari) * 100, 2)
        agg["edge_pct"] = round(roi + agg["prelevement_pct"], 2) if roi is not None else None
        agg["mise"] = round(mise, 2)
        agg["gain"] = round(agg["gain"], 2)
    return out


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

    # Référence CLASSEMENT : le même type de pari, joué sur les N premiers du
    # classement, sur les MÊMES courses. Rattaché à chaque segment de la dimension
    # `type_pari` — la seule où la comparaison a un sens (un « type de pari » a une
    # sélection de référence évidente, pas une « bande d'EV »).
    if dimension == "type_pari" and segments:
        try:
            baselines = await _baseline_classement_par_type(
                session, [p["course_id"] for p in plan_rows], list(segments))
        except Exception as exc:      # une référence indisponible ne casse jamais la mesure
            log.warning("bet_plan_performance.baseline_classement_skip", err=str(exc)[:160])
            baselines = {}
        for key, m in segments.items():
            base = baselines.get(key)
            if not base:
                continue
            m["baseline_classement"] = base
            # Écart en points de ROI entre notre sélection et le simple suivi du
            # classement. Négatif = la sélection DÉTRUIT de la valeur sur ce type.
            m["delta_vs_classement_pct"] = (
                round(m["roi_pct"] - base["roi_pct"], 2)
                if m.get("roi_pct") is not None and base.get("roi_pct") is not None
                else None)

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
# AVANTAGE (edge_pct = roi_pct + prélèvement du pool) sous ce seuil → suspension.
#
# L'ancien seuil était un ROI ABSOLU de −20 %, avec pour justification qu'il serait
# « nettement au-delà du prélèvement PMU ». C'était faux pour la moitié du catalogue :
# le PMU garde ~15,5 % sur un simple mais ~23 % sur un couplé, ~25 % sur un trio et
# ~30 % sur un Multi. Un seuil unique juge donc les pools à handicaps différents avec
# la même règle, et il coupe mécaniquement les pools chers, quelle que soit la
# compétence du système. Constat prod du 2026-08-23 (fenêtre 90 j) :
#   • Couplé Placé   −32,7 % de ROI, prélèvement 23 %  → avantage −9,7 pts  → suspendu
#   • Simple Gagnant −19,2 % de ROI, prélèvement 15,5 % → avantage −3,7 pts → gardé
# alors que la mesure sur le classement montre l'avantage le plus FORT sur les paires
# (couplés) et quasi nul sur le gagnant sec. Le tri était à l'envers.
#
# −8 points : on ne suspend que ce qui est franchement PIRE que le hasard sur son
# propre pool. Entre −8 et 0, le système ne bat pas le prélèvement mais n'aggrave pas
# non plus le tirage au sort : il reste jouable à conviction apprise (les poids ROI
# le pénalisent déjà) et continue de produire du signal d'apprentissage.
EDGE_SUSPEND_THRESHOLD_PCT = -8.0
# Repli quand le prélèvement du segment est inconnu (aucune mise, type hors
# catalogue) : on retombe sur l'ancien seuil absolu plutôt que de ne rien décider.
ROI_SUSPEND_THRESHOLD_PCT = -20.0
# Un drawdown ne signale un problème que s'il dépasse NETTEMENT celui qu'implique
# la fréquence du pari (cf. _streak_attendue). Facteur 2 : deux fois la série
# perdante attendue, c'est au-delà de la variance ordinaire.
DRAWDOWN_TOLERANCE_FACTOR = 2.0
REDUCE_FACTOR = 0.5
# Écart, en points de ROI, en dessous duquel la sélection est jugée DESTRUCTRICE
# face au simple suivi du classement (cf. _baseline_classement_par_type). Mesure
# du 2026-08-23 : sur le Couplé Placé, le moteur rend −32,7 % là où « les 2 premiers
# du classement » rend −11,5 % — 21 points perdus par le choix des chevaux, pas par
# le type de pari. Réduction (×0,5), pas suspension : le type reste bon, c'est la
# sélection qui doit être corrigée en amont.
DELTA_CLASSEMENT_REDUCE_PCT = -10.0
# Nombre minimal de courses derrière la référence classement avant d'en tirer une
# décision — même exigence de fiabilité que pour un segment.
MIN_BASELINE_COURSES = MIN_SEGMENT_OBS
# Avantage de la RÉFÉRENCE classement au-dessus duquel le type est jugé VIABLE :
# suivre bêtement le classement y bat déjà le prélèvement. Un tel type ne doit pas
# être éteint pour cause de mauvaise sélection — l'éteindre interdit la correction
# qu'il appelle. Mesure du 2026-08-23 : le Couplé Placé sort à −32,2 % de ROI avec
# le moteur (avantage −9,2 → suspendu par l'ancienne règle) mais à −10,3 % joué sur
# les 2 premiers du classement, soit +12,7 points d'avantage : c'est le MEILLEUR
# pool du système, et il était coupé. À l'inverse le Trio (référence à −6,2) et le
# 2sur4 (−5,8) ne passent pas ce test : eux restent suspendus.
BASELINE_EDGE_VIABLE_PCT = 0.0


def evaluate_segment_gates(perf: dict) -> dict[str, dict]:
    """Décision par segment à partir d'un rapport ``compute_forward_performance``.

    Ne tranche JAMAIS sous les seuils de fiabilité déjà appliqués par
    ``_metrics_for_group`` (``status == "observed"``) : un segment encore
    "observed" reste "active" ici, quel que soit son ROI apparent.

    Deux garde-fous ajoutés le 2026-08-31, après mesure sur 611 courses :

    1. La décision porte sur l'avantage **winsorisé** (``edge_pct_winsor``). Simulé
       sur la production : aucune suspension supplémentaire, aucun catalogue de
       profil éteint — mais Couplé Gagnant passe de +22,2 à −5,7 pts d'avantage et
       Couplé Ordre de +10,9 à −5,2. Ces deux types étaient crédités d'une
       compétence qu'ils n'ont pas ; ils sont désormais à 2 points de la suspension,
       ce qui est la vérité de la mesure.
    2. Un avantage positif sur moins de ``MIN_COURSES_POUR_ACTIF`` courses
       distinctes vaut ``reduced``, pas ``active``. Simulé : une seule décision
       change dans toute la production — « Mini Multi en 4 » (17 courses, +332 %).

    Ce qui a été essayé et REJETÉ : remplacer ``reliable = n_paris >= 30`` par
    ``n_courses >= 30``. Mesuré, cela réhabilitait 8 types ruineux (Multi en 4 à
    −100 % sur 7 courses, Pick5 −100 % sur 3, Tiercé et Quinté+ Désordre −100 % sur
    1 course chacun), parce qu'un segment redevenu "observed" retombe en "active"
    par défaut. Le seuil de SUSPENSION reste donc volontairement permissif.
    """
    out: dict[str, dict] = {}
    for key, m in (perf.get("segments") or {}).items():
        status, factor, reason = "active", 1.0, None
        # DÉCISION SUR L'AVANTAGE WINSORISÉ (audit 2026-08-31), pas sur le brut :
        # un segment ne doit ni survivre ni être condamné à cause d'un seul ticket.
        # Repli sur le brut si la winsorisation n'a pas pu se calculer (segment vide).
        edge = m.get("edge_pct_winsor")
        if edge is None:
            edge = m.get("edge_pct")
        edge_brut = m.get("edge_pct")
        n_courses = m.get("n_courses") or 0
        streak_att = m.get("losing_streak_attendue")
        streak_max = m.get("losing_streak_max")
        baseline = m.get("baseline_classement") or {}
        delta = m.get("delta_vs_classement_pct")
        # Le type est-il viable QUAND ON SUIT SIMPLEMENT LE CLASSEMENT ? Si oui, un
        # mauvais résultat vient de la sélection, pas du pari : on réduit, on ne coupe
        # pas — couper interdirait la correction que la mesure appelle.
        baseline_viable = (
            (baseline.get("n_courses") or 0) >= MIN_BASELINE_COURSES
            and baseline.get("edge_pct") is not None
            and baseline["edge_pct"] > BASELINE_EDGE_VIABLE_PCT
        )
        if (m.get("reliable") and baseline_viable and delta is not None
                and delta <= DELTA_CLASSEMENT_REDUCE_PCT):
            status, factor = "reduced", REDUCE_FACTOR
            reason = (f"type VIABLE sur le classement (référence {baseline['roi_pct']}%, "
                      f"avantage {baseline['edge_pct']} pts sur {baseline['n_courses']} courses) "
                      f"mais sélection {delta} pts en dessous — le pari n'est pas en cause, "
                      f"le choix des chevaux l'est")
        elif m.get("reliable") and edge is not None and edge <= EDGE_SUSPEND_THRESHOLD_PCT:
            status, factor = "suspended", 0.0
            reason = (f"avantage winsorisé={edge} pts <= {EDGE_SUSPEND_THRESHOLD_PCT} "
                      f"(roi winsorisé={m.get('roi_pct_winsor')}, roi brut={m.get('roi_pct')}, "
                      f"prélèvement={m.get('prelevement_pct')}%, "
                      f"n={m['n_paris']} paris sur {n_courses} courses)")
        elif (m.get("reliable") and edge is None and m.get("roi_pct") is not None
              and m["roi_pct"] <= ROI_SUSPEND_THRESHOLD_PCT):
            # Prélèvement inconnu → repli sur l'ancien critère absolu.
            status, factor = "suspended", 0.0
            reason = (f"prélèvement inconnu, repli roi_pct={m['roi_pct']} "
                      f"<= {ROI_SUSPEND_THRESHOLD_PCT} (n={m['n_paris']})")
        elif (m.get("reliable") and edge is not None and edge > 0
              and n_courses < MIN_COURSES_POUR_ACTIF):
            # AVANTAGE POSITIF MAIS TROP PEU DE COURSES DISTINCTES.
            # `reliable` compte des PARIS, or le même plan est ré-émis ~33 fois par
            # course : un segment peut donc paraître fiable sur une poignée de
            # courses. Constat au 2026-08-31 : « Mini Multi en 4 » était `active`
            # avec 228 paris… répartis sur 17 courses, ROI +332 %. On ne coupe pas
            # (rien ne prouve qu'il soit mauvais) mais on refuse de miser à plein
            # sur une performance qui n'a pas encore rencontré 30 courses.
            status, factor = "reduced", REDUCE_FACTOR
            reason = (f"avantage={edge} pts mais seulement {n_courses} courses "
                      f"distinctes < {MIN_COURSES_POUR_ACTIF} ({m.get('n_paris')} paris, "
                      f"le même plan étant ré-émis à chaque mouvement de cote)")
        elif (streak_att and streak_max is not None
              and streak_max > DRAWDOWN_TOLERANCE_FACTOR * streak_att
              and not (edge is not None and edge > 0)):
            # Série perdante bien au-delà de ce que la fréquence du pari implique,
            # ET aucun avantage démontré pour la justifier → on réduit sans couper.
            status, factor = "reduced", REDUCE_FACTOR
            reason = (f"série perdante {streak_max} > {DRAWDOWN_TOLERANCE_FACTOR:g}× "
                      f"l'attendu {streak_att} (drawdown_max={m.get('drawdown_max')})")
        out[key] = {
            "status": status, "factor": factor, "reason": reason,
            # `roi_pct` reste le BRUT : c'est lui que lit `_garantir_catalogue_profil`
            # pour classer les types à réanimer, et le changer ici changerait ce
            # classement sans que rien ne le dise.
            "roi_pct": m.get("roi_pct"),
            "roi_pct_winsor": m.get("roi_pct_winsor"),
            # `edge_pct` porte désormais l'avantage QUI A DÉCIDÉ (winsorisé) ;
            # `edge_pct_brut` garde le non-winsorisé pour pouvoir comparer.
            "edge_pct": edge, "edge_pct_brut": edge_brut,
            "prelevement_pct": m.get("prelevement_pct"),
            "delta_vs_classement_pct": delta,
            "n_paris": m.get("n_paris"), "n_courses": m.get("n_courses"),
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
            SELECT segment_key, status, factor, reason, roi_pct, n_paris
            FROM bet_plan_segment_gates WHERE dimension = :dim
        """), {"dim": dimension})).all()
        return {r[0]: {"status": r[1], "factor": float(r[2]), "reason": r[3],
                       # roi_pct sert à CLASSER les types quand il faut en réanimer
                       # (cf. bet_performance._garantir_catalogue_profil) : sans lui on
                       # ne saurait pas lequel est le moins mauvais.
                       "roi_pct": (float(r[4]) if r[4] is not None else None),
                       "n_paris": (int(r[5]) if r[5] is not None else None)}
                for r in rows}
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
