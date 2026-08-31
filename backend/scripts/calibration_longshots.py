"""
Calibration longshots — diagnostic READ-ONLY (n'écrit rien en DB).

Compare, par bucket de cote, la proba de victoire PRÉDITE par le modèle
(prediction_evaluation.proba_top1) à la fréquence RÉELLE de victoire observée
(resultats.classement, position == 1).

But : objectiver le biais longshot qui produit les value bets à EV absurde
(+296% sur des 37/1). Si, sur le bucket cote 15-40, la proba moyenne prédite
est très supérieure à la fréquence réelle de victoire, le modèle sur-évalue les
outsiders → il faut renforcer le shrinkage vers le marché (cf. ALPHA adaptatif).

Intégrité : aucune donnée inventée. Les buckets sans assez d'observations
(< MIN_OBS) sont affichés NULL, pas extrapolés.

Usage (sur le VPS, env DATABASE_URL déjà configuré) :
    python -m scripts.calibration_longshots
    python -m scripts.calibration_longshots --source betfair   # autre cote de réf
"""
import argparse
import asyncio
import json
import statistics
from collections import defaultdict

from sqlalchemy import text

from db.database import AsyncSessionLocal

# Bornes de cote (gagnant) pour le bucketing. Le dernier bucket = +inf.
COTE_BUCKETS = [1.5, 2.5, 4.0, 6.0, 8.0, 12.0, 20.0, 40.0, float("inf")]
# Nb minimal d'observations pour qu'un bucket soit jugé fiable (sinon NULL).
MIN_OBS = 30


def bucket_label(cote: float) -> str:
    lo = 1.0
    for hi in COTE_BUCKETS:
        if cote < hi:
            return f"[{lo:g} – {hi:g})" if hi != float("inf") else f"[{lo:g} – ∞)"
        lo = hi
    return f"[{lo:g} – ∞)"


async def fetch_rows(session, cote_col: str):
    """
    Récupère (proba_top1, cote, numero, course_id) pour toutes les prédictions
    dont la course a un résultat. cote_col ∈ {cote_pmu, cote_betfair, ...}.
    """
    # FLAG calib_on_raw : choix de la proba BRUTE ou finale uniquement. La garde
    # pré-départ est inconditionnelle : aucun flag ne peut réactiver le hindsight.
    from ml.algo_flags import FLAGS as _AF
    _col = "COALESCE(pr.proba_top1_raw, pr.proba_top1)" if _AF.calib_on_raw else "pr.proba_top1"
    rows = await session.execute(text(f"""
        SELECT {_col},
               CASE WHEN :use_frozen THEN COALESCE(pr.cote_figee, pa.cote_pmu)
                    ELSE pa.{cote_col} END AS cote,
               pa.numero, pr.course_id
        FROM prediction_evaluation pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN resultats r       ON r.course_id        = pr.course_id
        JOIN courses c         ON c.course_id        = pr.course_id
        WHERE {_col} IS NOT NULL
          AND (CASE WHEN :use_frozen THEN COALESCE(pr.cote_figee, pa.cote_pmu)
                    ELSE pa.{cote_col} END) IS NOT NULL
          AND (CASE WHEN :use_frozen THEN COALESCE(pr.cote_figee, pa.cote_pmu)
                    ELSE pa.{cote_col} END) > 1.0
          AND c.date_heure IS NOT NULL
          AND pr.created_at IS NOT NULL
          AND pr.created_at < c.date_heure
          AND pr.is_replayable = true
    """), {"use_frozen": cote_col == "cote_pmu"})
    return rows.fetchall()


async def fetch_winners(session) -> dict[str, set]:
    """course_id → set(numéros gagnants) extrait de resultats.classement (position == 1)."""
    rows = await session.execute(text("SELECT course_id, classement FROM resultats"))
    winners: dict[str, set] = {}
    for course_id, classement in rows.fetchall():
        if not classement:
            continue
        data = classement if isinstance(classement, (list, dict)) else json.loads(classement)
        entries = data if isinstance(data, list) else data.get("classement", [])
        gagnants = set()
        for e in entries:
            if not isinstance(e, dict):
                continue
            pos = e.get("position") or e.get("place") or e.get("rang")
            num = e.get("numero") or e.get("num")
            try:
                if pos is not None and int(pos) == 1 and num is not None:
                    gagnants.add(int(num))
            except (TypeError, ValueError):
                continue
        if gagnants:
            winners[course_id] = gagnants
    return winners


def compute_bucket_stats(rows, winners) -> list[dict]:
    """
    Agrège (proba_top1, cote, numero, course_id) par bucket de cote et croise avec
    les gagnants réels. Fonction PURE (aucune I/O) → testable sans DB.

    Retourne une liste ordonnée (un dict par bucket, dans l'ordre de COTE_BUCKETS) :
      {bucket, lo, hi, n, proba_moy, freq, implied_moy, ratio, verdict, reliable}.
    Les buckets sous MIN_OBS ont reliable=False et leurs métriques à None (pas
    d'extrapolation — cf. règle d'intégrité no-fake-data).
    """
    by_bucket: dict[str, dict] = defaultdict(lambda: {"probas": [], "wins": 0, "implied": []})
    for proba, cote, numero, course_id in rows:
        gagnants = winners.get(course_id)
        if gagnants is None:          # course sans résultat exploitable → ignorée
            continue
        try:
            cote = float(cote); proba = float(proba); numero = int(numero)
        except (TypeError, ValueError):
            continue
        if cote <= 1.0:
            continue
        b = bucket_label(cote)
        by_bucket[b]["probas"].append(proba)
        by_bucket[b]["implied"].append(1.0 / cote)
        if numero in gagnants:
            by_bucket[b]["wins"] += 1

    stats: list[dict] = []
    for hi_idx in range(len(COTE_BUCKETS)):
        lo = 1.0 if hi_idx == 0 else COTE_BUCKETS[hi_idx - 1]
        hi = COTE_BUCKETS[hi_idx]
        b = f"[{lo:g} – {hi:g})" if hi != float("inf") else f"[{lo:g} – ∞)"
        d = by_bucket.get(b)
        n = len(d["probas"]) if d else 0
        entry = {"bucket": b, "lo": lo, "hi": hi, "n": n,
                 "proba_moy": None, "freq": None, "implied_moy": None,
                 "ratio": None, "verdict": None, "reliable": False}
        if d and n >= MIN_OBS:
            proba_moy = statistics.mean(d["probas"])
            freq = d["wins"] / n
            ratio = proba_moy / freq if freq > 0 else float("inf")
            if ratio >= 1.5:
                verdict = "SUR-ÉVALUÉ ⚠"
            elif ratio <= 0.67:
                verdict = "sous-évalué"
            else:
                verdict = "ok"
            entry.update(proba_moy=proba_moy, freq=freq,
                         implied_moy=statistics.mean(d["implied"]),
                         ratio=ratio, verdict=verdict, reliable=True)
        stats.append(entry)
    return stats


def recommend_gate_params(stats: list[dict]) -> dict:
    """
    Dérive des valeurs concrètes pour les garde-fous de valuebets.py à partir des
    buckets FIABLES (reliable=True). Fonction PURE → testable sans DB.

    - longshot_cote_min : borne basse du 1er bucket fiable jugé SUR-ÉVALUÉ
      (ratio ≥ 1.5). En-dessous le modèle est calibré → on ne gate pas.
    - max_model_market_ratio : ratio P/réel médian des buckets sur-évalués, borné
      à [1.5, 3.0]. C'est l'ampleur du sur-fit à neutraliser.
    - cote_max_vb : borne basse du 1er bucket fiable où la fréquence réelle de
      victoire s'effondre (freq < 0.02 → quasi jamais gagnant, edge non crédible).

    Chaque champ vaut None si les données ne permettent pas de le caler (pas de
    bucket fiable correspondant) → ne JAMAIS inventer une valeur. `rationale`
    explique chaque choix ; `insufficient_data` liste les champs non calables.
    """
    reliable = [s for s in stats if s["reliable"]]
    over = [s for s in reliable if s["ratio"] is not None and s["ratio"] >= 1.5]

    rec: dict = {"longshot_cote_min": None, "max_model_market_ratio": None,
                 "cote_max_vb": None, "rationale": {}, "insufficient_data": []}

    if over:
        first_over = min(over, key=lambda s: s["lo"])
        rec["longshot_cote_min"] = first_over["lo"]
        rec["rationale"]["longshot_cote_min"] = (
            f"1er bucket fiable sur-évalué : {first_over['bucket']} "
            f"(ratio {first_over['ratio']:.2f})")
        ratio_med = statistics.median([s["ratio"] for s in over
                                       if s["ratio"] != float("inf")] or [1.5])
        rec["max_model_market_ratio"] = round(min(3.0, max(1.5, ratio_med)), 2)
        rec["rationale"]["max_model_market_ratio"] = (
            f"ratio médian des {len(over)} buckets sur-évalués = {ratio_med:.2f} "
            f"(borné [1.5, 3.0])")
    else:
        rec["insufficient_data"] += ["longshot_cote_min", "max_model_market_ratio"]

    collapse = [s for s in reliable if s["freq"] is not None and s["freq"] < 0.02]
    if collapse:
        first_collapse = min(collapse, key=lambda s: s["lo"])
        rec["cote_max_vb"] = first_collapse["lo"]
        rec["rationale"]["cote_max_vb"] = (
            f"1er bucket fiable à freq<2% : {first_collapse['bucket']} "
            f"(freq réelle {first_collapse['freq']:.4f})")
    else:
        rec["insufficient_data"].append("cote_max_vb")

    return rec


def _print_report(cote_col: str, n_used: int, n_courses: int,
                  stats: list[dict], rec: dict) -> None:
    print(f"\nCalibration longshots — cote de référence : {cote_col}")
    print(f"Observations exploitées : {n_used}  (courses avec résultat : {n_courses})\n")
    print(f"{'bucket cote':<16}{'n':>7}{'proba_préd':>13}{'freq_réelle':>13}"
          f"{'implicite':>12}{'ratio P/réel':>14}{'verdict':>20}")
    print("-" * 95)
    for s in stats:
        if not s["reliable"]:
            print(f"{s['bucket']:<16}{s['n']:>7}{'NULL':>13}{'NULL':>13}{'NULL':>12}"
                  f"{'NULL':>14}{'(n<'+str(MIN_OBS)+')':>20}")
            continue
        print(f"{s['bucket']:<16}{s['n']:>7}{s['proba_moy']:>13.4f}{s['freq']:>13.4f}"
              f"{s['implied_moy']:>12.4f}{s['ratio']:>14.2f}{s['verdict']:>20}")

    print("\nLecture : ratio P/réel > 1.5 sur les gros buckets = biais longshot confirmé.")
    print("La colonne 'implicite' (1/cote moyen) est le prior marché — souvent mieux")
    print("calibré que le modèle sur les grosses cotes. Cale ALPHA/shrinkage là-dessus.\n")

    print("Recommandations garde-fous (valuebets.py) — dérivées des buckets fiables :")
    for key in ("longshot_cote_min", "max_model_market_ratio", "cote_max_vb"):
        val = rec[key]
        if val is None:
            print(f"  {key:<24} = NULL  (données insuffisantes, valeur conservatrice conservée)")
        else:
            print(f"  {key:<24} = {val}   ← {rec['rationale'].get(key, '')}")
    print()


async def main(cote_col: str, as_json: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        rows = await fetch_rows(session, cote_col)
        winners = await fetch_winners(session)

    stats = compute_bucket_stats(rows, winners)
    rec = recommend_gate_params(stats)
    n_used = sum(s["n"] for s in stats)

    if as_json:
        print(json.dumps({"cote_col": cote_col, "n_used": n_used,
                          "n_courses": len(winners), "buckets": stats,
                          "recommendations": rec}, ensure_ascii=False, indent=2))
    else:
        _print_report(cote_col, n_used, len(winners), stats, rec)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cote_pmu",
                    help="colonne cote de participations (cote_pmu, cote_betfair, …)")
    ap.add_argument("--json", action="store_true",
                    help="sortie JSON machine (buckets + recommandations) au lieu du tableau")
    args = ap.parse_args()
    asyncio.run(main(args.source, as_json=args.json))
