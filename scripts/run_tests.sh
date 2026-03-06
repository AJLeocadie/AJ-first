#!/bin/bash
# ============================================================
# NormaCheck - Script d'execution des tests
# Niveau de fiabilite : bancaire
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Variables
REPORT_DIR="$PROJECT_DIR/test-reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
EXIT_CODE=0

mkdir -p "$REPORT_DIR"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  NormaCheck - Suite de Tests Qualite${NC}"
echo -e "${BLUE}  $(date)${NC}"
echo -e "${BLUE}============================================================${NC}"

# ===========================
# Phase 1 : Tests unitaires
# ===========================
echo -e "\n${YELLOW}[Phase 1/4] Tests unitaires...${NC}"
if python -m pytest tests/unit/ \
    -v --tb=short \
    --junitxml="$REPORT_DIR/unit_${TIMESTAMP}.xml" \
    --cov=urssaf_analyzer --cov=auth --cov=persistence \
    --cov-report=html:"$REPORT_DIR/coverage_html" \
    --cov-report=xml:"$REPORT_DIR/coverage_${TIMESTAMP}.xml" \
    --cov-report=term-missing \
    2>&1 | tee "$REPORT_DIR/unit_${TIMESTAMP}.log"; then
    echo -e "${GREEN}[OK] Tests unitaires passes${NC}"
else
    echo -e "${RED}[ECHEC] Tests unitaires echoues${NC}"
    EXIT_CODE=1
fi

# ===========================
# Phase 2 : Tests d'integration
# ===========================
echo -e "\n${YELLOW}[Phase 2/4] Tests d'integration...${NC}"
if python -m pytest tests/integration/ \
    -v --tb=short \
    --junitxml="$REPORT_DIR/integration_${TIMESTAMP}.xml" \
    2>&1 | tee "$REPORT_DIR/integration_${TIMESTAMP}.log"; then
    echo -e "${GREEN}[OK] Tests d'integration passes${NC}"
else
    echo -e "${RED}[ECHEC] Tests d'integration echoues${NC}"
    EXIT_CODE=1
fi

# ===========================
# Phase 3 : Tests E2E (optionnel)
# ===========================
echo -e "\n${YELLOW}[Phase 3/4] Tests E2E (Playwright)...${NC}"
if python -c "import playwright" 2>/dev/null; then
    if python -m pytest tests/e2e/ \
        -v --tb=short \
        --junitxml="$REPORT_DIR/e2e_${TIMESTAMP}.xml" \
        2>&1 | tee "$REPORT_DIR/e2e_${TIMESTAMP}.log"; then
        echo -e "${GREEN}[OK] Tests E2E passes${NC}"
    else
        echo -e "${RED}[ECHEC] Tests E2E echoues${NC}"
        EXIT_CODE=1
    fi
else
    echo -e "${YELLOW}[SKIP] Playwright non installe - tests E2E ignores${NC}"
fi

# ===========================
# Phase 4 : Verification couverture
# ===========================
echo -e "\n${YELLOW}[Phase 4/4] Verification couverture...${NC}"
if [ -f "$REPORT_DIR/coverage_${TIMESTAMP}.xml" ]; then
    echo -e "${GREEN}[OK] Rapport de couverture genere : $REPORT_DIR/coverage_html/index.html${NC}"
else
    echo -e "${YELLOW}[WARN] Rapport de couverture non genere${NC}"
fi

# ===========================
# Resume
# ===========================
echo -e "\n${BLUE}============================================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}  TOUS LES TESTS SONT PASSES${NC}"
    echo -e "${GREEN}  Deploiement AUTORISE${NC}"
else
    echo -e "${RED}  DES TESTS ONT ECHOUE${NC}"
    echo -e "${RED}  Deploiement BLOQUE${NC}"
fi
echo -e "${BLUE}  Rapports : $REPORT_DIR${NC}"
echo -e "${BLUE}============================================================${NC}"

exit $EXIT_CODE
