#!/usr/bin/env bash
# ==============================================================================
# Folio Web Service Entrypoint
# ==============================================================================
set -euo pipefail

echo "[INFO] [web] Initializing Folio web application container..."

# 1. Wait for PostgreSQL readiness
MAX_RETRIES=30
RETRY_COUNT=0
echo "[INFO] [web] Waiting for PostgreSQL database connectivity..."
until python3 -c "
import sys
from sqlalchemy import create_engine, text
from src.backend.core.config import settings
try:
    engine = create_engine(settings.DATABASE_URL, connect_args={'connect_timeout': 3})
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    sys.exit(0)
except Exception:
    sys.exit(1)
" > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ "${RETRY_COUNT}" -ge "${MAX_RETRIES}" ]; then
        echo "[ERROR] [web] Timed out waiting for database after ${MAX_RETRIES} attempts (connection details redacted)"
        exit 1
    fi
    echo "[INFO] [web] Database not ready yet (attempt ${RETRY_COUNT}/${MAX_RETRIES}). Sleeping 2s..."
    sleep 2
done
echo "[INFO] [web] Database connection confirmed."

# 2. Start Uvicorn ASGI Application Server
# NOTE: Web process NEVER automatically runs migrations to avoid concurrent migration races.
# Proxy headers are enabled to support trusted reverse proxy (Caddy / Nginx) headers.
echo "[INFO] [web] Starting Uvicorn server on 0.0.0.0:8000..."
exec uvicorn src.backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-access-log
