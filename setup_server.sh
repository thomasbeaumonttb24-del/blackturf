#!/usr/bin/env bash
# BlackTurf — Initial VPS setup (Hetzner CX31, Ubuntu 24.04)
# Run once as root: bash setup_server.sh
# Then configure .env and run deploy.sh

set -euo pipefail

APP_DIR="/opt/blackturf"
APP_USER="blackturf"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ─── System packages ─────────────────────────────────────────
log "Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    curl git ufw fail2ban \
    certbot python3-certbot-nginx \
    apt-transport-https ca-certificates gnupg lsb-release

# ─── Docker ──────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable --now docker
fi

# Compose plugin (v2)
if ! docker compose version >/dev/null 2>&1; then
    log "Installing Docker Compose plugin..."
    apt-get install -y docker-compose-plugin
fi

# ─── App user ────────────────────────────────────────────────
if ! id "$APP_USER" >/dev/null 2>&1; then
    log "Creating $APP_USER user..."
    useradd -m -s /bin/bash "$APP_USER"
    usermod -aG docker "$APP_USER"
fi

# ─── App directory ───────────────────────────────────────────
log "Setting up $APP_DIR..."
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

# ─── Firewall ────────────────────────────────────────────────
log "Configuring UFW firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ─── Fail2ban ────────────────────────────────────────────────
log "Configuring fail2ban..."
systemctl enable --now fail2ban

# ─── Swap (2GB for 8GB RAM VPS) ──────────────────────────────
if ! swapon --show | grep -q /swapfile; then
    log "Creating 2GB swapfile..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# ─── Clone repo ──────────────────────────────────────────────
log "Cloning BlackTurf repo to $APP_DIR..."
if [[ ! -d "$APP_DIR/.git" ]]; then
    su - "$APP_USER" -c "git clone https://github.com/YOUR_ORG/blackturf.git $APP_DIR"
else
    log "Repo already present, skipping clone."
fi

# ─── SSL (Let's Encrypt) ─────────────────────────────────────
log "Requesting SSL certificate..."
log "NOTE: Ensure DNS records point to this server BEFORE running certbot."
echo ""
echo "Run manually when DNS is ready:"
echo "  certbot certonly --standalone -d blackturf.fr -d www.blackturf.fr -d api.blackturf.fr --email admin@blackturf.fr --agree-tos --non-interactive"
echo ""

# ─── Done ────────────────────────────────────────────────────
log "Setup complete. Next steps:"
echo "  1. cd $APP_DIR"
echo "  2. cp .env.production.template .env && nano .env  # fill secrets"
echo "  3. Run certbot (see above) when DNS is live"
echo "  4. ./deploy.sh"
