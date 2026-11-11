"""
Round 4 Deployment Contract Tests (R4-01 Env Contract, R4-02 Cutover Storage/Rollback, R4-03 TLS Provisioning & Preflight).

Clean separation of verification scope:
- Parses .env.production.example and docker-compose.prod.yml and executes faithful Compose
  nested variable interpolation tests (plus runs real 'docker compose config' when Docker CLI is present).
- Spawns isolated Python subprocesses with resolved container environment variables to prove
  Settings, SearchService bounded executor pools, rate-limit flags, and fail-fast secret validation
  behave identically to configuration.
- Executes real scripts/ops/init_certs.py CLI subprocesses for missing, partial, domain-mismatch,
  non-clobbering, and CA certificate import flows.
- Executes real PostgreSQL 16 + storage sentinel cutover and switch-back integration drill via
  scripts/ops/restore.py CLI and separate FastAPI/TestClient web subprocesses.
"""

import os
import ssl
import sys
import json
import yaml
import shutil
import hashlib
import textwrap
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import pytest
from dotenv import dotenv_values
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from tests.conftest import test_db_url
from scripts.ops import backup
from scripts.ops.backup import perform_backup
from src.backend.models.auth import User
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category
from src.backend.search_index.manager import GenerationManager

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# Match the runbook's URL-safe secret generation and avoid Compose dollar interpolation.
STRONG_TEST_SECRET = "FolioTestSecret_K9mP2vL8xQzR5wY1bN7tC4jF_0123456789"


def _clean_subprocess_env(extra_env: Dict[str, str]) -> Dict[str, str]:
    """Builds an isolated OS environment without ambient Folio env leakage."""
    keep_keys = (
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LOCALAPPDATA",
        "HOME",
        "USERPROFILE",
        "POSTGRES_BIN_PATH",
    )
    env = {k: os.environ[k] for k in keep_keys if k in os.environ}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.update({k: str(v) for k, v in extra_env.items()})
    return env


class ComposeInterpolationError(ValueError):
    """Raised when Compose required interpolation (${VAR:?...}) fails."""


def _parse_dotenv_file(env_path: Path) -> Dict[str, str]:
    """Parses Compose-style .env lines cleanly (key=value, stripping matching quotes)."""
    env: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env[k] = v
    return env


def _format_dotenv_value(value: str) -> str:
    """Formats a .env assignment value compatibly with both Docker Compose and POSIX Bash source."""
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or any(ch in value for ch in ('"', "'", "#", ";", "$")):
        if "'" not in value:
            return f"'{value}'"
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
        return f'"{escaped}"'
    return value


def _resolve_posix_bash() -> Optional[str]:
    """Resolves a working POSIX Bash binary (Git Bash on Windows or /bin/bash on POSIX), skipping unconfigured WSL stubs."""
    candidates = []
    if os.name == "nt":
        for root_env in ("ProgramFiles", "ProgramW6432", "LocalAppData"):
            base = os.environ.get(root_env)
            if base:
                candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
                candidates.append(Path(base) / "Programs" / "Git" / "bin" / "bash.exe")
        candidates.append(Path("C:/Program Files/Git/bin/bash.exe"))
    else:
        candidates.append(Path("/bin/bash"))
        candidates.append(Path("/usr/bin/bash"))
    which_bash = shutil.which("bash")
    if which_bash:
        candidates.append(Path(which_bash))

    seen = set()
    for cand in candidates:
        cand_str = str(cand)
        if cand_str in seen or not cand.is_file():
            continue
        seen.add(cand_str)
        try:
            probe = subprocess.run(
                [cand_str, "-c", "printf OK"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0 and probe.stdout == "OK":
                return cand_str
        except Exception:
            continue
    return None


def _interpolate_compose_str(expr: str, env: Dict[str, str]) -> str:
    """
    Faithful recursive Compose v2 interpolation evaluator supporting:
    $$ -> $, ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?err}, ${VAR?err}
    including nested ${...} inside default/error segments.
    """
    out = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch != "$":
            out.append(ch)
            i += 1
            continue
        if i + 1 < n and expr[i + 1] == "$":
            out.append("$")
            i += 2
            continue
        if i + 1 < n and expr[i + 1] == "{":
            # Scan balanced braces
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if expr[j] == "$" and j + 1 < n and expr[j + 1] == "$":
                    j += 2
                    continue
                if expr[j] == "{":
                    depth += 1
                elif expr[j] == "}":
                    depth -= 1
                j += 1
            if depth != 0:
                raise ComposeInterpolationError(f"Unclosed variable brace in '{expr}'")
            inner = expr[i + 2 : j - 1]
            # Parse operator at top brace level
            op = None
            op_idx = None
            sub_depth = 0
            idx = 0
            while idx < len(inner):
                if inner[idx] == "{":
                    sub_depth += 1
                elif inner[idx] == "}":
                    sub_depth -= 1
                elif sub_depth == 0:
                    if inner[idx : idx + 2] in (":-", ":?"):
                        op = inner[idx : idx + 2]
                        op_idx = idx
                        break
                    if inner[idx] in ("-", "?") and idx > 0:
                        op = inner[idx]
                        op_idx = idx
                        break
                idx += 1

            if op is None:
                var_name = inner.strip()
                out.append(env.get(var_name, ""))
            else:
                var_name = inner[:op_idx].strip()
                rhs = inner[op_idx + len(op) :]
                is_set = var_name in env
                val = env.get(var_name, "")
                is_non_empty = is_set and val != ""
                if op == ":-":
                    out.append(val if is_non_empty else _interpolate_compose_str(rhs, env))
                elif op == "-":
                    out.append(val if is_set else _interpolate_compose_str(rhs, env))
                elif op == ":?":
                    if not is_non_empty:
                        err_msg = _interpolate_compose_str(rhs, env)
                        raise ComposeInterpolationError(f"{var_name}: {err_msg}")
                    out.append(val)
                elif op == "?":
                    if not is_set:
                        err_msg = _interpolate_compose_str(rhs, env)
                        raise ComposeInterpolationError(f"{var_name}: {err_msg}")
                    out.append(val)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _render_compose_with_env(compose_path: Path, env: Dict[str, str]) -> Dict[str, Any]:
    """Resolves service environment/command/volumes/top-level volumes from docker-compose.prod.yml."""
    raw = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return _interpolate_compose_str(node, env)
        return node

    return walk(raw)


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_signed_cert_bundle(
    out_dir: Path,
    domains: list[str],
    days_valid: int = 90,
    start_offset_days: int = 0,
    include_intermediate_chain: bool = False,
) -> tuple[Path, Path]:
    """Creates real X.509 PEM cert (or leaf+CA chain) and matching RSA-2048 key in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    not_before = now + timedelta(days=start_offset_days) - timedelta(minutes=5)
    not_after = not_before + timedelta(days=days_valid)

    san_names = [x509.DNSName(d) for d in domains]
    if include_intermediate_chain:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Folio Test CA")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        leaf_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])])
        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(leaf_subject)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_before)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        cert_pem = (
            leaf_cert.public_bytes(serialization.Encoding.PEM)
            + ca_cert.public_bytes(serialization.Encoding.PEM)
        )
    else:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_before)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    crt_path = out_dir / "fullchain.pem"
    key_path = out_dir / "privkey.pem"
    crt_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    return crt_path, key_path


@pytest.fixture
def ensure_pg_bin_path(monkeypatch):
    """Ensures pg_dump and psql binaries are resolvable in PATH or standard test dir."""
    if backup.find_pg_tool("pg_dump") and backup.find_pg_tool("psql"):
        return
    candidate = Path("F:/dpl13.10/folio-live-runtime/pgsql/bin")
    if candidate.is_dir():
        monkeypatch.setenv("POSTGRES_BIN_PATH", str(candidate))
    if not backup.find_pg_tool("pg_dump") or not backup.find_pg_tool("psql"):
        pytest.skip("PostgreSQL client tools (pg_dump/psql) unavailable")


# ==============================================================================
# R4-01: Env Contract & Runtime Configuration Propagation
# ==============================================================================


class TestR401EnvContract:
    def test_compose_interpolation_and_live_subprocess_honor_non_default_env_file(self, tmp_path):
        """
        Simulates a clean host with ONLY a populated .env.test file (copied from .env.production.example)
        using non-default tuning values, verifies Compose interpolation reaches services cleanly, and
        boots a real Python subprocess to confirm Settings + bounded semantic executor apply them.
        """
        compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
        template_path = PROJECT_ROOT / ".env.production.example"
        env_values = _parse_dotenv_file(template_path)

        env_values.update({
            "APP_ENV": "production",
            "APP_SECRET": STRONG_TEST_SECRET,
            "DOMAIN_NAME": "folio.unit.test",
            "STAGING_DOMAIN": "staging.folio.unit.test",
            "POSTGRES_DB": "folio_custom_db",
            "POSTGRES_USER": "folio_custom_user",
            "POSTGRES_PASSWORD": "StrongCustomDbPass2026",
            "DATABASE_URL": "",
            "COOKIE_SECURE": "true",
            "CORS_ALLOWED_ORIGINS": "https://folio.unit.test",
            "RATE_LIMIT_ENABLED": "false",
            "SEARCH_CONTEXT_TTL_MINUTES": "27",
            "SEARCH_TIMEOUT_SECONDS": "11.5",
            "SEMANTIC_EXECUTOR_WORKERS": "4",
            "SEMANTIC_MAX_PENDING": "6",
        })

        test_env_file = tmp_path / ".env.production.test"
        test_env_file.write_text(
            "\n".join(f"{k}={_format_dotenv_value(v)}" for k, v in env_values.items()) + "\n",
            encoding="utf-8",
        )

        # If Docker CLI exists on host (e.g. Linux CI), validate real 'docker compose config' render too
        docker_bin = shutil.which("docker")
        if docker_bin:
            proc = subprocess.run(
                [
                    docker_bin,
                    "compose",
                    "--env-file",
                    str(test_env_file),
                    "-f",
                    str(compose_path),
                    "--profile",
                    "tools",
                    "config",
                    "--format",
                    "json",
                ],
                env=_clean_subprocess_env({}),
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            assert proc.returncode == 0, f"docker compose config failed: {proc.stderr}"
            rendered = json.loads(proc.stdout)
        else:
            rendered = _render_compose_with_env(compose_path, _parse_dotenv_file(test_env_file))

        web_env = rendered["services"]["web"]["environment"]
        assert web_env["APP_ENV"] == "production"
        assert web_env["APP_SECRET"] == STRONG_TEST_SECRET
        assert (
            web_env["DATABASE_URL"]
            == "postgresql+psycopg://folio_custom_user:StrongCustomDbPass2026@db:5432/folio_custom_db"
        )
        assert str(web_env["RATE_LIMIT_ENABLED"]).lower() == "false"
        assert str(web_env["SEARCH_CONTEXT_TTL_MINUTES"]) == "27"
        assert str(web_env["SEARCH_TIMEOUT_SECONDS"]) == "11.5"
        assert str(web_env["SEMANTIC_EXECUTOR_WORKERS"]) == "4"
        assert str(web_env["SEMANTIC_MAX_PENDING"]) == "6"
        assert (
            rendered["services"]["proxy"]["environment"]["HSTS_HEADER"]
            == 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
        )
        assert (
            rendered["services"]["migration"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"]
            == "Super Administrator"
        )
        assert (
            rendered["services"]["ops"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"]
            == "Super Administrator"
        )

        # Now prove in an isolated Python subprocess that Settings + FastAPI lifespan + executor read these exact values
        inspect_code = textwrap.dedent(f"""\
            import json, sys
            sys.path.insert(0, {str(PROJECT_ROOT)!r})
            from fastapi.testclient import TestClient
            from src.backend.main import app
            from src.backend.core.config import settings
            from src.backend.services.search.search_service import _get_semantic_executor_state
            with TestClient(app):
                state = _get_semantic_executor_state()
                print(json.dumps({{
                    'APP_ENV': settings.APP_ENV,
                    'RATE_LIMIT_ENABLED': settings.RATE_LIMIT_ENABLED,
                    'SEARCH_CONTEXT_TTL_MINUTES': settings.SEARCH_CONTEXT_TTL_MINUTES,
                    'SEARCH_TIMEOUT_SECONDS': settings.SEARCH_TIMEOUT_SECONDS,
                    'SEMANTIC_EXECUTOR_WORKERS': settings.SEMANTIC_EXECUTOR_WORKERS,
                    'SEMANTIC_MAX_PENDING': settings.SEMANTIC_MAX_PENDING,
                    'executor_max_workers': state.max_workers,
                    'executor_max_pending': state.max_pending,
                    'executor_capacity': state.capacity,
                }}))
        """)
        sub_env = _clean_subprocess_env({k: str(v) for k, v in web_env.items()})
        sub_proc = subprocess.run(
            [sys.executable, "-c", inspect_code],
            env=sub_env,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert sub_proc.returncode == 0, f"Subprocess failed: {sub_proc.stderr}"
        parsed_runtime = json.loads(sub_proc.stdout.strip().splitlines()[-1])
        assert parsed_runtime == {
            "APP_ENV": "production",
            "RATE_LIMIT_ENABLED": False,
            "SEARCH_CONTEXT_TTL_MINUTES": 27,
            "SEARCH_TIMEOUT_SECONDS": 11.5,
            "SEMANTIC_EXECUTOR_WORKERS": 4,
            "SEMANTIC_MAX_PENDING": 6,
            "executor_max_workers": 4,
            "executor_max_pending": 6,
            "executor_capacity": 10,
        }

    def test_missing_or_placeholder_secrets_fail_closed(self, tmp_path):
        """
        Verbatim .env.production.example (empty APP_SECRET & POSTGRES_PASSWORD) MUST fail Compose
        interpolation cleanly, and empty/placeholder secrets fail Settings.validate_production() in subprocess.
        """
        compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
        template_vals = _parse_dotenv_file(PROJECT_ROOT / ".env.production.example")

        # 1. Missing APP_SECRET fails Compose interpolation
        with pytest.raises(ComposeInterpolationError, match="APP_SECRET"):
            _render_compose_with_env(compose_path, dict(template_vals))

        # 2. Providing APP_SECRET but leaving POSTGRES_PASSWORD empty fails Compose interpolation
        only_app_secret = dict(template_vals)
        only_app_secret["APP_SECRET"] = STRONG_TEST_SECRET
        with pytest.raises(ComposeInterpolationError, match="POSTGRES_PASSWORD"):
            _render_compose_with_env(compose_path, only_app_secret)

        # 3. Real Docker Compose CLI check when available
        docker_bin = shutil.which("docker")
        if docker_bin:
            incomplete_env = tmp_path / ".env.incomplete"
            # Check each required secret independently; Compose may visit services in any order.
            for missing_secret in ("APP_SECRET", "POSTGRES_PASSWORD"):
                values = {
                    "APP_ENV": "production",
                    "APP_SECRET": STRONG_TEST_SECRET,
                    "POSTGRES_PASSWORD": "StrongCustomDbPass2026",
                }
                values[missing_secret] = ""
                incomplete_env.write_text(
                    "\n".join(f"{key}={_format_dotenv_value(value)}" for key, value in values.items()) + "\n",
                    encoding="utf-8",
                )
                proc = subprocess.run(
                    [docker_bin, "compose", "--env-file", str(incomplete_env), "-f", str(compose_path), "config"],
                    env=_clean_subprocess_env({}),
                    capture_output=True,
                    text=True,
                    cwd=str(PROJECT_ROOT),
                    timeout=30,
                )
                assert proc.returncode != 0
                assert missing_secret in (proc.stderr + proc.stdout)

        # 4. Empty or placeholder APP_SECRET in Python production subprocess fails cleanly
        for bad_secret in [
            "",
            "replace_with_a_secure_random_64_character_hex_string_in_production_12345",
        ]:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        f"import sys; sys.path.insert(0, {str(PROJECT_ROOT)!r}); "
                        "from fastapi.testclient import TestClient; "
                        "from src.backend.main import app; "
                        "TestClient(app).__enter__()"
                    ),
                ],
                env=_clean_subprocess_env({
                    "APP_ENV": "production",
                    "COOKIE_SECURE": "true",
                    "APP_SECRET": bad_secret,
                    "CORS_ALLOWED_ORIGINS": "https://folio.unit.test",
                    "DATABASE_URL": "postgresql+psycopg://folio_prod:StrongPass@127.0.0.1:5432/folio",
                }),
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert proc.returncode != 0
            assert "APP_SECRET" in proc.stderr

    def test_host_python_cli_does_not_auto_load_dotenv_production(self, tmp_path):
        """
        Confirms Python CLI Settings() does NOT implicitly auto-load '.env.production' from CWD;
        host CLIs must export variables explicitly (or run inside Compose 'ops' runner).
        """
        dotenv_prod = tmp_path / ".env.production"
        dotenv_prod.write_text(
            "\n".join([
                "APP_ENV=production",
                f"APP_SECRET={STRONG_TEST_SECRET}",
                "SEARCH_TIMEOUT_SECONDS=19.5",
                "RATE_LIMIT_ENABLED=false",
            ]) + "\n",
            encoding="utf-8",
        )
        inspect_code = textwrap.dedent(f"""\
            import json, sys
            sys.path.insert(0, {str(PROJECT_ROOT)!r})
            from src.backend.core.config import Settings
            s = Settings()
            print(json.dumps({{
                'APP_ENV': s.APP_ENV,
                'SEARCH_TIMEOUT_SECONDS': s.SEARCH_TIMEOUT_SECONDS,
                'RATE_LIMIT_ENABLED': s.RATE_LIMIT_ENABLED,
            }}))
        """)
        proc = subprocess.run(
            [sys.executable, "-c", inspect_code],
            env=_clean_subprocess_env({}),
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, f"Subprocess failed: {proc.stderr}"
        parsed = json.loads(proc.stdout.strip().splitlines()[-1])
        assert parsed["APP_ENV"] == "development"
        assert parsed["SEARCH_TIMEOUT_SECONDS"] == 5.0
        assert parsed["RATE_LIMIT_ENABLED"] is True

    def test_env_production_template_compatible_with_bash_source_and_compose(self, tmp_path):
        """
        Regression for Round 4 P3:
        Verifies a literal copy of .env.production.example populated with dummy secrets loads
        identically in python-dotenv, Compose interpolation, AND real POSIX Bash 'set -a && source ... && set +a'
        without command-not-found errors or losing HSTS_HEADER / ADMIN_BOOTSTRAP_DISPLAY_NAME.
        """
        expected_hsts = 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
        expected_display_name = "Super Administrator"
        dummy_secret = "DummyReviewSecret_AlphaBetaGamma_1234567890"
        dummy_pg_pass = "DummyPgPass_2026_SafeChars"

        template_text = (PROJECT_ROOT / ".env.production.example").read_text(encoding="utf-8")
        populated_lines = []
        for line in template_text.splitlines():
            if line == "APP_SECRET=":
                populated_lines.append(f"APP_SECRET={dummy_secret}")
            elif line == "POSTGRES_PASSWORD=":
                populated_lines.append(f"POSTGRES_PASSWORD={dummy_pg_pass}")
            else:
                populated_lines.append(line)

        env_copy = tmp_path / ".env.production.dummy"
        env_copy.write_bytes(("\n".join(populated_lines) + "\n").encode("utf-8"))

        # 1. Verify python-dotenv and internal parser agree exactly with expected values
        dotenv_parsed = dotenv_values(env_copy)
        internal_parsed = _parse_dotenv_file(env_copy)
        assert dotenv_parsed["HSTS_HEADER"] == expected_hsts
        assert internal_parsed["HSTS_HEADER"] == expected_hsts
        assert dotenv_parsed["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name
        assert internal_parsed["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name

        # 2. Verify Compose interpolation (and real docker compose config if present) preserves exact values
        compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
        rendered = _render_compose_with_env(compose_path, internal_parsed)
        assert rendered["services"]["proxy"]["environment"]["HSTS_HEADER"] == expected_hsts
        assert rendered["services"]["migration"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name
        assert rendered["services"]["ops"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name

        docker_bin = shutil.which("docker")
        if docker_bin:
            dc_proc = subprocess.run(
                [
                    docker_bin,
                    "compose",
                    "--env-file",
                    str(env_copy),
                    "-f",
                    str(compose_path),
                    "--profile",
                    "tools",
                    "config",
                    "--format",
                    "json",
                ],
                env=_clean_subprocess_env({}),
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            assert dc_proc.returncode == 0, dc_proc.stderr
            dc_rendered = json.loads(dc_proc.stdout)
            assert dc_rendered["services"]["proxy"]["environment"]["HSTS_HEADER"] == expected_hsts
            assert dc_rendered["services"]["migration"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name
            assert dc_rendered["services"]["ops"]["environment"]["ADMIN_BOOTSTRAP_DISPLAY_NAME"] == expected_display_name

        # 3. Verify real POSIX Bash 'set -a && source ... && set +a' in clean environment
        bash_bin = _resolve_posix_bash()
        assert bash_bin is not None, "Expected a working POSIX Bash (Git Bash on Windows or /bin/bash on Linux)"
        bash_env_path = env_copy.as_posix()
        probe_script = (
            f'set -a && source "{bash_env_path}" && set +a && '
            'printf "HSTS=%s\\nNAME=%s\\nAPP_SECRET=%s\\nDOMAIN=%s\\n" '
            '"${HSTS_HEADER-<unset>}" "${ADMIN_BOOTSTRAP_DISPLAY_NAME-<unset>}" '
            '"${APP_SECRET-<unset>}" "${DOMAIN_NAME-<unset>}"'
        )
        bash_proc = subprocess.run(
            [bash_bin, "-c", probe_script],
            env=_clean_subprocess_env({}),
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert bash_proc.returncode == 0, f"Bash source failed: {bash_proc.stderr}"
        assert bash_proc.stderr == "", f"Unexpected stderr during Bash source: {bash_proc.stderr}"
        out_map = dict(line.split("=", 1) for line in bash_proc.stdout.splitlines() if "=" in line)
        assert out_map["HSTS"] == expected_hsts
        assert out_map["NAME"] == expected_display_name
        assert out_map["APP_SECRET"] == dummy_secret
        assert out_map["DOMAIN"] == "folio.example.com"

        # 4. Also verify staging HSTS disable value '# HSTS disabled in staging' in Bash source
        staging_env = tmp_path / ".env.staging.dummy"
        staging_env.write_bytes(
            ("\n".join(populated_lines) + "\nHSTS_HEADER='# HSTS disabled in staging'\n").encode("utf-8")
        )
        staging_bash = subprocess.run(
            [
                bash_bin,
                "-c",
                f'set -a && source "{staging_env.as_posix()}" && set +a && printf "%s" "${{HSTS_HEADER-<unset>}}"',
            ],
            env=_clean_subprocess_env({}),
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert staging_bash.returncode == 0 and staging_bash.stderr == ""
        assert staging_bash.stdout == "# HSTS disabled in staging"


# ==============================================================================
# R4-03: TLS Certificate Provisioning, Preflight, Domain Match & CA Import CLI
# ==============================================================================


class TestR403TlsProvisioningCli:
    def _run_cert_cli(self, *args: str, env_overrides: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        env = _clean_subprocess_env(env_overrides or {})
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "ops" / "init_certs.py"), *args],
            env=env,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_empty_and_partial_cert_volume_fail_closed_and_preserve_existing(self, tmp_path):
        cert_dir = tmp_path / "proxy_certs_vol"
        cert_dir.mkdir()

        # 1. Empty volume fails preflight cleanly
        res_empty = self._run_cert_cli(
            "--check-only", "--expected-domain", "folio.example.com",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_empty.returncode != 0
        assert "Missing certificate file" in res_empty.stderr

        # 2. Partial cert (folio.crt exists without folio.key) is NOT silently clobbered
        sentinel_crt = cert_dir / "folio.crt"
        sentinel_crt.write_bytes(b"SENTINEL_PARTIAL_CERT_BYTES")
        before_hash = _sha256_bytes(sentinel_crt)

        res_partial = self._run_cert_cli(
            "--domain", "folio.example.com",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_partial.returncode != 0
        assert "Incomplete certificate state" in res_partial.stderr
        assert _sha256_bytes(sentinel_crt) == before_hash

        # Same when only folio.key exists without folio.crt
        sentinel_crt.unlink()
        sentinel_key = cert_dir / "folio.key"
        sentinel_key.write_bytes(b"SENTINEL_PARTIAL_KEY_BYTES")
        key_hash = _sha256_bytes(sentinel_key)

        res_partial_key = self._run_cert_cli(
            "--domain", "folio.example.com",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_partial_key.returncode != 0
        assert "Incomplete certificate state" in res_partial_key.stderr
        assert _sha256_bytes(sentinel_key) == key_hash

    def test_self_signed_init_idempotency_domain_preflight_and_ca_import_cli(self, tmp_path):
        cert_dir = tmp_path / "proxy_certs_vol"

        # 1. First-deploy self-signed init via CERT_DIR (mirroring docker compose run --rm cert-init)
        res_init = self._run_cert_cli(
            env_overrides={
                "CERT_DIR": str(cert_dir),
                "DOMAIN_NAME": "staging.folio.test",
                "STAGING_DOMAIN": "alt.folio.test",
            }
        )
        assert res_init.returncode == 0, res_init.stderr
        crt_path = cert_dir / "folio.crt"
        key_path = cert_dir / "folio.key"
        assert crt_path.is_file() and key_path.is_file()
        init_crt_hash = _sha256_bytes(crt_path)
        init_key_hash = _sha256_bytes(key_path)

        if os.name == "posix":
            assert (crt_path.stat().st_mode & 0o777) == 0o644
            assert (key_path.stat().st_mode & 0o777) == 0o600

        # 2. Preflight succeeds for matching domain and FAILS for mismatched domain
        res_ok = self._run_cert_cli(
            "--check-only", "--expected-domain", "staging.folio.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_ok.returncode == 0, res_ok.stderr

        res_wrong_domain = self._run_cert_cli(
            "--check-only", "--expected-domain", "wrong.example.org",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_wrong_domain.returncode != 0
        assert "does not match expected domain" in res_wrong_domain.stderr

        # 3. Re-running init without --force must NOT clobber existing cert/key
        res_reinit = self._run_cert_cli(
            env_overrides={
                "CERT_DIR": str(cert_dir),
                "DOMAIN_NAME": "staging.folio.test",
            }
        )
        assert res_reinit.returncode == 0, res_reinit.stderr
        assert _sha256_bytes(crt_path) == init_crt_hash
        assert _sha256_bytes(key_path) == init_key_hash

        # 4. Importing CA cert with wrong domain or expired cert MUST fail closed WITHOUT touching existing certs
        expired_crt, expired_key = _create_signed_cert_bundle(
            tmp_path / "expired", ["prod.folio.test"], days_valid=1, start_offset_days=-30
        )
        res_expired = self._run_cert_cli(
            "--import-cert", str(expired_crt), "--import-key", str(expired_key),
            "--expected-domain", "prod.folio.test", "--force",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_expired.returncode != 0
        assert "expired" in res_expired.stderr.lower()
        assert _sha256_bytes(crt_path) == init_crt_hash

        valid_crt, valid_key = _create_signed_cert_bundle(
            tmp_path / "valid_ca",
            ["prod.folio.test", "www.prod.folio.test"],
            days_valid=180,
            include_intermediate_chain=True,
        )
        res_bad_dom = self._run_cert_cli(
            "--import-cert", str(valid_crt), "--import-key", str(valid_key),
            "--expected-domain", "unrelated.example.com", "--force",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_bad_dom.returncode != 0
        assert "does not match expected domain" in res_bad_dom.stderr
        assert _sha256_bytes(crt_path) == init_crt_hash

        # 5. Valid CA import WITHOUT --force refuses overwrite
        res_no_force = self._run_cert_cli(
            "--import-cert", str(valid_crt), "--import-key", str(valid_key),
            "--expected-domain", "prod.folio.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_no_force.returncode != 0
        assert "already exist" in res_no_force.stderr
        assert _sha256_bytes(crt_path) == init_crt_hash

        # 6. Valid CA import WITH --force installs full leaf+CA chain cleanly and passes preflight
        res_import_ok = self._run_cert_cli(
            "--import-cert", str(valid_crt), "--import-key", str(valid_key),
            "--expected-domain", "prod.folio.test", "--force",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_import_ok.returncode == 0, res_import_ok.stderr
        assert crt_path.read_bytes() == valid_crt.read_bytes()
        assert key_path.read_bytes() == valid_key.read_bytes()
        res_preflight_ca = self._run_cert_cli(
            "--check-only", "--expected-domain", "www.prod.folio.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_preflight_ca.returncode == 0, res_preflight_ca.stderr

    def test_fullchain_with_malformed_non_leaf_der_rejected_and_preserves_existing_on_force(self, tmp_path):
        """
        Regression for Round 4 P2:
        Valid leaf/key + appended CERTIFICATE block containing valid base64 'YWJj' (invalid DER 'abc')
        MUST be rejected on import (with and without --force) BEFORE touching destination files,
        keeping existing cert/key SHA-256 identical and still loadable by OpenSSL.
        """
        cert_dir = tmp_path / "proxy_certs_vol"

        # 1. Valid initial pair installed and verified loadable via SSLContext
        res_init = self._run_cert_cli(
            env_overrides={
                "CERT_DIR": str(cert_dir),
                "DOMAIN_NAME": "folio.example.test",
            }
        )
        assert res_init.returncode == 0, res_init.stderr
        crt_path = cert_dir / "folio.crt"
        key_path = cert_dir / "folio.key"
        orig_crt_hash = _sha256_bytes(crt_path)
        orig_key_hash = _sha256_bytes(key_path)
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(crt_path), str(key_path))

        # 2. Build malformed fullchain: valid leaf + base64 'YWJj' (invalid DER) block
        src_dir = tmp_path / "bad_bundle_src"
        leaf_crt, leaf_key = _create_signed_cert_bundle(src_dir, ["folio.example.test"])
        bad_bundle = src_dir / "bad_fullchain.pem"
        bad_bundle.write_bytes(
            leaf_crt.read_bytes()
            + b"\n-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n"
        )

        # 3. Import into fresh empty directory MUST fail and leave target directory untouched
        fresh_dir = tmp_path / "fresh_target"
        res_fresh = self._run_cert_cli(
            "--import-cert", str(bad_bundle), "--import-key", str(leaf_key),
            "--expected-domain", "folio.example.test",
            env_overrides={"CERT_DIR": str(fresh_dir)},
        )
        assert res_fresh.returncode != 0
        assert not (fresh_dir / "folio.crt").exists()
        assert not (fresh_dir / "folio.key").exists()

        # 4. Import over existing pair WITHOUT --force MUST fail without modifying hashes
        res_no_force = self._run_cert_cli(
            "--import-cert", str(bad_bundle), "--import-key", str(leaf_key),
            "--expected-domain", "folio.example.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_no_force.returncode != 0
        assert _sha256_bytes(crt_path) == orig_crt_hash
        assert _sha256_bytes(key_path) == orig_key_hash

        # 5. Import over existing pair WITH --force MUST fail without modifying hashes, and OpenSSL still loads old pair
        res_force = self._run_cert_cli(
            "--import-cert", str(bad_bundle), "--import-key", str(leaf_key),
            "--expected-domain", "folio.example.test", "--force",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_force.returncode != 0
        assert _sha256_bytes(crt_path) == orig_crt_hash
        assert _sha256_bytes(key_path) == orig_key_hash
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(crt_path), str(key_path))

    def test_check_only_rejects_corrupted_or_truncated_non_leaf_fullchain(self, tmp_path):
        """
        Regression for Round 4 P2:
        --check-only MUST reject bundles where the leaf is valid and matches domain/key,
        but a subsequent PEM block has invalid DER ('YWJj'), truncated framing, or non-cert PEM block.
        """
        src_dir = tmp_path / "src"
        leaf_crt, leaf_key = _create_signed_cert_bundle(src_dir, ["folio.example.test"])
        leaf_bytes = leaf_crt.read_bytes()
        key_bytes = leaf_key.read_bytes()

        malformed_payloads = {
            "invalid_der_ywjj": leaf_bytes + b"\n-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n",
            "truncated_non_leaf": leaf_bytes + b"\n-----BEGIN CERTIFICATE-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A\n",
            "non_cert_pem_block": leaf_bytes + b"\n" + key_bytes,
        }

        for name, payload in malformed_payloads.items():
            # Import must fail
            import_dir = tmp_path / f"import_{name}"
            bad_crt = tmp_path / f"{name}.crt"
            bad_crt.write_bytes(payload)
            res_import = self._run_cert_cli(
                "--import-cert", str(bad_crt), "--import-key", str(leaf_key),
                "--expected-domain", "folio.example.test",
                env_overrides={"CERT_DIR": str(import_dir)},
            )
            assert res_import.returncode != 0, f"Import unexpectedly accepted {name}"

            # --check-only on installed-looking dir must fail too
            check_dir = tmp_path / f"check_{name}"
            check_dir.mkdir()
            (check_dir / "folio.crt").write_bytes(payload)
            (check_dir / "folio.key").write_bytes(key_bytes)
            res_check = self._run_cert_cli(
                "--check-only", "--expected-domain", "folio.example.test",
                env_overrides={"CERT_DIR": str(check_dir)},
            )
            assert res_check.returncode != 0, f"--check-only unexpectedly accepted {name}"

    def test_valid_multi_cert_fullchain_imports_preserves_bytes_and_loads_in_openssl(self, tmp_path):
        """
        Regression for Round 4 P2:
        Valid 3-certificate fullchain (leaf -> intermediate CA -> root CA) imports cleanly,
        preserves exact bundle bytes (no intermediate stripping), passes --check-only,
        and loads via ssl.SSLContext.load_cert_chain without requiring OS trust store membership.
        """
        now = datetime.now(timezone.utc)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        inter_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Folio Private Root CA")])
        inter_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Folio Private Intermediate CA")])
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "chain.folio.test")])

        root_cert = (
            x509.CertificateBuilder()
            .subject_name(root_name)
            .issuer_name(root_name)
            .public_key(root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
            .sign(root_key, hashes.SHA256())
        )
        inter_cert = (
            x509.CertificateBuilder()
            .subject_name(inter_name)
            .issuer_name(root_name)
            .public_key(inter_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now + timedelta(days=1825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(root_key, hashes.SHA256())
        )
        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(inter_name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("chain.folio.test")]), critical=False)
            .sign(inter_key, hashes.SHA256())
        )

        src_dir = tmp_path / "multi_chain_src"
        src_dir.mkdir()
        fullchain_bytes = (
            leaf_cert.public_bytes(serialization.Encoding.PEM)
            + inter_cert.public_bytes(serialization.Encoding.PEM)
            + root_cert.public_bytes(serialization.Encoding.PEM)
        )
        key_bytes = leaf_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        src_crt = src_dir / "fullchain.pem"
        src_key = src_dir / "privkey.pem"
        src_crt.write_bytes(fullchain_bytes)
        src_key.write_bytes(key_bytes)

        cert_dir = tmp_path / "proxy_certs_chain"
        res_import = self._run_cert_cli(
            "--import-cert", str(src_crt), "--import-key", str(src_key),
            "--expected-domain", "chain.folio.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_import.returncode == 0, res_import.stderr
        assert (cert_dir / "folio.crt").read_bytes() == fullchain_bytes
        assert (cert_dir / "folio.key").read_bytes() == key_bytes

        res_check = self._run_cert_cli(
            "--check-only", "--expected-domain", "chain.folio.test",
            env_overrides={"CERT_DIR": str(cert_dir)},
        )
        assert res_check.returncode == 0, res_check.stderr
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(
            str(cert_dir / "folio.crt"),
            str(cert_dir / "folio.key"),
        )


# ==============================================================================
# R4-02: Non-Destructive Storage Cutover & Switch-Back Drill (PG16 + Index/Media)
# ==============================================================================


class TestR402StorageCutoverAndSwitchBack:
    def test_compose_cutover_volumes_switch_all_storage_consumers_together(self):
        """
        Verifies via Compose interpolation that overriding FOLIO_INDEX_VOLUME and FOLIO_MEDIA_VOLUME
        switches web, worker, migration, and ops simultaneously while keeping baseline volumes intact.
        """
        compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
        base_vals = _parse_dotenv_file(PROJECT_ROOT / ".env.production.example")
        base_vals.update({
            "APP_SECRET": STRONG_TEST_SECRET,
            "POSTGRES_PASSWORD": "StrongDbPassword_123!",
        })
        base_render = _render_compose_with_env(compose_path, base_vals)

        cutover_vals = dict(base_vals)
        cutover_vals.update({
            "DATABASE_URL": "postgresql+psycopg://folio_prod_user:StrongDbPassword_123!@db:5432/folio_restored_20261110",
            "FOLIO_INDEX_VOLUME": "folio-index-data-restored-20261110",
            "FOLIO_MEDIA_VOLUME": "folio-media-data-restored-20261110",
        })
        cutover_render = _render_compose_with_env(compose_path, cutover_vals)

        # Baseline volumes untouched in baseline profile
        assert base_render["volumes"]["folio-index-data"]["name"] == "folio-index-data"
        assert base_render["volumes"]["folio-media-data"]["name"] == "folio-media-data"

        # Cutover profile switches effective external volume names while container paths stay identical
        assert cutover_render["volumes"]["folio-index-data"]["name"] == "folio-index-data-restored-20261110"
        assert cutover_render["volumes"]["folio-media-data"]["name"] == "folio-media-data-restored-20261110"
        for svc in ("web", "worker", "migration", "ops"):
            svc_cfg = cutover_render["services"][svc]
            assert any(v.startswith("folio-index-data:/app/data/search_index") for v in svc_cfg["volumes"])
            assert any(v.startswith("folio-media-data:/app/data/media") for v in svc_cfg["volumes"])
            assert svc_cfg["environment"]["INDEX_STORAGE_DIR"] == "/app/data/search_index/generations"
            assert svc_cfg["environment"]["MEDIA_DIR"] == "/app/data/media"
            assert "folio_restored_20261110" in svc_cfg["environment"]["DATABASE_URL"]

    def test_restore_post_migration_escapes_percent_encoded_password(self, monkeypatch):
        """
        Verifies scripts.ops.restore.run_post_restore_migrations escapes '%' as '%%' in
        ConfigParser sqlalchemy.url so URL-encoded DB passwords (e.g. 'p%40ss') never crash Alembic.
        """
        from alembic import command as alembic_command
        from scripts.ops.restore import run_post_restore_migrations

        captured = {}

        def fake_upgrade(cfg, rev):
            captured["raw_url"] = cfg.get_section_option("alembic", "sqlalchemy.url", None)
            captured["main_opt_raw"] = cfg.file_config.get("alembic", "sqlalchemy.url", raw=True)
            captured["rev"] = rev
            captured["cmd_opts"] = cfg.cmd_opts

        monkeypatch.setattr(alembic_command, "upgrade", fake_upgrade)
        encoded_url = "postgresql+psycopg://folio_user:p%40ss%25word@127.0.0.1:5432/folio_restored_1"
        run_post_restore_migrations(encoded_url)
        assert captured["rev"] == "head"
        assert captured["main_opt_raw"] == "postgresql+psycopg://folio_user:p%%40ss%%25word@127.0.0.1:5432/folio_restored_1"
        assert captured["raw_url"] == encoded_url

    def test_real_pg16_restore_cutover_and_switch_back_with_distinct_sentinels(self, tmp_path, ensure_pg_bin_path):
        """
        Full behavioral end-to-end cutover & rollback drill on owned PostgreSQL 16 DBs:
        1. Populate OLD DB + old_index + old_media with Backup V1 baseline sentinel doc & media file.
        2. Create backup archive via perform_backup().
        3. Mutate OLD DB + old_index + old_media into V2 live sentinel (different doc, archived V1, new media bytes).
        4. Restore backup archive via CLI 'scripts/ops/restore.py --index-storage-dir ... --media-dir ...'
           into NEW DB + new_index + new_media; confirm OLD resources remain 100% untouched.
        5. Boot isolated web subprocess pointing at cutover profile -> reads V1 restored generation & V1 media ONLY.
        6. Boot isolated web subprocess switching back to old profile -> reads V2 live generation & V2 media ONLY.
        """
        parsed = make_url(test_db_url)
        admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
        old_db_name = f"folio_restore_drill_cutold_{os.getpid()}"
        new_db_name = f"folio_restore_drill_cutnew_{os.getpid()}"
        old_db_url = parsed.set(database=old_db_name).render_as_string(hide_password=False)
        new_db_url = parsed.set(database=new_db_name).render_as_string(hide_password=False)

        old_index_dir = tmp_path / "storage_old" / "search_index" / "generations"
        old_media_dir = tmp_path / "storage_old" / "media"
        new_index_dir = tmp_path / "storage_restored" / "search_index" / "generations"
        new_media_dir = tmp_path / "storage_restored" / "media"
        backups_dir = tmp_path / "backups"
        old_index_dir.mkdir(parents=True)
        old_media_dir.mkdir(parents=True)

        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        old_engine = None
        old_idx_restore_env = os.environ.get("INDEX_STORAGE_DIR")
        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{old_db_name}" WITH (FORCE)'))
                conn.execute(text(f'DROP DATABASE IF EXISTS "{new_db_name}" WITH (FORCE)'))
                conn.execute(text(f'CREATE DATABASE "{old_db_name}"'))
                conn.execute(text(f'CREATE DATABASE "{new_db_name}"'))

            # Seed baseline DB dump into old_db cleanly so old_db starts with realistic full Folio schema & fixtures
            seed_backup = perform_backup(
                output_dir=backups_dir,
                db_url=test_db_url,
                label="seed_clone",
                index_storage_dir=tmp_path / "unused_src_idx",
                media_dir=tmp_path / "unused_src_media",
            )
            clone_proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "ops" / "restore.py"),
                    "--archive",
                    seed_backup["archive_path"],
                    "--target-db-url",
                    old_db_url,
                    "--index-storage-dir",
                    str(old_index_dir),
                    "--media-dir",
                    str(old_media_dir),
                    "--rebuild-index",
                ],
                env=_clean_subprocess_env({
                    "DATABASE_URL": old_db_url,
                    "INDEX_STORAGE_DIR": str(old_index_dir),
                    "MEDIA_DIR": str(old_media_dir),
                }),
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert clone_proc.returncode == 0, f"Seed clone failed: {clone_proc.stderr}"

            # Step 1: Add distinct Backup V1 sentinel doc & media file in OLD profile
            os.environ["INDEX_STORAGE_DIR"] = str(old_index_dir)
            old_engine = create_engine(old_db_url)
            OldSession = sessionmaker(bind=old_engine, autoflush=False, autocommit=False)
            with OldSession() as session:
                author = session.query(User).first()
                category = session.query(Category).first()
                assert author is not None and category is not None
                v1_doc = Document(
                    id="99990001-0000-4000-8000-000000000001",
                    title="Cutover Sentinel Alpha Restored",
                    summary="Baseline document captured in backup V1",
                    content="This restored baseline corpus document contains unique token xyloquartzrestoredtoken.",
                    category_id=category.id,
                    author="Cutover Tester",
                    created_by=author.id,
                    status="published",
                    published_at=datetime.now(timezone.utc),
                )
                session.add(v1_doc)
                session.commit()
                gen_v1 = GenerationManager.build_new_generation(session, force=True)
                assert gen_v1.doc_count >= 1

            (old_media_dir / "sentinel.txt").write_text("MEDIA_SENTINEL_V1_BACKUP_BASELINE", encoding="utf-8")

            # Step 2: Take backup of V1 baseline
            v1_backup = perform_backup(
                output_dir=backups_dir,
                db_url=old_db_url,
                label="v1_cutover",
                index_storage_dir=old_index_dir,
                media_dir=old_media_dir,
            )

            # Step 3: Mutate OLD system after backup into V2 live state
            with OldSession() as session:
                doc_v1 = session.query(Document).filter(Document.id == "99990001-0000-4000-8000-000000000001").first()
                assert doc_v1 is not None
                doc_v1.status = "draft"
                doc_v1.deleted_at = datetime.now(timezone.utc)
                v2_doc = Document(
                    id="99990002-0000-4000-8000-000000000002",
                    title="Cutover Sentinel Beta Live System",
                    summary="Post-backup live document on old storage",
                    content="This live post-backup document contains unique token zebralitholdlivetoken.",
                    category_id=doc_v1.category_id,
                    author="Cutover Tester",
                    created_by=doc_v1.created_by,
                    status="published",
                    published_at=datetime.now(timezone.utc),
                )
                session.add(v2_doc)
                session.commit()
                gen_v2 = GenerationManager.build_new_generation(session, force=True)

            (old_media_dir / "sentinel.txt").write_text("MEDIA_SENTINEL_V2_LIVE_MUTATED", encoding="utf-8")

            # Step 4: Restore V1 archive via CLI into NEW DB + NEW isolated storage (preserving backed-up generation)
            restore_proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "ops" / "restore.py"),
                    "--archive",
                    v1_backup["archive_path"],
                    "--target-db-url",
                    new_db_url,
                    "--index-storage-dir",
                    str(new_index_dir),
                    "--media-dir",
                    str(new_media_dir),
                ],
                env=_clean_subprocess_env({
                    "DATABASE_URL": new_db_url,
                    "INDEX_STORAGE_DIR": str(new_index_dir),
                    "MEDIA_DIR": str(new_media_dir),
                }),
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert restore_proc.returncode == 0, f"CLI restore failed: {restore_proc.stderr}"
            restore_report = json.loads(restore_proc.stdout)
            assert restore_report["status"] == "success"
            assert restore_report["storage_paths"]["index_storage_dir"] == str(new_index_dir.resolve())
            assert restore_report["storage_paths"]["media_dir"] == str(new_media_dir.resolve())
            assert restore_report["index_recovery"]["action"] == "restored_from_backup"
            assert restore_report["index_recovery"]["generation_id"] == gen_v1.id
            assert restore_report["index_recovery"]["valid"] is True
            assert restore_report["smoke_test"]["search_smoke_test"]["status"] == "passed"

            # Assert OLD media sentinel remained completely untouched during restore
            assert (old_media_dir / "sentinel.txt").read_text(encoding="utf-8") == "MEDIA_SENTINEL_V2_LIVE_MUTATED"
            assert (new_media_dir / "sentinel.txt").read_text(encoding="utf-8") == "MEDIA_SENTINEL_V1_BACKUP_BASELINE"

            probe_code = textwrap.dedent(f"""\
                import json, sys
                sys.path.insert(0, {str(PROJECT_ROOT)!r})
                from fastapi.testclient import TestClient
                from src.backend.main import app
                from scripts.ops.backup import get_media_storage_root
                with TestClient(app) as client:
                    ready = client.get('/health/ready').json()
                    s_v1 = client.get('/api/v1/search?q=xyloquartzrestoredtoken').json()
                    s_v2 = client.get('/api/v1/search?q=zebralitholdlivetoken').json()
                    media_val = (get_media_storage_root() / 'sentinel.txt').read_text(encoding='utf-8')
                    print(json.dumps({{'ready': ready, 'v1': s_v1, 'v2': s_v2, 'media': media_val}}))
            """)

            # Step 5: Simulated Cutover Web Container (NEW DB + NEW index + NEW media)
            cutover_env = _clean_subprocess_env({
                "APP_ENV": "production",
                "COOKIE_SECURE": "true",
                "APP_SECRET": STRONG_TEST_SECRET,
                "CORS_ALLOWED_ORIGINS": "https://folio.unit.test",
                "DATABASE_URL": new_db_url,
                "INDEX_STORAGE_DIR": str(new_index_dir),
                "MEDIA_DIR": str(new_media_dir),
            })
            cutover_probe = subprocess.run(
                [sys.executable, "-c", probe_code],
                env=cutover_env,
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert cutover_probe.returncode == 0, f"Cutover probe failed: {cutover_probe.stderr}"
            cutover_out = json.loads(cutover_probe.stdout.strip().splitlines()[-1])
            assert cutover_out["ready"]["search"]["engine"] == "bm25"
            assert cutover_out["ready"]["search"]["is_degraded"] is False
            assert cutover_out["v1"]["engine_used"] == "bm25"
            assert cutover_out["v1"]["index_generation"] == restore_report["index_recovery"]["generation_id"]
            assert len(cutover_out["v1"]["items"]) == 1
            assert cutover_out["v1"]["items"][0]["id"] == "99990001-0000-4000-8000-000000000001"
            assert cutover_out["v2"]["items"] == []
            assert cutover_out["media"] == "MEDIA_SENTINEL_V1_BACKUP_BASELINE"

            # Step 6: Simulated Switch-Back Web Container (OLD DB + OLD index + OLD media)
            switchback_env = dict(cutover_env)
            switchback_env.update({
                "DATABASE_URL": old_db_url,
                "INDEX_STORAGE_DIR": str(old_index_dir),
                "MEDIA_DIR": str(old_media_dir),
            })
            switchback_probe = subprocess.run(
                [sys.executable, "-c", probe_code],
                env=switchback_env,
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert switchback_probe.returncode == 0, f"Switch-back probe failed: {switchback_probe.stderr}"
            sb_out = json.loads(switchback_probe.stdout.strip().splitlines()[-1])
            assert sb_out["ready"]["search"]["engine"] == "bm25"
            assert sb_out["ready"]["search"]["is_degraded"] is False
            assert sb_out["v2"]["engine_used"] == "bm25"
            assert sb_out["v2"]["index_generation"] == gen_v2.id
            assert sb_out["v2"]["index_generation"] != cutover_out["v1"]["index_generation"]
            assert len(sb_out["v2"]["items"]) == 1
            assert sb_out["v2"]["items"][0]["id"] == "99990002-0000-4000-8000-000000000002"
            assert sb_out["v1"]["items"] == []
            assert sb_out["media"] == "MEDIA_SENTINEL_V2_LIVE_MUTATED"
        finally:
            if old_idx_restore_env is not None:
                os.environ["INDEX_STORAGE_DIR"] = old_idx_restore_env
            else:
                os.environ.pop("INDEX_STORAGE_DIR", None)
            if old_engine is not None:
                old_engine.dispose()
            with admin_engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{old_db_name}" WITH (FORCE)'))
                conn.execute(text(f'DROP DATABASE IF EXISTS "{new_db_name}" WITH (FORCE)'))
            admin_engine.dispose()
