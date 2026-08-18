#!/usr/bin/env python3
"""Backfill : clôture les courses historiques restées 'a_venir' faute de résultat.

Corrige le passif laissé par la fenêtre 36h de `poll_resultats` (cf.
services/course_resolution.py). Au 2026-08-17 : 159 courses en prod, toutes
COURSE_ANNULEE côté PMU (Chateaubriant 23/06 8/8, Langon-Libourne 28/07 8/8,
Deauville 25/06 7/7, Palermo ARG, Casablanca, Wolvega…).

Réutilise EXACTEMENT le moteur du job quotidien — pas de logique dupliquée, donc
pas de divergence possible entre le rattrapage et le régime permanent.

Usage (dans le conteneur api ou scraper) :
    python -m scripts.backfill_courses_sans_resultat --dry-run
    python -m scripts.backfill_courses_sans_resultat --limite 400
    python -m scripts.backfill_courses_sans_resultat --fenetre-jours 0   # tout l'historique
"""
import argparse
import asyncio
import sys

from services.course_resolution import resolve_courses_sans_resultat


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="n'écrit rien, affiche seulement le verdict PMU par course")
    ap.add_argument("--depuis-heures", type=int, default=48,
                    help="ignore les courses plus récentes que N heures (défaut 48)")
    ap.add_argument("--fenetre-jours", type=int, default=0,
                    help="profondeur du balayage en jours ; 0 = tout l'historique (défaut)")
    ap.add_argument("--abandon-jours", type=int, default=4,
                    help="âge au-delà duquel une course sans verdict PMU passe "
                         "'sans_resultat' (défaut 4)")
    ap.add_argument("--limite", type=int, default=500,
                    help="nb max de courses traitées (borne les requêtes PMU)")
    args = ap.parse_args()

    cr = await resolve_courses_sans_resultat(
        depuis_heures=args.depuis_heures,
        fenetre_jours=(None if args.fenetre_jours <= 0 else args.fenetre_jours),
        delai_abandon_jours=args.abandon_jours,
        limite=args.limite,
        dry_run=args.dry_run,
    )

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Backfill courses sans résultat")
    print(f"  scannées      : {cr['scannees']}")
    print(f"  → termine     : {cr['terminees']}     (arrivée publiée en retard)")
    print(f"  → annule      : {cr['annulees']}     (PMU COURSE_ANNULEE)")
    print(f"  → sans_resultat: {cr['sans_resultat']}    (aucun verdict PMU)")
    print(f"  erreurs       : {cr['erreurs']}")
    if cr["scannees"] >= args.limite:
        print(f"\n  ⚠ limite {args.limite} atteinte — relancer pour traiter le reste")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
