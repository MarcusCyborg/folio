"""
test_pure_safety.py - Folio IA-02 Pure Safety Test Suite.

Tests test-target validation, driver connect-args evaluation, query override rejection,
loopback/port normalization, credential redaction, manifest ownership, selective teardown,
and connected identity verification.

CRITICAL SAFETY PROPERTY:
This module contains ZERO application imports (no FastAPI app, no config.settings, no core_db.engine)
and ZERO live database connections. It runs safely with `pytest --noconftest`.
"""

import os
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from src.backend.core.test_db_guard import (
    validate_test_database_target,
    validate_test_database_safety,
    redact_url_credentials,
    normalize_host,
    normalize_port,
    is_loopback_host,
    selective_terminate_backends_sql,
    verify_connected_identity,
    safe_reset_test_schema,
    safe_teardown_test_database,
    provision_test_database,
    check_ambient_libpq_env,
    sanitize_ambient_libpq_env,
    TestRunManifest,
    TestDatabaseSafetyError,
    UnownedDatabaseError,
    ConnectedIdentityMismatchError,
    PROTECTED_DB_NAMES,
    FORBIDDEN_TARGET_QUERY_PARAMS,
)


class TestCredentialRedaction:
    """Verifies that credentials are never exposed in error messages or logs."""

    def test_redact_url_credentials_standard(self):
        url = "postgresql+psycopg://test_user:SuperSecretPassword123!@127.0.0.1:5432/folio_test"
        redacted = redact_url_credentials(url)
        assert "SuperSecretPassword123!" not in redacted
        assert redacted == "postgresql+psycopg://test_user:***@127.0.0.1:5432/folio_test"

    def test_redact_url_credentials_no_username(self):
        url = "postgresql://:SecretPass@localhost:5432/folio_test"
        redacted = redact_url_credentials(url)
        assert "SecretPass" not in redacted
        assert redacted == "postgresql://:***@localhost:5432/folio_test"

    def test_redact_url_credentials_empty_or_none(self):
        assert redact_url_credentials(None) == ""
        assert redact_url_credentials("") == ""

    def test_exception_does_not_leak_password_on_invalid_url(self):
        secret = "UltraSecretToken999!"
        unsafe_url = f"postgresql+psycopg://admin:{secret}@127.0.0.1:5432/postgres"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(unsafe_url)
        error_msg = str(exc_info.value)
        assert secret not in error_msg
        assert "***" in error_msg


class TestDriverTargetQueryOverrides:
    """
    Finding IA-02 reproduction and fix:
    Inspect effective driver connect args and reject connection-target overrides
    without ever opening a connection to the database.
    """

    def test_reproduce_ia02_dbname_override_rejected(self):
        """
        Reproduce IA-02: URL path is 'review_test', but ?dbname=folio overrides
        psycopg connection kwargs to connect to 'folio'. Must be rejected!
        """
        unsafe_url = "postgresql+psycopg://review:secret@127.0.0.1:5432/review_test?dbname=folio"
        main_url = "postgresql+psycopg://review:secret@127.0.0.1:5432/folio"

        # 1. Verify dialect.create_connect_args actually produces dbname='folio'
        temp_engine = create_engine(unsafe_url)
        args, kwargs = temp_engine.dialect.create_connect_args(temp_engine.url)
        temp_engine.dispose()
        assert kwargs.get("dbname") == "folio", "Demonstrates that driver kwarg is overridden to 'folio'"

        # 2. Assert that our guard catches and rejects this BEFORE any connection
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(unsafe_url, main_url)
        assert "Forbidden connection-target query override 'dbname'" in str(exc_info.value)
        assert "secret" not in str(exc_info.value)

    @pytest.mark.parametrize("param", ["host", "port", "service", "database", "hostaddr", "options"])
    def test_forbidden_target_query_overrides_rejected(self, param):
        unsafe_url = f"postgresql+psycopg://review:secret@127.0.0.1:5432/folio_test?{param}=override_val"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(unsafe_url)
        assert f"Forbidden connection-target query override '{param}'" in str(exc_info.value)
        assert "secret" not in str(exc_info.value)

    def test_unsupported_query_param_rejected(self):
        unsafe_url = "postgresql+psycopg://review:secret@127.0.0.1:5432/folio_test?arbitrary_param=123"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(unsafe_url)
        assert "Unsupported query parameter 'arbitrary_param'" in str(exc_info.value)

    def test_allowed_query_params_accepted(self):
        safe_url = "postgresql+psycopg://review:secret@127.0.0.1:5432/folio_test?sslmode=disable&connect_timeout=10"
        result = validate_test_database_target(safe_url)
        assert result.effective_database == "folio_test"
        assert result.effective_port == 5432


class TestPortAndHostNormalizationCollisions:
    """
    Verifies that default port omission and loopback aliases cannot bypass
    collision detection against the primary DATABASE_URL.
    """

    def test_implicit_default_port_collides_with_explicit_5432(self):
        # test_url omits port (defaults to 5432); main_url explicitly has 5432
        test_url = "postgresql://review:secret@127.0.0.1/folio"
        main_url = "postgresql://review:secret@127.0.0.1:5432/folio"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(test_url, main_url)
        assert "Collision detected" in str(exc_info.value) or "protected/production" in str(exc_info.value)

    def test_loopback_alias_localhost_collides_with_127_0_0_1(self):
        # test_url uses localhost; main_url uses 127.0.0.1
        test_url = "postgresql://review:secret@localhost:5432/folio"
        main_url = "postgresql://review:secret@127.0.0.1:5432/folio"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(test_url, main_url)
        assert "Collision detected" in str(exc_info.value) or "protected/production" in str(exc_info.value)

    def test_loopback_alias_127_0_0_2_collides_with_127_0_0_1(self):
        # 127.0.0.2 is in 127.0.0.0/8 loopback network
        test_url = "postgresql://review:secret@127.0.0.2:5432/folio"
        main_url = "postgresql://review:secret@127.0.0.1:5432/folio"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(test_url, main_url)
        assert "Collision detected" in str(exc_info.value) or "protected/production" in str(exc_info.value)

    def test_loopback_ipv6_alias_collides_with_127_0_0_1(self):
        # ::1 is IPv6 loopback
        test_url = "postgresql://review:secret@[::1]:5432/folio"
        main_url = "postgresql://review:secret@127.0.0.1:5432/folio"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(test_url, main_url)
        assert "Collision detected" in str(exc_info.value) or "protected/production" in str(exc_info.value)

    def test_same_target_distinct_test_db_does_not_collide(self):
        test_url = "postgresql+psycopg://review:secret@localhost:5432/folio_test_run1"
        main_url = "postgresql+psycopg://review:secret@127.0.0.1:5432/folio"
        result = validate_test_database_target(test_url, main_url)
        assert result.effective_database == "folio_test_run1"
        assert result.normalized_host == "127.0.0.1"


class TestDatabaseNameSafetyAndValidation:
    """Verifies rejection of protected, invalid, or malformed database names."""

    @pytest.mark.parametrize("name", list(PROTECTED_DB_NAMES))
    def test_protected_names_rejected(self, name):
        url = f"postgresql://review:secret@127.0.0.1:5432/{name}"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "protected/production name" in str(exc_info.value) or "must end with '_test'" in str(exc_info.value)

    def test_missing_database_name_rejected(self):
        url = "postgresql://review:secret@127.0.0.1:5432/"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "No target database name specified" in str(exc_info.value)

    def test_non_test_designated_name_rejected(self):
        url = "postgresql://review:secret@127.0.0.1:5432/my_production_database"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "must end with '_test'" in str(exc_info.value)

    def test_invalid_identifier_rejected(self):
        url = "postgresql://review:secret@127.0.0.1:5432/folio-test"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "Invalid PostgreSQL identifier" in str(exc_info.value)

    def test_non_postgres_driver_rejected(self):
        url = "sqlite:///folio_test.db"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "Unsupported driver 'sqlite'" in str(exc_info.value)

    def test_multi_host_url_rejected(self):
        url = "postgresql://host1:5432,host2:5432/folio_test"
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            validate_test_database_target(url)
        assert "Multi-host TEST_DATABASE_URL is not allowed" in str(exc_info.value)


class TestTestRunManifestAndOwnership:
    """Verifies that manifest strictly bounds ownership and prevents unowned operations."""

    def test_manifest_creation_and_unique_naming(self):
        manifest1 = TestRunManifest.create("run_alpha")
        manifest2 = TestRunManifest.create("run_beta")

        assert manifest1.run_id == "run_alpha"
        assert manifest2.run_id == "run_beta"

        db1 = manifest1.generate_db_name("folio_test")
        db2 = manifest2.generate_db_name("folio_test")

        assert db1 == "folio_test_run_alpha"
        assert db2 == "folio_test_run_beta"
        assert db1 != db2

    def test_manifest_tracks_only_owned_databases(self):
        manifest = TestRunManifest.create("test_run")
        manifest.register_owned("folio_test_test_run")

        assert manifest.is_owned("folio_test_test_run") is True
        assert manifest.is_owned("folio_test_other_run") is False
        assert manifest.is_owned("folio") is False

    def test_safe_reset_refuses_unowned_database(self):
        manifest = TestRunManifest.create("isolated_run")
        mock_engine = MagicMock()

        # Attempting schema reset on unowned DB must fail immediately without touching engine
        with pytest.raises(UnownedDatabaseError) as exc_info:
            safe_reset_test_schema(mock_engine, manifest, "folio_test_unowned")
        assert "is not registered in current run manifest" in str(exc_info.value)
        mock_engine.connect.assert_not_called()

    def test_safe_teardown_refuses_unowned_database(self):
        manifest = TestRunManifest.create("isolated_run")

        # Attempting teardown on unowned DB must fail immediately
        with pytest.raises(UnownedDatabaseError) as exc_info:
            safe_teardown_test_database("postgresql://review@127.0.0.1:5432/postgres", manifest, "folio_test_unowned")
        assert "is not registered in current run manifest" in str(exc_info.value)

    def test_provision_refuses_existing_unowned_database(self):
        from unittest.mock import patch
        manifest = TestRunManifest.create("isolated_run")
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        # Database already exists in pg_database (scalar returns 1)
        mock_conn.execute.return_value.scalar.return_value = 1

        with patch("src.backend.core.test_db_guard.create_engine", return_value=mock_engine):
            with pytest.raises(UnownedDatabaseError) as exc_info:
                provision_test_database(
                    "postgresql://review:secret@127.0.0.1:5432/postgres",
                    manifest,
                    requested_dbname="folio_test_existing",
                )
        assert "already exists on server and is not owned by current test manifest" in str(exc_info.value)
        # Verify CREATE DATABASE was NEVER executed
        for call_arg in mock_conn.execute.call_args_list:
            assert "CREATE DATABASE" not in str(call_arg)

    def test_selective_terminate_sql_has_target_filter(self):
        """Verifies that backend termination SQL is strictly scoped to target datname."""
        sql = selective_terminate_backends_sql("folio_test_run_123")
        assert "datname = 'folio_test_run_123'" in sql
        assert "pid <> pg_backend_pid()" in sql
        # Must not be a blanket termination across all databases
        assert "WHERE datname =" in sql


class TestConnectedIdentityVerification:
    """Verifies that connected database identity is strictly checked before any mutation."""

    def test_verify_connected_identity_success(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            "folio_test_run_42",
            "folio_tester",
            "127.0.0.1",
            5432,
        )
        identity = verify_connected_identity(mock_conn, "folio_test_run_42")
        assert identity["connected_database"] == "folio_test_run_42"
        assert identity["connected_user"] == "folio_tester"

    def test_verify_connected_identity_mismatch_raises_without_mutation(self):
        mock_conn = MagicMock()
        # Simulated scenario: connection actually landed on production 'folio' database!
        mock_conn.execute.return_value.fetchone.return_value = (
            "folio",
            "postgres",
            "127.0.0.1",
            5432,
        )
        with pytest.raises(ConnectedIdentityMismatchError) as exc_info:
            verify_connected_identity(mock_conn, "folio_test_run_42")

        error_msg = str(exc_info.value)
        assert "Connected database identity mismatch" in error_msg
        assert "Connected to 'folio'" in error_msg
        assert "expected owned test database 'folio_test_run_42'" in error_msg
        assert "Aborting mutation without DROP!" in error_msg


class TestTwoConcurrentRunsIsolation:
    """Verifies that two concurrent test runs maintain distinct manifests and non-overlapping resources."""

    def test_concurrent_runs_have_isolated_names_and_teardown_scope(self):
        run1 = TestRunManifest.create("run_worker_1")
        run2 = TestRunManifest.create("run_worker_2")

        db1 = run1.generate_db_name()
        db2 = run2.generate_db_name()

        run1.register_owned(db1)
        run2.register_owned(db2)

        # 1. Database names must be completely different
        assert db1 != db2

        # 2. Run 1 does not own Run 2's DB
        assert run1.is_owned(db1) is True
        assert run1.is_owned(db2) is False

        # 3. Run 2 does not own Run 1's DB
        assert run2.is_owned(db2) is True
        assert run2.is_owned(db1) is False

        # 4. Termination SQL for Run 1 targets ONLY db1
        sql1 = selective_terminate_backends_sql(db1)
        assert f"datname = '{db1}'" in sql1
        assert db2 not in sql1

        # 5. Manifest dictionary representation is non-secret and contains run details
        dict1 = run1.to_dict()
        assert dict1["run_id"] == "run_worker_1"
        assert dict1["created_databases"] == [db1]
        assert "password" not in str(dict1)


class TestAmbientLibpqEnvControl:
    """Verifies that ambient libpq environment variables can be inspected and sanitized."""

    def test_ambient_env_check_and_sanitize(self):
        # Set a test ambient libpq variable
        os.environ["PGDATABASE"] = "ambient_production_db"
        try:
            detected = check_ambient_libpq_env()
            assert "PGDATABASE" in detected
            assert detected["PGDATABASE"] == "ambient_production_db"

            # Sanitize removes it
            removed = sanitize_ambient_libpq_env()
            assert "PGDATABASE" in removed
            assert "PGDATABASE" not in os.environ
        finally:
            os.environ.pop("PGDATABASE", None)
