#!/bin/bash
set -euo pipefail
DIR=/opt/blackturf/backups
mkdir -p "$DIR"
TS=$(date +%Y%m%d_%H%M%S)
FILE="$DIR/blackturf_$TS.sql.gz"
docker exec blackturf_db pg_dump -U blackturf -d blackturf --no-owner | gzip > "$FILE"
if [ ! -s "$FILE" ]; then echo "BACKUP FAILED vide"; rm -f "$FILE"; exit 1; fi
ls -1t "$DIR"/blackturf_*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "OK $FILE ($(du -h "$FILE" | cut -f1))"
