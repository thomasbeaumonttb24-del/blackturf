#!/usr/bin/env python3
"""D'où viennent les visiteurs et les payeurs de blackturf.fr ?

Deux sources, deux questions :

  · journaux nginx (30 jours, cf. deploy/logrotate) → pays des VISITEURS ;
  · Stripe (débits)                                  → pays des CARTES qui paient,
                                                       et des cartes refusées.

Le site n'embarque aucun outil d'audience : le journal nginx est la seule trace
des visites. Il contient l'IP réelle du client (pas de CDN devant nginx), qu'on
géolocalise avec la base libre DB-IP « country lite » (CC-BY 4.0, téléchargée une
fois et mise en cache). Aucune dépendance hors bibliothèque standard pour cette
partie : elle se lance directement sur l'hôte.

Ce qu'on compte comme visite humaine : une page HTML servie (GET, statut 2xx/3xx),
hors /api, /_next, /ws et fichiers statiques, par un navigateur dont l'User-Agent
ne se déclare pas robot. Les robots sont comptés à part, par pays : un gros volume
« africain » fait de scanners n'appelle pas la même réponse qu'un vrai public.

Usage sur le VPS :

    # Visiteurs (sur l'hôte, depuis /opt/blackturf)
    python3 backend/scripts/analyse_pays_visiteurs.py

    # Payeurs (dans le conteneur api, qui a la clé et la bibliothèque Stripe)
    docker exec -i blackturf_api python - --stripe < backend/scripts/analyse_pays_visiteurs.py

Options : --logs DIR (défaut /opt/blackturf/nginx/logs), --top N (défaut 25).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import io
import ipaddress
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ─── Géographie ────────────────────────────────────────────────────────────

CONTINENTS = {
    "Afrique": (
        "DZ AO BJ BW BF BI CV CM CF TD KM CD CG CI DJ EG GQ ER SZ ET GA GM GH GN GW "
        "KE LS LR LY MG MW ML MR MU YT MA MZ NA NE NG RE RW SH ST SN SC SL SO ZA SS "
        "SD TZ TG TN UG EH ZM ZW"
    ),
    "Europe": (
        "AL AD AT BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR GG HU IS IE IM IT JE "
        "XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB VA AX"
    ),
    "Amérique du Nord": (
        "US CA MX GT BZ SV HN NI CR PA CU DO HT JM PR BS BB TT GP MQ BL MF PM GL AG "
        "DM GD KN LC VC AW CW SX KY BM TC VG VI AI MS"
    ),
    "Amérique du Sud": "AR BO BR CL CO EC GY PY PE SR UY VE GF FK",
    "Asie / Moyen-Orient": (
        "AF AM AZ BH BD BT BN KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY "
        "MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE"
    ),
    "Océanie": "AU NZ NC PF WF FJ PG VU SB WS TO KI FM MH NR PW TV",
}
CONTINENT = {cc: nom for nom, codes in CONTINENTS.items() for cc in codes.split()}

NOMS = {
    "FR": "France", "BE": "Belgique", "CH": "Suisse", "LU": "Luxembourg",
    "MC": "Monaco", "CA": "Canada", "US": "États-Unis", "GB": "Royaume-Uni",
    "DE": "Allemagne", "ES": "Espagne", "IT": "Italie", "PT": "Portugal",
    "NL": "Pays-Bas", "IE": "Irlande", "RU": "Russie", "UA": "Ukraine",
    "PL": "Pologne", "RO": "Roumanie", "SE": "Suède", "FI": "Finlande",
    "CI": "Côte d'Ivoire", "SN": "Sénégal", "CM": "Cameroun", "ML": "Mali",
    "BF": "Burkina Faso", "BJ": "Bénin", "TG": "Togo", "NE": "Niger",
    "GN": "Guinée", "GA": "Gabon", "CG": "Congo", "CD": "RD Congo",
    "MG": "Madagascar", "TD": "Tchad", "CF": "Centrafrique", "DJ": "Djibouti",
    "MA": "Maroc", "DZ": "Algérie", "TN": "Tunisie", "EG": "Égypte",
    "MU": "Maurice", "RE": "La Réunion", "NG": "Nigeria", "GH": "Ghana",
    "KE": "Kenya", "ZA": "Afrique du Sud", "MR": "Mauritanie", "BI": "Burundi",
    "RW": "Rwanda", "GP": "Guadeloupe", "MQ": "Martinique", "GF": "Guyane",
    "NC": "Nouvelle-Calédonie", "PF": "Polynésie fr.", "YT": "Mayotte",
    "CN": "Chine", "IN": "Inde", "SG": "Singapour", "HK": "Hong Kong",
    "JP": "Japon", "KR": "Corée du Sud", "VN": "Viêt Nam", "BR": "Brésil",
    "TR": "Turquie", "IL": "Israël", "AE": "Émirats", "AU": "Australie",
    "??": "Inconnu",
}

# Pays où le français est langue officielle ou d'usage courant.
FRANCOPHONES = set(
    ["FR", "BE", "CH", "LU", "MC", "CA", "CI", "SN", "CM", "ML", "BF", "BJ", "TG", "NE", "GN", "GA", "CG", "CD", "MG", "TD", "CF", "DJ", "MA", "DZ", "TN", "MU", "RE", "GP", "MQ", "GF", "NC", "PF", "YT", "BI", "RW", "KM", "SC", "HT", "MR", "PM", "BL", "MF", "WF"]
)


def nom(cc: str) -> str:
    return NOMS.get(cc, cc)


# ─── Base IP → pays (DB-IP lite) ───────────────────────────────────────────

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "blackturf"


def _telecharger_base() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    auj = datetime.now().date()
    mois = [(auj.year, auj.month)]
    mois.append((auj.year - 1, 12) if auj.month == 1 else (auj.year, auj.month - 1))
    for a, m in mois:
        cible = CACHE / f"dbip-country-lite-{a}-{m:02d}.csv.gz"
        if cible.exists() and cible.stat().st_size > 1_000_000:
            return cible
        url = f"https://download.db-ip.com/free/dbip-country-lite-{a}-{m:02d}.csv.gz"
        try:
            print(f"Téléchargement de la base IP→pays : {url}", file=sys.stderr)
            with urllib.request.urlopen(url, timeout=60) as r:
                cible.write_bytes(r.read())
            return cible
        except OSError as e:  # mois pas encore publié → mois précédent
            print(f"  indisponible ({e})", file=sys.stderr)
    sys.exit("Impossible de récupérer la base DB-IP (réseau ?).")


class Geo:
    def __init__(self, chemin: Path):
        # Plages triées par début, séparées v4/v6 (entiers non comparables entre eux).
        self.debuts: dict[int, list[int]] = {4: [], 6: []}
        self.fins: dict[int, list[int]] = {4: [], 6: []}
        self.pays: dict[int, list[str]] = {4: [], 6: []}
        with gzip.open(chemin, "rt", newline="") as f:
            for debut, fin, cc in csv.reader(f):
                d = ipaddress.ip_address(debut)
                v = d.version
                self.debuts[v].append(int(d))
                self.fins[v].append(int(ipaddress.ip_address(fin)))
                self.pays[v].append(cc)
        for v in (4, 6):  # DB-IP est trié, mais la recherche dichotomique l'exige
            if self.debuts[v] != sorted(self.debuts[v]):
                trie = sorted(zip(self.debuts[v], self.fins[v], self.pays[v]))
                self.debuts[v], self.fins[v], self.pays[v] = map(list, zip(*trie))
        self._memo: dict[str, str] = {}

    def __call__(self, ip: str) -> str:
        if ip in self._memo:
            return self._memo[ip]
        cc = "??"
        try:
            a = ipaddress.ip_address(ip)
            v, n = a.version, int(a)
            i = bisect.bisect_right(self.debuts[v], n) - 1
            if i >= 0 and n <= self.fins[v][i]:
                cc = self.pays[v][i]
        except ValueError:
            pass
        if cc == "ZZ":
            cc = "??"
        self._memo[ip] = cc
        return cc


# ─── Journaux nginx ────────────────────────────────────────────────────────

# log_format main '$remote_addr - [$time_local] "$request" $status $body_bytes_sent "$http_user_agent"'
LIGNE = re.compile(
    r'^(?P<ip>\S+) - (?:\S+ )?\[(?P<t>[^\]]+)\] "(?P<req>[^"]*)" (?P<st>\d{3}) \S+'
    r'(?: "[^"]*")? "(?P<ua>[^"]*)"'
)
ROBOT = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|httpx|aiohttp|go-http|java/|okhttp|"
    r"scrapy|headless|phantom|axios|node-fetch|libwww|zgrab|masscan|nmap|nuclei|"
    r"censys|semrush|ahrefs|mj12|dotbot|petal|bytespider|gptbot|claude|facebookexternal|"
    r"preview|monitor|uptime|lighthouse|^-?$",
    re.IGNORECASE,
)
STATIQUE = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|map|txt|xml|json|webmanifest)$",
    re.IGNORECASE,
)
EXCLUS = ("/api/", "/_next/", "/ws", "/visuels/", "/favicon", "/icons/", "/manifest")
# Sondes classiques de scanners : jamais un visiteur.
SONDE = re.compile(r"wp-|\.php|\.env|\.git|cgi-bin|phpmyadmin|/admin\.|\.asp", re.IGNORECASE)


def lire_journaux(dossier: Path):
    fichiers = sorted(dossier.glob("access.log*"))
    if not fichiers:
        sys.exit(f"Aucun access.log* dans {dossier}")
    for f in fichiers:
        ouvrir = gzip.open if f.suffix == ".gz" else open
        with ouvrir(f, "rt", errors="replace") as h:
            yield from h


def analyser_visites(dossier: Path, top: int) -> None:
    geo = Geo(_telecharger_base())

    pages = Counter()                     # pages vues humaines par pays
    ips = defaultdict(set)                # IP humaines distinctes par pays
    jours_ip = defaultdict(set)           # (jour, ip) → visites journalières
    robots = Counter()                    # requêtes robots/sondes par pays
    pages_par_pays = defaultdict(Counter)
    mobile = Counter()
    t_min = t_max = None
    lignes = illisibles = 0

    for brut in lire_journaux(dossier):
        lignes += 1
        m = LIGNE.match(brut)
        if not m:
            illisibles += 1
            continue
        req = m["req"].split(" ")
        if len(req) < 2:
            continue
        methode, chemin = req[0], req[1].split("?", 1)[0]
        ip, ua, st = m["ip"], m["ua"], int(m["st"])
        try:
            t = datetime.strptime(m["t"], "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            continue
        t_min = t if t_min is None or t < t_min else t_min
        t_max = t if t_max is None or t > t_max else t_max

        cc = geo(ip)
        if ROBOT.search(ua) or SONDE.search(chemin):
            robots[cc] += 1
            continue
        if methode != "GET" or not (200 <= st < 400):
            continue
        if chemin.startswith(EXCLUS) or STATIQUE.search(chemin):
            continue

        pages[cc] += 1
        ips[cc].add(ip)
        jours_ip[cc].add((t.date(), ip))
        pages_par_pays[cc][chemin] += 1
        if re.search(r"Mobi|Android|iPhone", ua):
            mobile[cc] += 1

    if not pages:
        sys.exit("Aucune page humaine trouvée — format du journal inattendu ?")

    tot_pages = sum(pages.values())
    tot_ips = sum(len(s) for s in ips.values())
    tot_visites = sum(len(s) for s in jours_ip.values())
    tot_robots = sum(robots.values())

    print(f"\n=== VISITEURS HUMAINS — du {t_min:%d/%m/%Y} au {t_max:%d/%m/%Y} ===")
    print(f"{lignes:,} lignes lues ({illisibles:,} illisibles), "
          f"{tot_pages:,} pages vues, {tot_ips:,} IP distinctes, "
          f"{tot_visites:,} visites (IP × jour), {tot_robots:,} requêtes robots/sondes\n")

    print(f"{'Pays':<22}{'Visiteurs':>10}{'%':>7}{'Visites':>9}{'Pages':>9}{'%':>7}"
          f"{'P/visite':>9}{'Mobile':>8}")
    for cc, _ in sorted(ips.items(), key=lambda kv: -len(kv[1]))[:top]:
        n_ip, n_v, n_p = len(ips[cc]), len(jours_ip[cc]), pages[cc]
        print(f"{nom(cc)[:21]:<22}{n_ip:>10,}{100*n_ip/tot_ips:>6.1f}%{n_v:>9,}"
              f"{n_p:>9,}{100*n_p/tot_pages:>6.1f}%{n_p/max(n_v,1):>9.1f}"
              f"{100*mobile[cc]/max(n_p,1):>7.0f}%")

    print("\n--- Par continent (visiteurs) ---")
    cont = Counter()
    cont_p = Counter()
    for cc, s in ips.items():
        cont[CONTINENT.get(cc, "Inconnu")] += len(s)
        cont_p[CONTINENT.get(cc, "Inconnu")] += pages[cc]
    for c, n in cont.most_common():
        print(f"{c:<22}{n:>10,}{100*n/tot_ips:>6.1f}%   pages {100*cont_p[c]/tot_pages:5.1f}%")

    fr = sum(len(ips[cc]) for cc in ips if cc in FRANCOPHONES)
    afr_franco = sum(len(ips[cc]) for cc in ips
                     if cc in FRANCOPHONES and CONTINENT.get(cc) == "Afrique")
    print(f"\nPays francophones : {100*fr/tot_ips:.1f}% des visiteurs "
          f"(dont Afrique francophone : {100*afr_franco/tot_ips:.1f}%)")

    print("\n--- Pages les plus vues, 5 premiers pays ---")
    for cc, _ in sorted(ips.items(), key=lambda kv: -len(kv[1]))[:5]:
        tops = ", ".join(f"{p} ({n})" for p, n in pages_par_pays[cc].most_common(5))
        print(f"{nom(cc)}: {tops}")

    print("\n--- Robots / scanners par pays (requêtes, exclues ci-dessus) ---")
    for cc, n in robots.most_common(10):
        print(f"{nom(cc)[:21]:<22}{n:>10,}{100*n/max(tot_robots,1):>6.1f}%")


# ─── Stripe ────────────────────────────────────────────────────────────────

def analyser_stripe(top: int) -> None:
    import stripe  # présent dans le conteneur api uniquement

    cle = os.environ.get("STRIPE_SECRET_KEY", "")
    if not cle:
        sys.exit("STRIPE_SECRET_KEY absent — lancer dans le conteneur blackturf_api.")
    stripe.api_key = cle

    ok_n, ok_eur, ok_clients = Counter(), Counter(), defaultdict(set)
    ko_n, ko_raisons = Counter(), defaultdict(Counter)
    marques = defaultdict(Counter)

    for ch in stripe.Charge.list(limit=100).auto_paging_iter():
        carte = (ch.get("payment_method_details") or {}).get("card") or {}
        adr = ((ch.get("billing_details") or {}).get("address") or {})
        cc = carte.get("country") or adr.get("country") or "??"
        if ch.get("status") == "succeeded" and ch.get("paid"):
            ok_n[cc] += 1
            ok_eur[cc] += (ch.get("amount", 0) - ch.get("amount_refunded", 0)) / 100
            ok_clients[cc].add(ch.get("customer") or ch.get("id"))
            marques[cc][carte.get("brand") or "?"] += 1
        elif ch.get("status") == "failed":
            ko_n[cc] += 1
            ko_raisons[cc][ch.get("failure_code") or ch.get("outcome", {}).get("reason") or "?"] += 1

    tot_cli = sum(len(s) for s in ok_clients.values()) or 1
    tot_eur = sum(ok_eur.values()) or 1
    print("\n=== PAYEURS STRIPE (pays de la carte) — depuis l'ouverture du compte ===")
    print(f"{'Pays':<22}{'Clients':>8}{'%':>7}{'Paiements':>10}{'Net €':>10}{'%':>7}"
          f"{'Refusés':>9}{'Taux refus':>11}")
    pays = set(ok_n) | set(ko_n)
    for cc in sorted(pays, key=lambda c: (-len(ok_clients[c]), -ko_n[c]))[:top]:
        n_cli = len(ok_clients[cc])
        essais = ok_n[cc] + ko_n[cc]
        print(f"{nom(cc)[:21]:<22}{n_cli:>8}{100*n_cli/tot_cli:>6.1f}%{ok_n[cc]:>10}"
              f"{ok_eur[cc]:>10.2f}{100*ok_eur[cc]/tot_eur:>6.1f}%{ko_n[cc]:>9}"
              f"{100*ko_n[cc]/max(essais,1):>10.0f}%")

    print("\n--- Motifs de refus par pays ---")
    for cc, n in ko_n.most_common(10):
        print(f"{nom(cc)}: " + ", ".join(f"{r} ({k})" for r, k in ko_raisons[cc].most_common(4)))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--logs", default="/opt/blackturf/nginx/logs")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--stripe", action="store_true", help="analyser les payeurs Stripe")
    a = p.parse_args()
    # Sortie lisible même quand stdout est un tube (docker exec, | tee).
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.stripe:
        analyser_stripe(a.top)
    else:
        analyser_visites(Path(a.logs), a.top)


if __name__ == "__main__":
    main()
