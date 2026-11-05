# ==============================================================================
# Folio Multi-Stage Dockerfile (Phase P08 Production / Staging)
# Reproducible, non-root, pinned dependencies, minimal attack surface.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency Builder
# ------------------------------------------------------------------------------
FROM python:3.10-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install compilation tools and PostgreSQL client libraries for wheel compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy constraints and requirements
COPY constraints.txt requirements.txt /build/

# Upgrade pip and install pinned runtime dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -c constraints.txt -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Minimal Production Runtime
# ------------------------------------------------------------------------------
FROM python:3.10-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    INDEX_STORAGE_DIR="/app/data/search_index/generations"

# Install minimal runtime libraries (libpq5 for psycopg, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root dedicated application user and group (UID/GID 10001)
RUN groupadd -g 10001 folio && \
    useradd -u 10001 -g folio -m -s /bin/bash folio

# Prepare application and data volume directories with proper non-root permissions
RUN mkdir -p /app /app/data /app/data/search_index /app/data/search_index/generations /app/data/media /app/backups && \
    chown -R folio:folio /app

# Copy virtual environment from builder stage
COPY --from=builder --chown=folio:folio /opt/venv /opt/venv

WORKDIR /app

# Copy source code, migrations, scripts, fixtures, and configs
COPY --chown=folio:folio alembic.ini constraints.txt requirements.txt /app/
COPY --chown=folio:folio src/ /app/src/
COPY --chown=folio:folio alembic/ /app/alembic/
COPY --chown=folio:folio scripts/ /app/scripts/
COPY --chown=folio:folio fixtures/ /app/fixtures/
COPY --chown=folio:folio docker/ /app/docker/

# Ensure entrypoint scripts are executable
RUN chmod +x /app/docker/entrypoints/*.sh /app/scripts/ops/*.sh

# Switch to non-root execution
USER folio

# Expose internal HTTP port (only reachable within Docker network)
EXPOSE 8000

# Container liveness health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Default entrypoint starts the web application server
ENTRYPOINT ["/app/docker/entrypoints/entrypoint-web.sh"]
