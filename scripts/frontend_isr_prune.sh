#!/usr/bin/env bash
set -euo pipefail

# Purge du cache ISR du frontend (Next.js), lancée toutes les heures par cron :
#   20 * * * * /opt/blackturf/scripts/frontend_isr_prune.sh >> /var/log/bt-isr-prune.log 2>&1
#
# Pourquoi : chaque fiche course (`/courses/[id]`, revalidate 120 s) et chaque
# page `/resultats/[jour]` visitée est écrite par Next dans la couche inscriptible
# du conteneur (.html + .rsc + .meta + .segments, ~450 Ko par course). Les robots
# parcourent l'archive : ~2,5 Go par jour, sans aucune limite tant que le
# conteneur n'est pas recréé par un déploiement. Le 03/10/2026, 5,2 Go en deux
# jours (70 000 fichiers) — c'était la première cause des alertes disque à 83 %.
#
# Ce qu'on retire : les fichiers générés APRÈS le build (plus récents que
# BUILD_ID) et non réécrits depuis MAX_AGE_MIN minutes. Avec revalidate = 120 s
# ils sont de toute façon périmés : le visiteur suivant aurait déclenché une
# régénération. Fichier absent = Next rend la page à la demande (MISS, 200) puis
# la remet en cache (HIT) — vérifié en production le 03/10/2026.
# Ce qu'on ne touche JAMAIS : les fichiers du build, le reste de /app.
#
# Même règle pour le cache des `fetch` (.next/cache/fetch-cache) : une entrée
# absente est simplement refetchée depuis l'API.
#
# BT_PRUNE_DRY=1   compte ce qui serait retiré, sans rien retirer.
LOCK_FILE=/var/lock/blackturf-isr-prune.lock
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

CONTENEUR=blackturf_frontend
MAX_AGE_MIN="${BT_ISR_MAX_AGE_MIN:-720}"
DRY="${BT_PRUNE_DRY:-0}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTENEUR"; then
  echo "$(date -Is) ${CONTENEUR} absent, rien à faire"
  exit 0
fi

# Le script tourne DANS le conteneur (utilisateur nextjs, propriétaire des
# fichiers). `-mmin +N` et `-newer` : busybox find les connaît.
docker exec -i -e MAX_AGE_MIN="$MAX_AGE_MIN" -e DRY="$DRY" "$CONTENEUR" sh -s <<'EOF'
set -eu
REF=/app/.next/BUILD_ID
[ -f "$REF" ] || { echo "BUILD_ID absent, abandon"; exit 0; }
APP=/app/.next/server/app
CIBLES=""
for d in "$APP/courses" "$APP/resultats" /app/.next/cache/fetch-cache; do
  [ -d "$d" ] && CIBLES="$CIBLES $d"
done
[ -n "$CIBLES" ] || exit 0

octets=$(find $CIBLES -type f -newer "$REF" -mmin +"$MAX_AGE_MIN" -exec stat -c %s {} + 2>/dev/null \
  | awk '{s+=$1} END{printf "%.0f", s}')
n=$(find $CIBLES -type f -newer "$REF" -mmin +"$MAX_AGE_MIN" 2>/dev/null | wc -l)
if [ "$DRY" = "1" ]; then
  echo "(a blanc) retirerait $n fichiers, $((octets / 1048576)) Mo"
  exit 0
fi
find $CIBLES -type f -newer "$REF" -mmin +"$MAX_AGE_MIN" -delete 2>/dev/null || true
# Répertoires `.segments` restés vides : seulement si la page elle-même (.html)
# n'existe plus, qu'ils ne contiennent plus aucun fichier et qu'ils n'ont pas
# bougé depuis 10 min (Next n'est donc pas en train d'y écrire).
for d in "$APP"/courses/*.segments "$APP"/resultats/*.segments; do
  [ -d "$d" ] || continue
  [ -e "${d%.segments}.html" ] && continue
  [ -n "$(find "$d" -type f | head -1)" ] && continue
  [ -n "$(find "$d" -maxdepth 0 -mmin -10)" ] && continue
  rm -rf "$d"
done
echo "retires : $n fichiers, $((octets / 1048576)) Mo"
EOF
echo "$(date -Is) disque : $(df -h / | awk 'NR==2{print $5" utilise, "$4" libres"}')"
