#!/usr/bin/env bash
set -euo pipefail

# Entretien Docker : tags de retour périmés, puis cache de build. Les images
# utilisées par un conteneur (même arrêté), les volumes et les données
# PostgreSQL ne sont jamais ciblés.
#
# BT_PRUNE_DRY=1   liste ce qui serait supprimé, sans rien supprimer.
LOCK_FILE=/var/lock/blackturf-docker-builder-prune.lock
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

DRY="${BT_PRUNE_DRY:-0}"

# ── 1. Tags de retour (avant-*, avant_*, retour-*, rollback-*)
# Chaque déploiement tague les cinq images (~3 Go chacune) avant de
# reconstruire, et rien ne les retirait : le 14/09/2026, 95 tags tenaient
# ~35 Go et le disque était remonté de 57 % à 81 % en cinq jours.
# Règle : on garde toujours les KEEP plus récents par service, et au-delà on
# retire ceux dont l'image a plus de MAX_AGE_DAYS jours.
KEEP=5
MAX_AGE_DAYS=7
LIMITE=$(( $(date +%s) - MAX_AGE_DAYS * 86400 ))

EN_SERVICE=$(docker ps -aq | xargs -r docker inspect --format '{{.Image}}' \
  | sed 's/^sha256://' | cut -c1-12 | sort -u)

retires=0
for repo in $(docker images --format '{{.Repository}}' | grep -E '^blackturf-' | sort -u); do
  rang=0
  # `docker images` sort du plus récent au plus ancien.
  while IFS=$'\t' read -r tag id cree; do
    rang=$((rang + 1))
    [ "$rang" -le "$KEEP" ] && continue
    echo "$EN_SERVICE" | grep -qx "$id" && continue
    ts=$(date -d "$(echo "$cree" | awk '{print $1" "$2" "$3}')" +%s 2>/dev/null || echo "")
    [ -z "$ts" ] && continue
    [ "$ts" -ge "$LIMITE" ] && continue
    if [ "$DRY" = "1" ]; then
      echo "(a blanc) retirerait ${repo}:${tag} ${id} ${cree}"
    else
      docker rmi "${repo}:${tag}" >/dev/null 2>&1 && retires=$((retires + 1)) || true
    fi
  done < <(docker images "$repo" --format '{{.Tag}}	{{.ID}}	{{.CreatedAt}}' \
             | grep -E '^(avant|retour|rollback)')
done
echo "$(date -Is) tags de retour retires : ${retires}"

[ "$DRY" = "1" ] && exit 0

# ── 2. Cache de build
# Le filtre d'âge seul ne suffit PAS. Chaque build rafraîchit ses entrées de
# cache, si bien qu'un `--filter until=168h` sur un dépôt où l'on déploie
# plusieurs fois par semaine ne trouve jamais rien à supprimer : mesuré le
# 20/08/2026, il a rendu 0 octet alors que le cache pesait 60,7 Go — soit 60 %
# du disque occupé, sur un volume de 150 Go. Il faut donc aussi un PLAFOND DE
# TAILLE, qui lui s'applique quel que soit l'âge des entrées.
#
# 10 Go : de quoi garder le cache des couches lourdes (pip install du backend,
# node_modules du frontend) et donc des redéploiements rapides, sans laisser le
# cache dériver vers plusieurs dizaines de gigas.
/usr/bin/docker builder prune --force --max-used-space 10GB

echo "$(date -Is) cache après purge : $(docker buildx du 2>/dev/null | tail -1)"
echo "$(date -Is) disque : $(df -h / | awk 'NR==2{print $5" utilise, "$4" libres"}')"
