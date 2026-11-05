#!/usr/bin/env python3
"""
Folio P08 Compose, Containerization & Reverse Proxy Configuration Linter.
Validates production compose topology, network isolation, security headers,
entrypoints, and multi-stage Dockerfile invariants without requiring Docker daemon.
"""

import os
import sys
import yaml
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def validate():
    checks = []

    # 1. Check docker-compose.prod.yml
    prod_compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
    assert prod_compose_path.exists(), "Missing docker-compose.prod.yml"
    with open(prod_compose_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})
    required_services = ["proxy", "web", "worker", "db", "chroma", "migration"]
    for s in required_services:
        assert s in services, f"Missing service '{s}' in docker-compose.prod.yml"
    checks.append("All 6 required services defined in docker-compose.prod.yml")

    # 2. Port exposure security check
    # ONLY proxy is allowed to publish ports to the host
    for s_name, s_cfg in services.items():
        ports = s_cfg.get("ports", [])
        if s_name == "proxy":
            assert len(ports) >= 1, "Proxy must expose ports 80/443"
        else:
            assert len(ports) == 0, f"SECURITY VIOLATION: Service '{s_name}' must NOT publish ports to the host"
    checks.append("Strict port exposure invariant: ONLY reverse proxy exposes host ports (DB, worker, chroma internal only)")

    # 3. Network isolation check
    networks = compose.get("networks", {})
    assert "backend-net" in networks, "Missing backend-net"
    assert "frontend-net" in networks, "Missing frontend-net"
    assert networks["backend-net"].get("internal") is True, "backend-net must be internal: true"
    assert "backend-net" in services["db"].get("networks", []), "db must be on backend-net"
    assert "backend-net" in services["worker"].get("networks", []), "worker must be on backend-net"
    assert "frontend-net" not in services["db"].get("networks", []), "db must NOT be on frontend-net"
    assert "frontend-net" not in services["worker"].get("networks", []), "worker must NOT be on frontend-net"
    checks.append("Network isolation invariant: backend-net internal: true; DB and worker isolated from frontend")

    # 4. Persistence Volumes check
    volumes = compose.get("volumes", {})
    for v in ["folio-pgdata", "folio-index-data", "folio-media-data", "folio-proxy-certs"]:
        assert v in volumes, f"Missing volume '{v}'"
    checks.append("Persistence volumes declared for PostgreSQL, shared index, media, and certificates")

    # 5. Healthcheck dependency conditions
    assert services["web"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["proxy"]["depends_on"]["web"]["condition"] == "service_healthy"
    assert "healthcheck" in services["db"], "db must define a healthcheck"
    assert "healthcheck" in services["web"], "web must define a healthcheck"
    checks.append("Healthcheck dependency chain: db -> web -> proxy verified")

    # 6. Multi-stage Dockerfile inspection
    df_path = PROJECT_ROOT / "Dockerfile"
    assert df_path.exists(), "Missing Dockerfile"
    df_content = df_path.read_text(encoding="utf-8")
    assert "AS builder" in df_content, "Dockerfile must have multi-stage builder"
    assert "AS runtime" in df_content, "Dockerfile must have multi-stage runtime"
    assert "useradd" in df_content and "10001" in df_content, "Dockerfile must create dedicated non-root user"
    assert "USER folio" in df_content, "Dockerfile must switch to USER folio"
    assert "HEALTHCHECK" in df_content, "Dockerfile must declare HEALTHCHECK"
    assert "constraints.txt" in df_content, "Dockerfile must enforce constraints.txt"
    checks.append("Multi-stage Dockerfile: builder + runtime, non-root user folio (10001), HEALTHCHECK verified")

    # 7. Entrypoints inspection
    entrypoints = [
        PROJECT_ROOT / "docker" / "entrypoints" / "entrypoint-web.sh",
        PROJECT_ROOT / "docker" / "entrypoints" / "entrypoint-worker.sh",
        PROJECT_ROOT / "docker" / "entrypoints" / "entrypoint-migrate.sh",
    ]
    for ep in entrypoints:
        assert ep.exists(), f"Missing entrypoint {ep.name}"
        c = ep.read_text(encoding="utf-8")
        assert "set -euo pipefail" in c, f"Entrypoint {ep.name} must use set -euo pipefail"
    assert "alembic upgrade head" not in entrypoints[1].read_text(encoding="utf-8"), "Worker must NEVER run migrations"
    assert "alembic upgrade head" in entrypoints[2].read_text(encoding="utf-8"), "Migration entrypoint must run alembic"
    checks.append("Entrypoints verified: web, worker (migration-free), one-shot migration runner")

    # 8. Reverse Proxy Configurations (Nginx & Caddy)
    nginx_conf = PROJECT_ROOT / "docker" / "proxy" / "templates" / "default.conf.template"
    caddy_conf = PROJECT_ROOT / "docker" / "proxy" / "Caddyfile"
    assert nginx_conf.exists(), "Missing Nginx virtual host template"
    assert caddy_conf.exists(), "Missing Caddyfile"
    n_text = nginx_conf.read_text(encoding="utf-8")
    assert "X-Forwarded-For" in n_text and "X-Request-ID" in n_text, "Nginx must forward trusted headers"
    assert "Content-Security-Policy" in n_text, "Nginx must declare CSP header"
    assert "return 301 https://" in n_text, "Nginx must redirect HTTP to HTTPS"
    checks.append("Reverse Proxy: HTTP-to-HTTPS redirect, X-Forwarded-*, CSP, and trusted proxy headers verified")

    # 9. Dockerignore check
    dignore = PROJECT_ROOT / ".dockerignore"
    assert dignore.exists(), "Missing .dockerignore"
    dig_content = dignore.read_text(encoding="utf-8")
    for secret_pat in [".env", ".git", "test-results", "data/"]:
        assert secret_pat in dig_content, f".dockerignore must ignore {secret_pat}"
    checks.append(".dockerignore: excludes secrets, .git, test artifacts, and local data")

    # 10. Gitattributes line endings check
    gitattributes_path = PROJECT_ROOT / ".gitattributes"
    assert gitattributes_path.exists(), "Missing .gitattributes in repository root"
    ga_content = gitattributes_path.read_text(encoding="utf-8")
    assert "*.sh" in ga_content and "eol=lf" in ga_content, ".gitattributes must enforce *.sh text eol=lf"
    for sh_file in PROJECT_ROOT.rglob("*.sh"):
        if ".git" in sh_file.parts:
            continue
        assert b"\r" not in sh_file.read_bytes(), f"Shell script {sh_file} contains CRLF carriage return bytes"
    checks.append(".gitattributes: strictly enforces *.sh text eol=lf across all POSIX shell scripts")

    # 11. Reverse proxy SSL certificate tooling check
    init_certs_py = PROJECT_ROOT / "scripts" / "ops" / "init_certs.py"
    init_certs_sh = PROJECT_ROOT / "scripts" / "ops" / "init_certs.sh"
    assert init_certs_py.exists(), "Missing scripts/ops/init_certs.py"
    assert init_certs_sh.exists(), "Missing scripts/ops/init_certs.sh"
    assert b"\r" not in init_certs_sh.read_bytes(), "init_certs.sh must have LF line endings"

    from scripts.ops.init_certs import generate_self_signed_cert, verify_certificates
    with tempfile.TemporaryDirectory() as tmp_cert_dir:
        tmp_p = Path(tmp_cert_dir)
        cert_info = generate_self_signed_cert(tmp_p, domain="validate.local")
        assert cert_info["status"] == "valid"
        assert (tmp_p / "folio.crt").exists()
        assert (tmp_p / "folio.key").exists()
        verified = verify_certificates(tmp_p)
        assert verified["status"] == "valid"
    checks.append("SSL Certificate Precondition: init_certs.py & init_certs.sh verified for proxy service")

    print("\n[OK] All Configuration & Topology Audits Passed:")
    for c in checks:
        print(f"  + {c}")


if __name__ == "__main__":
    validate()
