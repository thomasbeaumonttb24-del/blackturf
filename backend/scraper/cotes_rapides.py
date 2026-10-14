"""
Relevé RAPIDE des cotes PMU en base, près du départ.

POURQUOI. `participations.cote_pmu` n'est réécrite que par le cycle de scrape
complet (navigateur furtif + toutes les sources), qui repasse sur une course toutes
les 7 à 11 min. Or c'est cette cote que lisent le re-gel T-10 (`predict_course`
réécrit `cote_figee`, les value bets et les plans figés des trois profils).

Mesuré sur 412 courses (08→14/10/2026) : au moment du gel T-10, la dernière cote
PMU en base avait 3,7 min d'âge en médiane, 7,6 min au 90e centile, 13,2 min au
pire — précisément dans la demi-heure où le marché PMU bouge le plus.

CE QUE FAIT CE MODULE. Toutes les `TICK_S` secondes, pour les seules courses qui
partent dans les `FENETRE_MIN` minutes, une requête JSON au PMU par course (pas de
navigateur), puis mise à jour de la cote, de son horodatage PMU et du mouvement
natif. Charge : 1 à 4 courses dans la fenêtre en pratique, soit quelques requêtes
HTTP et quelques UPDATE par minute.

CE QU'IL NE FAIT PAS, délibérément :
  - il n'ajoute AUCUNE ligne à `cotes_historique`. Les features `mouvement_30min`,
    `spi_score`, `variance_cotes_7j` et `momentum_3j` sont calculées sur cette série,
    et `momentum_3j` coupe la série en deux par le NOMBRE de points : densifier la
    dernière demi-heure changerait leur distribution par rapport à l'entraînement.
    La série garde donc le rythme du cycle complet ;
  - il ne touche pas aux non-partants (le cycle complet en reste seul juge) ;
  - il n'écrit jamais une cote plus ANCIENNE que celle en base (le PMU date chaque
    rapport : `cote_pmu_datetime`).
"""
from __future__ import annotations

import time

import httpx
import structlog
from sqlalchemy import text

from scraper.sources.pmu import _epoch_ms_to_dt
from scraper.validation import valid_cote
from services.pmu_cotes import _BASE, _HEADERS, parse_course_id

log = structlog.get_logger(module="cotes_rapides")

FENETRE_MIN = 30      # min — on ne suit en rapide que les courses qui partent bientôt
TICK_S = 60           # s — cadence de la boucle
HTTP_TIMEOUT_S = 6.0


async def fetch_rapports(client: httpx.AsyncClient, course_id: str) -> dict[int, dict]:
    """Cote directe PMU de chaque partant : {numero: {cote, cote_ref, date, tendance, force}}.

    Vide si la course est inconnue du PMU ou si l'appel échoue : on ne réécrit
    alors rien, la cote du cycle complet reste en place.
    """
    parsed = parse_course_id(course_id)
    if not parsed:
        return {}
    d, r, c = parsed
    url = f"{_BASE}/programme/{d}/R{r}/C{c}/participants?specialisation=INTERNET"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("cotes_rapides.fetch_echec", course_id=course_id, error=str(e)[:120])
        return {}

    participants = data if isinstance(data, list) else data.get("participants", [])
    out: dict[int, dict] = {}
    for p in participants:
        num = p.get("numPmu")
        rd = p.get("dernierRapportDirect") or {}
        rr = p.get("dernierRapportReference") or {}
        cote = valid_cote(rd.get("rapport"))
        if not num or cote is None:
            continue
        if str(p.get("statut") or "").upper() == "NON_PARTANT":
            continue
        cote_ref = valid_cote(rr.get("rapport"))
        force = rd.get("nombreIndicateurTendance")
        out[int(num)] = {
            "cote": cote,
            "cote_ref": cote_ref,
            "mouvement": round((cote - cote_ref) / cote_ref, 4) if cote_ref else None,
            "date": _epoch_ms_to_dt(rd.get("dateRapport")),
            "tendance": (str(rd["indicateurTendance"])[:2]
                         if rd.get("indicateurTendance") is not None else None),
            "force": float(force) if isinstance(force, (int, float)) and not isinstance(force, bool) else None,
        }
    return out


async def ecrire_rapports(session, course_id: str, rapports: dict[int, dict]) -> tuple[int, int]:
    """Met à jour les partants dont la cote PMU a bougé. Rend (nb_suivis, nb_modifiés).

    `nb_suivis` = partants en base qui ont une cote PMU live ; `nb_modifiés` = ceux
    dont la cote en base différait de la cote live (donc périmée avant ce passage).
    """
    if not rapports:
        return 0, 0
    lignes = (await session.execute(text("""
        SELECT numero, cote_pmu, cote_pmu_datetime
        FROM participations
        WHERE course_id = :cid AND non_partant = false
    """), {"cid": course_id})).fetchall()

    suivis = modifies = 0
    for numero, cote_base, date_base in lignes:
        rp = rapports.get(int(numero)) if numero is not None else None
        if rp is None:
            continue
        suivis += 1
        # Jamais en arrière : une cote datée AVANT celle en base est plus vieille.
        if date_base is not None and rp["date"] is not None and rp["date"] < date_base:
            continue
        if cote_base is not None and abs(float(cote_base) - rp["cote"]) < 1e-9:
            if rp["date"] is None or rp["date"] == date_base:
                continue
            # Même cote, rapport plus récent : on rafraîchit seulement la date.
            await session.execute(text("""
                UPDATE participations SET cote_pmu_datetime = :dt
                WHERE course_id = :cid AND numero = :num AND non_partant = false
            """), {"dt": rp["date"], "cid": course_id, "num": numero})
            continue
        modifies += 1
        await session.execute(text("""
            UPDATE participations
            SET cote_pmu = :cote,
                cote_pmu_datetime = COALESCE(:dt, cote_pmu_datetime),
                cote_reference = COALESCE(:ref, cote_reference),
                mouvement_cote_pct = COALESCE(:mvt, mouvement_cote_pct),
                tendance_cote = COALESCE(:tend, tendance_cote),
                tendance_force = COALESCE(:force, tendance_force),
                updated_at = now()
            WHERE course_id = :cid AND numero = :num AND non_partant = false
        """), {"cote": rp["cote"], "dt": rp["date"], "ref": rp["cote_ref"],
               "mvt": rp["mouvement"], "tend": rp["tendance"], "force": rp["force"],
               "cid": course_id, "num": numero})
    return suivis, modifies


async def rafraichir_course(session_factory, course_id: str,
                            client: httpx.AsyncClient | None = None) -> tuple[int, int]:
    """Relève et écrit la cote PMU d'UNE course. Rend (nb_suivis, nb_modifiés)."""
    if client is None:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=HTTP_TIMEOUT_S,
                                     follow_redirects=True) as c:
            return await rafraichir_course(session_factory, course_id, c)
    rapports = await fetch_rapports(client, course_id)
    if not rapports:
        return 0, 0
    async with session_factory() as session:
        res = await ecrire_rapports(session, course_id, rapports)
        await session.commit()
    return res


async def run_cotes_rapides(session_factory) -> dict:
    """Un passage : toutes les courses qui partent dans les FENETRE_MIN minutes."""
    t0 = time.monotonic()
    async with session_factory() as session:
        courses = [r[0] for r in (await session.execute(text("""
            SELECT c.course_id
            FROM courses c
            WHERE c.statut = 'a_venir'
              AND c.date_heure >  now()
              AND c.date_heure <= now() + make_interval(mins => :fenetre)
            ORDER BY c.date_heure
        """), {"fenetre": FENETRE_MIN})).fetchall()]
    bilan = {"courses": len(courses), "suivis": 0, "modifies": 0}
    if not courses:
        return bilan

    async with httpx.AsyncClient(headers=_HEADERS, timeout=HTTP_TIMEOUT_S,
                                 follow_redirects=True) as client:
        for cid in courses:
            try:
                suivis, modifies = await rafraichir_course(session_factory, cid, client)
            except Exception as e:
                log.error("cotes_rapides.ecriture_echec", course_id=cid, error=str(e)[:200])
                continue
            bilan["suivis"] += suivis
            bilan["modifies"] += modifies
    bilan["sec"] = round(time.monotonic() - t0, 1)
    log.info("cotes_rapides.passage", **bilan)
    return bilan
