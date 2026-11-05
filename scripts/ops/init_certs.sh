#!/usr/bin/env bash
# ==============================================================================
# Folio Reverse Proxy SSL Certificate Initialization Wrapper
# Ensures folio.crt and folio.key exist for Nginx/Caddy proxy service.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CERT_DIR="${CERT_DIR:-${PROJECT_ROOT}/docker/proxy/certs}"
DOMAIN_NAME="${DOMAIN_NAME:-localhost}"
STAGING_DOMAIN="${STAGING_DOMAIN:-staging.localhost}"

echo "[INFO] Running Folio SSL certificate initialization..."
echo "[INFO] Target Directory: ${CERT_DIR}"
echo "[INFO] Primary Domain: ${DOMAIN_NAME}"

python3 "${SCRIPT_DIR}/init_certs.py" \
    --cert-dir "${CERT_DIR}" \
    --domain "${DOMAIN_NAME}" \
    --staging-domain "${STAGING_DOMAIN}" \
    "$@"

echo "[INFO] SSL certificate operation completed successfully."
