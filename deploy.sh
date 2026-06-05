#!/usr/bin/env bash
# BlackTurf — Zero-downtime deploy script
# Run from /opt/blackturf on Hetzner VPS
# Usage: ./deploy.sh [branch]

set -euo pipefail

BRANCH=${1:-main}
COMPOSE="docker compose -f docker-compose.prod.yml"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { echo "[ERROR] $*" >&2; exit 1; }

cd "$APP_DIR"

# ─── Checks ─────────────────────────────────────────────────
[[ -f .env ]] || die ".env not found. Copy .env.production.template → .env and fill values."
command -v docker >/dev/null 2>&1 || die "docker not installed"
command -v git >/dev/null 2>&1 || die "git not installed"

# ─── Pull latest code ────────────────────────────────────────
log "Pulling $BRANCH..."
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

# ─── Build images ────────────────────────────────────────────
log "Building images..."
$COMPOSE build --no-cache api scraper worker

# ─── Migrate DB ──────────────────────────────────────────────
log "Running migrations..."
$COMPOSE run --rm --no-deps api alembic -c db/migrations/alembic.ini upgrade head

# ─── Rolling restart (API first, then worker, then scraper) ──
log "Restarting API..."
$COMPOSE up -d --no-deps api
sleep 5

# Wait for API health
for i in $(seq 1 12); do
    if $COMPOSE exec -T api curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then
        log "API healthy."
        break
    fi
    [[ $i -eq 12 ]] && die "API failed to become healthy after 60s"
    log "Waiting for API... ($i/12)"
    sleep 5
done

log "Restarting worker..."
$COMPOSE up -d --no-deps worker
sleep 3

log "Restarting scraper..."
$COMPOSE up -d --no-deps scraper
sleep 2

log "Reloading nginx..."
$COMPOSE exec -T nginx nginx -s reload

# ─── Prune old images ────────────────────────────────────────
log "Pruning old images..."
docker image prune -f --filter "until=24h"

# ─── Status ──────────────────────────────────────────────────
log "Deploy complete. Status:"
$COMPOSE ps
