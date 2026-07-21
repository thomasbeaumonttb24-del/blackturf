"""
Calcule les stats GLOBALES jockey & entraîneur depuis NOS propres résultats
(participations ⋈ resultats), et upsert dans stats_jockeys / stats_entraineurs.

POURQUOI : le scraper Turfoo (censé remplir ces tables) renvoie 403 depuis l'IP
du VPS → il a créé des lignes mais avec taux=0. Conséquence : la feature
`jockey_taux_victoire_global` (et entraîneur) tombait sur le défaut 0.12 pour
TOUS les partants → la qualité jockey/entraîneur ne pesait PAS dans l'évaluation
des chevaux. Ici on remplace ces zéros par des taux RÉELS calculés sur l'arrivée
officielle (resultats.classement), sans aucune donnée inventée.

Source de vérité : resultats.classement (jsonb [{numero, position}]). On joint
chaque participation (course finie) à sa position via le numéro, puis on agrège
par acteur sur une fenêtre glissante.

Usage (conteneur api/worker) :
    cd /app && PYTHONPATH=/app python scripts/compute_acteur_stats.py [MOIS]
    MOIS = fenêtre d'historique (défaut 18). Idempotent (upsert par saison).
"""
import asyncio
import sys
from datetime import date

from sqlalchemy import text

from db.database import AsyncSessionLocal

MIN_COURSES = 10   # en-dessous, taux trop bruité → on n'écrit pas (pas de faux signal)


# Agrégation commune : positions réelles via classement. acteur_col = jockey_id|entraineur_id
_AGG_SQL = """
    SELECT p.{acteur} AS acteur_id,
           count(*)                                              AS rides,
           count(*) FILTER (WHERE (e->>'position') ~ '^[0-9]+$'
                                  AND (e->>'position')::int = 1) AS wins,
           count(*) FILTER (WHERE (e->>'position') ~ '^[0-9]+$'
                                  AND (e->>'position')::int <= 3) AS places
    FROM participations p
    JOIN courses c   ON c.course_id = p.course_id
    JOIN resultats r ON r.course_id = p.course_id
    JOIN LATERAL jsonb_array_elements(r.classement) e
              ON (e->>'numero') ~ '^[0-9]+$' AND (e->>'numero')::int = p.numero
    WHERE p.{acteur} IS NOT NULL
      AND c.date_heure > now() - (:mois || ' months')::interval
    GROUP BY p.{acteur}
    HAVING count(*) >= :minc
"""

_UPSERT_SQL = """
    INSERT INTO {table} (stat_id, {acteur}, saison, victoires_saison,
                         taux_victoire_global, taux_place_global)
    VALUES (gen_random_uuid(), :aid, :saison, :wins, :tv, :tp)
    ON CONFLICT ({acteur}, saison) DO UPDATE SET
        victoires_saison      = EXCLUDED.victoires_saison,
        taux_victoire_global  = EXCLUDED.taux_victoire_global,
        taux_place_global     = EXCLUDED.taux_place_global,
        updated_at            = now()
"""


async def _compute(session, table: str, acteur: str, mois: int) -> tuple[int, float]:
    rows = (await session.execute(
        text(_AGG_SQL.format(acteur=acteur)), {"mois": str(mois), "minc": MIN_COURSES}
    )).fetchall()
    saison = date.today().year
    n = 0
    tv_sum = 0.0
    for aid, rides, wins, places in rows:
        if not rides:
            continue
        tv = round(wins / rides, 4)
        tp = round(places / rides, 4)
        await session.execute(text(_UPSERT_SQL.format(table=table, acteur=acteur)), {
            "aid": aid, "saison": saison, "wins": int(wins), "tv": tv, "tp": tp,
        })
        n += 1
        tv_sum += tv
    await session.commit()
    return n, (tv_sum / n if n else 0.0)


async def main(mois: int = 18) -> None:
    print(f"# compute_acteur_stats (fenêtre {mois} mois, min {MIN_COURSES} courses)")
    async with AsyncSessionLocal() as session:
        nj, tvj = await _compute(session, "stats_jockeys", "jockey_id", mois)
        print(f"  jockeys     : {nj} mis à jour, taux_victoire moyen {tvj:.3f}")
        ne, tve = await _compute(session, "stats_entraineurs", "entraineur_id", mois)
        print(f"  entraîneurs : {ne} mis à jour, taux_victoire moyen {tve:.3f}")


if __name__ == "__main__":
    m = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    asyncio.run(main(m))
