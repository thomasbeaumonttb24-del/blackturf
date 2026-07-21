#!/usr/bin/env python3
"""
Daemon cotes live ZEturf → BlackTurf (colonne cote_unibet, car Unibet turf = ZEturf).

Fonctionnement (sans navigateur par requête pour la DB : on tape psql via `docker exec`) :
  - Boucle LENTE (SLOW_INTERVAL) : ré-énumère le programme ZEturf du jour (camoufox),
    liste les courses actuellement exposées (= live/imminentes), les mappe aux courses
    BlackTurf par hippodrome (fuzzy) + heure de départ (±MATCH_MIN min), et écrit les cotes.
  - Boucle RAPIDE (FAST_INTERVAL, ~5s) : garde ouverte la page de la course IMMINENTE
    (prochaine à partir, non terminée) et relit juste les cellules cote → écrit en DB.
    Pas de relance de navigateur, pas de re-navigation : lecture DOM pure.

Écriture : participations.cote_unibet + historique cotes_bookmakers(source='unibet').
Aucune donnée inventée : si pas de correspondance course/partant, on ignore.

Lancé par systemd, tourne dans /opt/scrapling_venv (camoufox installé).
"""
from __future__ import annotations
import re
import sys
import time
import json
import signal
import subprocess
import unicodedata
from datetime import datetime, timezone, timedelta

from camoufox.sync_api import Camoufox

# ─── Config ─────────────────────────────────────────────────────────────────
DB_CONTAINER = "blackturf_db"
DB_USER = "blackturf"
DB_NAME = "blackturf"
PROG_URL = "https://www.zeturf.fr/fr/programmes-et-pronostics-du-jour"
BASE = "https://www.zeturf.fr"
SLOW_INTERVAL = 90      # s — ré-énumération complète du programme
FAST_INTERVAL = 5       # s — relecture cote de la course imminente
MATCH_MIN = 14          # ±minutes pour matcher course zeturf ↔ BlackTurf
PAGE_WAIT_MS = 4500     # attente rendu cotes après navigation

_run = True
def _stop(*_):
    global _run
    _run = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def log(msg: str, **kv):
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg} {extra}".rstrip(), flush=True)

# ─── DB via docker exec psql ────────────────────────────────────────────────
def db_query(sql: str) -> list[list[str]]:
    """SELECT → liste de lignes (champs str). Séparateur | , non-aligné, sans en-tête."""
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
         "-t", "-A", "-F", "\x1f", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        log("db_query.error", err=out.stderr.strip()[:120])
        return []
    rows = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            rows.append(line.split("\x1f"))
    return rows

def db_exec(sql: str) -> bool:
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-q", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        log("db_exec.error", err=out.stderr.strip()[:120])
        return False
    return True

# ─── Normalisation hippodrome ───────────────────────────────────────────────
_STOP = re.compile(r"\b(hippodrome|de|du|des|la|le|l|d|suisse|allemagne|angleterre|prix|grand)\b")
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("-", " ").replace("'", " ")
    s = _STOP.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)

# ─── BlackTurf : courses + partants du jour ─────────────────────────────────
def load_blackturf():
    """Retourne {course_id: {hippo_norm, dt(UTC), nums:set, partants:{numero:pid}}} pour aujourd'hui/demain."""
    rows = db_query(
        "SELECT c.course_id, c.hippodrome_nom, to_char(c.date_heure AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI'), "
        "p.numero, p.participation_id "
        "FROM courses c JOIN participations p ON p.course_id=c.course_id "
        "WHERE c.date_heure::date >= (now() AT TIME ZONE 'UTC')::date "
        "AND c.date_heure::date <= (now() AT TIME ZONE 'UTC')::date + 1 "
        "AND c.statut <> 'termine'"
    )
    courses: dict[str, dict] = {}
    for cid, hippo, dts, num, pid in rows:
        # numero de course PMU = suffixe Cxx du course_id (…R2C1 -> 1)
        m = re.search(r"C(\d+)$", cid)
        cnum = int(m.group(1)) if m else 0
        c = courses.setdefault(cid, {"hippo": norm(hippo), "dt": dts, "cnum": cnum, "partants": {}})
        try:
            c["partants"][int(num)] = pid
        except ValueError:
            pass
    for c in courses.values():
        try:
            c["dt_obj"] = datetime.fromisoformat(c["dt"]).replace(tzinfo=timezone.utc)
        except Exception:
            c["dt_obj"] = None
    return courses

def match_course(bt: dict, z_hippo: str, z_cnum: int, z_dt: datetime | None):
    """course_id BlackTurf correspondant à une course zeturf.

    Clé : hippodrome (fuzzy) + n° de course (ZEturf mirror le numéro PMU pour le FR).
    L'heure de départ, si dispo, sert de confirmation (±MATCH_MIN)."""
    for cid, c in bt.items():
        if not c["hippo"] or not z_hippo:
            continue
        if not (c["hippo"] in z_hippo or z_hippo in c["hippo"]):
            continue
        if c["cnum"] != z_cnum:
            continue
        if z_dt and c["dt_obj"] and abs((c["dt_obj"] - z_dt).total_seconds()) > MATCH_MIN * 60:
            continue
        return cid
    return None

# ─── Écriture cotes ─────────────────────────────────────────────────────────
def write_odds(course_id: str, partants: dict[int, str], cotes: dict[int, float]) -> int:
    """UPDATE cote_unibet + INSERT historique. Retourne nb partants écrits."""
    sets = []
    hist = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for num, cote in cotes.items():
        pid = partants.get(num)
        if not pid or cote <= 1.0:
            continue
        sets.append(f"WHEN participation_id='{pid}' THEN {cote}")
        hist.append(f"(gen_random_uuid()::text,'{pid}','{course_id}','unibet',{cote},false,now())")
    if not sets:
        return 0
    ids = ",".join(f"'{partants[n]}'" for n in cotes if partants.get(n))
    sql = (
        f"UPDATE participations SET cote_unibet = CASE {' '.join(sets)} ELSE cote_unibet END "
        f"WHERE participation_id IN ({ids});"
    )
    db_exec(sql)
    # historique (best-effort ; table cotes_bookmakers)
    db_exec(
        "INSERT INTO cotes_bookmakers(id,participation_id,course_id,source,cote,est_cote_ouverture,scraped_at) "
        f"VALUES {','.join(hist)} ON CONFLICT DO NOTHING;"
    )
    return len(sets)

# ─── Scraping ZEturf ────────────────────────────────────────────────────────
def _parse_course_links(hrefs: list[str]) -> list[dict]:
    """Liens course-du-jour → [{url, hippo, cnum, rc}] (jour courant uniquement)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out, seen = [], set()
    for h in hrefs:
        if not h:
            continue
        h = h.split("#")[0].split("?")[0]
        m = re.search(r"/(\d{4}-\d{2}-\d{2})/(R\d+)(C\d+)-([a-z0-9-]+)", h)
        if not m or m.group(1) != today:
            continue
        key = (m.group(2), m.group(3))
        if key in seen:
            continue
        seen.add(key)
        slug = m.group(4)
        hippo = re.split(r"-(prix|premio|grand|handicap|prkfg)", slug)[0]
        out.append({"url": BASE + h, "hippo": norm(hippo),
                    "cnum": int(m.group(3)[1:]), "rc": key[0] + key[1]})
    return out


def enum_courses(page) -> list[dict]:
    """Énumère le programme COMPLET du jour.

    Le programme (/programmes-et-pronostics-du-jour) n'expose que le meeting
    LIVE du moment. Découverte 2026-07-03 : n'importe quelle page
    /fr/reunion-du-jour/{date}/R1-x (même slug faux → 200) rend la navigation
    de TOUTE la journée (~150-200 liens course-du-jour, toutes réunions). On
    l'utilise comme source principale, programme en secours.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hrefs: list[str] = []
    try:
        page.goto(f"{BASE}/fr/reunion-du-jour/{today}/R1-x",
                  timeout=45000, wait_until="networkidle")
        page.wait_for_timeout(2500)
        hrefs = page.eval_on_selector_all(
            'a[href*="course-du-jour/"]',
            'els=>[...new Set(els.map(e=>e.getAttribute("href")))]',
        )
    except Exception as e:
        log("enum.reunion_page_error", err=str(e)[:100])
    out = _parse_course_links(hrefs)
    if out:
        return out
    # Secours : ancienne énumération via le programme (meeting live seul).
    page.goto(PROG_URL, timeout=45000, wait_until="networkidle")
    page.wait_for_timeout(3000)
    hrefs = page.eval_on_selector_all(
        'a[href*="course-du-jour/"]',
        'els=>[...new Set(els.map(e=>e.getAttribute("href")))]',
    )
    return _parse_course_links(hrefs)

def eval_odds(page) -> tuple[dict[int, float], datetime | None]:
    """Relit les cotes du DOM DÉJÀ chargé (pas de navigation). Pour la boucle rapide :
    zeturf pousse les cotes en live sur la page ouverte, on ne fait que relire."""
    data = page.evaluate("""() => {
      const cotes = {};
      document.querySelectorAll('tr').forEach(r => {
        const n = r.querySelector('.numero');
        const c = r.querySelector('.cote-simplegagnant.cote-live');
        if (!n || !c) return;
        const num = (n.textContent||'').trim().match(/^\\d{1,2}$/);
        const raw = (c.getAttribute('data-order') || c.textContent || '').replace(',', '.');
        const cote = raw.match(/\\d{1,3}(\\.\\d)?/);
        if (num && cote) cotes[parseInt(num[0])] = parseFloat(cote[0]);
      });
      let iso = null;
      const t = document.querySelector('time[datetime], [data-start], [class*="depart"] time');
      if (t) iso = t.getAttribute('datetime') || t.getAttribute('data-start');
      return { cotes, iso };
    }""")
    dt = None
    if data.get("iso"):
        try:
            dt = datetime.fromisoformat(data["iso"].replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return {int(k): float(v) for k, v in data["cotes"].items()}, dt

def read_course(page, url: str) -> tuple[dict[int, float], datetime | None]:
    """Navigue vers une page course (si pas déjà dessus) → ({numero: cote_live}, heure)."""
    if page.url.split("#")[0] != url:
        page.goto(url, timeout=45000, wait_until="networkidle")
        page.wait_for_timeout(PAGE_WAIT_MS)
    return eval_odds(page)

# ─── Boucle principale ──────────────────────────────────────────────────────
def main():
    log("zeturf_daemon.start", slow=SLOW_INTERVAL, fast=FAST_INTERVAL)
    with Camoufox(headless=True, geoip=True) as browser:
        page = browser.new_page()
        last_slow = 0.0
        bt = {}
        imminent = None  # (course_id, url, partants)
        while _run:
            now = time.time()
            # ── LENTE : ré-énumère + mappe tout ──
            if now - last_slow >= SLOW_INTERVAL:
                last_slow = now
                try:
                    bt = load_blackturf()
                    zc = enum_courses(page)
                    # L'énumération complète (~150-200 courses/jour) rendrait le
                    # sweep interminable (~6 s/page). On ne VISITE que les courses
                    # (a) matchables BlackTurf (hippo+cnum, sans confirmation heure)
                    # et (b) dont le départ est à <3 h (ou parti depuis <10 min).
                    now_utc = datetime.now(timezone.utc)
                    visit = []
                    for z in zc:
                        cid = match_course(bt, z["hippo"], z["cnum"], None)
                        if not cid:
                            continue
                        dt_obj = bt[cid].get("dt_obj")
                        if dt_obj and not (timedelta(minutes=-10) <= (dt_obj - now_utc) <= timedelta(hours=3)):
                            continue
                        visit.append(z)
                    log("enum", zeturf=len(zc), blackturf=len(bt), fenetre_3h=len(visit))
                    matched = 0
                    soonest = None
                    for z in visit:
                        cotes, zdt = read_course(page, z["url"])
                        if not cotes:
                            continue
                        cid = match_course(bt, z["hippo"], z["cnum"], zdt)
                        if not cid:
                            continue
                        n = write_odds(cid, bt[cid]["partants"], cotes)
                        matched += 1
                        log("wrote", rc=z["rc"], course=cid, partants=n)
                        # course imminente = la matchée la plus proche dans le futur
                        dt_obj = bt[cid].get("dt_obj")
                        if dt_obj and dt_obj > datetime.now(timezone.utc):
                            if soonest is None or dt_obj < soonest[0]:
                                soonest = (dt_obj, cid, z["url"], bt[cid]["partants"])
                    imminent = (soonest[1], soonest[2], soonest[3]) if soonest else None
                    log("slow.done", matched=matched, imminent=(imminent[0] if imminent else None))
                except Exception as e:
                    log("slow.error", err=str(e)[:140])
            # ── RAPIDE : relit la cote de la course imminente ──
            if imminent:
                try:
                    cid, url, partants = imminent
                    cotes, _ = read_course(page, url)
                    if cotes:
                        n = write_odds(cid, partants, cotes)
                        log("fast", course=cid, partants=n)
                except Exception as e:
                    log("fast.error", err=str(e)[:120])
            time.sleep(FAST_INTERVAL)
    log("zeturf_daemon.stop")

if __name__ == "__main__":
    main()
