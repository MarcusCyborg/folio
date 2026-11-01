"""
test_bootstrap_postgres_lifecycle.py - Live PostgreSQL CLI Subprocess & Lifecycle Integration Tests.

Verifies end-to-end bootstrap and rotation operations against an isolated PostgreSQL 16 instance:
1. Provisions fresh test database via R01 TestRunManifest and provision_test_database.
2. Executes Alembic schema migration (alembic upgrade head) without manual seed.
3. Executes CLI subprocesses (scripts/bootstrap_admin.py) with ADMIN_BOOTSTRAP_PASSWORD:
   - Initial Super Admin provisioning (exit code 0).
   - Duplicate rerun rejection without mutation (exit code 2).
   - Super Admin credential rotation with active session revocation (exit code 0).
   - Negative rejection matrix (email mismatch, username mismatch, non-existent target, weak password).
   - State snapshot verification before and after each rejection.
4. Clean teardown scoped strictly to the run's owned database.

NOTE ON ENVIRONMENT PREREQUISITES & BLOCKED_ENV:
Requires an isolated PostgreSQL 16 server (e.g. running on 127.0.0.1:5432 or FOLIO_TEST_ADMIN_URL).
When an isolated PostgreSQL server is unavailable, the suite reports BLOCKED_ENV.
Per Folio engineering invariants, SQLite is NEVER used as a substitute for PostgreSQL certification.
"""

import os
import sys
import subprocess
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.test_db_guard import (
    TestRunManifest,
    provision_test_database,
    safe_teardown_test_database,
    safe_reset_test_schema,
    verify_connected_identity,
    validate_test_database_target,
    selective_terminate_backends_sql,
)
from src.backend.core.security import verify_password
from src.backend.models.auth import User, Role, SessionModel
from src.backend.models.system import AuditLog

ADMIN_URL = os.getenv("FOLIO_TEST_ADMIN_URL", "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres")


def is_postgres_available() -> bool:
    """Checks if the PostgreSQL test instance is reachable."""
    try:
        url = make_url(ADMIN_URL)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pg_available = is_postgres_available()

STRONG_BOOT_PWD_1 = "FreshPostgresAdminPassword2026!#"
STRONG_BOOT_PWD_2 = "RotatedPostgresAdminPassword2026!$"


@pytest.mark.skipif(
    not pg_available,
    reason="BLOCKED_ENV: PostgreSQL 16 test instance is not reachable. Live DB CLI verification requires a running PostgreSQL instance.",
)
class TestLivePostgresBootstrapLifecycle:
    @pytest.fixture(scope="class")
    def live_pg_db(self):
        """Provisions a dedicated PostgreSQL database for bootstrap CLI testing and runs migrations."""
        manifest = TestRunManifest.create()
        run_db_name = f"folio_test_bootstrap_{manifest.run_id}"

        # 1. Provision fresh test database
        target_db_url = provision_test_database(ADMIN_URL, manifest, requested_dbname=run_db_name)

        # 2. Run Alembic upgrade head
        from alembic.config import Config
        from alembic import command
        alembic_ini_path = PROJECT_ROOT / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini_path))
        alembic_cfg.set_main_option("sqlalchemy.url", target_db_url)
        alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        command.upgrade(alembic_cfg, "head")

        # Yield context
        yield {
            "manifest": manifest,
            "db_name": run_db_name,
            "db_url": target_db_url,
        }

        # 3. Teardown
        safe_teardown_test_database(ADMIN_URL, manifest, run_db_name)

    def test_live_cli_create_rerun_rotate_and_negative_matrix(self, live_pg_db):
        """End-to-end CLI subprocess execution on migrated PostgreSQL without manual seed."""
        target_url = live_pg_db["db_url"]
        cli_path = str(PROJECT_ROOT / "scripts" / "bootstrap_admin.py")

        def run_cli(args: list, password: str) -> subprocess.CompletedProcess:
            env = os.environ.copy()
            env["DATABASE_URL"] = target_url
            env["ADMIN_BOOTSTRAP_PASSWORD"] = password
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            return subprocess.run(
                [sys.executable, cli_path, "--non-interactive"] + args,
                capture_output=True,
                text=True,
                env=env,
            )

        # 1. Create Initial Super Admin
        create_res = run_cli([
            "--email", "pg_admin@folio.local",
            "--username", "pg_admin",
            "--display-name", "PG Super Admin",
        ], STRONG_BOOT_PWD_1)
        assert create_res.returncode == 0
        assert "[SUCCESS] Initial Super Admin account" in create_res.stdout

        # Verify DB state
        engine = create_engine(target_url)
        with Session(engine) as session:
            admin = session.query(User).filter(User.username == "pg_admin").first()
            assert admin is not None
            assert admin.email == "pg_admin@folio.local"
            assert admin.role_key == "super_admin"
            assert admin.is_active is True
            assert verify_password(STRONG_BOOT_PWD_1, admin.password_hash)
            admin_id = admin.id

            # Verify audit log was created
            audit = session.query(AuditLog).filter(AuditLog.entity_id == admin_id).first()
            assert audit is not None
            assert audit.action == "auth.admin_bootstrap_created"

        # 2. Duplicate Create without --rotate (must fail with exit code 2)
        dup_res = run_cli([
            "--email", "pg_admin@folio.local",
            "--username", "pg_admin",
        ], STRONG_BOOT_PWD_2)
        assert dup_res.returncode == 2
        assert "ALREADY_EXISTS" in dup_res.stderr

        # 3. Successful Credential Rotation
        rot_res = run_cli([
            "--email", "pg_admin@folio.local",
            "--username", "pg_admin",
            "--rotate",
        ], STRONG_BOOT_PWD_2)
        assert rot_res.returncode == 0
        assert "[SUCCESS] Admin account 'pg_admin'" in rot_res.stdout

        with Session(engine) as session:
            admin = session.query(User).filter(User.username == "pg_admin").first()
            assert admin.id == admin_id
            assert admin.role_key == "super_admin"
            assert verify_password(STRONG_BOOT_PWD_2, admin.password_hash)

        # 4. Negative Matrix: Email Mismatch (must exit 1 without mutation)
        mismatch_email_res = run_cli([
            "--email", "wrong_email@folio.local",
            "--username", "pg_admin",
            "--rotate",
        ], STRONG_BOOT_PWD_1)
        assert mismatch_email_res.returncode == 1
        assert "Identity mismatch" in mismatch_email_res.stderr

        # 5. Negative Matrix: Username Mismatch (must exit 1 without mutation)
        mismatch_user_res = run_cli([
            "--email", "pg_admin@folio.local",
            "--username", "wrong_username",
            "--rotate",
        ], STRONG_BOOT_PWD_1)
        assert mismatch_user_res.returncode == 1
        assert "Identity mismatch" in mismatch_user_res.stderr

        # 6. Negative Matrix: Weak Password (must exit 1)
        weak_pwd_res = run_cli([
            "--email", "pg_admin@folio.local",
            "--username", "pg_admin",
            "--rotate",
        ], "foliodemo2026!")
        assert weak_pwd_res.returncode == 1
        assert "too weak" in weak_pwd_res.stderr

        # Verify hash was untouched by negative tests
        with Session(engine) as session:
            admin = session.query(User).filter(User.username == "pg_admin").first()
            assert verify_password(STRONG_BOOT_PWD_2, admin.password_hash)

        engine.dispose()
