"""
Backfill 2b — peuple terrain / corde / poids / vitesse / œillères sur l'historique
existant (~31k lignes) à partir des données API PMU jusque-là non parsées.

Pour chaque course (course_id daté) : fetch performances-detaillees (renvoie
l'historique complet de tous les partants) → UPDATE historique_courses par
(cheval_id, date_course, hippodrome). Idempotent (ne touche que les lignes encore
NULL). Lecture PMU + UPDATE DB uniquement — aucun impact modèle.
"""
import asyncio
import json
import os
import re
from datetime import datetime

import httpx
import asyncpg

BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
CID = re.compile(r"^(\d{8})R(\d+)C(\d+)$")


async def main():
    dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)

    rows = await conn.fetch(
        "SELECT course_id FROM courses WHERE course_id ~ '^[0-9]{8}R[0-9]+C[0-9]+$' ORDER BY date_heure DESC"
    )
    courses = [r["course_id"] for r in rows]
    print(f"{len(courses)} courses à traiter", flush=True)

    name2id = {}
    for r in await conn.fetch("SELECT cheval_id, nom FROM chevaux"):
        name2id.setdefault(r["nom"], r["cheval_id"])

    updated = 0
    done = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        for cid in courses:
            m = CID.match(cid)
            if not m:
                continue
            d, R, C = m.groups()
            try:
                resp = await client.get(f"{BASE}/programme/{d}/R{R}/C{C}/performances-detaillees/pretty")
                data = resp.json()
            except Exception:
                done += 1
                continue

            for p in data.get("participants", []):
                chid = name2id.get(p.get("nomCheval"))
                if not chid:
                    continue
                for c in (p.get("coursesCourues") or []):
                    dms = c.get("date")
                    if not dms:
                        continue
                    dcourse = datetime.fromtimestamp(dms / 1000.0).date()
                    hippo = (c.get("hippodrome") or "?")[:100]
                    moi = next((x for x in (c.get("participants") or []) if x.get("itsHim")), None) or {}
                    terr = c.get("etatTerrain")
                    corde = moi.get("corde")
                    poids = moi.get("poidsJockey")
                    tdp = c.get("tempsDuPremier")
                    dist = c.get("distance")
                    vit = (round(dist / (tdp / 100.0), 2)
                           if isinstance(tdp, (int, float)) and tdp > 0
                           and isinstance(dist, (int, float)) and dist > 0 else None)
                    oeil = moi.get("oeillere")
                    oe = (oeil not in (None, "SANS_OEILLERES")) if oeil is not None else None

                    res = await conn.execute(
                        """
                        UPDATE historique_courses SET
                          terrain = COALESCE($1, terrain),
                          corde = COALESCE($2, corde),
                          poids_porte_course = COALESCE($3, poids_porte_course),
                          indice_vitesse = COALESCE($4, indice_vitesse),
                          equipement_course = COALESCE($5::jsonb, equipement_course)
                        WHERE cheval_id = $6 AND date_course = $7 AND hippodrome = $8
                          AND (terrain IS NULL OR indice_vitesse IS NULL OR corde IS NULL)
                        """,
                        terr,
                        (str(corde) if corde is not None else None),
                        (float(poids) if isinstance(poids, (int, float)) else None),
                        vit,
                        (json.dumps({"oeilleres": bool(oe)}) if oe is not None else None),
                        chid, dcourse, hippo,
                    )
                    try:
                        updated += int(res.split()[-1])
                    except Exception:
                        pass
            done += 1
            if done % 100 == 0:
                print(f"{done}/{len(courses)} courses · {updated} lignes mises à jour", flush=True)
            await asyncio.sleep(0.2)

    print(f"DONE — {done} courses, {updated} lignes mises à jour", flush=True)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
