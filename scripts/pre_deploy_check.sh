#!/bin/bash
# ============================================================
# NormaCheck - Gate de deploiement
# Si un test echoue -> deploiement bloque
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================================"
echo "  NormaCheck - Verification Pre-Deploiement"
echo "  $(date)"
echo "============================================================"

ERRORS=0

# 1. Linting
echo -e "\n${YELLOW}[1/4] Verification du code (ruff)...${NC}"
if python -m ruff check . 2>/dev/null; then
    echo -e "${GREEN}  [OK] Pas d'erreur de linting${NC}"
else
    echo -e "${RED}  [ECHEC] Erreurs de linting detectees${NC}"
    ERRORS=$((ERRORS + 1))
fi

# 2. Tests unitaires
echo -e "\n${YELLOW}[2/4] Tests unitaires...${NC}"
if python -m pytest tests/unit/ -x -q --tb=line 2>&1; then
    echo -e "${GREEN}  [OK] Tests unitaires passes${NC}"
else
    echo -e "${RED}  [ECHEC] Tests unitaires echoues${NC}"
    ERRORS=$((ERRORS + 1))
fi

# 3. Tests d'integration
echo -e "\n${YELLOW}[3/4] Tests d'integration...${NC}"
if python -m pytest tests/integration/ -x -q --tb=line 2>&1; then
    echo -e "${GREEN}  [OK] Tests d'integration passes${NC}"
else
    echo -e "${RED}  [ECHEC] Tests d'integration echoues${NC}"
    ERRORS=$((ERRORS + 1))
fi

# 4. Couverture minimale
echo -e "\n${YELLOW}[4/4] Verification couverture (min 40%)...${NC}"
if python -m pytest tests/unit/ --cov=urssaf_analyzer --cov-fail-under=40 -q 2>&1; then
    echo -e "${GREEN}  [OK] Couverture suffisante${NC}"
else
    echo -e "${RED}  [ECHEC] Couverture insuffisante${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Decision
echo ""
echo "============================================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}  DEPLOIEMENT AUTORISE - Toutes les verifications passees${NC}"
    echo "============================================================"
    exit 0
else
    echo -e "${RED}  DEPLOIEMENT BLOQUE - $ERRORS verification(s) echouee(s)${NC}"
    echo -e "${RED}  Corrigez les erreurs avant de deployer.${NC}"
    echo "============================================================"
    exit 1
fi
