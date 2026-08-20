#!/usr/bin/env bash
set -euo pipefail

# Entretien du cache de build uniquement. Les images utilisées, conteneurs,
# volumes et données PostgreSQL ne sont jamais ciblés.
#
# Le filtre d'âge seul ne suffit PAS. Chaque build rafraîchit ses entrées de
# cache, si bien qu'un `--filter until=168h` sur un dépôt où l'on déploie
# plusieurs fois par semaine ne trouve jamais rien à supprimer : mesuré le
# 20/08/2026, il a rendu 0 octet alors que le cache pesait 60,7 Go — soit 60 %
# du disque occupé, sur un volume de 150 Go. Il faut donc aussi un PLAFOND DE
# TAILLE, qui lui s'applique quel que soit l'âge des entrées.
LOCK_FILE=/var/lock/blackturf-docker-builder-prune.lock
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

# 10 Go : de quoi garder le cache des couches lourdes (pip install du backend,
# node_modules du frontend) et donc des redéploiements rapides, sans laisser le
# cache dériver vers plusieurs dizaines de gigas.
/usr/bin/docker builder prune --force --max-used-space 10GB

echo "$(date -Is) cache après purge : $(docker buildx du 2>/dev/null | tail -1)"
