"""Cherche sur Wikimedia Commons des photos sous licence libre de chaque hippodrome.

Lancé par .github/workflows/photos-hippodromes.yml (les runners GitHub ont internet).
Écrit, pour chaque fiche, jusqu'à 8 candidates en 640 px dans
`frontend/public/img/hippodromes/_candidates/<slug>/` et leurs métadonnées (auteur,
licence, URL d'origine) dans `candidates.json`. Seules les licences CC0, domaine public,
CC BY et CC BY-SA sont retenues ; NC, ND et inconnues sont écartées.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "BlackTurfPhotoBot/1.0 (https://blackturf.fr; contact@blackturf.fr)"
SORTIE = Path("frontend/public/img/hippodromes/_candidates")

RECHERCHES = {
    "vincennes": ["Hippodrome de Vincennes"],
    "paris-longchamp": ["Hippodrome de Longchamp", "ParisLongchamp"],
    "chantilly": ["Hippodrome de Chantilly"],
    "deauville": ["Hippodrome de Deauville-La Touques", "Hippodrome de Deauville"],
    "auteuil": ["Hippodrome d'Auteuil"],
    "saint-cloud": ["Hippodrome de Saint-Cloud"],
    "enghien": ["Hippodrome d'Enghien-Soisy", "Hippodrome d'Enghien"],
    "cagnes-sur-mer": ["Hippodrome de la Côte d'Azur", "Hippodrome de Cagnes-sur-Mer"],
    "maisons-laffitte": ["Hippodrome de Maisons-Laffitte"],
    "vichy": ["Hippodrome de Vichy-Bellerive", "Hippodrome de Vichy"],
    "toulouse": ["Hippodrome de la Cépière", "Hippodrome de Toulouse"],
    "marseille-borely": ["Hippodrome Marseille-Borély", "Hippodrome du parc Borély"],
    "pau": ["Hippodrome de Pau"],
    "compiegne": ["Hippodrome de Compiègne"],
    "cabourg": ["Hippodrome de Cabourg"],
    "le-croise-laroche": ["Hippodrome du Croisé-Laroche"],
    "caen": ["Hippodrome de Caen", "Hippodrome de la Prairie Caen"],
    "lyon-parilly": ["Hippodrome de Parilly", "Hippodrome de Lyon-Parilly"],
    "clairefontaine": ["Hippodrome de Clairefontaine", "Hippodrome de Deauville-Clairefontaine"],
    "nantes": ["Hippodrome du Petit Port", "Hippodrome de Nantes"],
    "bordeaux-le-bouscat": ["Hippodrome du Bouscat", "Hippodrome de Bordeaux-Le Bouscat"],
    "strasbourg": ["Hippodrome de Hoerdt", "Hippodrome de Strasbourg"],
    "laval": ["Hippodrome de Laval", "Hippodrome de Bellevue-la-Forêt"],
    "marseille-vivaux": ["Hippodrome de Pont-de-Vivaux", "Hippodrome Marseille-Vivaux"],
    "le-lion-d-angers": ["Hippodrome du Lion-d'Angers", "Hippodrome de l'Isle-Briand"],
}

LICENCE_OK = re.compile(r"^(cc0|public domain|pd|cc[- ]by(-sa)?[- ]?\d(\.\d)?)", re.I)
LICENCE_KO = re.compile(r"\b(nc|nd)\b", re.I)


def api(params):
    params = {"action": "query", **params, "format": "json", "formatversion": "2"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    for essai in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                corps = r.read()
            return json.loads(corps)
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} : {e.read()[:300]!r}")
            if e.code in (429, 503):
                time.sleep(5 * (essai + 1))
                continue
            raise
        except json.JSONDecodeError:
            print(f"  réponse non JSON : {corps[:200]!r}")
            break
    raise RuntimeError("API Commons injoignable")


def texte(v):
    return html.unescape(re.sub(r"<[^>]+>", "", v or "")).strip()


def fichiers(requete):
    commun = {"prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "640"}
    pages = []
    for gen in (
        {"generator": "categorymembers", "gcmtitle": f"Category:{requete}", "gcmtype": "file", "gcmlimit": "40"},
        {"generator": "search", "gsrsearch": f"{requete} filetype:bitmap", "gsrnamespace": "6", "gsrlimit": "20"},
    ):
        try:
            pages += api({**commun, **gen}).get("query", {}).get("pages", [])
        except Exception as e:  # noqa: BLE001
            print("  erreur API", requete, e)
        time.sleep(0.5)
    return pages


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    tout = {}
    for slug, requetes in RECHERCHES.items():
        vus, retenus = set(), []
        for q in requetes:
            for p in fichiers(q):
                if p["title"] in vus or not p.get("imageinfo"):
                    continue
                vus.add(p["title"])
                ii = p["imageinfo"][0]
                meta = ii.get("extmetadata", {})
                lic = texte(meta.get("LicenseShortName", {}).get("value"))
                if ii.get("mime") not in ("image/jpeg", "image/png"):
                    continue
                if ii.get("width", 0) < 1200 or ii["width"] <= ii.get("height", 0):
                    continue
                if not LICENCE_OK.search(lic) or LICENCE_KO.search(lic):
                    continue
                retenus.append({
                    "titre": p["title"],
                    "page": ii.get("descriptionurl"),
                    "original": ii.get("url"),
                    "apercu": ii.get("thumburl"),
                    "largeur": ii.get("width"),
                    "hauteur": ii.get("height"),
                    "auteur": texte(meta.get("Artist", {}).get("value")) or "Auteur inconnu",
                    "licence": lic,
                    "licence_url": texte(meta.get("LicenseUrl", {}).get("value")),
                    "description": texte(meta.get("ImageDescription", {}).get("value"))[:300],
                })
        retenus = retenus[:8]
        dossier = SORTIE / slug
        dossier.mkdir(exist_ok=True)
        for i, c in enumerate(retenus):
            nom = f"{i + 1}.jpg"
            try:
                req = urllib.request.Request(c["apercu"], headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    (dossier / nom).write_bytes(r.read())
                c["fichier"] = nom
            except Exception as e:  # noqa: BLE001
                print("  téléchargement raté", c["titre"], e)
            time.sleep(0.3)
        tout[slug] = retenus
        print(f"{slug}: {len(retenus)} candidate(s)")
    (SORTIE / "candidates.json").write_text(json.dumps(tout, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
