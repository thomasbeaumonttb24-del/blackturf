#!/bin/bash
set -e
cd /opt/blackturf
echo "=== rebuild api (nouvel env.py) ==="
docker compose -f docker-compose.prod.yml build api
echo "=== bootstrap ==="
bash scripts/bootstrap.sh blackturf.fr thomas.beaumont.tb24@gmail.com bacf7fa8536ec39679532bfe1704a62d
echo "=== REDEPLOY DONE ==="
