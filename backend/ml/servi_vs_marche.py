"""
servi_vs_marche.py — le pronostic SERVI bat-il le marché ?

Pourquoi ce module
──────────────────
La supervision montrait, sous le titre « Le filtre de conviction bat-il le
marché ? », la sortie de `edge_monitor` : un filtre qui multiplie des
coefficients de signaux et ne retient que les chevaux au-dessus de 1,1. Ce filtre
n'est pas ce que le site sert, et il s'est éteint tout seul — 92 paris retenus en
juin, 4 à 7 depuis septembre sur 45 000 partants testés. Il ne pouvait plus rien
conclure (seuil : 50 paris) et ne le pourra jamais. `edge_monitor` reste calculé :
il alimente une gate de déploiement, ce n'est pas l'objet ici.

Ce qu'on mesure
───────────────
Pour chaque course terminée, le DERNIER pronostic émis AVANT le départ, tel qu'il a
été figé dans `prediction_snapshots` (table append-only, un trigger interdit toute
réécriture : rien de ce qui est mesuré ici n'a pu être retouché après l'arrivée).
Ce pronostic est confronté :

  - au marché AU MÊME INSTANT : `cote_figee`, la cote PMU que le modèle voyait
    quand il a calculé — la comparaison loyale ;
  - au marché FINAL : la cote PMU de clôture, plus informée que le modèle (elle
    intègre l'argent du dernier quart d'heure). La battre est bien plus dur.

Les probas du marché sont les inverses des cotes, renormalisées à 1 sur la course
(retrait du prélèvement). Métrique principale : la log-loss du vrai gagnant,
−log p(gagnant), moyennée par course — plus elle est basse, mieux le gagnant était
annoncé. L'écart servi − marché reçoit un intervalle de confiance à 95 % par
bootstrap sur les courses : sans lui, un écart de 0,01 sur 300 courses ne veut
rien dire.

À côté, deux grandeurs que tout le monde comprend : le taux de victoire du n°1
servi contre celui du favori du marché, et le rendement d'une mise de 1 € en
simple gagnant sur chacun, à la cote finale PMU.

Calcul nocturne (≈ 9 s sur 90 jours), stocké en historique dans
`servi_vs_marche` — même convention `CREATE TABLE IF NOT EXISTS` qu'`edge_monitor`.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="servi_vs_marche")

FENETRE_JOURS = 90
FENETRES_RESUME = (30, 90)
SEMAINES = 12
N_BOOTSTRAP = 2000
MIN_COURSES_VERDICT = 100
P_MIN = 1e-6
PARIS = ZoneInfo("Europe/Paris")


_REQUETE = text("""
    WITH dernier AS (
        SELECT DISTINCT ON (s.course_id) s.course_id, s.prediction_run_id, s.observed_at
        FROM prediction_snapshots s
        JOIN courses c ON c.course_id = s.course_id
        WHERE c.date_heure >  now() - make_interval(days => :jours)
          AND c.date_heure <  now()
          AND s.is_pre_course
          AND s.observed_at < c.date_heure
        ORDER BY s.course_id, s.observed_at DESC
    )
    SELECT d.course_id, c.date_heure, c.discipline,
           pa.numero, s.proba_top1, s.rang_predit, s.cote_figee, pa.cote_pmu,
           (r.classement->0->>'numero')::int AS gagnant
    FROM dernier d
    JOIN prediction_snapshots s
      ON s.prediction_run_id = d.prediction_run_id AND s.course_id = d.course_id
    JOIN participations pa ON pa.participation_id = s.participation_id
    JOIN courses c ON c.course_id = d.course_id
    JOIN resultats r ON r.course_id = d.course_id
    WHERE jsonb_typeof(r.classement) = 'array'
      AND jsonb_array_length(r.classement) > 0
""")


def _devig(cotes: np.ndarray) -> np.ndarray | None:
    """Probas implicites d'un jeu de cotes, prélèvement retiré. None si une cote
    manque : un champ partiel donnerait une proba de marché inventée."""
    if cotes.size == 0 or not np.all(np.isfinite(cotes)) or np.any(cotes <= 1.0):
        return None
    inv = 1.0 / cotes
    return inv / inv.sum()


def _mesure_course(lignes: list[tuple]) -> dict | None:
    """Une course → ses métriques. Ignorée (None) si l'arrivée ne désigne aucun des
    partants scorés, ou si le marché au moment du prono est incomplet."""
    gagnant = lignes[0][8]
    nums = [int(l[3]) for l in lignes if l[3] is not None]
    if gagnant is None or gagnant not in nums or len(nums) != len(lignes) or len(nums) < 2:
        return None
    idx = nums.index(gagnant)

    p_srv = np.array([float(l[4] or 0.0) for l in lignes])
    if p_srv.sum() <= 0:
        return None
    p_srv = p_srv / p_srv.sum()
    p_fige = _devig(np.array([float(l[6]) if l[6] is not None else np.nan for l in lignes]))
    if p_fige is None:
        return None
    cotes_fin = np.array([float(l[7]) if l[7] is not None else np.nan for l in lignes])
    p_fin = _devig(cotes_fin)

    rangs = [l[5] if l[5] is not None else 999 for l in lignes]
    i_srv = int(np.argmin(rangs))
    i_fav = int(np.argmin(1.0 / p_fige))  # plus petite cote figée
    cote_fin_srv = cotes_fin[i_srv] if np.isfinite(cotes_fin[i_srv]) else None
    cote_fin_fav = cotes_fin[i_fav] if np.isfinite(cotes_fin[i_fav]) else None

    return {
        "ll_servi": -math.log(max(float(p_srv[idx]), P_MIN)),
        "ll_fige": -math.log(max(float(p_fige[idx]), P_MIN)),
        "ll_final": -math.log(max(float(p_fin[idx]), P_MIN)) if p_fin is not None else None,
        "top1_servi": int(i_srv == idx),
        "top1_favori": int(i_fav == idx),
        # Rendement d'1 € en simple gagnant à la cote finale PMU (None si cote absente).
        "net_servi": (cote_fin_srv - 1.0 if i_srv == idx else -1.0) if cote_fin_srv else None,
        "net_favori": (cote_fin_fav - 1.0 if i_fav == idx else -1.0) if cote_fin_fav else None,
        "partants": len(nums),
    }


def _ic_ecart(a: np.ndarray, b: np.ndarray, seed: int = 7) -> tuple[float, float, float]:
    """Moyenne de (a − b) et IC 95 % bootstrap, rééchantillonné PAR COURSE."""
    d = a - b
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, d.size, size=(N_BOOTSTRAP, d.size))
    moy = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(moy, 2.5)), float(np.percentile(moy, 97.5))


def _verdict(n: int, lo: float, hi: float) -> str:
    if n < MIN_COURSES_VERDICT:
        return "insuffisant"
    if hi < 0:
        return "meilleur"
    if lo > 0:
        return "moins_bon"
    return "egal"


def _resume(mesures: list[dict]) -> dict:
    n = len(mesures)
    out: dict = {"n_courses": n}
    if n == 0:
        return out
    srv = np.array([m["ll_servi"] for m in mesures])
    fige = np.array([m["ll_fige"] for m in mesures])
    out["logloss_servi"] = round(float(srv.mean()), 4)
    out["logloss_marche_fige"] = round(float(fige.mean()), 4)
    e, lo, hi = _ic_ecart(srv, fige)
    out["ecart_fige"] = {"moyen": round(e, 4), "ic_bas": round(lo, 4), "ic_haut": round(hi, 4),
                         "verdict": _verdict(n, lo, hi)}

    avec_fin = [m for m in mesures if m["ll_final"] is not None]
    out["n_courses_cote_finale"] = len(avec_fin)
    if avec_fin:
        s2 = np.array([m["ll_servi"] for m in avec_fin])
        f2 = np.array([m["ll_final"] for m in avec_fin])
        out["logloss_marche_final"] = round(float(f2.mean()), 4)
        e, lo, hi = _ic_ecart(s2, f2)
        out["ecart_final"] = {"moyen": round(e, 4), "ic_bas": round(lo, 4), "ic_haut": round(hi, 4),
                              "verdict": _verdict(len(avec_fin), lo, hi)}

    out["top1_servi_pct"] = round(100.0 * sum(m["top1_servi"] for m in mesures) / n, 1)
    out["top1_favori_pct"] = round(100.0 * sum(m["top1_favori"] for m in mesures) / n, 1)
    for cle, nom in (("net_servi", "roi_servi_pct"), ("net_favori", "roi_favori_pct")):
        nets = [m[cle] for m in mesures if m[cle] is not None]
        out[nom] = round(100.0 * sum(nets) / len(nets), 1) if nets else None
    out["partants_moyen"] = round(sum(m["partants"] for m in mesures) / n, 1)
    return out


async def compute_servi_vs_marche(session: AsyncSession, jours: int = FENETRE_JOURS) -> dict:
    rows = (await session.execute(_REQUETE, {"jours": jours})).all()
    par_course: dict[str, list] = defaultdict(list)
    dates: dict[str, datetime] = {}
    for r in rows:
        par_course[r[0]].append(tuple(r))
        dates[r[0]] = r[1]

    maintenant = datetime.now(timezone.utc)
    mesures: list[tuple[datetime, dict]] = []
    ignorees = 0
    for cid, lignes in par_course.items():
        m = _mesure_course(lignes)
        if m is None:
            ignorees += 1
            continue
        mesures.append((dates[cid], m))

    fenetres = {}
    for j in FENETRES_RESUME:
        sel = [m for d, m in mesures if (maintenant - d).days < j]
        fenetres[f"{j}j"] = _resume(sel)

    # Série hebdomadaire (semaine ISO, heure de Paris) — sans IC : la tendance se
    # lit sur la courbe, le verdict sur la fenêtre.
    semaines: dict[str, list[dict]] = defaultdict(list)
    for d, m in mesures:
        loc = d.astimezone(PARIS)
        lundi = (loc.date().toordinal() - loc.weekday())
        semaines[datetime.fromordinal(lundi).strftime("%Y-%m-%d")].append(m)
    serie = []
    for sem in sorted(semaines)[-SEMAINES:]:
        ms = semaines[sem]
        fin = [m["ll_final"] for m in ms if m["ll_final"] is not None]
        serie.append({
            "semaine": sem,
            "n": len(ms),
            "logloss_servi": round(sum(m["ll_servi"] for m in ms) / len(ms), 4),
            "logloss_marche_fige": round(sum(m["ll_fige"] for m in ms) / len(ms), 4),
            "logloss_marche_final": round(sum(fin) / len(fin), 4) if fin else None,
            "top1_servi_pct": round(100.0 * sum(m["top1_servi"] for m in ms) / len(ms), 1),
            "top1_favori_pct": round(100.0 * sum(m["top1_favori"] for m in ms) / len(ms), 1),
        })

    return {
        "version": 1,
        "fenetre_jours": jours,
        "n_courses_lues": len(par_course),
        "n_courses_ignorees": ignorees,
        "fenetres": fenetres,
        "par_semaine": serie,
        "calcule_le": maintenant.isoformat(),
    }


_DDL = """
CREATE TABLE IF NOT EXISTS servi_vs_marche (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    data        JSONB NOT NULL
)
"""


async def persist_servi_vs_marche(session: AsyncSession, snap: dict) -> None:
    await session.execute(text(_DDL))
    await session.execute(
        text("INSERT INTO servi_vs_marche (data) VALUES (CAST(:d AS JSONB))"),
        {"d": json.dumps(snap)},
    )
    await session.commit()


async def load_dernier(session: AsyncSession) -> dict | None:
    """Dernière mesure stockée, ou None (table absente ou vide)."""
    try:
        r = (await session.execute(text(
            "SELECT data, created_at FROM servi_vs_marche ORDER BY created_at DESC LIMIT 1"
        ))).first()
    except Exception:
        await session.rollback()
        return None
    if not r:
        return None
    data = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    data["mesure_le"] = r[1].isoformat() if r[1] else None
    return data


# ── Brier « top 3 » du marché, course par course ─────────────────────────────
#
# `race_learning_log.brier_score` est le Brier de la proba TOP 3 servie, moyenné
# sur les partants (cf. post_race_analyzer). Pour le lire contre une référence, il
# faut la MÊME grandeur côté marché : une proba d'être dans les trois premiers. Le
# marché ne cote que la victoire ; on en déduit le top 3 par Harville (le 2e est
# tiré parmi les restants au prorata de leur proba de victoire, idem le 3e) — le
# modèle standard, exact pour la victoire et connu pour légèrement sous-estimer les
# outsiders à la place. Il sert de repère, pas d'oracle.

def proba_top3_harville(p: np.ndarray) -> np.ndarray:
    """P(cheval i finit dans les 3 premiers) sous Harville, depuis les probas de
    victoire `p` (somme 1). O(n³), n ≤ 20 : négligeable."""
    n = p.size
    out = p.copy()
    if n <= 3:
        return np.ones(n)
    for j in range(n):
        rj = 1.0 - p[j]
        if rj <= 0:
            continue
        for k in range(n):
            if k == j:
                continue
            q2 = p[j] * p[k] / rj          # j 1er, k 2e
            out[k] += q2
            rjk = rj - p[k]
            if rjk <= 0:
                continue
            # 3e : tout i ∉ {j, k}
            reste = p / rjk * q2
            reste[j] = 0.0
            reste[k] = 0.0
            out += reste
    return np.clip(out, 0.0, 1.0)


async def brier_top3_marche(session: AsyncSession, course_ids: list[str]) -> dict[str, float]:
    """Brier top 3 du marché (cote figée au dernier pronostic, Harville) pour chaque
    course demandée, sur les MÊMES partants que `race_learning_log` (la table
    `predictions`). Course absente du résultat = marché incomplet ou arrivée
    illisible : pas de valeur inventée."""
    if not course_ids:
        return {}
    rows = (await session.execute(text("""
        SELECT p.course_id, pa.numero, p.cote_figee
        FROM predictions p
        JOIN participations pa ON pa.participation_id = p.participation_id
        WHERE p.course_id = ANY(:ids)
    """), {"ids": list(course_ids)})).all()
    arr = (await session.execute(text("""
        SELECT course_id, classement FROM resultats
        WHERE course_id = ANY(:ids) AND jsonb_typeof(classement) = 'array'
    """), {"ids": list(course_ids)})).all()

    top3: dict[str, set[int]] = {}
    for cid, cl in arr:
        cl = cl if isinstance(cl, list) else json.loads(cl)
        s = set()
        for e in cl:
            try:
                if e.get("numero") and e.get("position") and 1 <= int(e["position"]) <= 3:
                    s.add(int(e["numero"]))
            except (TypeError, ValueError, AttributeError):
                continue
        if s:
            top3[cid] = s

    champs: dict[str, list[tuple[int, float | None]]] = defaultdict(list)
    for cid, num, cote in rows:
        if num is not None:
            champs[cid].append((int(num), float(cote) if cote is not None else None))

    out: dict[str, float] = {}
    for cid, champ in champs.items():
        if cid not in top3:
            continue
        p = _devig(np.array([c if c is not None else np.nan for _, c in champ]))
        if p is None:
            continue
        p3 = proba_top3_harville(p)
        lab = np.array([1.0 if num in top3[cid] else 0.0 for num, _ in champ])
        out[cid] = round(float(np.mean((p3 - lab) ** 2)), 4)
    return out
