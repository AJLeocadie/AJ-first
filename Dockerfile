# ============================================
# NormaCheck - Dockerfile OVHcloud Production
# Multi-stage build optimise
# ============================================

# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for compilation (lxml, cryptography, Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt-dev libffi-dev \
    libjpeg62-turbo-dev zlib1g-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --- Stage 2: Production ---
FROM python:3.11-slim

LABEL maintainer="NormaCheck" \
      version="3.8.1" \
      description="NormaCheck - Audit social, fiscal et conformite"

# Runtime dependencies only (no compiler) + Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 libjpeg62-turbo libpng16-16 \
    curl sqlite3 \
    tesseract-ocr tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r normacheck && useradd -r -g normacheck -d /app normacheck

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Application code
WORKDIR /app
COPY urssaf_analyzer/ ./urssaf_analyzer/
COPY api/ ./api/
COPY auth.py ./
COPY persistence.py ./
COPY setup.py ./
COPY requirements.txt ./

# Create persistent directories
RUN mkdir -p /data/normacheck/db \
             /data/normacheck/uploads \
             /data/normacheck/reports \
             /data/normacheck/backups \
             /data/normacheck/logs \
             /data/normacheck/temp \
             /data/normacheck/encrypted \
    && chown -R normacheck:normacheck /data/normacheck /app

# Copy deployment configs
COPY gunicorn.conf.py ./
COPY start.sh ./
RUN chmod +x start.sh

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NORMACHECK_DATA_DIR=/data/normacheck \
    NORMACHECK_ENV=production \
    PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

USER normacheck

CMD ["./start.sh"]
