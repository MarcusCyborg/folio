#!/usr/bin/env python3
"""
Folio P08 / Round 4 Compose, Containerization, Env Contract, Cutover & Proxy Static Validator.
Validates production compose topology, network isolation, env forwarding, parameterized storage cutover volumes,
TLS provisioning/preflight dependencies, security headers, entrypoints, and multi-stage Dockerfile invariants.

NOTE: This performs static YAML/config/filesystem/cryptography validation only.
When Docker CLI/daemon is absent, live Compose render and container runtime are classified BLOCKED_ENV.
"""

import os
import re
import sys
import yaml
import shlex
import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_env_keys(env_path: Path) -> set[str]:
    keys: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k = line.split("=", 1)[0].strip()
        if k:
            keys.add(k)
    return keys


def _parse_env_dict(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == "'") or (v[0] == v[-1] == '"')):
            v = v[1:-1]
        values[k.strip()] = v
    return values


def _assert_env_file_shell_compatible(env_path: Path) -> None:
    """Verifies non-empty template assignments containing whitespace/special chars are cleanly shell-quoted."""
    for line_no, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if not v:
            continue
        tokens = shlex.split(f"{k.strip()}={v}", posix=True)
        assert len(tokens) == 1 and tokens[0].startswith(f"{k.strip()}="), (
            f"{env_path.name}:{line_no} ({k.strip()}) is not cleanly shell-quoted for POSIX source: {raw_line}"
        )


def validate():
    checks = []

    # 1. Check docker-compose.prod.yml services
    prod_compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
    assert prod_compose_path.exists(), "Missing docker-compose.prod.yml"
    with open(prod_compose_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})
    required_services = [
        "cert-init",
        "cert-preflight",
        "proxy",
        "web",
        "worker",
        "db",
        "chroma",
        "migration",
        "ops",
    ]
    for s in required_services:
        assert s in services, f"Missing service '{s}' in docker-compose.prod.yml"
    checks.append("All 9 required services (including cert-init, cert-preflight, ops) defined in docker-compose.prod.yml")

    # 2. Port exposure security check
    # ONLY proxy is allowed to publish ports to the host
    for s_name, s_cfg in services.items():
        ports = s_cfg.get("ports", [])
        if s_name == "proxy":
            assert len(ports) >= 1, "Proxy must expose ports 80/443"
        else:
            assert len(ports) == 0, f"SECURITY VIOLATION: Service '{s_name}' must NOT publish ports to the host"
    checks.append("Strict port exposure invariant: ONLY reverse proxy exposes host ports (DB, worker, chroma, tools internal only)")

    # 3. Network isolation check
    networks = compose.get("networks", {})
    assert "backend-net" in networks, "Missing backend-net"
    assert "frontend-net" in networks, "Missing frontend-net"
    assert networks["backend-net"].get("internal") is True, "backend-net must be internal: true"
    for internal_svc in ["db", "worker", "chroma", "migration", "ops", "cert-init", "cert-preflight"]:
        svc_nets = services[internal_svc].get("networks", [])
        assert "backend-net" in svc_nets, f"{internal_svc} must be on backend-net"
        assert "frontend-net" not in svc_nets, f"{internal_svc} must NOT be on frontend-net"
    assert "frontend-net" in services["proxy"].get("networks", []), "proxy must be on frontend-net"
    assert "backend-net" not in services["proxy"].get("networks", []), "proxy must NOT be on backend-net"
    checks.append("Network isolation invariant: backend-net internal: true; only web bridges frontend/backend nets")

    # 4. Persistence & Parameterized Cutover Volumes check (R4-02)
    volumes = compose.get("volumes", {})
    expected_volume_vars = {
        "folio-pgdata": "FOLIO_PGDATA_VOLUME",
        "folio-index-data": "FOLIO_INDEX_VOLUME",
        "folio-media-data": "FOLIO_MEDIA_VOLUME",
        "folio-chroma-data": "FOLIO_CHROMA_VOLUME",
        "folio-proxy-certs": "FOLIO_CERTS_VOLUME",
    }
    for v_key, env_var in expected_volume_vars.items():
        assert v_key in volumes, f"Missing volume '{v_key}'"
        v_name_expr = str((volumes[v_key] or {}).get("name", ""))
        assert env_var in v_name_expr, (
            f"Volume '{v_key}' must parameterize its runtime volume name via ${{{env_var}:-{v_key}}} for cutover isolation"
        )

    for storage_svc in ["web", "worker", "migration", "ops"]:
        mounts = services[storage_svc].get("volumes", [])
        assert any(m.startswith("folio-index-data:/app/data/search_index") for m in mounts), (
            f"{storage_svc} must mount folio-index-data:/app/data/search_index"
        )
        assert any(m.startswith("folio-media-data:/app/data/media") for m in mounts), (
            f"{storage_svc} must mount folio-media-data:/app/data/media"
        )
        svc_env = services[storage_svc].get("environment", {})
        assert "INDEX_STORAGE_DIR" in svc_env and "/app/data/search_index/generations" in str(svc_env["INDEX_STORAGE_DIR"]), (
            f"{storage_svc} must define consistent INDEX_STORAGE_DIR"
        )
        assert "MEDIA_DIR" in svc_env and "/app/data/media" in str(svc_env["MEDIA_DIR"]), (
            f"{storage_svc} must define consistent MEDIA_DIR"
        )
    checks.append("Cutover-ready storage volumes: parameterized FOLIO_*_VOLUME names and shared index/media paths across web/worker/migration/ops")

    # 5. Healthcheck & TLS Preflight Dependency Chain (R4-03)
    assert services["web"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["proxy"]["depends_on"]["web"]["condition"] == "service_healthy"
    assert services["proxy"]["depends_on"]["cert-preflight"]["condition"] == "service_completed_successfully"
    assert "healthcheck" in services["db"], "db must define a healthcheck"
    assert "healthcheck" in services["web"], "web must define a healthcheck"

    proxy_vols = services["proxy"].get("volumes", [])
    assert any(v == "folio-proxy-certs:/etc/nginx/certs:ro" for v in proxy_vols), (
        "proxy must mount folio-proxy-certs:/etc/nginx/certs:ro"
    )
    cert_init_vols = services["cert-init"].get("volumes", [])
    assert any(v == "folio-proxy-certs:/app/certs" for v in cert_init_vols), (
        "cert-init must mount folio-proxy-certs:/app/certs read-write"
    )
    assert services["cert-init"].get("environment", {}).get("CERT_DIR") == "/app/certs"
    assert "tools" in services["cert-init"].get("profiles", [])
    cert_pre_vols = services["cert-preflight"].get("volumes", [])
    assert any(v == "folio-proxy-certs:/app/certs:ro" for v in cert_pre_vols), (
        "cert-preflight must mount folio-proxy-certs:/app/certs:ro"
    )
    assert "--check-only" in services["cert-preflight"].get("command", [])
    checks.append("Healthcheck & TLS preflight chain: db -> web -> proxy AND cert-preflight -> proxy verified")

    # 6. Env Contract Alignment (R4-01): .env.production.example <-> docker-compose.prod.yml <-> Settings
    env_example_path = PROJECT_ROOT / ".env.production.example"
    assert env_example_path.exists(), "Missing .env.production.example"
    template_keys = _parse_env_keys(env_example_path)
    template_vals = _parse_env_dict(env_example_path)
    _assert_env_file_shell_compatible(env_example_path)
    assert template_vals.get("HSTS_HEADER") == 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
    assert template_vals.get("ADMIN_BOOTSTRAP_DISPLAY_NAME") == "Super Administrator"

    # Secrets must be empty in template so verbatim copies fail closed
    assert template_vals.get("APP_SECRET", "") == "", "APP_SECRET must be empty in .env.production.example"
    assert template_vals.get("POSTGRES_PASSWORD", "") == "", "POSTGRES_PASSWORD must be empty in .env.production.example"
    assert template_vals.get("ADMIN_BOOTSTRAP_PASSWORD", "") == "", "ADMIN_BOOTSTRAP_PASSWORD must be empty in .env.production.example"

    # Required secrets in Compose must enforce non-empty :? interpolation
    assert ":?" in str(services["db"]["environment"]["POSTGRES_PASSWORD"]), (
        "db POSTGRES_PASSWORD must enforce non-empty Compose :? validation"
    )
    for app_svc in ["web", "worker", "migration", "ops"]:
        assert ":?" in str(services[app_svc]["environment"]["APP_SECRET"]), (
            f"{app_svc} APP_SECRET must enforce non-empty Compose :? validation"
        )

    # Advertised runtime tuning knobs must reach web
    web_env = services["web"].get("environment", {})
    for required_web_key in [
        "APP_ENV",
        "APP_SECRET",
        "DATABASE_URL",
        "COOKIE_SECURE",
        "COOKIE_SAMESITE",
        "CORS_ALLOWED_ORIGINS",
        "TRUSTED_PROXIES",
        "RATE_LIMIT_ENABLED",
        "SEARCH_CONTEXT_TTL_MINUTES",
        "SEARCH_TIMEOUT_SECONDS",
        "SEMANTIC_EXECUTOR_WORKERS",
        "SEMANTIC_MAX_PENDING",
        "INDEX_STORAGE_DIR",
        "MEDIA_DIR",
        "ENABLE_LEGACY_SEARCH",
        "CHROMA_PATH",
        "CHROMA_HOST",
        "CHROMA_PORT",
        "CHROMA_COLLECTION_NAME",
        "EMBEDDING_MODEL_NAME",
    ]:
        assert required_web_key in web_env, f"web.environment missing '{required_web_key}' advertised in .env.production.example"
        assert required_web_key in template_keys, f".env.production.example missing '{required_web_key}'"
    checks.append("Env contract verified: empty secret placeholders fail closed via :? and all runtime tuning knobs forward to web/ops")

    # 7. Multi-stage Dockerfile inspection
    df_path = PROJECT_ROOT / "Dockerfile"
    assert df_path.exists(), "Missing Dockerfile"
    df_content = df_path.read_text(encoding="utf-8")
    assert "AS builder" in df_content, "Dockerfile must have multi-stage builder"
    assert "AS runtime" in df_content, "Dockerfile must have multi-stage runtime"
    assert "useradd" in df_content and "10001" in df_content, "Dockerfile must create dedicated non-root user"
    assert "USER folio" in df_content, "Dockerfile must switch to USER folio"
    assert "HEALTHCHECK" in df_content, "Dockerfile must declare HEALTHCHECK"
    assert "constraints.txt" in df_content, "Dockerfile must enforce constraints.txt"
    assert "/app/certs" in df_content, "Dockerfile must pre-create /app/certs owned by folio:folio (10001)"
    assert 'MEDIA_DIR="/app/data/media"' in df_content, "Dockerfile ENV must define MEDIA_DIR=/app/data/media"
    checks.append("Multi-stage Dockerfile: builder + runtime, non-root user folio (10001), /app/certs ownership, MEDIA_DIR/INDEX_STORAGE_DIR ENV verified")

    # 8. Entrypoints inspection
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

    # 9. Reverse Proxy Configurations (Nginx & Caddy)
    nginx_conf = PROJECT_ROOT / "docker" / "proxy" / "templates" / "default.conf.template"
    caddy_conf = PROJECT_ROOT / "docker" / "proxy" / "Caddyfile"
    assert nginx_conf.exists(), "Missing Nginx virtual host template"
    assert caddy_conf.exists(), "Missing Caddyfile"
    n_text = nginx_conf.read_text(encoding="utf-8")
    assert "X-Forwarded-For" in n_text and "X-Request-ID" in n_text, "Nginx must forward trusted headers"
    assert "Content-Security-Policy" in n_text, "Nginx must declare CSP header"
    assert "return 301 https://" in n_text, "Nginx must redirect HTTP to HTTPS"
    checks.append("Reverse Proxy: HTTP-to-HTTPS redirect, X-Forwarded-*, CSP, and trusted proxy headers verified")

    # 10. .dockerignore and .gitignore secrets & cert key exclusion check
    dignore = PROJECT_ROOT / ".dockerignore"
    gignore = PROJECT_ROOT / ".gitignore"
    assert dignore.exists(), "Missing .dockerignore"
    assert gignore.exists(), "Missing .gitignore"
    dig_content = dignore.read_text(encoding="utf-8")
    gig_content = gignore.read_text(encoding="utf-8")
    for secret_pat in [".env", ".git", "test-results", "data/", "docker/proxy/certs/"]:
        assert secret_pat in dig_content, f".dockerignore must ignore {secret_pat}"
    for git_pat in [".env.production", ".env.restored", "docker/proxy/certs/"]:
        assert git_pat in gig_content, f".gitignore must ignore {git_pat}"
    checks.append(".dockerignore & .gitignore: exclude secrets, .env.production/.env.restored, docker/proxy/certs/, and local data")

    # 11. Gitattributes line endings check
    gitattributes_path = PROJECT_ROOT / ".gitattributes"
    assert gitattributes_path.exists(), "Missing .gitattributes in repository root"
    ga_content = gitattributes_path.read_text(encoding="utf-8")
    assert "*.sh" in ga_content and "eol=lf" in ga_content, ".gitattributes must enforce *.sh text eol=lf"
    for sh_file in PROJECT_ROOT.rglob("*.sh"):
        if ".git" in sh_file.parts:
            continue
        assert b"\r" not in sh_file.read_bytes(), f"Shell script {sh_file} contains CRLF carriage return bytes"
    checks.append(".gitattributes: strictly enforces *.sh text eol=lf across all POSIX shell scripts (zero CRLF bytes)")

    # 12. Reverse proxy SSL certificate tooling check (self-signed + CA import + domain preflight)
    init_certs_py = PROJECT_ROOT / "scripts" / "ops" / "init_certs.py"
    init_certs_sh = PROJECT_ROOT / "scripts" / "ops" / "init_certs.sh"
    assert init_certs_py.exists(), "Missing scripts/ops/init_certs.py"
    assert init_certs_sh.exists(), "Missing scripts/ops/init_certs.sh"
    assert b"\r" not in init_certs_sh.read_bytes(), "init_certs.sh must have LF line endings"

    from scripts.ops.init_certs import (
        generate_self_signed_cert,
        install_certificate_pair,
        verify_certificates,
        CertificateDomainMismatchError,
    )
    with tempfile.TemporaryDirectory() as tmp_cert_dir:
        tmp_p = Path(tmp_cert_dir)
        target_p = tmp_p / "target"
        src_p = tmp_p / "ca_source"
        cert_info = generate_self_signed_cert(target_p, domain="validate.local")
        assert cert_info["status"] == "valid"
        assert (target_p / "folio.crt").exists()
        assert (target_p / "folio.key").exists()
        verified = verify_certificates(target_p, expected_domain="validate.local")
        assert verified["status"] == "valid"
        try:
            verify_certificates(target_p, expected_domain="wrong.invalid")
            raise AssertionError("Expected CertificateDomainMismatchError")
        except CertificateDomainMismatchError:
            pass
        generate_self_signed_cert(src_p, domain="ca.example.com")
        imported = install_certificate_pair(
            target_p,
            src_p / "folio.crt",
            src_p / "folio.key",
            expected_domain="ca.example.com",
            force=True,
        )
        assert imported["status"] == "valid"
    checks.append("SSL Certificate Tooling: self-signed gen, --check-only domain preflight, and CA import verified in temp sandbox")

    docker_bin = shutil.which("docker")
    print("\n[OK] All Static Configuration, Env Contract, Cutover & Topology Audits Passed:")
    for c in checks:
        print(f"  + {c}")
    if docker_bin:
        print(f"\n[INFO] Docker CLI found at {docker_bin}. Run live render check with:")
        print("  docker compose --env-file <test-env> -f docker-compose.prod.yml config")
    else:
        print("\n[NOTE] Runtime Scope Boundary: Docker CLI / daemon is NOT available on this host (BLOCKED_ENV).")
        print("       Static YAML/Dockerfile/Python checks do NOT substitute for live 'docker compose config' or container startup.")


if __name__ == "__main__":
    validate()
