"""
test_startup_subprocess.py - Real Subprocess Application Startup & Security Validator Tests.

Verifies fail-fast security invariants during actual application startup in dedicated Python subprocesses:
1. Production boot fails fast when APP_SECRET contains insecure/default patterns.
2. Production boot fails fast when APP_SECRET is shorter than 32 characters or has low entropy.
3. Production boot fails fast when COOKIE_SECURE is False (HTTPS enforcement).
4. Production boot fails fast when CORS_ALLOWED_ORIGINS contains wildcard '*'.
5. Boot fails fast when APP_ENV is invalid or unrecognized.
6. Production boot fails fast when DATABASE_URL uses default 'postgres:postgres' credentials.
7. Compliant production configuration boots lifespan cleanly without validation failure.
8. Development environment boots lifespan cleanly with local defaults.

Invariants Verified:
- Runs in an isolated subprocess with explicit OS environment variables (zero in-memory settings pollution).
- Executes application lifespan context manager directly.
"""

import os
import sys
import subprocess
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STRONG_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF(9a1b2c3d4e5f6g7h8i9j0k"
COMPLIANT_PROD_DB = "postgresql+psycopg://folio_prod_admin:SecureProductionPassword2026!@127.0.0.1:5432/folio_prod"

BOOT_HARNESS_CODE = """
import sys
from pathlib import Path
PROJECT_ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.main import app
from fastapi.testclient import TestClient

try:
    with TestClient(app) as client:
        print("LIFESPAN_BOOT_SUCCESS")
except Exception as e:
    print(f"LIFESPAN_BOOT_ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
"""


def run_boot_subprocess(env_overrides: dict) -> subprocess.CompletedProcess:
    """Spawns an isolated Python process to execute application lifespan boot."""
    env = os.environ.copy()
    # Disable python dotenv loading in test runs if supported, or override keys explicitly
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.update(env_overrides)

    return subprocess.run(
        [sys.executable, "-c", BOOT_HARNESS_CODE, str(PROJECT_ROOT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


class TestStartupSubprocessSecurity:
    def test_subprocess_boot_fails_fast_on_weak_secret(self):
        """Production boot in real subprocess fails fast when APP_SECRET contains default/insecure pattern."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "true",
            "APP_SECRET": "folio_dev_insecure_pattern_32_characters_long",
            "CORS_ALLOWED_ORIGINS": "https://folio.example.com",
            "DATABASE_URL": COMPLIANT_PROD_DB,
        })
        assert proc.returncode != 0
        assert "APP_SECRET contains insecure or default pattern" in proc.stderr

    def test_subprocess_boot_fails_fast_on_short_secret(self):
        """Production boot in real subprocess fails fast when APP_SECRET is under 32 characters."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "true",
            "APP_SECRET": "TooShortSecret123!",
            "CORS_ALLOWED_ORIGINS": "https://folio.example.com",
            "DATABASE_URL": COMPLIANT_PROD_DB,
        })
        assert proc.returncode != 0
        assert "APP_SECRET must be at least 32 characters long" in proc.stderr

    def test_subprocess_boot_fails_fast_on_insecure_cookie(self):
        """Production boot in real subprocess fails fast when COOKIE_SECURE is False."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "false",
            "APP_SECRET": STRONG_SECRET,
            "CORS_ALLOWED_ORIGINS": "https://folio.example.com",
            "DATABASE_URL": COMPLIANT_PROD_DB,
        })
        assert proc.returncode != 0
        assert "COOKIE_SECURE must be True in production environment" in proc.stderr

    def test_subprocess_boot_fails_fast_on_wildcard_cors(self):
        """Production boot in real subprocess fails fast when CORS_ALLOWED_ORIGINS contains wildcard '*'."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "true",
            "APP_SECRET": STRONG_SECRET,
            "CORS_ALLOWED_ORIGINS": "*,https://folio.example.com",
            "DATABASE_URL": COMPLIANT_PROD_DB,
        })
        assert proc.returncode != 0
        assert "CORS_ALLOWED_ORIGINS cannot contain wildcard '*'" in proc.stderr

    def test_subprocess_boot_fails_fast_on_invalid_app_env(self):
        """Application boot in real subprocess fails fast when APP_ENV is unrecognized/typo."""
        proc = run_boot_subprocess({
            "APP_ENV": "typo-production",
            "APP_SECRET": STRONG_SECRET,
        })
        assert proc.returncode != 0
        assert "Invalid APP_ENV" in proc.stderr

    def test_subprocess_boot_fails_fast_on_default_postgres_credentials(self):
        """Production boot in real subprocess fails fast when DATABASE_URL has postgres:postgres credentials."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "true",
            "APP_SECRET": STRONG_SECRET,
            "CORS_ALLOWED_ORIGINS": "https://folio.example.com",
            "DATABASE_URL": "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/folio_prod",
        })
        assert proc.returncode != 0
        assert "DATABASE_URL uses default 'postgres:postgres' development credentials in production" in proc.stderr

    def test_subprocess_boot_succeeds_in_compliant_production(self):
        """Compliant production environment in real subprocess boots cleanly."""
        proc = run_boot_subprocess({
            "APP_ENV": "production",
            "COOKIE_SECURE": "true",
            "APP_SECRET": STRONG_SECRET,
            "CORS_ALLOWED_ORIGINS": "https://folio.example.com",
            "DATABASE_URL": COMPLIANT_PROD_DB,
        })
        assert proc.returncode == 0
        assert "LIFESPAN_BOOT_SUCCESS" in proc.stdout

    def test_subprocess_boot_succeeds_in_development(self):
        """Standard development environment in real subprocess boots cleanly."""
        proc = run_boot_subprocess({
            "APP_ENV": "development",
        })
        assert proc.returncode == 0
        assert "LIFESPAN_BOOT_SUCCESS" in proc.stdout
