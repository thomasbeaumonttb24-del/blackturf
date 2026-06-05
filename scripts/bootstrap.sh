#!/usr/bin/env bash
# bootstrap.sh — Installe et démarre TOUT BlackTurf en une commande.
#
# Sur ton VPS (Docker installé), une fois le DNS pointé vers ce serveur :
#   ./scripts/bootstrap.sh <domaine> <cle_openweather> <email>
#   ex : ./scripts/bootstrap.sh blackturf.fr ab12cd34... toi@mail.com
#
# Fait : .env (secrets auto) → nginx domaine → certificats HTTPS → base →
#        migrations → modèle de base → API/worker/scraper/frontend → nginx.
# Idempotent : relançable sans casser l'existant.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE="docker compose -f docker-compose.prod.yml"

DOMAIN="${1:-}"
OPENWEATHER="${2:-}"
EMAIL="${3:-}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { echo "[ERREUR] $*" >&2; exit 1; }

[[ -n "$DOMAIN" && -n "$OPENWEATHER" && -n "$EMAIL" ]] || \
  die "Usage: ./scripts/bootstrap.sh <domaine> <cle_openweather> <email>"
command -v docker >/dev/null 2>&1 || die "Docker non installé."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 requis."

# ── 1. .env (secrets auto-générés) ───────────────────────────────────────
log "Génération du .env…"
./scripts/setup_env.sh "$DOMAIN" "$OPENWEATHER" "$EMAIL"

# ── 2. Config nginx pour CE domaine ──────────────────────────────────────
log "Génération de nginx.runtime.conf pour $DOMAIN…"
sed "s/blackturf\.fr/${DOMAIN}/g" nginx/nginx.prod.conf > nginx/nginx.runtime.conf

# ── 3. Vérif DNS (soft) ──────────────────────────────────────────────────
SERVER_IP="$(curl -fsS https://api.ipify.org 2>/dev/null || echo '')"
DNS_IP="$(getent hosts "$DOMAIN" | awk '{print $1; exit}' 2>/dev/null || echo '')"
if [[ -n "$SERVER_IP" && -n "$DNS_IP" && "$SERVER_IP" != "$DNS_IP" ]]; then
  log "⚠ DNS: $DOMAIN → $DNS_IP, mais ce serveur = $SERVER_IP."
  log "  Si le DNS n'est pas encore propagé, les certificats HTTPS échoueront."
  log "  Vérifie que $DOMAIN, www.$DOMAIN et api.$DOMAIN pointent vers $SERVER_IP."
fi

# ── 4. Certificats HTTPS (Let's Encrypt, standalone sur le port 80) ──────
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
if [[ -f "$CERT_PATH" ]]; then
  log "Certificats déjà présents pour $DOMAIN — étape sautée."
else
  log "Obtention des certificats HTTPS (port 80 doit être libre)…"
  docker run --rm -p 80:80 \
    -v /etc/letsencrypt:/etc/letsencrypt \
    certbot/certbot certonly --standalone --non-interactive --agree-tos \
    -m "$EMAIL" \
    -d "$DOMAIN" -d "www.${DOMAIN}" -d "api.${DOMAIN}" \
    || die "Échec certbot. Vérifie le DNS (les 3 domaines → ce serveur) et que le port 80 est libre."
fi

# ── 5. Base + cache ──────────────────────────────────────────────────────
log "Démarrage base de données + cache…"
$COMPOSE up -d db redis
log "Attente que la base soit prête…"
for i in $(seq 1 30); do
  if $COMPOSE exec -T db pg_isready -U blackturf >/dev/null 2>&1; then break; fi
  sleep 2
done

# ── 6. Migrations (inclut 0009 dynamique) ────────────────────────────────
log "Migrations…"
$COMPOSE run --rm --no-deps api alembic -c db/migrations/alembic.ini upgrade head

# ── 7. Modèle de base (best-effort — devient pertinent avec les données) ─
log "Modèle ML de base…"
$COMPOSE run --rm --no-deps api python scripts/seed_model.py || \
  log "  (seed_model ignoré — le modèle s'entraînera quand assez de résultats seront collectés)"

# ── 8. Services applicatifs ──────────────────────────────────────────────
log "Build + démarrage API / worker / scraper / frontend…"
$COMPOSE up -d --build api worker scraper frontend

# ── 9. Nginx (HTTPS) ─────────────────────────────────────────────────────
log "Démarrage nginx (HTTPS)…"
$COMPOSE up -d nginx

# ── 10. Vérification ─────────────────────────────────────────────────────
sleep 5
log "Vérification de l'API…"
if curl -fsS "https://api.${DOMAIN}/api/v1/health" >/dev/null 2>&1; then
  log "✓ API en ligne : https://api.${DOMAIN}"
else
  log "⚠ API pas encore joignable en HTTPS — vérifie 'docker compose -f docker-compose.prod.yml logs api nginx'."
fi

cat <<EOF

============================================================
 BlackTurf démarré.
   Site      : https://${DOMAIN}
   API       : https://api.${DOMAIN}
   Scraper   : actif (mode prudent, sans proxy)

 Étapes suivantes :
   1. Ouvre https://${DOMAIN} et crée ton compte.
   2. Passe-toi admin :
      $COMPOSE exec db psql -U blackturf -d blackturf \\
        -c "UPDATE users SET plan='expert', is_admin=true WHERE email='ton-email';"
   3. Laisse le scraper tourner quelques jours : les pronostics
      deviennent pertinents quand l'historique se remplit.

 Logs scraper : $COMPOSE logs -f scraper
============================================================
EOF
