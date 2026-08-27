#!/usr/bin/env python3
"""
Daemon cotes GenyBet → BlackTurf (colonne cote_geny, = les cotes de l'opérateur Geny).

GenyBet est protégé par Cloudflare → chaque page nécessite un solve_cloudflare via
scrapling.StealthyFetcher (Chrome réel, ~15-25 s). Impossible de faire du 5 s live
(re-challenge). On rafraîchit donc en boucle LENTE uniquement (SLOW_INTERVAL), et on
ne fetch QUE les pages des courses imminentes (fenêtre IMMINENT_H heures) pour borner
le coût des CF-solves.

Énumération (1 seul fetch/cycle) : la timeline du programme donne, par course, son id
GenyBet, son n° de course et son heure de départ — mais NI l'hippodrome NI le n° de
réunion. Elle ne sert donc qu'à décider quelles pages fetcher. L'appariement BlackTurf
se fait ensuite sur le <h1> de la page course (« R5 - Pornichet-La Baule ») : le n° de
réunion GenyBet est celui du PMU, donc RxCy identifie la course sans ambiguïté, et
l'hippodrome sert de seconde ceinture.

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
from zeturf_live_daemon import db_exec, db_exec_rows, norm, load_blackturf, log  # helpers partagés
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

# Les courses ETRANGERES prefixent le pays : « USA - R6 - Saratoga », quand une
# reunion francaise donne « R5 - Pornichet-La Baule ». Ancrer sur le debut du <h1>
# rejetait donc toutes les courses etrangeres — 96 sautees en trois heures.
_H1_REUNION = re.compile(r"<h1[^>]*>[^<]*?R(\d+)\s*-\s*([^<]+)</h1>")


def read_course(gid: str) -> tuple[dict[int, float], int | None, str]:
    """Page course GenyBet → ({numero: cote_gagnant}, n° réunion, hippodrome normalisé).

    Le <h1> de la page porte « R5 - Pornichet-La Baule » : le numéro de réunion
    GenyBet est celui du PMU, donc RxCy identifie la course SANS ambiguïté. C'est
    la seule identification fiable disponible — la timeline du programme ne donne
    ni hippodrome ni n° de réunion. Marché partiel toléré.
    """
    html = fetch_html(COURSE.format(id=gid))
    if not html:
        return {}, None, ""
    m = _H1_REUNION.search(html)
    rnum = int(m.group(1)) if m else None
    hippo = norm(m.group(2)) if m else ""
    cotes: dict[int, float] = {}
    # découpe par ligne partant pour éviter le cross-match
    for blk in re.split(r'(?=id="partant-\d+")', html):
        mn = re.match(r'id="partant-(\d+)"', blk)
        if not mn:
            continue
        num = int(mn.group(1))
        # La cote appartient à la LIGNE du partant : on borne au premier </tr>.
        # Sans cette borne, le bloc s'étend jusqu'au partant suivant et `re.search`
        # repart sur le `img-cote` d'un AUTRE cheval dès que celui-ci n'a pas de
        # cote au format attendu — la cote du voisin était alors écrite ici.
        ligne = blk.split("</tr>", 1)[0]
        # Décimale OPTIONNELLE : GenyBet affiche « 7.4 » sous 10 mais « 12 », « 15 »,
        # « 126 » au-dessus. L'ancien motif exigeait `[.,]\d` et jetait donc EN SILENCE
        # toute cote >= 10 : sur 476 479 lignes d'historique geny, le maximum relevé
        # était 9,9 et pas une seule valeur au-dessus de 10, quand unibet en compte
        # 1,7 million. La source ne livrait que les favoris, décalés d'un cheval.
        mc = re.search(r'img-cote[^>]*>\s*(\d{1,3}(?:[.,]\d)?)\s*<', ligne)
        if mc:
            cotes[num] = float(mc.group(1).replace(",", "."))
    return cotes, rnum, hippo

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
    lignes = db_exec_rows(
        f"UPDATE participations SET cote_geny = CASE {' '.join(sets)} ELSE cote_geny END "
        f"WHERE participation_id IN ({ids});"
    )
    db_exec(
        "INSERT INTO cotes_bookmakers(id,participation_id,course_id,source,cote,est_cote_ouverture,scraped_at) "
        f"VALUES {','.join(hist)} ON CONFLICT DO NOTHING;"
    )
    if lignes != len(sets):
        # On rendait len(sets) : le nombre de clauses CONSTRUITES. Le journal affichait
        # donc « wrote=3 » alors que zero ligne bougeait. Ce que la base confirme fait foi.
        log("cotes.ecriture_non_confirmee", source="geny", course=course_id,
            attendu=len(sets), confirme=lignes)
    return max(lignes, 0)

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
                # Pré-filtre BON MARCHÉ : au moins UNE course BlackTurf porte ce numéro
                # à cette heure. Il ne sert qu'à éviter un solve Cloudflare inutile — il ne
                # DÉSIGNE PLUS la course (voir l'appariement autoritaire juste en dessous).
                if not any(c["cnum"] == g["cnum"] and c.get("dt_obj")
                           and abs((c["dt_obj"] - g["dt_utc"]).total_seconds()) <= 14 * 60
                           for c in bt.values()):
                    continue

                cotes, rnum, hippo_geny = read_course(g["id"])

                # Appariement AUTORITAIRE sur R+C lus dans le <h1> de la page course.
                # L'ancien appariement ne comparait QUE le n° de course et l'heure (±14 min)
                # et retenait le PREMIER dict qui passait — l'hippodrome n'était jamais
                # comparé, malgré ce que promet l'en-tête de ce module. Le 26/08/2026, trois
                # paires Vincennes/Gelsenkirchen partageaient le même Cx à moins de 14 min :
                # les cotes allemandes ont été écrites sur les partants français (corrélation
                # geny↔cote PMU de -0,13 sur 26082026R2C7, quand unibet était à +0,85).
                if rnum is None:
                    log("genybet.reunion_illisible", geny_id=g["id"], cnum=g["cnum"])
                    continue
                suffixe = f"R{rnum}C{g['cnum']}"
                cid = None
                for bcid, c in bt.items():
                    # L'heure reste exigée : `bt` contient aujourd'hui ET demain, deux
                    # journées peuvent porter le même RxCy.
                    if not bcid.endswith(suffixe) or not c.get("dt_obj"):
                        continue
                    if abs((c["dt_obj"] - g["dt_utc"]).total_seconds()) > 14 * 60:
                        continue
                    # Seconde ceinture, comme le daemon ZEturf : l'hippodrome doit
                    # concorder. Un RxCy qui colle avec un hippodrome qui ne colle pas
                    # signale une numérotation décalée, pas un appariement.
                    if hippo_geny and c["hippo"] and not (
                            c["hippo"] in hippo_geny or hippo_geny in c["hippo"]):
                        log("genybet.hippodrome_discordant", course=bcid,
                            geny=hippo_geny[:24], blackturf=c["hippo"][:24])
                        continue
                    cid = bcid
                    break
                if not cid:
                    log("genybet.sans_correspondance", geny_id=g["id"], suffixe=suffixe,
                        hippo=hippo_geny[:24])
                    continue
                matched += 1
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
