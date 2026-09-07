"""Chiffres RÉELS par type de pari, pour la supervision IA.

Source unique : ``profil_run_log`` — le conseil de mise réellement émis pour une
course, réglé sur les vrais rapports PMU. Deux gardes d'intégrité identiques à
celles du palmarès et de ``learning-convergence`` :

- ``created_at < courses.date_heure`` : le conseil existait AVANT le départ ;
- ``meta->>'backfill' <> 'true'`` : jamais un run reconstruit a posteriori.

Sans ces gardes, un ROI est contaminé par la connaissance du résultat.

Trois règles gouvernent chaque chiffre publié ici — elles viennent toutes de
mesures faites sur cette base, pas d'un principe théorique :

1. **Winsorisation à 50× la mise** (``PB_GAIN_CAP``) pour tout ROI qui sert de
   VERDICT. Sans elle, le Trio affiche +84 % de ROI sur 1 305 paris… dont 24
   gagnants et un unique rapport à 4 526 €. Winsorisé, le même Trio tombe à
   -46 %. Le chiffre brut reste exposé à côté : l'écart entre les deux EST
   l'information. En revanche, **une courbe de capital vécu n'est jamais
   winsorisée** : l'argent réellement encaissé un jour donné n'a pas de plafond
   (cf. ``compute_profitability_timeline``, qui renvoie les deux séries).
2. **La fiabilité se compte en GAGNANTS, pas en paris** (``PB_MIN_WINS…``).
   836 paris à 4 % de réussite (~33 gagnants) ne valent pas 2 208 paris à 37 %
   (~815 gagnants). Aucun segment n'est déclaré rentable sous 150 gagnants.
3. **Test de robustesse** : le ROI recalculé en retirant les 1/5/20 plus gros
   gains. Un ROI qui s'effondre quand on retire cinq coups n'est pas un edge,
   c'est une poignée de coups.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.bet_plan_performance import _drawdown_and_streak
from ml.signal_performance import PB_GAIN_CAP, PB_MIN_WINS_POUR_FAVORISER
from services.pmu_paris_reference import PAR_NOM, _famille

log = structlog.get_logger(module="bet_type_analytics")

# Nombre de gagnants sous lequel aucun verdict (rentable / perdant) n'est rendu.
MIN_WINS_VERDICT = PB_MIN_WINS_POUR_FAVORISER
# Retraits successifs testés par le test de robustesse.
ROBUSTNESS_DROPS = (1, 5, 20)
# Profils exposés côté produit, dans l'ordre de risque croissant.
PROFIL_LABELS = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}

_SQL_BETS = """
    SELECT r.log_id, r.profil, r.course_id, c.date_heure, c.discipline,
           r.resultat
    FROM profil_run_log r
    JOIN courses c ON c.course_id = r.course_id
    WHERE r.statut = 'settled'
      AND r.resultat IS NOT NULL
      AND c.date_heure IS NOT NULL
      AND r.created_at < c.date_heure
      AND COALESCE(r.meta->>'backfill', '') <> 'true'
      {since_clause}
    ORDER BY c.date_heure
"""


def _as_json(value: Any) -> dict:
    """``resultat`` arrive en dict via asyncpg, en chaîne via un driver texte."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


async def _load_bets(session: AsyncSession, since: Optional[datetime]) -> list[dict]:
    """Aplatit tous les paris réglés de la fenêtre, un dict par PARI."""
    sql = _SQL_BETS.format(
        since_clause="AND c.date_heure >= :since" if since else ""
    )
    params = {"since": since} if since else {}
    rows = (await session.execute(text(sql), params)).all()

    bets: list[dict] = []
    for log_id, profil, course_id, date_heure, discipline, resultat in rows:
        res = _as_json(resultat)
        for p in res.get("paris") or []:
            mise = float(p.get("mise") or 0.0)
            if mise <= 0:
                continue                      # un pari sans mise n'est pas un pari
            statut = p.get("statut")
            if statut == "en_attente":
                continue                      # rapport PMU pas encore publié
            nom = p.get("type") or "inconnu"
            bets.append({
                "log_id": log_id,
                "profil": profil,
                "course_id": course_id,
                "jour": date_heure.date() if date_heure else None,
                "date_heure": date_heure,
                "discipline": discipline,
                "type": nom,
                "famille": _famille(nom) or nom,
                "mise": mise,
                "gain": float(p.get("gain") or 0.0),
                "gagne": statut == "gagne",
                "niveau": p.get("niveau"),
            })
    return bets


def _roi(mise: float, retour: float) -> Optional[float]:
    return round((retour - mise) / mise * 100, 2) if mise > 0 else None


# Sous ce nombre de paris, aucun intervalle n'est publié : la moyenne d'une
# poignée de rendements très asymétriques n'a pas d'intervalle interprétable.
MIN_PARIS_IC = 30
Z90 = 1.645


def _ic90(nets: list[float], mises: list[float]) -> Optional[list[float]]:
    """IC 90 % du ROI PUBLIÉ, en %, par la variance de l'estimateur de ratio.

    Le ROI affiché est ``Σnet / Σmise`` : il pondère chaque pari par sa mise. Un
    intervalle bâti sur la moyenne NON pondérée des rendements ne décrit pas ce
    chiffre-là — sur la fenêtre 90 j de prod, il donnait [-26,6 % ; -17,6 %]
    autour d'un ROI publié de -15,96 %, soit un point estimé HORS de son propre
    intervalle. On utilise donc la variance de l'estimateur de ratio :
    ``Var(net - R·mise) / (n · mise_moyenne²)``.

    Les rendements sont DÉJÀ winsorisés à 50× la mise quand ils arrivent ici :
    la queue qui invaliderait le TCL a donc été coupée en amont, et un bootstrap
    (2 000 ré-échantillonnages × 18 000 paris) coûtait 25 s pour un intervalle
    identique à la deuxième décimale. Le coût comptait : cette page se
    rafraîchit toute seule.
    """
    n = len(nets)
    if n < MIN_PARIS_IC:
        return None
    total_mise = sum(mises)
    if total_mise <= 0:
        return None
    ratio = sum(nets) / total_mise
    mise_moy = total_mise / n
    residus = [net - ratio * mise for net, mise in zip(nets, mises)]
    marge = Z90 * statistics.pstdev(residus) / (n ** 0.5) / mise_moy
    return [round((ratio - marge) * 100, 2), round((ratio + marge) * 100, 2)]


def _robustness(bets: list[dict]) -> list[dict]:
    """ROI winsorisé recalculé en retirant les k plus gros gains.

    Le pari retiré l'est ENTIÈREMENT (mise comprise) : c'est la question posée —
    « et si ces coups-là n'avaient jamais eu lieu ? ».
    """
    gagnants = sorted(
        (b for b in bets if b["gagne"]),
        key=lambda b: min(b["gain"], PB_GAIN_CAP * b["mise"]),
        reverse=True,
    )
    out = []
    for k in ROBUSTNESS_DROPS:
        # Retirer plus de paris qu'il n'y a de gagnants reviendrait à retirer des
        # PERDANTS, ce qui remonterait le ROI : l'inverse de la question posée.
        if k > len(gagnants):
            break
        retires = {id(b) for b in gagnants[:k]}
        reste = [b for b in bets if id(b) not in retires]
        mise = sum(b["mise"] for b in reste)
        retour = sum(min(b["gain"], PB_GAIN_CAP * b["mise"]) for b in reste)
        out.append({"retires": k, "roi_pct": _roi(mise, retour), "n_restants": len(reste)})
    return out


def _agg(bets: list[dict]) -> dict:
    """Agrégat complet d'un groupe de paris — brut, winsorisé, IC, verdict."""
    n = len(bets)
    if n == 0:
        return {"n_paris": 0, "n_gagnants": 0, "verdict": "insuffisant"}

    mise = sum(b["mise"] for b in bets)
    retour = sum(b["gain"] for b in bets)
    retour_w = sum(min(b["gain"], PB_GAIN_CAP * b["mise"]) for b in bets)
    n_wins = sum(1 for b in bets if b["gagne"])

    # IC 90 % du ROI winsorisé publié — même pondération par la mise que lui.
    nets_w = [min(b["gain"], PB_GAIN_CAP * b["mise"]) - b["mise"] for b in bets]
    ic90 = _ic90(nets_w, [b["mise"] for b in bets])

    roi_w = _roi(mise, retour_w)
    if n_wins < MIN_WINS_VERDICT or ic90 is None:
        verdict = "insuffisant"
    elif ic90[0] > 0:
        verdict = "rentable"
    elif ic90[1] < 0:
        verdict = "perdant"
    else:
        verdict = "neutre"

    gains = [b["gain"] for b in bets if b["gagne"]]
    return {
        "n_paris": n,
        "n_gagnants": n_wins,
        "n_courses": len({b["course_id"] for b in bets}),
        "mise": round(mise, 2),
        "retour": round(retour, 2),
        "net": round(retour - mise, 2),
        "net_winsorise": round(retour_w - mise, 2),
        "roi_brut_pct": _roi(mise, retour),
        "roi_pct": roi_w,
        "hit_rate": round(n_wins / n * 100, 2),
        "gain_max": round(max(gains), 2) if gains else 0.0,
        "gain_median": round(statistics.median(gains), 2) if gains else None,
        "mise_moyenne": round(mise / n, 2),
        "ic90_roi_pct": ic90,
        "n_gagnants_requis": MIN_WINS_VERDICT,
        "verdict": verdict,
        "robustesse": _robustness(bets),
    }


def _reference(nom: str) -> Optional[dict]:
    """Fiche PMU du type (prélèvement, champ minimal, conseil d'emploi)."""
    ref = PAR_NOM.get(_famille(nom))
    if ref is None:
        return None
    return {
        "famille": ref.nom,
        "a_trouver": ref.a_trouver,
        "prelevement_pct": round(ref.prelevement * 100, 1),
        "mise_base": ref.mise_base,
        "partants_min": ref.partants_min,
        "frequence_offre_pct": round(ref.frequence_offre * 100, 1) if ref.frequence_offre else None,
        "quand_le_jouer": ref.quand_le_jouer,
    }


def _semaine(d) -> str:
    iso = d.isocalendar()
    return f"S{iso[1]:02d}"


async def compute_bet_type_analytics(
    session: AsyncSession, days: Optional[int] = 90, top_series: int = 6,
) -> dict:
    """Tous les chiffres par type de pari sur la fenêtre demandée."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    bets = await _load_bets(session, since)

    by_type: dict[str, list[dict]] = {}
    by_famille: dict[str, list[dict]] = {}
    by_profil_type: dict[tuple[str, str], list[dict]] = {}
    for b in bets:
        by_type.setdefault(b["type"], []).append(b)
        by_famille.setdefault(b["famille"], []).append(b)
        by_profil_type.setdefault((b["profil"], b["type"]), []).append(b)

    glob = _agg(bets)
    mise_totale = glob.get("mise") or 0.0
    net_total = glob.get("net_winsorise") or 0.0

    types = []
    for nom, group in by_type.items():
        m = _agg(group)
        m["type"] = nom
        m["famille"] = _famille(nom) or nom
        m["part_mise_pct"] = round(m["mise"] / mise_totale * 100, 1) if mise_totale else None
        m["contribution_net_pct"] = (
            round(m["net_winsorise"] / abs(net_total) * 100, 1) if net_total else None
        )
        m["reference"] = _reference(nom)
        types.append(m)
    types.sort(key=lambda t: t["mise"], reverse=True)

    familles = []
    for nom, group in by_famille.items():
        m = _agg(group)
        m["famille"] = nom
        m["part_mise_pct"] = round(m["mise"] / mise_totale * 100, 1) if mise_totale else None
        familles.append(m)
    familles.sort(key=lambda f: f["mise"], reverse=True)

    # Matrice profil × type — uniquement les types les plus joués, sinon illisible.
    top_types = [t["type"] for t in types[:top_series]]
    matrice = []
    for (profil, nom), group in by_profil_type.items():
        if nom not in top_types:
            continue
        mise = sum(b["mise"] for b in group)
        retour_w = sum(min(b["gain"], PB_GAIN_CAP * b["mise"]) for b in group)
        matrice.append({
            "profil": PROFIL_LABELS.get(profil, profil),
            "profil_key": profil,
            "type": nom,
            "n_paris": len(group),
            "n_gagnants": sum(1 for b in group if b["gagne"]),
            "mise": round(mise, 2),
            "roi_pct": _roi(mise, retour_w),
        })

    # Série hebdomadaire : volume misé et ROI winsorisé, par type le plus joué.
    semaines: dict[str, dict] = {}
    for b in bets:
        if not b["jour"]:
            continue
        wk = b["jour"] - timedelta(days=b["jour"].weekday())
        key = wk.isoformat()
        cell = semaines.setdefault(key, {"semaine": _semaine(wk), "debut": key, "_par_type": {}})
        t = b["type"] if b["type"] in top_types else "Autres"
        agg = cell["_par_type"].setdefault(t, {"mise": 0.0, "retour": 0.0, "n": 0})
        agg["mise"] += b["mise"]
        agg["retour"] += min(b["gain"], PB_GAIN_CAP * b["mise"])
        agg["n"] += 1

    serie = []
    for key in sorted(semaines):
        cell = semaines[key]
        row: dict[str, Any] = {"semaine": cell["semaine"], "debut": cell["debut"]}
        for t, agg in cell["_par_type"].items():
            row[f"roi::{t}"] = _roi(agg["mise"], agg["retour"])
            row[f"mise::{t}"] = round(agg["mise"], 2)
            row[f"n::{t}"] = agg["n"]
        serie.append(row)

    return {
        "fenetre_jours": days,
        "since": since.isoformat() if since else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": ("profil_run_log — conseils émis avant le départ, réglés sur les "
                   "rapports PMU réels ; runs backfillés exclus"),
        "gain_cap_mise": PB_GAIN_CAP,
        "min_gagnants_verdict": MIN_WINS_VERDICT,
        "global": glob,
        "types": types,
        "familles": familles,
        "matrice_profil_type": matrice,
        "types_series": top_types,
        "serie_hebdo": serie,
    }


async def compute_profitability_timeline(
    session: AsyncSession, days: Optional[int] = 90,
) -> dict:
    """Rentabilité jour par jour : net, ROI, capital cumulé, drawdown vécu.

    Deux séries sont renvoyées CÔTE À CÔTE, jamais l'une à la place de l'autre :

    - ``net`` / ``cumul_net`` / ``roi_pct`` : les gains RÉELLEMENT encaissés,
      sans plafond. C'est ce qu'a vécu quelqu'un qui a suivi les conseils — le
      19/07 vaut +4 306 € parce qu'un rapport à 4 526 € est réellement tombé.
    - ``*_winsor`` : les mêmes jours avec les gains coupés à ``PB_GAIN_CAP`` ×
      la mise. Lecture prudente, utile pour juger une stratégie sans laisser un
      coup unique décider du verdict.

    Winsoriser la courbe « capital vécu » la rendait fausse dans les deux sens :
    elle écrasait les gros jours gagnants (+4 306 € affichés +280 €) et
    retournait 4 jours bénéficiaires en jours perdants. Le plafond reste partout
    où un ROI sert de VERDICT (``_agg``, poids de profil), jamais sur l'argent
    réellement compté.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    bets = await _load_bets(session, since)

    par_jour: dict[str, dict] = {}
    par_jour_profil: dict[str, dict[str, dict]] = {}
    for b in bets:
        if not b["jour"]:
            continue
        key = b["jour"].isoformat()
        cell = par_jour.setdefault(key, {
            "jour": key, "mise": 0.0, "retour": 0.0, "retour_winsor": 0.0,
            "n_paris": 0, "n_gagnants": 0, "courses": set(),
        })
        gain_w = min(b["gain"], PB_GAIN_CAP * b["mise"])
        cell["mise"] += b["mise"]
        cell["retour"] += b["gain"]
        cell["retour_winsor"] += gain_w
        cell["n_paris"] += 1
        cell["n_gagnants"] += 1 if b["gagne"] else 0
        cell["courses"].add(b["course_id"])

        pcell = par_jour_profil.setdefault(b["profil"], {}).setdefault(
            key, {"mise": 0.0, "retour": 0.0, "retour_winsor": 0.0})
        pcell["mise"] += b["mise"]
        pcell["retour"] += b["gain"]
        pcell["retour_winsor"] += gain_w

    jours = sorted(par_jour)
    cumul = 0.0
    cumul_w = 0.0
    serie = []
    for j in jours:
        c = par_jour[j]
        net = c["retour"] - c["mise"]
        net_w = c["retour_winsor"] - c["mise"]
        cumul += net
        cumul_w += net_w
        serie.append({
            "jour": j,
            "mise": round(c["mise"], 2),
            "retour": round(c["retour"], 2),
            "retour_winsor": round(c["retour_winsor"], 2),
            "net": round(net, 2),
            "net_winsor": round(net_w, 2),
            "roi_pct": _roi(c["mise"], c["retour"]),
            "roi_winsor_pct": _roi(c["mise"], c["retour_winsor"]),
            "cumul_net": round(cumul, 2),
            "cumul_net_winsor": round(cumul_w, 2),
            "n_paris": c["n_paris"],
            "n_gagnants": c["n_gagnants"],
            "n_courses": len(c["courses"]),
        })

    # ROI glissant 14 jours : lisse le bruit quotidien sans masquer une tendance.
    # Tant que la fenêtre n'est pas PLEINE, aucune valeur n'est publiée : sinon
    # le premier point est le ROI d'une seule journée, affiché sur une courbe qui
    # annonce quatorze — un +8 % de départ qui n'a jamais existé.
    FEN = 14
    for i, row in enumerate(serie):
        if i + 1 < FEN:
            row["roi_glissant_pct"] = None
            row["roi_glissant_winsor_pct"] = None
            continue
        window = serie[i - FEN + 1: i + 1]
        m = sum(w["mise"] for w in window)
        row["roi_glissant_pct"] = _roi(m, sum(w["retour"] for w in window))
        row["roi_glissant_winsor_pct"] = _roi(m, sum(w["retour_winsor"] for w in window))

    nets = [row["net"] for row in serie]
    nets_w = [row["net_winsor"] for row in serie]
    drawdown, streak = _drawdown_and_streak(nets) if nets else (None, None)
    drawdown_w, streak_w = _drawdown_and_streak(nets_w) if nets_w else (None, None)

    cumul_profil: dict[str, list[dict]] = {}
    for profil, jours_p in par_jour_profil.items():
        run = 0.0
        run_w = 0.0
        label = PROFIL_LABELS.get(profil, profil)
        for j in sorted(jours_p):
            run += jours_p[j]["retour"] - jours_p[j]["mise"]
            run_w += jours_p[j]["retour_winsor"] - jours_p[j]["mise"]
            cumul_profil.setdefault(label, []).append({
                "jour": j, "cumul": round(run, 2), "cumul_winsor": round(run_w, 2),
            })

    meilleur = max(serie, key=lambda r: r["net"]) if serie else None
    pire = min(serie, key=lambda r: r["net"]) if serie else None
    jours_positifs = sum(1 for r in serie if r["net"] > 0)
    jours_positifs_w = sum(1 for r in serie if r["net_winsor"] > 0)
    mise_totale = sum(r["mise"] for r in serie)

    return {
        "fenetre_jours": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gain_cap_mise": PB_GAIN_CAP,
        "serie": serie,
        "cumul_par_profil": cumul_profil,
        "resume": {
            "n_jours": len(serie),
            "jours_positifs": jours_positifs,
            "jours_positifs_winsor": jours_positifs_w,
            "taux_jours_positifs_pct": round(jours_positifs / len(serie) * 100, 1) if serie else None,
            "mise_totale": round(mise_totale, 2),
            "net_total": round(sum(r["net"] for r in serie), 2),
            "net_total_winsor": round(sum(r["net_winsor"] for r in serie), 2),
            "roi_pct": _roi(mise_totale, sum(r["retour"] for r in serie)),
            "roi_winsor_pct": _roi(mise_totale, sum(r["retour_winsor"] for r in serie)),
            "drawdown_max": drawdown,
            "drawdown_max_winsor": drawdown_w,
            "serie_perdante_max_jours": streak,
            "serie_perdante_max_jours_winsor": streak_w,
            "meilleur_jour": meilleur,
            "pire_jour": pire,
        },
    }


async def compute_algo_evolution(session: AsyncSession, limit: int = 60) -> dict:
    """Trajectoire du modèle : une ligne par version entraînée, dans l'ordre.

    `rank_delta_market` — le classement intra-course du modèle MOINS celui d'un
    simple tri par cote PMU — était mesuré chaque nuit, écrit en base, et jamais
    servi à la page : la supervision montrait AUC / Brier / walk-forward, c'est-à-dire
    tout sauf le chiffre que le pipeline lui-même appelle « le seul qui dit si le
    modèle mérite d'exister » (cf. ml/ranking_metrics.rank_auc_report).

    `rank_source` accompagne OBLIGATOIREMENT le delta, parce que les valeurs
    stockées ne décrivent pas le même objet selon les versions :

      ``hold_out``     — le vrai modèle, sur les 20 % de courses récentes qu'il n'a
                         pas vues. La mesure qui compte.
      ``h2h``          — le même modèle sur l'échantillon restreint du duel
                         champion/challenger.
      ``walk_forward`` — un XGBoost jetable ré-entraîné par fold : il mesure le
                         DATASET, pas le modèle. C'est ce que portaient TOUTES les
                         versions antérieures à la migration 0045 (`rank_source`
                         NULL), avec un delta flatteur d'environ +0,019 face au
                         −0,035 de la première mesure honnête.

    Tracer les deux dans la même courbe reviendrait à empiler deux unités. Le
    champ est donc renvoyé tel quel, source comprise, et c'est l'affichage qui
    sépare — jamais un `COALESCE` qui les confondrait.
    """
    rows = (await session.execute(text("""
        SELECT version_num, created_at, auc_roc, brier_score, precision_top3,
               roi_simule, nb_courses_train, walk_forward_auc, walk_forward_variance,
               est_actif, est_rollback,
               rank_auc, market_rank_auc, rank_delta_market, rank_source
        FROM model_versions
        WHERE est_synthetique = false
        ORDER BY version_num DESC
        LIMIT :lim
    """), {"lim": limit})).all()

    versions = [{
        "version": r[0],
        "date": r[1].isoformat() if r[1] else None,
        "auc_roc": round(float(r[2]), 4) if r[2] is not None else None,
        "brier": round(float(r[3]), 4) if r[3] is not None else None,
        # precision_top3 = 0 sur les versions antérieures à sa mesure : jamais
        # affiché comme « 0 % de réussite », c'est une absence de mesure.
        "precision_top3": round(float(r[4]) * 100, 1) if r[4] else None,
        "roi_simule": round(float(r[5]), 2) if r[5] is not None else None,
        "courses_train": r[6],
        "walk_forward_auc": round(float(r[7]), 4) if r[7] is not None else None,
        "walk_forward_variance": round(float(r[8]), 5) if r[8] is not None else None,
        "actif": bool(r[9]),
        "rollback": bool(r[10]),
        # Classement intra-course : le modèle, la cote, et l'écart entre les deux.
        "rank_auc": round(float(r[11]), 4) if r[11] is not None else None,
        "market_rank_auc": round(float(r[12]), 4) if r[12] is not None else None,
        "rank_delta_market": round(float(r[13]), 4) if r[13] is not None else None,
        # NULL = versions antérieures à la migration 0045, dont le delta vient du
        # walk-forward. Jamais remplacé par une valeur par défaut : c'est
        # précisément l'information qui empêche de comparer deux unités.
        "rank_source": r[14],
    } for r in rows]
    versions.reverse()

    cadence = (await session.execute(text("""
        SELECT created_at::date AS j, count(*) AS n
        FROM model_versions
        WHERE est_synthetique = false AND created_at > now() - interval '30 days'
        GROUP BY 1 ORDER BY 1
    """))).all()

    active = next((v for v in versions if v["actif"]), None)
    precedente = None
    if active:
        idx = versions.index(active)
        precedente = versions[idx - 1] if idx > 0 else None

    delta = None
    if active and precedente:
        def _d(k):
            a, b = active.get(k), precedente.get(k)
            return round(a - b, 4) if a is not None and b is not None else None
        delta = {"auc_roc": _d("auc_roc"), "brier": _d("brier"),
                 "walk_forward_auc": _d("walk_forward_auc")}
        # `rank_delta_market` n'entre PAS dans ce bloc : d'une version à l'autre il
        # peut changer de source (walk_forward → hold_out), et la différence de
        # deux mesures qui ne portent pas sur le même objet ne veut rien dire.
        # Le verdict marché a son bloc à lui, ci-dessous, source comprise.

    # ── Verdict marché de la version en service ────────────────────────────
    # La question à laquelle la page ne répondait pas : le modèle apporte-t-il
    # quelque chose que la cote ne dit pas déjà ? Négatif, le produit ferait mieux
    # avec un simple tri par cote.
    #
    # `comparable` dit si le chiffre porte sur le modèle réellement déployé
    # (`hold_out` / `h2h`) ou sur le XGBoost jetable du walk-forward. Un delta
    # non comparable n'est pas promu en verdict — il est renvoyé, étiqueté, et
    # l'affichage le grise.
    verdict_marche = None
    if active:
        _src = active.get("rank_source")
        _d_mkt = active.get("rank_delta_market")
        verdict_marche = {
            "delta": _d_mkt,
            "rank_auc": active.get("rank_auc"),
            "market_rank_auc": active.get("market_rank_auc"),
            "source": _src,
            "comparable": _src in ("hold_out", "h2h"),
            # `None` quand la mesure manque : une absence n'est jamais un succès.
            "bat_le_marche": (_d_mkt > 0) if _d_mkt is not None else None,
            # Ce que mesure le delta stocké : le modèle NU. Le produit servi passe
            # ensuite par le mélange avec le marché (cf. ml/blend_calibration), qui
            # n'est pas jugé ici. Dit explicitement pour qu'un delta négatif ne soit
            # pas lu comme « le produit est sous le marché ».
            "porte_sur": "modele_nu",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": versions,
        "active": active,
        "precedente": precedente,
        "delta_vs_precedente": delta,
        "verdict_marche": verdict_marche,
        "cadence_30j": [{"jour": r[0].isoformat(), "n": r[1]} for r in cadence],
        "total_versions": (await session.execute(
            text("SELECT count(*) FROM model_versions WHERE est_synthetique = false")
        )).scalar(),
    }


async def compute_pulse(session: AsyncSession) -> dict:
    """Battement de cœur du système — ce qui bouge MAINTENANT.

    Volontairement court : cet appel est rafraîchi toutes les 15 s par la page de
    supervision, il ne doit toucher qu'à des index.
    """
    now = datetime.now(timezone.utc)

    courses = (await session.execute(text("""
        SELECT count(*) FILTER (WHERE statut = 'termine') AS terminees,
               count(*) FILTER (WHERE statut = 'a_venir') AS a_venir,
               count(*) AS total,
               max(date_heure) FILTER (WHERE statut = 'termine') AS derniere
        FROM courses
        WHERE date_heure >= date_trunc('day', now())
          AND date_heure < date_trunc('day', now()) + interval '1 day'
    """))).first()

    runs = (await session.execute(text("""
        SELECT count(*) AS emis,
               count(*) FILTER (WHERE r.statut = 'settled') AS regles,
               max(r.settled_at) AS dernier_reglement
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE c.date_heure >= date_trunc('day', now())
          AND r.created_at < c.date_heure
    """))).first()

    net_jour = (await session.execute(text("""
        SELECT COALESCE(sum((r.resultat->>'net')::numeric), 0),
               COALESCE(sum((r.resultat->>'total_mise')::numeric), 0)
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE c.date_heure >= date_trunc('day', now())
          AND r.statut = 'settled' AND r.resultat IS NOT NULL
          AND r.created_at < c.date_heure
          AND COALESCE(r.meta->>'backfill', '') <> 'true'
    """))).first()

    appr = (await session.execute(text("""
        SELECT count(*) FILTER (WHERE analyzed_at > now() - interval '24 hours'),
               max(analyzed_at)
        FROM race_learning_log
    """))).first()

    cotes = (await session.execute(text(
        'SELECT max("time") FROM cotes_historique'
    ))).scalar()

    # ── Fraîcheur des sources ────────────────────────────────────────────────
    # Le `statut` de la dernière ligne de `scrape_log` n'est PAS un état : c'est le
    # souvenir d'un succès. Servi tel quel, il affichait « ok » pour betfair
    # (dernier passage le 06/06, 93 jours), france_galop et turfoo (79 j), zeturf
    # (69 j), geny (20 j), betclic/unibet/winamax (7 j) — huit sources sur
    # quatorze, toutes vertes.
    #
    # Le statut est donc DÉDUIT de deux faits mesurés sur une fenêtre de 24 h :
    # la source a-t-elle tourné, et a-t-elle ramené quelque chose. Une source qui
    # tourne à vide (le cas vécu par quatre scrapers en août 2026 : conteneurs
    # sains, endpoints à 200, zéro donnée) est le cas qu'aucun statut de run ne
    # peut signaler.
    #
    # La fenêtre est de 24 h et non du dernier run, parce que les cadences
    # diffèrent et qu'un run vide isolé est normal : letrot a produit 768 partants
    # sur la journée alors que son DERNIER passage en ramenait zéro. Juger sur la
    # dernière ligne aurait créé une fausse alerte.
    #
    # Une seule passe sur la table (85 k lignes, pas d'index sur created_at) :
    # l'appel est rafraîchi toutes les 15 s.
    scrapers = (await session.execute(text("""
        SELECT source,
               max(created_at) AS dernier,
               (array_agg(statut ORDER BY created_at DESC))[1] AS dernier_statut,
               count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS runs_24h,
               count(*) FILTER (WHERE created_at > now() - interval '24 hours'
                                  AND statut <> 'ok') AS echecs_24h,
               COALESCE(sum(COALESCE(nb_courses, 0) + COALESCE(nb_partants, 0))
                        FILTER (WHERE created_at > now() - interval '24 hours'), 0) AS volume_24h
        FROM scrape_log
        GROUP BY source
        ORDER BY source
    """))).all()

    def _age_min(dt) -> Optional[float]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((now - dt).total_seconds() / 60, 1)

    def _statut_source(runs_24h: int, volume_24h: int) -> str:
        """Trois états, tous déductibles de faits mesurés.

        `silencieuse` — aucun passage sur 24 h. Ne dit pas « en panne » : une
        source volontairement arrêtée est silencieuse elle aussi. Elle dit que
        cette source n'alimente plus rien aujourd'hui, ce que « ok » niait.
        `tourne_a_vide` — elle passe et ne ramène rien : le seul état qu'un statut
        de run ne peut pas exprimer.
        `alimentee` — elle passe et ramène.
        """
        if runs_24h == 0:
            return "silencieuse"
        if volume_24h <= 0:
            return "tourne_a_vide"
        return "alimentee"

    return {
        "server_time": now.isoformat(),
        "courses_du_jour": {
            "total": courses[2] if courses else 0,
            "terminees": courses[0] if courses else 0,
            "a_venir": courses[1] if courses else 0,
            "derniere_terminee": courses[3].isoformat() if courses and courses[3] else None,
        },
        "conseils_du_jour": {
            "emis": runs[0] if runs else 0,
            "regles": runs[1] if runs else 0,
            "dernier_reglement": runs[2].isoformat() if runs and runs[2] else None,
            "age_dernier_reglement_min": _age_min(runs[2]) if runs else None,
            "net": round(float(net_jour[0]), 2) if net_jour else 0.0,
            "mise": round(float(net_jour[1]), 2) if net_jour else 0.0,
        },
        "apprentissage": {
            "courses_apprises_24h": appr[0] if appr else 0,
            "derniere_analyse": appr[1].isoformat() if appr and appr[1] else None,
            "age_derniere_analyse_min": _age_min(appr[1]) if appr else None,
        },
        "fraicheur": {
            "cotes_age_min": _age_min(cotes),
            "fenetre_volume_heures": 24,
            "sources": [{
                "source": s[0],
                # Statut DÉDUIT (voir `_statut_source`), plus le souvenir du
                # dernier run conservé sous son vrai nom : rien n'est perdu, mais
                # « le dernier passage s'est bien terminé » ne peut plus se faire
                # passer pour « cette source alimente le système ».
                "statut": _statut_source(int(s[3] or 0), int(s[5] or 0)),
                "dernier_statut_run": s[2],
                "age_min": _age_min(s[1]),
                "runs_24h": int(s[3] or 0),
                "echecs_24h": int(s[4] or 0),
                "volume_24h": int(s[5] or 0),
            } for s in scrapers],
        },
    }
