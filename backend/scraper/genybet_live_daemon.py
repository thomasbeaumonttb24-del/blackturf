#!/usr/bin/env python3
"""
Daemon cotes GenyBet → BlackTurf (colonne cote_geny, = les cotes de l'opérateur Geny).

GenyBet est protégé par Cloudflare → chaque page nécessite un solve_cloudflare via
scrapling.StealthyFetcher (Chrome réel, ~15-25 s). Impossible de faire du 5 s live
(re-challenge). On rafraîchit donc en boucle LENTE uniquement (SLOW_INTERVAL), et on
ne fetch QUE les pages des courses imminentes (fenêtre IMMINENT_H heures) pour borner
le coût des CF-solves.

Énumération (1 seul fetch/cycle) : la home liste toutes les courses du jour avec, par
lien, l'hippodrome + le n° de course (« Clairefontaine-Deauville C3 ») et l'heure. Le n°
de réunion GenyBet = n° PMU. Mapping BlackTurf = hippodrome (fuzzy) + n° course.

Extraction cote/course : chaque <tr id="partant-N"> porte le numéro ; la cote (gagnant)
est le texte juste après l'image de tendance `.img-cote`. Marché partiel toléré (GenyBet
n'ouvre pas toutes les cotes d'emblée) → on écrit ce qui existe.

Écrit participations.cote_geny + historique cotes_bookmakers(source='geny').
Réutilise les helpers DB/normalisation du daemon ZEturf (même dossier).
"""
from __future__ import annotations
import os
import re
import sys
import time
import signal
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "/opt/blackturf_odds")
from zeturf_live_daemon import db_exec, norm, load_blackturf, log  # helpers partagés
from live_daemon_watchdog import CycleWatchdog
from scrapling.fetchers import StealthyFetcher

PARIS = ZoneInfo("Europe/Paris")
PROGRAM = "https://www.genybet.fr/reunions/{ddmmyyyy}"
COURSE = "https://www.genybet.fr/courses/partants-pronostics/{id}"
SLOW_INTERVAL = 180     # s — un cycle complet
IMMINENT_H = 3          # h — ne fetch que les courses partant dans cette fenêtre
FETCH_KW = dict(headless=True, real_chrome=True, solve_cloudflare=True,
                humanize=True, geoip=True, network_idle=True, timeout=90000)
WATCHDOG_TIMEOUT_S = int(os.getenv("BT_GENYBET_CYCLE_TIMEOUT", "1200"))
WATCHDOG_GRACE_S = int(os.getenv("BT_GENYBET_WATCHDOG_GRACE", "120"))
# Cf. `zeturf_live_daemon` : même garde de stérilité, calibrée sur un cycle plus
# long (SLOW_INTERVAL = 180 s), soit 6 cycles avant redémarrage.
WATCHDOG_STERILE_S = int(os.getenv("BT_GENYBET_STERILE_TIMEOUT", "1080"))
HEARTBEAT_PATH = os.getenv(
    "BT_GENYBET_HEARTBEAT", "/opt/blackturf_odds/genybet_heartbeat"
)

_run = True
def _stop(*_):
    global _run
    _run = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

_watchdog = CycleWatchdog(
    name="genybet_daemon",
    timeout_s=WATCHDOG_TIMEOUT_S,
    grace_s=WATCHDOG_GRACE_S,
    heartbeat_path=HEARTBEAT_PATH,
    log=log,
    sterile_timeout_s=WATCHDOG_STERILE_S,
)

def fetch_html(url: str) -> str:
    try:
        return StealthyFetcher.fetch(url, **FETCH_KW).html_content or ""
    except Exception as e:
        log("genybet.fetch_error", url=url[-40:], err=str(e)[:90])
        return ""

def enum_program(html: str, today_utc: datetime) -> list[dict]:
    """Parse la page /reunions/JJ-MM-AAAA (timeline) → [{id, cnum, dt_utc}].

    Chaque course : <li class="race" id="timeline-course-ID" data-startime="18h23" ...>
      <a href="/courses/partants-pronostics/ID"> CNUM </a>
    L'heure est locale Paris → convertie en UTC pour matcher BlackTurf.
    """
    out, seen = [], set()
    day = today_utc.astimezone(PARIS).date()
    for m in re.finditer(
        r'id="timeline-course-(\d+)"[^>]*data-startime="(\d{1,2})h(\d{2})"'
        r'[^>]*>\s*<a href="/courses/partants-pronostics/\1">\s*(\d+)\s*<', html
    ):
        gid, hh, mm, cnum = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if gid in seen:
            continue
        seen.add(gid)
        try:
            dt_local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=PARIS)
        except ValueError:
            continue
        out.append({"id": gid, "cnum": cnum, "dt_utc": dt_local.astimezone(timezone.utc)})
    return out

def read_course(gid: str) -> dict[int, float]:
    """Page course GenyBet → {numero: cote_gagnant}. Marché partiel toléré."""
    html = fetch_html(COURSE.format(id=gid))
    if not html:
        return {}
    cotes: dict[int, float] = {}
    # découpe par ligne partant pour éviter le cross-match
    for blk in re.split(r'(?=id="partant-\d+")', html):
        mn = re.match(r'id="partant-(\d+)"', blk)
        if not mn:
            continue
        num = int(mn.group(1))
        mc = re.search(r'img-cote[^>]*>\s*(\d{1,3}[.,]\d)', blk)
        if mc:
            cotes[num] = float(mc.group(1).replace(",", "."))
    return cotes

def write_geny(course_id: str, partants: dict[int, str], cotes: dict[int, float]) -> int:
    sets, hist = [], []
    for num, cote in cotes.items():
        pid = partants.get(num)
        if not pid or cote <= 1.0:
            continue
        sets.append(f"WHEN participation_id='{pid}' THEN {cote}")
        hist.append(f"(gen_random_uuid()::text,'{pid}','{course_id}','geny',{cote},false,now())")
    if not sets:
        return 0
    ids = ",".join(f"'{partants[n]}'" for n in cotes if partants.get(n))
    db_exec(
        f"UPDATE participations SET cote_geny = CASE {' '.join(sets)} ELSE cote_geny END "
        f"WHERE participation_id IN ({ids});"
    )
    db_exec(
        "INSERT INTO cotes_bookmakers(id,participation_id,course_id,source,cote,est_cote_ouverture,scraped_at) "
        f"VALUES {','.join(hist)} ON CONFLICT DO NOTHING;"
    )
    return len(sets)

def main():
    log("genybet_daemon.start", slow=SLOW_INTERVAL, imminent_h=IMMINENT_H)
    _watchdog.start()
    while _run:
        _watchdog.begin_cycle()
        t0 = time.time()
        try:
            now = datetime.now(timezone.utc)
            bt = load_blackturf()
            prog = fetch_html(PROGRAM.format(ddmmyyyy=now.astimezone(PARIS).strftime("%d-%m-%Y")))
            gc = enum_program(prog, now)
            matched = wrote = 0
            for g in gc:
                # borne : seulement les courses imminentes (fenêtre) pour limiter les CF-solves
                dh = (g["dt_utc"] - now).total_seconds() / 3600.0
                if dh < -0.25 or dh > IMMINENT_H:
                    continue
                # match BlackTurf : même n° course + heure proche (±14 min)
                cid = None
                for bcid, c in bt.items():
                    if c["cnum"] != g["cnum"] or not c.get("dt_obj"):
                        continue
                    if abs((c["dt_obj"] - g["dt_utc"]).total_seconds()) <= 14 * 60:
                        cid = bcid
                        break
                if not cid:
                    continue
                matched += 1
                cotes = read_course(g["id"])
                n = write_geny(cid, bt[cid]["partants"], cotes)
                if n:
                    wrote += 1
                    log("geny.wrote", course=cid, partants=n)
            log("genybet.cycle", prog_courses=len(gc), imminent=matched, wrote=wrote,
                sec=round(time.time() - t0))
            # Cycle mené à son terme : c'est ce qui réarme la garde de stérilité,
            # pas le heartbeat (qui se pose aussi quand le cycle a échoué).
            _watchdog.record_progress()
        except Exception as e:
            log("genybet.cycle_error", err=str(e)[:140])
        finally:
            _watchdog.finish_cycle()
        # dormir le reste du cycle
        for _ in range(int(SLOW_INTERVAL)):
            if not _run:
                break
            time.sleep(1)
    log("genybet_daemon.stop")

if __name__ == "__main__":
    main()
