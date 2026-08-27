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
import os
import re
import sys
import time
import json
import signal
import subprocess
import unicodedata
from datetime import datetime, timezone, timedelta

from camoufox.sync_api import Camoufox
from live_daemon_watchdog import CycleWatchdog

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
# Énumérations vides consécutives avant de recréer la page — même correctif que
# le daemon oddschecker (18/08/2026). 3 cycles de SLOW_INTERVAL = 4,5 min.
ENUM_VIDES_AVANT_RECREATION = 3
WATCHDOG_TIMEOUT_S = int(os.getenv("BT_ZETURF_CYCLE_TIMEOUT", "1200"))
WATCHDOG_GRACE_S = int(os.getenv("BT_ZETURF_WATCHDOG_GRACE", "120"))
# Délai sans UN SEUL cycle lent mené à son terme avant de redémarrer le process.
# 15 min = 10 cycles de SLOW_INTERVAL : assez pour absorber une rafale de
# timeouts passagers, assez court pour ne pas perdre la fenêtre de cotes d'une
# course (elles bougent surtout dans la dernière demi-heure).
WATCHDOG_STERILE_S = int(os.getenv("BT_ZETURF_STERILE_TIMEOUT", "900"))
HEARTBEAT_PATH = os.getenv(
    "BT_ZETURF_HEARTBEAT", "/opt/blackturf_odds/zeturf_heartbeat"
)

_run = True
def _stop(*_):
    global _run
    _run = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def log(msg: str, **kv):
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg} {extra}".rstrip(), flush=True)


# Signatures d'un driver Playwright MORT : le process Node qui pilote le
# navigateur a crashé, plus aucun appel ne pourra aboutir.
_DRIVER_MORT = (
    "connection closed",
    "target closed",
    "browser has been closed",
    "browser closed",
)


def _exit_si_driver_mort(exc: BaseException) -> None:
    """Sort du process quand le driver est mort, pour que systemd relance.

    Observé sur le daemon oddschecker le 18/08/2026 : le driver Node de
    Playwright crashe sur un bug interne, puis CHAQUE appel échoue avec
    « Connection closed while reading from the driver » — mais le process Python
    reste vivant, attrape l'exception, dort et recommence indéfiniment. Le
    watchdog ne se déclenche jamais (les cycles échouent VITE, loin de leur
    timeout) et `Restart=always` ne sert à rien tant que le process ne meurt pas.
    Recréer la page ne suffit pas : `browser.new_page()` échoue aussi.
    """
    message = str(exc).lower()
    if any(signature in message for signature in _DRIVER_MORT):
        log("driver.dead_exit", err=str(exc)[:120])
        os._exit(1)   # systemd Restart=always relance avec un driver neuf


_watchdog = CycleWatchdog(
    name="zeturf_daemon",
    timeout_s=WATCHDOG_TIMEOUT_S,
    grace_s=WATCHDOG_GRACE_S,
    heartbeat_path=HEARTBEAT_PATH,
    log=log,
    sterile_timeout_s=WATCHDOG_STERILE_S,
)

# ─── DB via docker exec psql ────────────────────────────────────────────────
# Ces appels ne coûtent que ~0,1 s sur un serveur au repos, mais `docker exec`
# démarre un process dans un conteneur : sous la charge des trois camoufox
# (load 5-6 sur 4 cœurs, 2,4 Go de swap le 26/08/2026) l'ordonnancement seul
# dépasse les 30 s d'origine. Une expiration ici faisait tomber TOUT le cycle
# lent, `load_blackturf()` étant sa première étape.
DB_TIMEOUT_S = int(os.getenv("BT_ZETURF_DB_TIMEOUT", "60"))


def _psql(args: list[str], quoi: str) -> subprocess.CompletedProcess:
    """Lance psql, avec UNE reprise : une expiration ici est un pic de charge,
    pas une panne — abandonner au premier essai coûte le cycle entier.

    Après la reprise on LÈVE, au lieu de rendre un résultat vide : un programme
    vide et une base injoignable se ressemblent, et confondre les deux ferait
    passer un daemon aveugle pour un daemon sans travail.
    """
    cmd = ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, *args]
    for tentative in (1, 2):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=DB_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            log(f"{quoi}.timeout", tentative=tentative, timeout_s=DB_TIMEOUT_S)
    raise RuntimeError(f"{quoi}: psql injoignable après 2 essais de {DB_TIMEOUT_S}s")


def db_query(sql: str) -> list[list[str]]:
    """SELECT → liste de lignes (champs str). Séparateur | , non-aligné, sans en-tête."""
    out = _psql(["-t", "-A", "-F", "\x1f", "-c", sql], "db_query")
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
    out = _psql(["-q", "-c", sql], "db_exec")
    if out.returncode != 0:
        # `rc` journalise le code de sortie : un stderr VIDE avec rc != 0 n'est pas
        # une erreur SQL (psql ecrit toujours son ERROR) mais un `docker exec` qui a
        # echoue — les deux se ressemblaient dans le journal.
        log("db_exec.error", rc=out.returncode, err=out.stderr.strip()[:120])
        return False
    return True


_TAG = re.compile(r"^(?:UPDATE|INSERT|DELETE)\s+(?:\d+\s+)?(\d+)\s*$", re.M)


def db_exec_rows(sql: str) -> int:
    """Comme db_exec, mais rend le nombre de lignes REELLEMENT touchees (-1 si echec).

    `db_exec` ne rendait qu'un booleen, et les daemons journalisaient le nombre de
    clauses SET CONSTRUITES : `wrote=3` s'affichait meme quand la base n'avait rien
    modifie. C'est ce qui a laisse participations.cote_geny vide sans qu'aucune
    alerte ne parte. On lance donc psql SANS -q pour lire son etiquette de commande
    (« UPDATE 12 »), seule source de verite sur ce qui a ete ecrit.
    """
    out = _psql(["-c", sql], "db_exec_rows")
    if out.returncode != 0:
        # Cle DISTINCTE de celle de db_exec : les deux partageaient « db_exec.error »,
        # et une ligne d'erreur ne disait plus laquelle des deux requetes avait echoue.
        log("db_exec_rows.error", rc=out.returncode, err=out.stderr.strip()[:120])
        return -1
    tags = _TAG.findall(out.stdout or "")
    if not tags:
        log("db_exec_rows.tag_absente", extrait=(out.stdout or "").strip()[:80])
        return -1
    return int(tags[-1])

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
    lignes = db_exec_rows(sql)
    # historique (best-effort ; table cotes_bookmakers)
    db_exec(
        "INSERT INTO cotes_bookmakers(id,participation_id,course_id,source,cote,est_cote_ouverture,scraped_at) "
        f"VALUES {','.join(hist)} ON CONFLICT DO NOTHING;"
    )
    if lignes != len(sets):
        # Ecart = quelqu'un d'autre a la main sur la colonne, ou l'UPDATE a echoue.
        log("cotes.ecriture_non_confirmee", source="unibet", course=course_id,
            attendu=len(sets), confirme=lignes)
    return max(lignes, 0)

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
    _watchdog.start()
    with Camoufox(headless=True, geoip=True) as browser:
        page = browser.new_page()
        last_slow = 0.0
        enum_vides = 0
        bt = {}
        imminent = None  # (course_id, url, partants)
        while _run:
            _watchdog.begin_cycle()
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

                    # AUTO-RÉPARATION D'UNE SESSION FIGÉE — même défaut que le
                    # daemon oddschecker, corrigé le 18/08/2026 : la page Camoufox
                    # vit aussi longtemps que le process, et une session figée
                    # (bannière de consentement, redirection géo, session expirée)
                    # ne se rétablit jamais. Le watchdog ne voit rien : aucun cycle
                    # ne dépasse son timeout, le daemon tourne « sainement » en ne
                    # ramenant plus rien. Correctif préventif ici : zeturf alimente
                    # `cote_unibet`, la meilleure couverture hors PMU (88 %), sa
                    # perte silencieuse coûterait la comparaison de marché.
                    if zc:
                        enum_vides = 0
                    else:
                        enum_vides += 1
                        if enum_vides >= ENUM_VIDES_AVANT_RECREATION:
                            log("session.recreate", enum_vides=enum_vides)
                            try:
                                page.close()
                            except Exception as e:
                                log("session.close_error", err=str(e)[:90])
                            page = browser.new_page()
                            enum_vides = 0
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
                    # Seul un cycle lent ARRIVÉ ICI prouve que la chaîne complète
                    # tient (DB joignable, programme énuméré, pages lues). C'est
                    # le seul point du daemon qui a le droit de réarmer la garde
                    # de stérilité : le heartbeat, lui, se pose même en échec.
                    _watchdog.record_progress()
                except Exception as e:
                    log("slow.error", err=str(e)[:140])
                    _exit_si_driver_mort(e)
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
                    _exit_si_driver_mort(e)
            _watchdog.finish_cycle()
            time.sleep(FAST_INTERVAL)
    log("zeturf_daemon.stop")

if __name__ == "__main__":
    main()
