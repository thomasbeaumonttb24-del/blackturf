"""
backfill_numero_corde.py — Rattrape la STALLE de départ (`participations.numero_corde`)
des courses déjà courues.

Le scraper lit `placeCorde` depuis le 01/09/2026 seulement. Avant, la colonne est
vide et le biais de corde ne peut rien apprendre. Le PMU sert encore la stalle des
courses PASSÉES sur le même endpoint `/participants` (vérifié le 2026-09-24 sur des
courses de janvier et mars 2026 : plat renseigné, obstacle jamais — l'API n'envoie
pas `placeCorde` en obstacle, le trot renvoie le numéro lui-même).

Règles, toutes vérifiées par tests/test_backfill_numero_corde.py :

  • n'écrit QUE `participations.numero_corde`, et seulement là où il est NULL
    (`WHERE numero_corde IS NULL` dans l'UPDATE même : une valeur posée par le
    scraper live entre-temps n'est jamais écrasée) ;
  • apparie par (date, réunion, course, numéro de partant) — l'identifiant de
    course PMU `{ddmmyyyy}R{reunion}C{course}` et `numPmu` — JAMAIS par nom. Le
    nom sert uniquement de GARDE : si les noms d'une course ne concordent pas avec
    la base (moins de la moitié), la course est écartée comme incohérente au lieu
    d'être écrite ;
  • réutilise le client, les en-têtes, le délai humain et le parseur du scraper
    (`PmuScraper.enrich_partants` → `_corde_int`) ; un seul appel à la fois, et au
    plus ~1 requête par seconde (`--pause`) ;
  • journalise chaque `participation_id` écrit (`--journal`), et compte lu / mis à
    jour / introuvable.

Idempotent : relancer ne retraite que les courses qui ont encore une stalle NULL.

    python scripts/backfill_numero_corde.py --dry-run --limite 5
    python scripts/backfill_numero_corde.py --depuis 2025-09-01 --disciplines Plat \\
        --journal /tmp/backfill_corde.log
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf"
)

from sqlalchemy import text  # noqa: E402

# `{ddmmyyyy}R{reunion}C{course}` — cf. scraper.sources.pmu.make_course_id.
_COURSE_ID = re.compile(r"^(\d{8})R(\d+)C(\d+)$")

PAUSE_DEFAUT = 1.0          # secondes minimum entre deux requêtes PMU
SEUIL_CONCORDANCE_NOMS = 0.5


@dataclass
class Bilan:
    courses_lues: int = 0
    courses_introuvables: int = 0      # API vide / 204 / erreur
    courses_sans_corde: int = 0        # API répond, aucun `placeCorde`
    courses_incoherentes: int = 0      # garde des noms déclenchée
    courses_id_non_standard: int = 0
    partants_lus: int = 0
    mis_a_jour: int = 0
    deja_remplis: int = 0              # ligne remplie entre-temps (live) : intouchée
    absents_en_base: int = 0           # numPmu inconnu en base
    ecrits: list[tuple[str, str, int, int]] = field(default_factory=list)

    def ligne(self) -> str:
        return (f"courses lues={self.courses_lues} introuvables={self.courses_introuvables} "
                f"sans_corde={self.courses_sans_corde} incoherentes={self.courses_incoherentes} "
                f"id_non_standard={self.courses_id_non_standard} | partants lus={self.partants_lus} "
                f"mis_a_jour={self.mis_a_jour} deja_remplis={self.deja_remplis} "
                f"absents_en_base={self.absents_en_base}")


def decouper_course_id(course_id: str) -> tuple[str, str, int] | None:
    """`18032026R4C5` → ("18032026", "4", 5). None si l'identifiant n'est pas au
    format PMU daté (on ne devine jamais une date ou une réunion)."""
    m = _COURSE_ID.match(course_id or "")
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _nom_normalise(nom: str | None) -> str:
    if not nom:
        return ""
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\(.*?\)", " ", s)            # suffixe pays « (SWE) »
    return re.sub(r"[^A-Z0-9]", "", s)


def noms_concordent(base: dict[int, str | None], api: dict[int, str | None]) -> bool:
    """Garde anti-mauvaise-course : sur les numéros communs portant un nom des deux
    côtés, au moins la moitié doivent désigner le même cheval. Aucun nom comparable
    → on ne bloque pas (l'appariement reste par numéro)."""
    comparables = 0
    egaux = 0
    for num, nb in base.items():
        na = api.get(num)
        a, b = _nom_normalise(na), _nom_normalise(nb)
        if not a or not b:
            continue
        comparables += 1
        if a == b or a.startswith(b) or b.startswith(a):
            egaux += 1
    if comparables == 0:
        return True
    return egaux / comparables >= SEUIL_CONCORDANCE_NOMS


async def courses_a_traiter(session, depuis: datetime, disciplines: Iterable[str],
                            limite: int) -> list[str]:
    """Courses passées (≥ 30 min) de ces disciplines ayant au moins un partant sans
    stalle. Plus récentes d'abord : ce sont elles qui pèsent le plus dans le biais."""
    discs = [d for d in disciplines if d]
    marqueurs = ", ".join(f":d{i}" for i in range(len(discs)))
    params = {f"d{i}": d for i, d in enumerate(discs)}
    params.update({"depuis": depuis, "limite": limite,
                   "avant": datetime.now(timezone.utc).replace(microsecond=0)})
    rows = (await session.execute(text(f"""
        SELECT c.course_id
        FROM courses c
        WHERE c.date_heure >= :depuis
          AND c.date_heure < :avant
          AND c.discipline IN ({marqueurs})
          AND EXISTS (SELECT 1 FROM participations p
                      WHERE p.course_id = c.course_id AND p.numero_corde IS NULL)
        ORDER BY c.date_heure DESC
        LIMIT :limite
    """), params)).all()
    return [r[0] for r in rows]


async def appliquer_course(session, course_id: str, partants_api: list,
                           bilan: Bilan, dry_run: bool = False) -> int:
    """Écrit la stalle des partants d'UNE course. `partants_api` = liste d'objets
    portant `.numero`, `.nom`, `.numero_corde` (PartantScrape du scraper).
    Retourne le nombre de lignes écrites."""
    base_rows = (await session.execute(text("""
        SELECT p.participation_id, p.numero, p.numero_corde, ch.nom
        FROM participations p
        LEFT JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        WHERE p.course_id = :cid
    """), {"cid": course_id})).all()
    base = {int(r[1]): r for r in base_rows}

    api_noms = {int(p.numero): p.nom for p in partants_api if p.numero is not None}
    if not noms_concordent({n: r[3] for n, r in base.items()}, api_noms):
        bilan.courses_incoherentes += 1
        print(f"  ! {course_id} : noms discordants base/PMU — course écartée", flush=True)
        return 0

    avec_corde = [p for p in partants_api if p.numero_corde is not None]
    bilan.partants_lus += len(partants_api)
    if not avec_corde:
        bilan.courses_sans_corde += 1
        return 0

    ecrits = 0
    for p in avec_corde:
        num = int(p.numero)
        row = base.get(num)
        if row is None:
            bilan.absents_en_base += 1
            continue
        if row[2] is not None:
            bilan.deja_remplis += 1
            continue
        if dry_run:
            ecrits += 1
            continue
        res = (await session.execute(text("""
            UPDATE participations
               SET numero_corde = :corde
             WHERE course_id = :cid AND numero = :num AND numero_corde IS NULL
            RETURNING participation_id
        """), {"corde": int(p.numero_corde), "cid": course_id, "num": num})).all()
        if res:
            ecrits += 1
            bilan.ecrits.append((res[0][0], course_id, num, int(p.numero_corde)))
        else:
            bilan.deja_remplis += 1
    bilan.mis_a_jour += ecrits
    return ecrits


Fetcher = Callable[[str, str, int], Awaitable[list]]


async def traiter(session_factory, fetch: Fetcher, course_ids: list[str], *,
                  pause: float = PAUSE_DEFAUT, dry_run: bool = False,
                  journal: Path | None = None, bilan: Bilan | None = None,
                  progression: int = 50) -> Bilan:
    """Boucle séquentielle : une requête PMU à la fois, au moins `pause` s entre
    deux départs de requête. Commit par course (un arrêt en route ne perd rien)."""
    bilan = bilan or Bilan()
    dernier = 0.0
    fj = open(journal, "a", encoding="utf-8") if journal else None
    try:
        for i, cid in enumerate(course_ids, 1):
            parts = decouper_course_id(cid)
            if parts is None:
                bilan.courses_id_non_standard += 1
                continue
            attente = pause - (time.monotonic() - dernier)
            if attente > 0:
                await asyncio.sleep(attente)
            dernier = time.monotonic()
            date_s, reunion, course_num = parts
            try:
                partants = await fetch(date_s, reunion, course_num)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {cid} : {str(e)[:120]}", flush=True)
                partants = []
            bilan.courses_lues += 1
            if not partants:
                bilan.courses_introuvables += 1
                continue
            avant = len(bilan.ecrits)
            async with session_factory() as s:
                await appliquer_course(s, cid, partants, bilan, dry_run=dry_run)
                if not dry_run:
                    await s.commit()
            if fj:
                for pid, c, num, corde in bilan.ecrits[avant:]:
                    fj.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')};"
                             f"{pid};{c};{num};{corde}\n")
                fj.flush()
            if progression and i % progression == 0:
                print(f"  … {i}/{len(course_ids)} — {bilan.ligne()}", flush=True)
    finally:
        if fj:
            fj.close()
    return bilan


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depuis", default="2025-09-01", help="date plancher (AAAA-MM-JJ, UTC)")
    ap.add_argument("--disciplines", default="Plat",
                    help="liste séparée par des virgules (valeurs de courses.discipline)")
    ap.add_argument("--limite", type=int, default=100_000)
    ap.add_argument("--pause", type=float, default=PAUSE_DEFAUT,
                    help="secondes minimum entre deux requêtes PMU (défaut 1,0)")
    ap.add_argument("--journal", default=None,
                    help="fichier où consigner chaque participation_id écrite")
    ap.add_argument("--dry-run", action="store_true", help="lit le PMU, n'écrit rien")
    args = ap.parse_args()

    from db.database import AsyncSessionLocal
    from scraper.sources.pmu import PmuScraper

    plancher = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    discs = [d.strip() for d in args.disciplines.split(",") if d.strip()]
    async with AsyncSessionLocal() as s:
        cibles = await courses_a_traiter(s, plancher, discs, args.limite)
    print(f"[backfill-corde] {len(cibles)} courses {discs} depuis {args.depuis} "
          f"avec au moins une stalle NULL (pause {args.pause}s, dry_run={args.dry_run})",
          flush=True)
    if not cibles:
        return 0

    scraper = PmuScraper()

    async def fetch(date_s: str, reunion: str, course_num: int) -> list:
        # Disjoncteur du scraper (propre à CE processus) : ouvert après 5 échecs
        # d'affilée. On attend qu'il se referme plutôt que de compter des
        # dizaines de courses « introuvables » à tort.
        while scraper._cb.is_open():
            print("  … disjoncteur PMU ouvert, pause 60 s", flush=True)
            await asyncio.sleep(60)
        return await scraper.enrich_partants(reunion, course_num, course_date=date_s)

    journal = Path(args.journal) if args.journal else None
    t0 = time.monotonic()
    try:
        bilan = await traiter(AsyncSessionLocal, fetch, cibles, pause=args.pause,
                              dry_run=args.dry_run, journal=journal)
    finally:
        await scraper.close()
    print(f"[backfill-corde] TERMINÉ en {time.monotonic() - t0:.0f}s — {bilan.ligne()}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
