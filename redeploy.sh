#!/bin/bash
set -e
cd /opt/blackturf
echo "=== rebuild api (nouvel env.py) ==="
docker compose -f docker-compose.prod.yml build api
echo "=== bootstrap ==="
# E-mail Let's Encrypt et cle OpenWeather lus dans l'environnement : le depot est public.
bash scripts/bootstrap.sh blackturf.fr "${CERTBOT_EMAIL:?CERTBOT_EMAIL manquant}" "${OPENWEATHER_API_KEY:-}"
echo "=== REDEPLOY DONE ==="
