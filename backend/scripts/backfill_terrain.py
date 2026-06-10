"""Backfill terrain_officiel + penetrometre_coef des courses passées depuis
l'archive programme PMU (champ `penetrometre` {valeurMesure, intitule} publié
au niveau course pour plat/obstacle).

Usage (dans le conteneur api) :
    cd /app && PYTHONPATH=/app python scripts/backfill_terrain.py [N_JOURS]

Idempotent : UPDATE uniquement si terrain_officiel IS NULL. Aucune invention :
course sans penetrometre dans l'archive → intouchée.
"""
import asyncio
import sys
from datetime import date, timedelta

import httpx
from sqlalchemy import text

from db.database import AsyncSessionLocal

BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


async def backfill(n_jours: int = 35) -> None:
    today = date.today()
    total = 0
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        async with AsyncSessionLocal() as session:
            for delta in range(n_jours):
                d = today - timedelta(days=delta)
                dstr = d.strftime("%d%m%Y")
                try:
                    resp = await client.get(f"{BASE}/programme/{dstr}")
                    if resp.status_code != 200:
                        continue
                    prog = resp.json().get("programme", {})
                except Exception as e:  # noqa: BLE001
                    print(f"[terrain] {dstr} fetch KO: {e}")
                    continue
                n_day = 0
                for reunion in prog.get("reunions", []):
                    r_id = reunion.get("numOfficiel")
                    for c in reunion.get("courses", []):
                        pen = c.get("penetrometre") or {}
                        intitule = pen.get("intitule")
                        coef = None
                        try:
                            vm = str(pen.get("valeurMesure") or "").replace(",", ".").strip()
                            coef = float(vm) if vm else None
                        except (ValueError, TypeError):
                            coef = None
                        if not intitule and coef is None:
                            continue
                        course_id = f"{dstr}R{r_id}C{c.get('numOrdre')}"
                        res = await session.execute(text("""
                            UPDATE courses
                            SET terrain_officiel = COALESCE(terrain_officiel, :t),
                                penetrometre_coef = COALESCE(penetrometre_coef, :p)
                            WHERE course_id = :cid
                              AND (terrain_officiel IS NULL OR penetrometre_coef IS NULL)
                        """), {"t": intitule, "p": coef, "cid": course_id})
                        n_day += res.rowcount or 0
                await session.commit()
                total += n_day
                print(f"[terrain] {dstr}: {n_day} courses mises à jour")
    print(f"[terrain] DONE — {total} courses mises à jour")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 35
    asyncio.run(backfill(n))
