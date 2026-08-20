#!/usr/bin/env python3
"""
Daemon cotes live Oddschecker → BlackTurf (cote_bet365 + cote_betfair_exchange).

Pourquoi : les bookmakers FR hors PMU/ZEturf/Genybet sont géo-bloqués côté IP
depuis le VPS (Betclic/Vbet 403 pays, testé 2026-07-03 — un anti-bot stealth ne
contourne PAS un blocage IP). Oddschecker (agrégateur UK, accessible) price les
réunions françaises de galop/mixte via Bet365 (colonne B3) et parfois le
Betfair Exchange (BF) → deux cotes « marché fixe international », utiles en
signal de valeur face au mutuel PMU.

Fonctionnement (camoufox, même toolchain que zeturf-odds) :
  - Toutes ENUM_INTERVAL s : liste les meetings du jour sur /horse-racing
    (liens `/horse-racing/{slug}/{HH:MM}/winner`, heures LOCALES UK), mappe les
    meetings aux hippodromes BlackTurf (norm fuzzy) et chaque course par heure
    de départ Londres→UTC (±MATCH_MIN min).
  - Pour chaque course matchée à <3 h du départ : ouvre la page, lit les lignes
    `tr.diff-row.evTabRow` (data-bname = nom cheval, td[data-bk][data-odig] =
    cote décimale par bookmaker), matche les chevaux PAR NOM normalisé.
  - Écrit participations.cote_bet365 (B3) et cote_betfair_exchange (BF si >1)
    + historique cotes_bookmakers(source='bet365'/'betfair_exchange').

Aucune donnée inventée : pas de match nom → pas d'écriture.
Lancé par systemd (oddschecker-odds), tourne dans /opt/scrapling_venv.
"""
from __future__ import annotations
import os
import re
import signal
import subprocess
import threading
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from camoufox.sync_api import Camoufox

# ─── Config ─────────────────────────────────────────────────────────────────
DB_CONTAINER = "blackturf_db"
DB_USER = "blackturf"
DB_NAME = "blackturf"
BASE = "https://www.oddschecker.com"
INDEX_URL = f"{BASE}/horse-racing"
ENUM_INTERVAL = 300     # s — ré-énumération index + sweep des courses en fenêtre
WINDOW_H = 3            # h — ne visite que les courses partant dans < WINDOW_H
MATCH_MIN = 7           # ± minutes heure oddschecker (UK) ↔ BlackTurf (UTC)
PAGE_WAIT_MS = 5000
# La session Camoufox ne survit PAS à un cycle : dès qu'elle a servi à lire des
# pages de course, la ré-énumération de l'index ne ramène plus rien. Mesuré dans
# le journal du 20/08/2026 : après chaque page neuve, `enum oddschecker=180`,
# puis `enum=0` sur les trois cycles suivants, indéfiniment — soit 3 cycles
# perdus sur 4 et une couverture bet365/ladbrokes/betfair tombée à 0,7 %, alors
# que le daemon se portait « bien » (process vivant, aucune exception).
# On ouvre donc une session NEUVE à chaque cycle : `browser.new_page()` crée un
# contexte isolé (cookies, consentement, redirection géo repartent à zéro) et le
# `page.close()` du `finally` le referme — pas d'accumulation mémoire.
LONDON = ZoneInfo("Europe/London")

_run = True
def _stop(*_):
    global _run
    _run = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

# ── Anti-gel ─────────────────────────────────────────────────────────────────
# Constaté le 2026-08-16 : le daemon s'est figé le 02/08 à 11:01 (driver Playwright
# mort — "Connection closed while reading from the driver"), et le process Python
# est resté vivant, spinnant à 92% CPU EN CONTINU pendant 15 jours (`systemctl
# status` : "Active: active (running) since 2026-08-01", même PID). Le try/except
# du cycle capte les erreurs applicatives, mais un appel sync Playwright/Camoufox
# qui bloque sur un pipe IPC mort ne lève rien — il ne rend simplement jamais la
# main. `Restart=always` de systemd est configuré mais NE SERT À RIEN tant que le
# process ne meurt pas de lui-même : il faut le tuer explicitement.
#
# Script SYNCHRONE (Camoufox sync API) : pas d'event loop à annuler proprement
# comme pour l'orchestrator asyncio → seul un watchdog THREAD, indépendant du
# thread principal, peut détecter le gel et forcer la sortie.
CYCLE_TIMEOUT_S = int(os.getenv("BT_ODDSCHECKER_CYCLE_TIMEOUT", str(ENUM_INTERVAL * 3)))
_cycle_started_at: float | None = None


def _start_watchdog() -> None:
    def _loop() -> None:
        while True:
            time.sleep(30)
            started = _cycle_started_at
            if started is not None and (time.time() - started) > CYCLE_TIMEOUT_S:
                log("watchdog.kill", elapsed_s=int(time.time() - started),
                    timeout_s=CYCLE_TIMEOUT_S)
                os._exit(1)  # systemd Restart=always relance avec un driver neuf
    threading.Thread(target=_loop, name="cycle-watchdog", daemon=True).start()

def log(msg: str, **kv):
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg} {extra}".rstrip(), flush=True)


# Signatures d'un driver Playwright MORT : le process Node qui pilote le
# navigateur a crashé, et plus aucun appel ne pourra aboutir.
_DRIVER_MORT = (
    "connection closed",
    "target closed",
    "browser has been closed",
    "browser closed",
)


def _exit_si_driver_mort(exc: BaseException) -> None:
    """Sort du process quand le driver est mort, pour que systemd relance.

    Constaté le 18/08/2026 : le driver Node de Playwright a crashé sur un bug
    interne (`Cannot read properties of undefined (reading 'url')` dans son
    propre bundle, déclenché par une erreur JS de la page). Ensuite CHAQUE appel
    échoue avec « Connection closed while reading from the driver », mais le
    process Python reste bien vivant : le cycle attrape l'exception, la
    journalise, dort, recommence — indéfiniment. Le watchdog ne se déclenche
    jamais puisque les cycles échouent VITE, loin de dépasser leur timeout, et
    `Restart=always` ne sert à rien tant que le process ne meurt pas
    (`NRestarts=0` après des heures de panne).

    Recréer la page ne suffit pas : `browser.new_page()` échoue aussi. Seule la
    sortie du process permet de repartir avec un driver neuf.
    """
    message = str(exc).lower()
    if any(signature in message for signature in _DRIVER_MORT):
        log("driver.dead_exit", err=str(exc)[:120])
        os._exit(1)   # systemd Restart=always relance avec un driver neuf

# ─── DB via docker exec psql (même pattern que zeturf/genybet daemons) ──────
def db_query(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
         "-t", "-A", "-F", "\x1f", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        log("db_query.error", err=out.stderr.strip()[:120])
        return []
    return [l.split("\x1f") for l in out.stdout.splitlines() if l.strip()]

def db_exec(sql: str) -> bool:
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-q", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        log("db_exec.error", err=out.stderr.strip()[:120])
        return False
    return True

# ─── Normalisation ──────────────────────────────────────────────────────────
_STOP = re.compile(r"\b(hippodrome|de|du|des|la|le|l|d)\b")
def norm_hippo(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("-", " ").replace("'", " ")
    s = _STOP.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)

def norm_nom(s: str) -> str:
    """Nom de cheval : accents/casse/ponctuation neutralisés."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)

# ─── BlackTurf : courses + chevaux du jour ──────────────────────────────────
def load_blackturf() -> dict:
    """{course_id: {hippo, dt_obj, chevaux:{nom_norm: (numero, pid)}}} du jour."""
    rows = db_query(
        "SELECT c.course_id, c.hippodrome_nom, "
        "to_char(c.date_heure AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI'), "
        "p.numero, p.participation_id, ch.nom "
        "FROM courses c "
        "JOIN participations p ON p.course_id=c.course_id "
        "JOIN chevaux ch ON ch.cheval_id=p.cheval_id "
        "WHERE c.date_heure::date = (now() AT TIME ZONE 'UTC')::date "
        "AND c.statut <> 'termine' AND NOT p.non_partant"
    )
    courses: dict[str, dict] = {}
    for cid, hippo, dts, num, pid, nom in rows:
        c = courses.setdefault(cid, {"hippo": norm_hippo(hippo), "dt": dts, "chevaux": {}})
        c["chevaux"][norm_nom(nom)] = (num, pid)
    for c in courses.values():
        try:
            c["dt_obj"] = datetime.fromisoformat(c["dt"]).replace(tzinfo=timezone.utc)
        except Exception:
            c["dt_obj"] = None
    return courses

# ─── Écriture ───────────────────────────────────────────────────────────────
def write_odds(course_id: str, matches: list[tuple[str, str, str, float]]) -> int:
    """matches = [(participation_id, colonne, source, cote)] → UPDATE + historique."""
    written = 0
    by_col: dict[str, list[tuple[str, float]]] = {}
    hist = []
    for pid, col, src, cote in matches:
        by_col.setdefault(col, []).append((pid, cote))
        hist.append(f"(gen_random_uuid()::text,'{pid}','{course_id}','{src}',{cote},false,now())")
    for col, pairs in by_col.items():
        sets = " ".join(f"WHEN participation_id='{pid}' THEN {cote}" for pid, cote in pairs)
        ids = ",".join(f"'{pid}'" for pid, _ in pairs)
        if db_exec(f"UPDATE participations SET {col} = CASE {sets} ELSE {col} END "
                   f"WHERE participation_id IN ({ids});"):
            written += len(pairs)
    if hist:
        db_exec(
            "INSERT INTO cotes_bookmakers(id,participation_id,course_id,source,cote,est_cote_ouverture,scraped_at) "
            f"VALUES {','.join(hist)} ON CONFLICT DO NOTHING;"
        )
    return written

# ─── Scraping Oddschecker ───────────────────────────────────────────────────
def enum_races(page) -> list[dict]:
    """Index → [{slug, hhmm, url, dt_utc}] des courses du JOUR (heures UK locales)."""
    page.goto(INDEX_URL, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(PAGE_WAIT_MS)
    hrefs = page.eval_on_selector_all(
        'a[href*="/horse-racing/"]',
        'els=>[...new Set(els.map(e=>e.getAttribute("href")))]',
    )
    today_london = datetime.now(LONDON).date()
    out = []
    for h in hrefs or []:
        m = re.match(r"^/horse-racing/([a-z-]+)/(\d{2}):(\d{2})/winner$", h or "")
        if not m:
            continue
        dt_local = datetime(today_london.year, today_london.month, today_london.day,
                            int(m.group(2)), int(m.group(3)), tzinfo=LONDON)
        out.append({"slug": m.group(1), "hhmm": f"{m.group(2)}:{m.group(3)}",
                    "url": BASE + h, "dt_utc": dt_local.astimezone(timezone.utc)})
    return out

def read_race(page, url: str) -> dict[str, dict[str, float]]:
    """Page course → {nom_norm: {bk: cote}} (cotes décimales > 1).

    Books retenus : B3=Bet365, BF=Betfair Exchange, LD=Ladbrokes, CE=Coral
    (LD/CE = Entain, cotes quasi identiques — CE sert de repli si LD absent).
    """
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(PAGE_WAIT_MS)
    rows = page.evaluate("""() => {
      const KEEP = new Set(['B3', 'BF', 'LD', 'CE']);
      const out = [];
      document.querySelectorAll('tr.diff-row.evTabRow').forEach(r => {
        const nom = r.getAttribute('data-bname') || '';
        const odds = {};
        r.querySelectorAll('td[data-bk]').forEach(td => {
          const bk = td.getAttribute('data-bk');
          if (!KEEP.has(bk)) return;
          const v = parseFloat(td.getAttribute('data-odig') || '0');
          if (v > 1) odds[bk] = v;
        });
        if (nom) out.push({nom, odds});
      });
      return out;
    }""")
    return {norm_nom(r["nom"]): r["odds"] for r in rows if r.get("odds")}

def match_course(bt: dict, slug: str, dt_utc: datetime):
    """course_id BlackTurf pour un meeting oddschecker (hippo fuzzy + heure ±MATCH_MIN)."""
    s = norm_hippo(slug)
    for cid, c in bt.items():
        if not c["hippo"] or not s:
            continue
        if not (s in c["hippo"] or c["hippo"] in s):
            continue
        if c["dt_obj"] and abs((c["dt_obj"] - dt_utc).total_seconds()) <= MATCH_MIN * 60:
            return cid
    return None

# ─── Boucle principale ──────────────────────────────────────────────────────
def main():
    global _cycle_started_at
    log("oddschecker_daemon.start", enum=ENUM_INTERVAL, window_h=WINDOW_H,
        cycle_timeout_s=CYCLE_TIMEOUT_S)
    _start_watchdog()
    # Le watchdog est armé AVANT l'ouverture du navigateur : un hang dans
    # `Camoufox(...)` lui-même (déjà observé sur les daemons soeurs) est
    # couvert, pas seulement les hangs à l'intérieur de la boucle `while _run`.
    _cycle_started_at = time.time()
    with Camoufox(headless=True, geoip=True) as browser:
        while _run:
            _cycle_started_at = time.time()
            t0 = time.time()
            page = None
            cotes_du_cycle = 0
            try:
                # Session NEUVE à chaque cycle : réutiliser la page fige
                # l'énumération de l'index dès la première course lue (cf. note
                # en tête de fichier).
                page = browser.new_page()
                bt = load_blackturf()
                races = enum_races(page)
                now = datetime.now(timezone.utc)
                visit = []
                for r in races:
                    if not (timedelta(minutes=-10) <= (r["dt_utc"] - now) <= timedelta(hours=WINDOW_H)):
                        continue
                    cid = match_course(bt, r["slug"], r["dt_utc"])
                    if cid:
                        visit.append((cid, r))
                log("enum", oddschecker=len(races), blackturf=len(bt), fenetre=len(visit))
                for cid, r in visit:
                    try:
                        odds_by_nom = read_race(page, r["url"])
                        chevaux = bt[cid]["chevaux"]
                        matches = []
                        for nom_n, odds in odds_by_nom.items():
                            entry = chevaux.get(nom_n)
                            if not entry:
                                continue
                            _, pid = entry
                            if "B3" in odds:
                                matches.append((pid, "cote_bet365", "bet365", odds["B3"]))
                            if "BF" in odds:
                                matches.append((pid, "cote_betfair_exchange", "betfair_exchange", odds["BF"]))
                            ld = odds.get("LD") or odds.get("CE")
                            if ld:
                                matches.append((pid, "cote_ladbrokes", "ladbrokes", ld))
                        if matches:
                            n = write_odds(cid, matches)
                            cotes_du_cycle += n
                            log("wrote", race=f"{r['slug']}/{r['hhmm']}", course=cid, cotes=n)
                    except Exception as e:
                        log("race.error", url=r["url"][-40:], err=str(e)[:100])
                # Bilan de PRODUCTIVITÉ, pas de simple survie : cette ligne
                # distingue « rien à faire » de « tourne à vide ».
                log("cycle", courses=len(visit), cotes=cotes_du_cycle,
                    sec=int(time.time() - t0))
            except Exception as e:
                log("cycle.error", err=str(e)[:140])
                _exit_si_driver_mort(e)
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception as e:
                        log("session.close_error", err=str(e)[:90])
            # attente jusqu'au prochain cycle (interruptible)
            elapsed = time.time() - t0
            for _ in range(int(max(5.0, ENUM_INTERVAL - elapsed))):
                if not _run:
                    break
                time.sleep(1)
    log("oddschecker_daemon.stop")

if __name__ == "__main__":
    main()
