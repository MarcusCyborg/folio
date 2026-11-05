#!/usr/bin/env bash
# ==============================================================================
# Folio Disaster Recovery: Automated Backup Wrapper Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/backups}"
INCLUDE_VECTOR="${INCLUDE_VECTOR:-false}"

echo "[INFO] Starting Folio system backup..."
echo "[INFO] Project Root: ${PROJECT_ROOT}"
echo "[INFO] Backup Output Directory: ${BACKUP_DIR}"

EXTRA_ARGS=""
if [ "${INCLUDE_VECTOR}" = "true" ]; then
    EXTRA_ARGS="--include-vector"
fi

python3 "${SCRIPT_DIR}/backup.py" --output-dir "${BACKUP_DIR}" ${EXTRA_ARGS} "$@"

echo "[INFO] Backup completed successfully."
