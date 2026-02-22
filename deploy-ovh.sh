#!/bin/bash
# ============================================
# NormaCheck - Script de deploiement OVHcloud
# Usage: ./deploy-ovh.sh [commande]
#
# Commandes:
#   setup     - Installation initiale (1ere fois)
#   deploy    - Deployer/mettre a jour
#   ssl       - Configurer SSL Let's Encrypt
#   logs      - Voir les logs en temps reel
#   backup    - Lancer un backup manuel
#   status    - Etat des services
#   restart   - Redemarrer les services
#   stop      - Arreter les services
# ============================================
set -e

DOMAIN="${NORMACHECK_DOMAIN:-normacheck.votredomaine.fr}"
EMAIL="${NORMACHECK_EMAIL:-admin@votredomaine.fr}"
COMPOSE="docker compose"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

case "${1:-deploy}" in

setup)
    info "=== Installation initiale OVHcloud ==="

    # 1. Prerequis
    info "Installation de Docker..."
    if ! command -v docker &> /dev/null; then
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
        info "Docker installe."
    else
        info "Docker deja installe."
    fi

    # Docker Compose plugin
    if ! docker compose version &> /dev/null; then
        apt-get update && apt-get install -y docker-compose-plugin
    fi

    # 2. Firewall
    info "Configuration du firewall..."
    if command -v ufw &> /dev/null; then
        ufw allow 22/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw --force enable
        info "Firewall configure (22, 80, 443)."
    fi

    # 3. Creer les repertoires
    info "Creation des repertoires persistants..."
    mkdir -p /data/normacheck/{db,uploads,reports,backups,logs,temp,encrypted}

    # 4. Configurer le domaine dans nginx
    info "Configuration du domaine: $DOMAIN"
    if [ "$DOMAIN" != "normacheck.votredomaine.fr" ]; then
        sed -i "s/normacheck.votredomaine.fr/$DOMAIN/g" nginx/conf.d/normacheck.conf
        info "Domaine configure: $DOMAIN"
    else
        warn "Domaine par defaut! Modifiez NORMACHECK_DOMAIN avant le deploiement."
        warn "  export NORMACHECK_DOMAIN=votre-domaine.fr"
    fi

    # 5. Build et lancement
    info "Build de l'image Docker..."
    $COMPOSE build --no-cache normacheck

    info "Demarrage des services..."
    $COMPOSE up -d normacheck nginx

    info ""
    info "=== Installation terminee ==="
    info "Site accessible sur http://$DOMAIN"
    info ""
    info "Prochaine etape: configurer SSL"
    info "  export NORMACHECK_DOMAIN=votre-domaine.fr"
    info "  export NORMACHECK_EMAIL=votre@email.fr"
    info "  ./deploy-ovh.sh ssl"
    ;;

deploy)
    info "=== Deploiement NormaCheck ==="

    # Pull derniere version si git repo
    if [ -d .git ]; then
        info "Pull des derniers changements..."
        git pull origin main 2>/dev/null || git pull origin claude/urssaf-innovation-analysis-LjoxK 2>/dev/null || true
    fi

    info "Build de l'image..."
    $COMPOSE build normacheck

    info "Redemarrage zero-downtime..."
    $COMPOSE up -d --no-deps normacheck

    # Attendre que le health check passe
    info "Attente du health check..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
            info "Service operationnel!"
            break
        fi
        sleep 2
    done

    # Afficher la version deployee
    VERSION=$(curl -sf http://localhost:8000/api/version 2>/dev/null || echo '{"version":"?"}')
    info "Version deployee: $VERSION"
    ;;

ssl)
    info "=== Configuration SSL Let's Encrypt ==="

    if [ "$DOMAIN" = "normacheck.votredomaine.fr" ]; then
        error "Configurez d'abord votre domaine:"
        error "  export NORMACHECK_DOMAIN=votre-domaine.fr"
        error "  export NORMACHECK_EMAIL=votre@email.fr"
        exit 1
    fi

    # Mettre a jour la config nginx
    sed -i "s/normacheck.votredomaine.fr/$DOMAIN/g" nginx/conf.d/normacheck.conf

    # Generer le certificat
    info "Generation du certificat SSL pour $DOMAIN..."
    $COMPOSE run --rm certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        -d "$DOMAIN"

    # Redemarrer nginx avec SSL
    $COMPOSE restart nginx

    info "SSL configure! Site accessible sur https://$DOMAIN"

    # Demarrer le renouvellement auto
    $COMPOSE up -d certbot
    info "Renouvellement automatique active."
    ;;

logs)
    info "=== Logs en temps reel ==="
    $COMPOSE logs -f --tail=100 normacheck
    ;;

backup)
    info "=== Backup manuel ==="
    STAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_DIR="/data/normacheck/backups"
    mkdir -p "$BACKUP_DIR"

    # Backup SQLite
    if [ -f /data/normacheck/db/normacheck.db ]; then
        cp /data/normacheck/db/normacheck.db "$BACKUP_DIR/normacheck_$STAMP.db"
        info "Base de donnees sauvegardee."
    fi

    # Backup JSON stores
    tar czf "$BACKUP_DIR/json_stores_$STAMP.tar.gz" -C /data/normacheck/db . 2>/dev/null || true
    info "Stores JSON sauvegardes."

    # Backup uploads
    if [ -d /data/normacheck/uploads ] && [ "$(ls -A /data/normacheck/uploads 2>/dev/null)" ]; then
        tar czf "$BACKUP_DIR/uploads_$STAMP.tar.gz" -C /data/normacheck uploads
        info "Fichiers uploades sauvegardes."
    fi

    # Cleanup vieux backups (> 30 jours)
    find "$BACKUP_DIR" -name "*.db" -mtime +30 -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete 2>/dev/null || true

    info "Backup termine: $BACKUP_DIR"
    ls -lh "$BACKUP_DIR"/*"$STAMP"* 2>/dev/null
    ;;

status)
    info "=== Etat des services ==="
    $COMPOSE ps
    echo ""
    info "Health check:"
    curl -s http://localhost:8000/api/health 2>/dev/null | python3 -m json.tool 2>/dev/null || warn "Service non accessible"
    echo ""
    info "Version:"
    curl -s http://localhost:8000/api/version 2>/dev/null | python3 -m json.tool 2>/dev/null || warn "Service non accessible"
    echo ""
    info "Espace disque donnees:"
    du -sh /data/normacheck/* 2>/dev/null || true
    ;;

restart)
    info "Redemarrage des services..."
    $COMPOSE restart
    info "Services redemarres."
    ;;

stop)
    warn "Arret des services..."
    $COMPOSE down
    info "Services arretes. Les donnees sont preservees dans /data/normacheck/"
    ;;

*)
    echo "Usage: $0 {setup|deploy|ssl|logs|backup|status|restart|stop}"
    exit 1
    ;;
esac
