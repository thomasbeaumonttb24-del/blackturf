"""
recreer_hippodromes_perdus.py — Recrée les lignes `hippodromes` perdues par l'ancien
upsert sur code tronqué (audit du 2026-09-28).

Le code tronqué à 20 caractères faisait renommer une ligne existante à chaque nouvel
hippodrome d'un même préfixe (`HIPPODROME_DE_SAINT_` pour Saint-Brieuc, Saint-Malo,
Saint-Galmier…). Les noms perdus n'ont plus de ligne, donc plus de pays pour les
jointures faites après coup. Le correctif de `scraper.db_writer.upsert_hippodrome`
empêche la récidive ; ce script recrée les lignes manquantes par ce même upsert.

Leur historique existe (vérifié le 2026-09-29 : 211 courses, 2 061 lignes, pays
renseigné) : le script le CONTRÔLE et le signale, il ne le réécrit pas.

Simulation par défaut ; `--appliquer` crée les lignes (retour arrière : DELETE par nom).

    python scripts/recreer_hippodromes_perdus.py [--appliquer]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

# Hippodromes perdus, mesurés le 2026-09-29 (courses d'un an sans ligne `hippodromes`).
HIPPODROMES_PERDUS = {
    "HIPPODROME DE SAINT GALMIER": "FRA",
    "HIPPODROME DE SAINT BRIEUC": "FRA",
    "HIPPODROME DE MUNICH-RIEM ALL": "DEU",
    "HIPPODROME DE HAMBOURG HORN ALL": "DEU",
}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true")
    args = ap.parse_args()

    from db.database import AsyncSessionLocal
    from scraper.db_writer import upsert_hippodrome

    async with AsyncSessionLocal() as s:
        if not args.appliquer:
            await s.execute(text("SET TRANSACTION READ ONLY"))
        manquants = [nom for nom in HIPPODROMES_PERDUS if not (await s.execute(text(
            "SELECT 1 FROM hippodromes WHERE nom = :n"), {"n": nom})).first()]
        sans_histo = (await s.execute(text("""
            SELECT count(*) FROM courses c JOIN resultats r ON r.course_id = c.course_id
            WHERE c.hippodrome_nom = ANY(:noms) AND c.statut = 'termine'
              AND r.classement IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM historique_courses h WHERE h.course_id = c.course_id)
        """), {"noms": list(HIPPODROMES_PERDUS)})).scalar()
        print(f"[hippodromes] à recréer : {manquants}", flush=True)
        print(f"[hippodromes] courses réglées sans historique : {sans_histo}", flush=True)
        if not args.appliquer:
            await s.rollback()
            print("[hippodromes] simulation : rien écrit", flush=True)
            return 0
        for nom in manquants:
            await upsert_hippodrome(s, nom, HIPPODROMES_PERDUS[nom])
        await s.commit()
        print(f"[hippodromes] {len(manquants)} ligne(s) créée(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
