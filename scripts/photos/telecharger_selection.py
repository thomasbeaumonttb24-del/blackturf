"""Télécharge en 1920 px les photos retenues (scripts/photos/selection.json) et écrit
leurs crédits (auteur, licence, page Commons) dans
frontend/src/lib/photosHippodromes.json, lu par les fiches d'hippodrome."""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "BlackTurfPhotoBot/1.0 (https://blackturf.fr; contact@blackturf.fr)"
DOSSIER = Path("frontend/public/img/hippodromes")


def texte(v):
    return html.unescape(re.sub(r"<[^>]+>", "", v or "")).strip()


def info(titre):
    q = {"action": "query", "titles": titre, "prop": "imageinfo",
         "iiprop": "url|size|user|extmetadata", "iiurlwidth": "1920",
         "format": "json", "formatversion": "2"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["query"]["pages"][0]["imageinfo"][0]


def main():
    selection = json.loads(Path("scripts/photos/selection.json").read_text())
    credits = {}
    for slug, titre in selection.items():
        ii = info(titre)
        meta = ii.get("extmetadata", {})
        auteur = texte(meta.get("Artist", {}).get("value")) or ii.get("user") or "Contributeur Wikimedia Commons"
        req = urllib.request.Request(ii.get("thumburl") or ii["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as r:
            (DOSSIER / f"{slug}.jpg").write_bytes(r.read())
        credits[slug] = {
            "fichier": f"/img/hippodromes/{slug}.webp",
            "auteur": auteur[:120],
            "licence": texte(meta.get("LicenseShortName", {}).get("value")),
            "licence_url": texte(meta.get("LicenseUrl", {}).get("value")),
            "source": ii.get("descriptionurl"),
        }
        print(slug, "ok", credits[slug]["licence"], "|", auteur[:50])
        time.sleep(0.5)
    Path("frontend/src/lib/photosHippodromes.json").write_text(json.dumps(credits, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
