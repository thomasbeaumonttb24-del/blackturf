#!/usr/bin/env bash
# setup_env.sh — Génère un .env complet avec secrets auto-générés.
# Tu fournis seulement : domaine + clé OpenWeather. Le reste est généré.
#
# Usage :
#   ./scripts/setup_env.sh <domaine> <cle_openweather> [email_admin]
#   ex : ./scripts/setup_env.sh blackturf.fr ab12cd34ef... admin@blackturf.fr
#
# N'écrase PAS un .env existant (sécurité).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

DOMAIN="${1:-}"
OPENWEATHER="${2:-}"          # optionnel — vide = source météo désactivée
ADMIN_EMAIL="${3:-admin@${DOMAIN}}"

[[ -n "$DOMAIN" ]] || { echo "ERREUR: domaine manquant. Usage: ./scripts/setup_env.sh <domaine> [cle_openweather]"; exit 1; }

# Météo optionnelle : sans clé, on désactive la source meteo (jamais de fausse donnée).
DISABLED_SOURCES="racing_post"
if [[ -z "$OPENWEATHER" ]]; then
  DISABLED_SOURCES="racing_post,meteo"
  echo "ℹ Pas de clé OpenWeather → source météo désactivée (ajoutable plus tard)."
fi

if [[ -f "$ENV_FILE" ]]; then
  echo ".env existe déjà — non écrasé. Supprime-le d'abord pour régénérer."
  exit 0
fi

command -v openssl >/dev/null 2>&1 || { echo "ERREUR: openssl requis."; exit 1; }
gen() { openssl rand -hex "$1"; }

PG_PW="$(gen 16)"
REDIS_PW="$(gen 16)"
SECRET_KEY="$(gen 32)"        # 64 hex chars
NEXTAUTH_SECRET="$(gen 32)"

cat > "$ENV_FILE" <<EOF
# Généré par setup_env.sh — NE PAS committer
ENVIRONMENT=production
FRONTEND_URL=https://${DOMAIN}
API_URL=https://api.${DOMAIN}

# PostgreSQL
POSTGRES_USER=blackturf
POSTGRES_PASSWORD=${PG_PW}
POSTGRES_DB=blackturf
DATABASE_URL=postgresql+asyncpg://blackturf:${PG_PW}@db:5432/blackturf
DATABASE_URL_SYNC=postgresql://blackturf:${PG_PW}@db:5432/blackturf

# Redis
REDIS_PASSWORD=${REDIS_PW}
REDIS_URL=redis://:${REDIS_PW}@redis:6379/0

# JWT
SECRET_KEY=${SECRET_KEY}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# Anthropic (optionnel — narration IA ; laisser tel quel si non utilisé)
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

# Stripe (optionnel — paiements ; à remplir plus tard)
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=

# Emails (optionnel)
RESEND_API_KEY=
EMAIL_FROM=noreply@${DOMAIN}
EMAIL_FROM_NAME=BlackTurf

# Météo (REQUIS)
OPENWEATHER_API_KEY=${OPENWEATHER}

# Scraping — démarrage prudent sans proxy
BRIGHTDATA_PROXY=
SCRAPER_INTERVAL=5
SCRAPER_INTERVAL_MULTIPLIER=2.0
SCRAPER_DISABLED_SOURCES=${DISABLED_SOURCES}

# ML
MODELS_PATH=/app/models
MODEL_MIN_AUC=0.60
RETRAIN_HOUR_UTC=2
RETRAIN_EVERY_N_RESULTS=20

# Admin
ADMIN_EMAIL=${ADMIN_EMAIL}

# Frontend
NEXT_PUBLIC_API_URL=https://api.${DOMAIN}
NEXT_PUBLIC_WS_URL=wss://api.${DOMAIN}/ws
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
NEXTAUTH_URL=https://${DOMAIN}

# TLS — chemin des certificats Let's Encrypt (monté dans nginx)
TLS_CERT_DIR=/etc/letsencrypt/live/${DOMAIN}
EOF

chmod 600 "$ENV_FILE"
echo "✓ .env généré pour ${DOMAIN} (secrets aléatoires, permissions 600)."
