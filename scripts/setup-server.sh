#!/bin/bash
# ============================================
# NormaCheck - Installation initiale OVH VPS
# Executer en root sur le VPS: bash setup-server.sh
# ============================================
set -e

DEPLOY_DIR="/opt/normacheck"
DOMAIN="${1:-normacheck.votredomaine.fr}"
GIT_REPO="${2:-git@github.com:AJLeocadie/AJ-first.git}"

echo "========================================="
echo " NormaCheck - Setup OVH VPS"
echo " Domaine: $DOMAIN"
echo " Repo: $GIT_REPO"
echo "========================================="

# ---- 1. System update ----
echo "[1/7] Mise a jour systeme..."
apt-get update && apt-get upgrade -y

# ---- 2. Install Docker ----
echo "[2/7] Installation Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installe: $(docker --version)"
else
    echo "Docker deja installe: $(docker --version)"
fi

# Install Docker Compose plugin if missing
if ! docker compose version &> /dev/null; then
    apt-get install -y docker-compose-plugin
fi

# ---- 3. Install utilities ----
echo "[3/7] Installation utilitaires..."
apt-get install -y git curl ufw fail2ban unattended-upgrades

# ---- 4. Firewall ----
echo "[4/7] Configuration firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
echo "y" | ufw enable
ufw status

# ---- 5. Clone repository ----
echo "[5/7] Clonage du repository..."
if [ -d "$DEPLOY_DIR" ]; then
    echo "  Repertoire $DEPLOY_DIR existe deja, mise a jour..."
    cd "$DEPLOY_DIR"
    git pull origin main
else
    git clone "$GIT_REPO" "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"
fi

# ---- 6. Configure environment ----
echo "[6/7] Configuration environnement..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    # Generate a secure random key
    SECRET_KEY=$(openssl rand -hex 32)
    cat > "$DEPLOY_DIR/.env" << ENVEOF
# NormaCheck - Production Environment
NORMACHECK_ENV=production
NORMACHECK_SECRET_KEY=$SECRET_KEY
NORMACHECK_TOKEN_EXPIRY=28800
NORMACHECK_WORKERS=4
NORMACHECK_MAX_UPLOAD_MB=2000
NORMACHECK_MAX_FILES=50

# Domain (used by nginx config)
DOMAIN_NAME=$DOMAIN

# Supabase (optionnel)
# SUPABASE_URL=
# SUPABASE_KEY=
ENVEOF
    echo "  .env cree avec cle secrete generee"
    echo "  IMPORTANT: editez $DEPLOY_DIR/.env pour personnaliser"
else
    echo "  .env existe deja, conservation"
fi

# Update nginx config with actual domain
sed -i "s/normacheck.votredomaine.fr/$DOMAIN/g" "$DEPLOY_DIR/nginx/conf.d/normacheck.conf"
echo "  Nginx configure pour $DOMAIN"

# ---- 7. SSL Certificate ----
echo "[7/7] Certificat SSL Let's Encrypt..."

# First start without SSL to get certificate
echo "  Demarrage temporaire pour obtenir le certificat..."

# Create a temporary nginx config for HTTP only (certbot challenge)
mkdir -p "$DEPLOY_DIR/nginx/conf.d-tmp"
cat > "$DEPLOY_DIR/nginx/conf.d-tmp/temp.conf" << 'TMPNGINX'
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 200 'NormaCheck setup in progress';
        add_header Content-Type text/plain;
    }
}
TMPNGINX

# Start nginx with temp config
docker run -d --name certbot-nginx \
    -p 80:80 \
    -v "$DEPLOY_DIR/nginx/conf.d-tmp:/etc/nginx/conf.d:ro" \
    -v "$DEPLOY_DIR/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    --mount type=volume,source=certbot_www,target=/var/www/certbot \
    nginx:alpine

sleep 3

# Request certificate
docker run --rm \
    --mount type=volume,source=certbot_certs,target=/etc/letsencrypt \
    --mount type=volume,source=certbot_www,target=/var/www/certbot \
    certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMAIN" \
    --agree-tos \
    --no-eff-email \
    --email "admin@$DOMAIN" \
    --non-interactive \
    2>&1 || echo "[WARN] Certificat SSL echoue - verifiez que le DNS pointe vers ce serveur"

# Cleanup temp nginx
docker stop certbot-nginx 2>/dev/null && docker rm certbot-nginx 2>/dev/null
rm -rf "$DEPLOY_DIR/nginx/conf.d-tmp"

# ---- Start everything ----
echo ""
echo "========================================="
echo " Lancement NormaCheck..."
echo "========================================="
cd "$DEPLOY_DIR"
docker compose up -d --build

echo ""
echo "========================================="
echo " INSTALLATION TERMINEE"
echo "========================================="
echo ""
echo " URL:     https://$DOMAIN"
echo " Sante:   https://$DOMAIN/api/health"
echo " Logs:    docker logs normacheck-app -f"
echo " Status:  docker compose ps"
echo ""
echo " PROCHAINES ETAPES:"
echo " 1. Configurez le DNS A record: $DOMAIN -> $(curl -s ifconfig.me)"
echo " 2. Editez /opt/normacheck/.env si necessaire"
echo " 3. Ajoutez les GitHub Secrets dans votre repo:"
echo "    - OVH_SSH_HOST = $(curl -s ifconfig.me)"
echo "    - OVH_SSH_USER = root"
echo "    - OVH_SSH_KEY  = (votre cle SSH privee)"
echo " 4. Creez un utilisateur admin:"
echo "    docker exec normacheck-app python3 -c \\"
echo "      \"from auth import create_user; print(create_user('admin@$DOMAIN','VotreMotDePasse','Admin','NormaCheck','admin'))\""
echo ""
