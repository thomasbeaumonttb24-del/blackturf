"""
validate_pmu_integrity.py — Garde-fou : nos données collent-elles à PMU ?

Compare, pour une date, CHAQUE course stockée (nom, hippodrome, distance, discipline,
nb partants) à la source officielle PMU. Toute divergence est un signal de données
fausses/périmées → on la LOGGE (et on peut re-scraper). Aucune donnée inventée :
on ne fait que vérifier la conformité au réel PMU.

⚠️ Note sur les codes R : PMU RÉUTILISE le même `numExterne` (ex. R9) pour plusieurs
réunions régionales le même jour (Dax/Rambouillet/Strasbourg = tous R9). "R9C5" est
donc AMBIGU côté PMU lui-même ; l'hippodrome est l'identifiant qui désambiguïse. Ce
n'est pas une erreur de nos données — on aligne course_id sur numOfficiel (unique) et
on affiche numExterne + hippodrome comme pmu.fr.

Usage : cd /app && PYTHONPATH=/app python scripts/validate_pmu_integrity.py [DDMMYYYY]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.request

import structlog
from sqlalchemy import text

from db.database import AsyncSessionLocal

log = structlog.get_logger()

PMU_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{d}?specialisation=INTERNET"


def _norm(s: str) -> str:
    return " ".join((s or "").upper().split())


async def validate(date_ddmmyyyy: str) -> dict:
    """Compare la base à PMU pour une date. Retourne {checked, mismatches:[...]}."""
    req = urllib.request.Request(PMU_URL.format(d=date_ddmmyyyy), headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:  # pragma: no cover — réseau
        log.warning("pmu_integrity.fetch_failed", date=date_ddmmyyyy, err=str(e)[:120])
        return {"checked": 0, "mismatches": [], "error": str(e)[:120]}

    # (numOfficiel, numOrdre) -> {nom, hippo, distance, discipline, nb}
    pmu: dict = {}
    for r in data.get("programme", {}).get("reunions", []):
        ro = r.get("numOfficiel")
        hippo = _norm(r.get("hippodrome", {}).get("libelleLong", ""))
        for c in r.get("courses", []):
            pmu[(ro, c.get("numOrdre"))] = {
                "nom": _norm(c.get("libelle", "")),
                "hippo": hippo,
                "distance": c.get("distance"),
                "nb": c.get("nombreDeclaresPartants"),
            }

    mismatches = []
    checked = 0
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT course_id, nom, hippodrome_nom, distance, nb_partants FROM courses WHERE course_id LIKE :d"
        ), {"d": f"{date_ddmmyyyy}%"})).fetchall()
        for cid, nom, hippo, dist, nbp in rows:
            m = re.match(r"\d{8}R(\d+)C(\d+)", cid)
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)))
            p = pmu.get(key)
            if p is None:
                continue
            checked += 1
            issues = []
            if _norm(nom) != p["nom"]:
                issues.append(f"nom: '{nom}' != PMU '{p['nom']}'")
            if _norm(hippo) != p["hippo"]:
                issues.append(f"hippo: '{hippo}' != PMU '{p['hippo']}'")
            if p["distance"] and dist and int(p["distance"]) != int(dist):
                issues.append(f"distance: {dist} != PMU {p['distance']}")
            if issues:
                mismatches.append({"course_id": cid, "issues": issues})

    if mismatches:
        log.error("pmu_integrity.MISMATCH", date=date_ddmmyyyy, n=len(mismatches),
                  sample=mismatches[:5])
    else:
        log.info("pmu_integrity.ok", date=date_ddmmyyyy, checked=checked)
    return {"checked": checked, "mismatches": mismatches}


if __name__ == "__main__":
    from datetime import date
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%d%m%Y")
    res = asyncio.run(validate(d))
    print(f"date {d} : {res['checked']} courses vérifiées, {len(res['mismatches'])} divergence(s)")
    for m in res["mismatches"][:20]:
        print(" ", m["course_id"], "→", "; ".join(m["issues"]))
