#!/usr/bin/env bash
# ==============================================================================
# Folio Disaster Recovery: Automated Restore Wrapper Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path-to-backup-archive.tar.gz> [--rebuild-index] [extra args...]"
    exit 1
fi

ARCHIVE="$1"
shift

echo "[INFO] Starting Folio restore drill..."
echo "[INFO] Archive: ${ARCHIVE}"

python3 "${SCRIPT_DIR}/restore.py" --archive "${ARCHIVE}" "$@"

echo "[INFO] Restore process completed successfully."
