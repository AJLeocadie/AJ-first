#!/bin/bash
# ============================================
# NormaCheck - Script de demarrage OVHcloud
# ============================================
set -e

DATA_DIR="${NORMACHECK_DATA_DIR:-/data/normacheck}"
ENV="${NORMACHECK_ENV:-production}"

echo "========================================"
echo " NormaCheck v3.8.1 - Demarrage"
echo " Environnement: $ENV"
echo " Donnees: $DATA_DIR"
echo "========================================"

# Creer les repertoires persistants si absents
for dir in db uploads reports backups logs temp encrypted; do
    mkdir -p "$DATA_DIR/$dir"
done

# Initialiser la base SQLite si absente
if [ ! -f "$DATA_DIR/db/normacheck.db" ]; then
    echo "[INIT] Creation de la base de donnees..."
    python3 -c "
from urssaf_analyzer.database.db_manager import Database
db = Database('$DATA_DIR/db/normacheck.db')
print('Base de donnees initialisee avec succes.')
"
fi

# Log rotation simple
for logfile in access.log error.log; do
    if [ -f "$DATA_DIR/logs/$logfile" ] && [ "$(stat -f%z "$DATA_DIR/logs/$logfile" 2>/dev/null || stat -c%s "$DATA_DIR/logs/$logfile" 2>/dev/null)" -gt 104857600 ]; then
        mv "$DATA_DIR/logs/$logfile" "$DATA_DIR/logs/$logfile.$(date +%Y%m%d)"
    fi
done

echo "[START] Lancement Gunicorn avec $(nproc) CPU disponibles..."

if [ "$ENV" = "development" ]; then
    # Dev: rechargement auto, 1 worker
    exec uvicorn api.index:app \
        --host 0.0.0.0 \
        --port "${PORT:-8000}" \
        --reload \
        --log-level debug
else
    # Production: Gunicorn multi-worker
    exec gunicorn api.index:app \
        --config gunicorn.conf.py
fi
