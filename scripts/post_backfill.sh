#!/bin/bash
exec >> /opt/blackturf/backups/pipeline.log 2>&1
echo "=== $(date) PIPELINE START : attente fin bt_backfill ==="
docker wait bt_backfill
echo "=== $(date) backfill termine -> rejeu ELO ==="
docker run --rm --network blackturf_default --env-file /tmp/bt.env -v /opt/blackturf/backend/scripts:/sc blackturf-worker sh -c "cd /app && PYTHONPATH=/app python /sc/elo_rejeu.py"
echo "=== $(date) recompute features_ml ==="
docker run --rm --network blackturf_default --env-file /tmp/bt.env blackturf-worker sh -c "cd /app && PYTHONPATH=/app python scripts/force_recompute_features.py"
echo "=== $(date) PIPELINE_DONE — retrain via nightly 2h UTC sur donnees propres ==="
