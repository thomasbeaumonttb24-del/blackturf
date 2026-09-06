"""
backfill_enjeux.py — Reconstitue l'argent misé cheval par cheval sur les courses
déjà courues.

Le PMU sert `combinaisons` et `masse-enjeu` pour les journées PASSÉES (vérifié le
2026-09-06 jusqu'au 15/09/2025, soit tout l'historique de la base). Les courses
antérieures à la mise en service du relevé n'ont donc pas à rester aveugles :
19 500 d'entre elles n'avaient aucune donnée d'enjeux au 2026-09-06.

Ce que ce script écrit est une PHOTO FINALE, prise après la clôture des paris :

  • elle dit parfaitement OÙ est allé l'argent (répartition définitive) ;
  • elle ne dit RIEN de son mouvement — il n'y a qu'un point, donc ni afflux ni
    grosse mise, et c'est exactement ce qu'on veut : une série de mouvements
    reconstituée après coup serait fausse.

Elle est marquée `source = "backfill"`. Ce marquage n'est pas décoratif : une
photo prise après la clôture connaît indirectement l'issue du marché. La faire
entrer dans un apprentissage serait une fuite de données, du même ordre que les
`computed_at` postérieurs à la course qui avaient déjà rendu un backfill
inexploitable. Tout consommateur qui juge un signal PRÉ-course doit filtrer
`source = 'live'`.

Idempotent : ne traite que les courses SANS aucun relevé. Une course qui a déjà
sa série live n'est jamais complétée par une photo finale — mélanger les deux
ferait apparaître, au dernier point, un afflux général qui n'a jamais eu lieu.

    python scripts/backfill_enjeux.py --depuis 2025-09-01 --limite 500
    python scripts/backfill_enjeux.py --depuis 2026-08-01 --concurrence 3 --pause 0.2
    python scripts/backfill_enjeux.py --dry-run --limite 20
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf"
)

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from scraper.db_writer import save_enjeux_course  # noqa: E402
from services.pmu_enjeux import _HEADERS, fetch_enjeux  # noqa: E402

# Le scraper live partage l'API PMU avec ce script, et il porte un disjoncteur :
# assez d'erreurs d'affilée et il cesse d'appeler le PMU pour de VRAIES courses.
# On reste donc volontairement lent — 19 500 courses en quelques heures suffisent,
# personne n'attend ce rattrapage.
CONCURRENCE_DEFAUT = 2
PAUSE_DEFAUT = 0.25


async def _a_traiter(depuis: str, limite: int) -> list[tuple[str, int | None, datetime]]:
    # asyncpg refuse une chaîne pour un paramètre `timestamptz` : il veut un
    # objet date. Le convertir ici plutôt que dans le SQL garde l'erreur lisible
    # quand l'argument est mal formé.
    plancher = datetime.strptime(depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT c.course_id, c.nb_partants, c.date_heure
            FROM courses c
            LEFT JOIN enjeux_course_historique e ON e.course_id = c.course_id
            WHERE c.date_heure < now() - interval '30 minutes'
              AND c.date_heure >= :depuis
              AND e.id IS NULL
            GROUP BY c.course_id, c.nb_partants, c.date_heure
            ORDER BY c.date_heure DESC
            LIMIT :limite
        """), {"depuis": plancher, "limite": limite})).all()
    return [(r[0], r[1], r[2]) for r in rows]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--depuis", default="2025-09-01", help="date plancher (AAAA-MM-JJ)")
    ap.add_argument("--limite", type=int, default=500, help="nombre de courses par passage")
    ap.add_argument("--concurrence", type=int, default=CONCURRENCE_DEFAUT)
    ap.add_argument("--pause", type=float, default=PAUSE_DEFAUT,
                    help="secondes entre deux lectures d'un même worker")
    ap.add_argument("--dry-run", action="store_true", help="lit le PMU, n'écrit rien")
    args = ap.parse_args()

    cibles = await _a_traiter(args.depuis, args.limite)
    print(f"Courses sans aucun relevé d'enjeux : {len(cibles)}")
    if not cibles:
        return 0

    ecrits = vides = erreurs = 0
    par_perimetre: dict[str, int] = {}
    verrou = asyncio.Semaphore(args.concurrence)

    async with httpx.AsyncClient(headers=_HEADERS, timeout=8.0, follow_redirects=True) as client:

        async def _une(course_id: str, nb_partants: int | None, date_heure: datetime):
            nonlocal ecrits, vides, erreurs
            async with verrou:
                try:
                    vue = await fetch_enjeux(course_id, nb_partants=nb_partants, client=client)
                except Exception as e:  # noqa: BLE001
                    erreurs += 1
                    print(f"  ! {course_id} : {str(e)[:100]}")
                    return
                finally:
                    await asyncio.sleep(args.pause)

            if not vue:
                vides += 1
                return
            per = vue.get("perimetre") or "?"
            par_perimetre[per] = par_perimetre.get(per, 0) + 1
            if args.dry_run:
                sg = (vue.get("simples") or {}).get("SIMPLE_GAGNANT") or {}
                print(f"  = {course_id} [{per}] {len(sg.get('par_cheval') or {})} chevaux, "
                      f"masse {(sg.get('masse_centimes') or 0) / 100:.0f} €")
                ecrits += 1
                return

            vue["source"] = "backfill"
            # L'heure du relevé est celle de la course : voir la docstring.
            quand = date_heure if date_heure.tzinfo else date_heure.replace(tzinfo=timezone.utc)
            try:
                async with AsyncSessionLocal() as s:
                    if await save_enjeux_course(s, course_id, vue, scraped_at=quand):
                        await s.commit()
                        ecrits += 1
                    else:
                        vides += 1
            except Exception as e:  # noqa: BLE001
                erreurs += 1
                print(f"  ! {course_id} (écriture) : {str(e)[:120]}")

        taille = 50
        for i in range(0, len(cibles), taille):
            lot = cibles[i:i + taille]
            await asyncio.gather(*(_une(*c) for c in lot))
            print(f"  … {min(i + taille, len(cibles))}/{len(cibles)} — "
                  f"{ecrits} écrits, {vides} sans enjeux, {erreurs} erreurs")

    print(f"\nTerminé : {ecrits} relevés écrits, {vides} courses sans enjeux publiés, "
          f"{erreurs} erreurs")
    print(f"Périmètres : {par_perimetre or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
