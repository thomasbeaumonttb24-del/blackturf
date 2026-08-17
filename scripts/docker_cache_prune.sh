#!/usr/bin/env bash
set -euo pipefail

# Entretien hebdomadaire du cache de build uniquement. Les images utilisées,
# conteneurs, volumes et données PostgreSQL ne sont jamais ciblés.
LOCK_FILE=/var/lock/blackturf-docker-builder-prune.lock
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

/usr/bin/docker builder prune --force --filter until=168h
