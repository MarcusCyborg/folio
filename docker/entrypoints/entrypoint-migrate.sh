#!/usr/bin/env bash
# ==============================================================================
# Folio Database Migration & Provisioning One-Shot Entrypoint
# ==============================================================================
set -euo pipefail

echo "[INFO] [migrate] Initializing Folio database migration job..."

# 1. Wait for PostgreSQL readiness
MAX_RETRIES=30
RETRY_COUNT=0
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
        echo "[ERROR] [migrate] Timed out waiting for database at ${DATABASE_URL}"
        exit 1
    fi
    echo "[INFO] [migrate] Database not ready yet (attempt ${RETRY_COUNT}/${MAX_RETRIES}). Sleeping 2s..."
    sleep 2
done
echo "[INFO] [migrate] Database connection confirmed."

# 2. Run Alembic Upgrade Head
echo "[INFO] [migrate] Applying Alembic database migrations to head..."
python3 -m alembic upgrade head
echo "[INFO] [migrate] Database migrations applied successfully."

# 3. Optional Admin Provisioning (if ADMIN_BOOTSTRAP_PASSWORD is provided)
if [ -n "${ADMIN_BOOTSTRAP_PASSWORD:-}" ]; then
    echo "[INFO] [migrate] Provisioning initial super_admin account via bootstrap_admin.py..."
    python3 scripts/bootstrap_admin.py || true
fi

# 4. Optional Initial Index Build (if no active generation exists yet)
echo "[INFO] [migrate] Verifying search index generation..."
python3 -c "
import sys
from src.backend.core.database import SessionLocal
from src.backend.search_index.manager import GenerationManager
db = SessionLocal()
try:
    active = GenerationManager.get_active_generation(db)
    if not active:
        print('[INFO] [migrate] No active index generation found. Building initial index generation...')
        gen = GenerationManager.build_new_generation(db, force=True)
        print(f'[INFO] [migrate] Built generation {gen.generation_num} with {gen.doc_count} document(s).')
    else:
        print(f'[INFO] [migrate] Active index generation {active.generation_num} already exists.')
finally:
    db.close()
"

echo "[INFO] [migrate] Migration task finished cleanly."
