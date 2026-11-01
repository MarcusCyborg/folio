"""
test_db_lifecycle.py - Folio IA-02 Live Database Lifecycle & Concurrency Integration Tests.

Verifies end-to-end lifecycle operations against an isolated PostgreSQL 16 test instance:
1. Fresh test DB provisioning with unique TestRunManifest.
2. Full Alembic schema migration (upgrade head) and baseline seeding (run_seed).
3. Disposable sentinel database verification (proves other databases are never dropped or mutated).
4. Rejection of existing unowned databases without mutation.
5. Two concurrent test runs with non-overlapping databases and isolated teardown boundaries.
6. Teardown strictly scoped to the test run's owned database.

NOTE ON ENVIRONMENT PREREQUISITES:
Requires an isolated PostgreSQL 16 server (e.g. running on 127.0.0.1:5432 or FOLIO_TEST_ADMIN_URL).
When an isolated PostgreSQL server is unavailable, the suite reports BLOCKED_ENV.
Per Folio engineering invariants, SQLite is NEVER used as a substitute for PostgreSQL lifecycle verification.
"""

import os
import sys
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
    UnownedDatabaseError,
    ConnectedIdentityMismatchError,
    TestDatabaseSafetyError,
)

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


# Invariant: If PostgreSQL is missing, mark as BLOCKED_ENV
pg_available = is_postgres_available()
requires_postgres = pytest.mark.skipif(
    not pg_available,
    reason="BLOCKED_ENV: Isolated PostgreSQL 16 test instance is not reachable. Live DB checks pending."
)


@requires_postgres
class TestLiveDatabaseLifecycle:
    """Live database tests requiring a real, isolated PostgreSQL server."""

    def test_live_provision_migrate_seed_and_teardown(self):
        manifest = TestRunManifest.create()
        db_name = manifest.generate_db_name()

        # 1. Provision fresh test database
        test_url_str = provision_test_database(ADMIN_URL, manifest, db_name)
        assert manifest.is_owned(db_name) is True

        test_engine = create_engine(test_url_str)
        try:
            # 2. Verify connected identity
            with test_engine.connect() as conn:
                identity = verify_connected_identity(conn, db_name)
                assert identity["connected_database"] == db_name

            # 3. Reset schema
            safe_reset_test_schema(test_engine, manifest, db_name)

            # 4. Run Alembic upgrade head
            from alembic.config import Config
            from alembic import command
            import argparse

            alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
            alembic_cfg.set_main_option("sqlalchemy.url", test_url_str)
            alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
            alembic_cfg.cmd_opts = argparse.Namespace(x=[f"db_url={test_url_str}"])

            old_env = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = test_url_str
            try:
                command.upgrade(alembic_cfg, "head")
            finally:
                if old_env is not None:
                    os.environ["DATABASE_URL"] = old_env
                else:
                    os.environ.pop("DATABASE_URL", None)

            # 5. Seed baseline fixtures
            from scripts.seed_folio import run_seed
            run_seed(target=test_engine)

            # 6. Verify seed data exists
            with test_engine.connect() as conn:
                doc_count = conn.execute(text("SELECT count(*) FROM documents")).scalar()
                assert doc_count is not None and doc_count > 0

        finally:
            test_engine.dispose()
            # 7. Safe teardown
            safe_teardown_test_database(ADMIN_URL, manifest, db_name)
            assert manifest.is_owned(db_name) is False

        # Verify database was dropped
        admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name}
            ).scalar()
            assert not exists
        admin_engine.dispose()

    def test_live_two_concurrent_runs_and_sentinel_isolation(self):
        admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        sentinel_db = TestRunManifest.create().generate_db_name("folio_test_sentinel")

        # Create sentinel database on disposable test instance
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{sentinel_db}"'))

        sentinel_url = make_url(ADMIN_URL).set(database=sentinel_db).render_as_string(hide_password=False)
        sentinel_engine = create_engine(sentinel_url, isolation_level="AUTOCOMMIT")
        with sentinel_engine.connect() as conn:
            conn.execute(text("CREATE TABLE sentinel_marker (id int, val text)"))
            conn.execute(text("INSERT INTO sentinel_marker VALUES (1, 'untouched_data')"))

        run1 = TestRunManifest.create()
        run2 = TestRunManifest.create()

        db1 = run1.generate_db_name()
        db2 = run2.generate_db_name()

        try:
            # Provision DB for Run 1 and Run 2
            url1 = provision_test_database(ADMIN_URL, run1, db1)
            url2 = provision_test_database(ADMIN_URL, run2, db2)

            engine1 = create_engine(url1)
            engine2 = create_engine(url2)

            with engine1.begin() as conn:
                conn.execute(text("CREATE TABLE t1 (val text)"))
                conn.execute(text("INSERT INTO t1 VALUES ('run1_private')"))

            with engine2.begin() as conn:
                conn.execute(text("CREATE TABLE t2 (val text)"))
                conn.execute(text("INSERT INTO t2 VALUES ('run2_private')"))

            # Teardown Run 1
            engine1.dispose()
            safe_teardown_test_database(ADMIN_URL, run1, db1)

            # Assert: Run 1 DB is gone
            with admin_engine.connect() as conn:
                assert conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db1}).scalar() is None
                # Assert: Run 2 DB is completely intact
                assert conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db2}).scalar() == 1

            # Assert: Run 2 data still accessible
            with engine2.connect() as conn:
                assert conn.execute(text("SELECT val FROM t2")).scalar() == "run2_private"

            # Assert: Sentinel data is completely untouched
            with sentinel_engine.connect() as conn:
                assert conn.execute(text("SELECT val FROM sentinel_marker")).scalar() == "untouched_data"

            # Teardown Run 2
            engine2.dispose()
            safe_teardown_test_database(ADMIN_URL, run2, db2)

        finally:
            sentinel_engine.dispose()
            with admin_engine.connect() as conn:
                conn.execute(text(selective_terminate_backends_sql(sentinel_db)))
                conn.execute(text(f'DROP DATABASE IF EXISTS "{sentinel_db}"'))
            admin_engine.dispose()

    def test_live_existing_unowned_database_rejected(self):
        admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        unowned_db = TestRunManifest.create().generate_db_name("folio_test_unowned")

        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{unowned_db}"'))

        try:
            manifest = TestRunManifest.create("intruder_run")
            with pytest.raises(UnownedDatabaseError):
                provision_test_database(ADMIN_URL, manifest, unowned_db)

            # Verify unowned DB was not dropped
            with admin_engine.connect() as conn:
                assert conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": unowned_db}).scalar() == 1
        finally:
            with admin_engine.connect() as conn:
                conn.execute(text(selective_terminate_backends_sql(unowned_db)))
                conn.execute(text(f'DROP DATABASE IF EXISTS "{unowned_db}"'))
            admin_engine.dispose()
