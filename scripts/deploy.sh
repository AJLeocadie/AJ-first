#!/bin/bash
# ============================================
# NormaCheck - Script de deploiement manuel
# Usage: bash scripts/deploy.sh [--force]
# ============================================
set -e

DEPLOY_DIR="/opt/normacheck"
FORCE_BUILD="${1:-}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "========================================="
echo " NormaCheck - Deploiement $TIMESTAMP"
echo "========================================="

cd "$DEPLOY_DIR"

# ---- Backup DB before deploy ----
echo "[1/5] Sauvegarde pre-deploiement..."
DB_FILE="/data/normacheck/db/normacheck.db"
if docker exec normacheck-app test -f "$DB_FILE" 2>/dev/null; then
    docker exec normacheck-app cp "$DB_FILE" "/data/normacheck/backups/pre_deploy_${TIMESTAMP}.db"
    echo "  DB sauvegardee"
else
    echo "  Pas de DB existante (premiere installation?)"
fi

# ---- Pull latest ----
echo "[2/5] Pull du code..."
git fetch origin main
CURRENT=$(git rev-parse HEAD)
LATEST=$(git rev-parse origin/main)

if [ "$CURRENT" = "$LATEST" ] && [ "$FORCE_BUILD" != "--force" ]; then
    echo "  Deja a jour ($CURRENT)"
    echo "  Utilisez --force pour forcer le rebuild"
    exit 0
fi

git reset --hard origin/main
echo "  Mis a jour: ${CURRENT:0:7} -> ${LATEST:0:7}"

# ---- Build ----
echo "[3/5] Build Docker..."
if [ "$FORCE_BUILD" = "--force" ]; then
    docker compose build --no-cache normacheck
else
    docker compose build normacheck
fi

# ---- Deploy ----
echo "[4/5] Deploiement..."
docker compose up -d --remove-orphans

# ---- Health check ----
echo "[5/5] Verification sante..."
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' normacheck-app 2>/dev/null || echo "starting")
    echo "  Check $i/12: $STATUS"
    if [ "$STATUS" = "healthy" ]; then
        echo ""
        echo "[OK] Deploiement reussi!"
        VERSION=$(docker exec normacheck-app curl -s http://localhost:8000/api/version 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
        echo "  Version: $VERSION"
        echo "  Commit:  ${LATEST:0:7}"
        echo "  Heure:   $TIMESTAMP"

        # Cleanup old images
        docker image prune -f --filter "until=168h" 2>/dev/null || true
        exit 0
    fi
done

echo ""
echo "[ERREUR] L'application ne repond pas apres 60s"
echo "  Derniers logs:"
docker logs normacheck-app --tail 20
echo ""
echo "  Pour rollback: git checkout $CURRENT && docker compose up -d --build"
exit 1
