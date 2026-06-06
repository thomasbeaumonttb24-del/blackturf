"""
Cotes PMU en direct (live) — BlackTurf.

Récupère à la demande les cotes PMU réelles d'une course via l'API JSON
officielle (offline.turfinfo.api.pmu.fr), sans passer par le scraper/daemon.
Permet un vrai rafraîchissement « live » côté API (cache court partagé).

Aucune donnée inventée : on lit `dernierRapportDirect.rapport` du PMU. Si le PMU
ne renvoie pas de cote pour un partant, il est simplement absent du résultat.
"""
from __future__ import annotations

import re
import httpx
import structlog

log = structlog.get_logger(module="pmu_cotes")

_BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.pmu.fr/",
    "Origin": "https://www.pmu.fr",
}

_COURSE_ID_RE = re.compile(r"^(\d{8})R(\d+)C(\d+)$")


def parse_course_id(course_id: str) -> tuple[str, int, int] | None:
    """`06062026R3C6` → ('06062026', 3, 6). None si format inattendu."""
    m = _COURSE_ID_RE.match(course_id or "")
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3))


async def fetch_live_cotes(course_id: str) -> list[dict]:
    """
    Récupère les cotes PMU en direct pour une course.

    Retourne une liste [{"numero": int, "cote": float}] (vide si indisponible).
    """
    parsed = parse_course_id(course_id)
    if not parsed:
        return []
    d, reunion, course = parsed
    url = f"{_BASE}/programme/{d}/R{reunion}/C{course}/participants?specialisation=INTERNET"

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=4.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("pmu_cotes.fetch_failed", course_id=course_id, error=str(e)[:120])
        return []

    participants = data if isinstance(data, list) else data.get("participants", [])
    out: list[dict] = []
    for p in participants:
        num = p.get("numPmu")
        rapport = p.get("dernierRapportDirect") or {}
        cote = rapport.get("rapport")
        if num and cote:
            try:
                out.append({"numero": int(num), "cote": float(cote)})
            except (TypeError, ValueError):
                continue
    return out
