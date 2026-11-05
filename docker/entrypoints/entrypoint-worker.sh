#!/usr/bin/env bash
# ==============================================================================
# Folio Search Index Worker Service Entrypoint
# ==============================================================================
set -euo pipefail

echo "[INFO] [worker] Initializing Folio search index lifecycle worker..."

# 1. Wait for PostgreSQL readiness
MAX_RETRIES=30
RETRY_COUNT=0
echo "[INFO] [worker] Waiting for PostgreSQL database connectivity..."
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
        echo "[ERROR] [worker] Timed out waiting for database at ${DATABASE_URL}"
        exit 1
    fi
    echo "[INFO] [worker] Database not ready yet (attempt ${RETRY_COUNT}/${MAX_RETRIES}). Sleeping 2s..."
    sleep 2
done
echo "[INFO] [worker] Database connection confirmed."

# IMPORTANT INVARIANT: Worker NEVER runs migrations to prevent schema race conditions.
POLL_INTERVAL="${WORKER_POLL_INTERVAL:-1.0}"
BATCH_SIZE="${WORKER_BATCH_SIZE:-10}"

echo "[INFO] [worker] Starting IndexWorker daemon (poll_interval=${POLL_INTERVAL}s, batch_size=${BATCH_SIZE})..."
exec python3 scripts/run_worker.py \
    --poll-interval "${POLL_INTERVAL}" \
    --batch-size "${BATCH_SIZE}"
