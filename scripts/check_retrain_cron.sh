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

# Les logs sont un CONFORT, pas la source du verdict (celui-ci vient de
# `learning_step_runs`, cf. backend/scripts/check_retrain_nightly.py). Un
# fichier vide — conteneur worker recréé, rotation — n'empêche donc plus rien ;
# on le signale ici pour que la plomberie se répare, et on continue.
if [ ! -s "$LOGS" ]; then
  echo "AVERTISSEMENT : docker logs blackturf_worker n'a rien renvoyé sur 12 h."
fi

# Le script n'est plus monté depuis l'hôte. Il l'était pour pouvoir être corrigé
# sans rebuild, mais son verdict dépend désormais de `ml/learning_steps.py` : un
# fichier hôte plus récent que l'image donnerait un rapport à moitié à jour,
# c'est-à-dire un rapport dont on ne sait plus ce qu'il mesure. Une seule source
# de vérité : l'image déployée.
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps \
  -e BT_WORKER_LOGS_FILE=/tmp/worker_logs.txt \
  -e BT_RAPPORT_CANAL=cron \
  -v "$LOGS:/tmp/worker_logs.txt:ro" \
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
