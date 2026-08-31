"""
Recalcule les stats jockey & entraîneur depuis NOS propres résultats
(participations ⋈ resultats) et les upsert dans stats_jockeys / stats_entraineurs.

POURQUOI : le scraper Turfoo (censé remplir ces tables) renvoie 403 depuis l'IP
du VPS → il a créé des lignes avec des taux à 0. Les features jockey/entraîneur
tombaient donc sur leurs valeurs par défaut pour TOUS les partants, et la qualité
de l'homme ne pesait pas dans l'évaluation du cheval.

Ce script ne fait plus que DÉCLENCHER le calcul : la logique vit dans
`scraper.db_writer.compute_and_save_acteur_stats`, qui tourne aussi dans le cycle
du scraper. Deux copies du même SQL avaient divergé (celle-ci ignorait le ROI et
l'activité récente), et rien ne signalait l'écart — une seule source désormais.

Source de vérité : resultats.classement (positions réelles) et resultats.rapports
(rapports PMU officiels, base 1 €). Aucune donnée inventée.

Usage (conteneur api/worker) :
    cd /app && PYTHONPATH=/app python scripts/compute_acteur_stats.py [MOIS]
    MOIS = fenêtre d'historique (défaut 18). Idempotent (upsert par saison).
"""
import asyncio
import sys

from db.database import AsyncSessionLocal
from scraper.db_writer import compute_and_save_acteur_stats


async def main(mois: int = 18) -> None:
    print(f"# compute_acteur_stats (fenêtre {mois} mois)")
    async with AsyncSessionLocal() as session:
        n_jockeys, n_entraineurs = await compute_and_save_acteur_stats(session, mois=mois)
        await session.commit()
    print(f"  jockeys     : {n_jockeys} mis à jour")
    print(f"  entraîneurs : {n_entraineurs} mis à jour")


if __name__ == "__main__":
    m = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    asyncio.run(main(m))
