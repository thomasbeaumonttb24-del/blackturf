"""Healthcheck du conteneur scraper — détecte un daemon GELÉ.

Le mode de panne réel (2026-08-11 → 2026-08-16) n'était pas un crash mais un
gel : le process restait vivant, `docker ps` le montrait « Up 3 weeks », et
personne n'a rien vu pendant 4 j 16 h. Un healthcheck « le process tourne » est
donc inutile ici — on vérifie que le daemon PRODUIT quelque chose, via le
heartbeat écrit à la fin de chaque cycle par scraper.orchestrator.

Le kill/restart est assuré par le watchdog thread de l'orchestrateur (Docker ne
redémarre PAS un conteneur unhealthy) ; ce script sert à rendre le gel visible
dans `docker ps` et exploitable par une alerte.

Sortie : 0 = sain, 1 = gelé ou heartbeat absent.
"""
import os
import sys
import time

HEARTBEAT_PATH = os.getenv("BT_SCRAPER_HEARTBEAT", "/app/data/scraper_heartbeat")
# Pire cas légitime ≈ 30 min (timeout cycle 20 + grâce watchdog 2 + redémarrage
# + un cycle complet 6). 45 min laisse de la marge sans jamais masquer un gel.
MAX_AGE_S = int(os.getenv("BT_SCRAPER_HEARTBEAT_MAX_AGE", "2700"))


def main() -> int:
    try:
        with open(HEARTBEAT_PATH) as fh:
            last = float(fh.read().strip())
    except (OSError, ValueError) as e:
        print(f"heartbeat illisible ({HEARTBEAT_PATH}): {e}", file=sys.stderr)
        return 1

    age = time.time() - last
    if age > MAX_AGE_S:
        print(f"scraper GELÉ : dernier cycle il y a {int(age)}s (max {MAX_AGE_S}s)",
              file=sys.stderr)
        return 1

    print(f"ok : dernier cycle il y a {int(age)}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
