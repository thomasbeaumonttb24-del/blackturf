"""Rend aux participations la cote PMU que le re-scrape avait effacée.

LE DÉFAUT. L'upsert du scraper réécrivait `participations.cote_pmu`
INCONDITIONNELLEMENT. Or le PMU cesse de publier `dernierRapportDirect` dès que la
course quitte le pari : la passe suivante repassait donc NULL par-dessus une cote
parfaitement valide. Le 05/09/2026, la dernière passe de la journée a effacé
295 cotes sur 743 — la couverture PMU du jour est tombée à 60,3 %, ce qui a
déclenché l'anomalie `source_critique_degradee`. Corrigé dans
`scraper.db_writer.champs_reecrits_participation` (2026-09-06).

CE QUE CE SCRIPT RÉPARE. La cote n'était pas perdue : `cotes_historique` l'avait
toujours. On restaure la DERNIÈRE cote PMU observée AVANT le départ — c'est
exactement la valeur qui a été écrasée, et la borne `time <= date_heure` interdit
qu'une cote post-course entre dans une colonne pré-course.

Usage (dans le conteneur api) :
    cd /app && PYTHONPATH=/app python scripts/restaure_cotes_pmu_effacees.py [N_JOURS] [--ecrire]

Sans `--ecrire`, le script COMPTE et n'écrit rien. Idempotent : ne touche que les
lignes dont `cote_pmu IS NULL`, et n'invente jamais une cote qui n'a pas été
observée (une course jamais ouverte au pari reste sans cote).
"""
import asyncio
import sys

from sqlalchemy import text

from db.database import AsyncSessionLocal

# Mêmes bornes que `scraper.validation.valid_cote` : une valeur que le scraper
# aurait refusée à l'écriture ne doit pas rentrer par la porte de derrière.
COTE_MIN, COTE_MAX = 1.01, 1000.0

SQL_RECUPERABLES = """
    SELECT p.participation_id,
           (SELECT ch.cote FROM cotes_historique ch
             WHERE ch.participation_id = p.participation_id
               AND ch.source = 'pmu'
               AND ch.time <= c.date_heure
             ORDER BY ch.time DESC LIMIT 1) AS cote
    FROM participations p
    JOIN courses c ON c.course_id = p.course_id
    WHERE p.cote_pmu IS NULL
      AND c.date_heure >= now() - make_interval(days => :jours)
"""


async def restaurer(jours: int, ecrire: bool) -> None:
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(text(SQL_RECUPERABLES), {"jours": jours})).all()
        a_ecrire = [(pid, float(cote)) for pid, cote in lignes
                    if cote is not None and COTE_MIN <= float(cote) <= COTE_MAX]
        print(f"[cotes] {len(lignes)} participations sans cote sur {jours} j — "
              f"{len(a_ecrire)} récupérables depuis cotes_historique")
        if not ecrire:
            print("[cotes] lecture seule (passer --ecrire pour appliquer)")
            return
        for pid, cote in a_ecrire:
            await session.execute(
                text("UPDATE participations SET cote_pmu = :c "
                     "WHERE participation_id = :p AND cote_pmu IS NULL"),
                {"c": cote, "p": pid})
        await session.commit()
        print(f"[cotes] {len(a_ecrire)} cotes restaurées")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(restaurer(int(args[0]) if args else 30, "--ecrire" in sys.argv))
