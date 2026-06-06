"""
Calibration longshots — diagnostic READ-ONLY (n'écrit rien en DB).

Compare, par bucket de cote, la proba de victoire PRÉDITE par le modèle
(predictions.proba_top1) à la fréquence RÉELLE de victoire observée
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
    rows = await session.execute(text(f"""
        SELECT pr.proba_top1, pa.{cote_col} AS cote, pa.numero, pr.course_id
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        JOIN resultats r       ON r.course_id        = pr.course_id
        WHERE pr.proba_top1 IS NOT NULL
          AND pa.{cote_col}  IS NOT NULL
          AND pa.{cote_col}  > 1.0
    """))
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


async def main(cote_col: str) -> None:
    async with AsyncSessionLocal() as session:
        rows = await fetch_rows(session, cote_col)
        winners = await fetch_winners(session)

    # Agrège par bucket : probas prédites + outcomes réels.
    by_bucket: dict[str, dict] = defaultdict(lambda: {"probas": [], "wins": 0, "implied": []})
    n_used = 0
    for proba, cote, numero, course_id in rows:
        gagnants = winners.get(course_id)
        if gagnants is None:          # course sans résultat exploitable → ignorée
            continue
        try:
            cote = float(cote); proba = float(proba); numero = int(numero)
        except (TypeError, ValueError):
            continue
        b = bucket_label(cote)
        by_bucket[b]["probas"].append(proba)
        by_bucket[b]["implied"].append(1.0 / cote)
        if numero in gagnants:
            by_bucket[b]["wins"] += 1
        n_used += 1

    print(f"\nCalibration longshots — cote de référence : {cote_col}")
    print(f"Observations exploitées : {n_used}  (courses avec résultat : {len(winners)})\n")
    print(f"{'bucket cote':<16}{'n':>7}{'proba_préd':>13}{'freq_réelle':>13}"
          f"{'implicite':>12}{'ratio P/réel':>14}{'verdict':>20}")
    print("-" * 95)

    for hi_idx in range(len(COTE_BUCKETS)):
        lo = 1.0 if hi_idx == 0 else COTE_BUCKETS[hi_idx - 1]
        hi = COTE_BUCKETS[hi_idx]
        b = f"[{lo:g} – {hi:g})" if hi != float("inf") else f"[{lo:g} – ∞)"
        d = by_bucket.get(b)
        if not d or len(d["probas"]) < MIN_OBS:
            n = len(d["probas"]) if d else 0
            print(f"{b:<16}{n:>7}{'NULL':>13}{'NULL':>13}{'NULL':>12}{'NULL':>14}"
                  f"{'(n<'+str(MIN_OBS)+')':>20}")
            continue
        n = len(d["probas"])
        proba_moy = statistics.mean(d["probas"])
        freq = d["wins"] / n
        implied_moy = statistics.mean(d["implied"])
        ratio = proba_moy / freq if freq > 0 else float("inf")
        if ratio >= 1.5:
            verdict = "SUR-ÉVALUÉ ⚠"
        elif ratio <= 0.67:
            verdict = "sous-évalué"
        else:
            verdict = "ok"
        print(f"{b:<16}{n:>7}{proba_moy:>13.4f}{freq:>13.4f}"
              f"{implied_moy:>12.4f}{ratio:>14.2f}{verdict:>20}")

    print("\nLecture : ratio P/réel > 1.5 sur les gros buckets = biais longshot confirmé.")
    print("La colonne 'implicite' (1/cote moyen) est le prior marché — souvent mieux")
    print("calibré que le modèle sur les grosses cotes. Cale ALPHA/shrinkage là-dessus.\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cote_pmu",
                    help="colonne cote de participations (cote_pmu, cote_betfair, …)")
    args = ap.parse_args()
    asyncio.run(main(args.source))
