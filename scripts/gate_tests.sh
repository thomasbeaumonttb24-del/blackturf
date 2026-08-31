#!/usr/bin/env bash
# Gate de tests — la SEULE invocation qui exerce les invariants de déploiement.
#
# Pourquoi un script plutôt qu'une ligne de commande dans un handoff : lancée
# depuis l'image (son contexte naturel), la suite ne voit ni les compose, ni le
# Dockerfile, ni nginx.prod.conf — `tests/` est même dockerignoré. Elle sautait
# donc dix invariants de sécurité en affichant « 1380 passed, 10 skipped » et un
# code de retour 0. Depuis `tests/_descripteurs_deploiement.py` ces absences sont
# ROUGES ; ce script est ce qui les fait exister.
#
#   ./scripts/gate_tests.sh              # suite complète
#   ./scripts/gate_tests.sh tests/test_nginx_rate_limits.py -q
#
# À lancer depuis la racine du dépôt (sur le VPS : /opt/blackturf).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${BLACKTURF_IMAGE:-blackturf-api}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image '$IMAGE' introuvable. La construire d'abord, ou poser BLACKTURF_IMAGE." >&2
    exit 2
fi

# Le dépôt ENTIER est monté en lecture seule : c'est ce qui rend les descripteurs
# visibles (y compris nginx/nginx.runtime.conf, gitignoré et présent seulement ici).
# `-w /repo/backend` + BLACKTURF_BACKEND_DIR : les tests remontent d'un cran pour
# trouver la racine, exactement comme dans un checkout de dev.
exec docker run --rm \
    -v "$RACINE:/repo:ro" \
    -w /repo/backend \
    -e BLACKTURF_BACKEND_DIR=/repo/backend \
    -e PYTHONDONTWRITEBYTECODE=1 \
    "$IMAGE" \
    python -m pytest -q -rs "${@:-tests/}"
