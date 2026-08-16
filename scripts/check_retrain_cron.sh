#!/usr/bin/env bash
# Rapport quotidien de retrain BlackTurf — lancé par cron sur le VPS à 07:00 Paris.
#
# Pourquoi ce fichier : les infos nécessaires ne vivent pas au même endroit.
#   - `docker logs` n'est accessible que depuis l'HÔTE
#   - la base et la clé Resend ne le sont que depuis le CONTENEUR
# On dépose donc les logs dans un fichier temporaire, qu'on monte dans un
# conteneur api éphémère chargé d'analyser et d'envoyer le rapport.
#
# Installation : voir la ligne crontab en bas de ce fichier.
set -euo pipefail

cd /opt/blackturf

LOGS=$(mktemp /tmp/bt_worker_logs.XXXXXX)
trap 'rm -f "$LOGS"' EXIT

# 12 h couvre largement le retrain de 02:00 UTC, même en cas de démarrage tardif.
docker logs blackturf_worker --since 12h > "$LOGS" 2>&1 || true
# mktemp crée en 0600/root ; le conteneur tourne en 1001:1001 et ne pourrait pas
# lire le fichier monté (le rapport tomberait en « logs indisponibles »).
chmod 0644 "$LOGS"

# Le script est monté depuis l'hôte plutôt que bâké dans l'image : il peut ainsi
# être corrigé sans rebuild, et le cron lit de toute façon le même fichier.
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps \
  -e BT_WORKER_LOGS_FILE=/tmp/worker_logs.txt \
  -v "$LOGS:/tmp/worker_logs.txt:ro" \
  -v /opt/blackturf/backend/scripts/check_retrain_nightly.py:/app/scripts/check_retrain_nightly.py:ro \
  api python -m scripts.check_retrain_nightly

# ─────────────────────────────────────────────────────────────────────────────
# Ligne crontab à installer (07:00 Europe/Paris = 05:00 UTC en été, 06:00 en
# hiver — on fixe 05:00 UTC, l'écart d'une heure est sans importance ici) :
#
#   0 5 * * * /opt/blackturf/scripts/check_retrain_cron.sh >> /var/log/bt-retrain-report.log 2>&1
#
# Installation :
#   chmod +x /opt/blackturf/scripts/check_retrain_cron.sh
#   ( crontab -l 2>/dev/null; echo "0 5 * * * /opt/blackturf/scripts/check_retrain_cron.sh >> /var/log/bt-retrain-report.log 2>&1" ) | crontab -
# ─────────────────────────────────────────────────────────────────────────────
