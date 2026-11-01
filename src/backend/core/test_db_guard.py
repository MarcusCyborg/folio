"""
test_db_guard.py - Folio Test Database Target Safety & Ownership Validator.

Strict, pure safety guard for test database target validation, driver target
override detection, loopback/port normalization, credential redaction,
and test run ownership manifest lifecycle.

Zero application/engine/conftest dependencies. Pure validation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import ipaddress
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs

from sqlalchemy.engine import make_url, URL
from sqlalchemy import create_engine


# --- Error Classes ---

class TestDatabaseSafetyError(RuntimeError):
    """Raised when a test database URL or operation violates safety policies."""
    __test__ = False


class UnownedDatabaseError(TestDatabaseSafetyError):
    """Raised when attempting an operation on a database not owned by the current run manifest."""
    __test__ = False


class ConnectedIdentityMismatchError(TestDatabaseSafetyError):
    """Raised when the connected database/server identity does not match the expected owned test database."""
    __test__ = False


class AmbientEnvOverrideError(TestDatabaseSafetyError):
    """Raised when ambient environment variables could alter the effective database target."""
    __test__ = False


# --- Constants & Policies ---

SUPPORTED_POSTGRES_SCHEMES: Set[str] = {
    "postgresql",
    "postgresql+psycopg",
    "postgresql+psycopg2",
    "postgresql+asyncpg",
}

# Forbidden query parameters that could redirect driver connection target
FORBIDDEN_TARGET_QUERY_PARAMS: Set[str] = {
    "dbname",
    "database",
    "host",
    "hostaddr",
    "port",
    "service",
    "servicefile",
    "target_session_attrs",
    "options",
}

# Safe query parameters allowlist (cannot redirect connection target)
ALLOWED_QUERY_PARAMS: Set[str] = {
    "sslmode",
    "connect_timeout",
    "application_name",
    "client_encoding",
    "keepalives",
    "keepalives_idle",
    "keepalives_interval",
    "keepalives_count",
}

# Protected / Production database names that must NEVER be used as test databases
PROTECTED_DB_NAMES: Set[str] = {
    "postgres",
    "template0",
    "template1",
    "folio",
    "folio_prod",
    "production",
    "prod",
    "master",
    "main",
    "dev",
    "development",
    "staging",
}

# Ambient libpq environment variables capable of redirecting target
CONTROLLED_LIBPQ_ENV_VARS: List[str] = [
    "PGDATABASE",
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGSERVICE",
    "PGSYSCONFDIR",
    "PGSERVICEFILE",
]

DEFAULT_POSTGRES_PORT: int = 5432
VALID_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def ownership_endpoint(target):
    # Collision checks deliberately conflate loopback aliases; ownership must not:
    # separate servers may bind 127.0.0.1 and 127.0.0.2 on the same port.
    host = (target.effective_host or "127.0.0.1").lower()
    return ("127.0.0.1" if host == "localhost" else host, target.normalized_port)


# --- Pure Helpers ---

def redact_url_credentials(url_str: str | None) -> str:
    """
    Safely redacts username:password credentials from any URL or connection string.
    Never raises an exception even if the URL string is malformed.
    """
    if not url_str:
        return ""
    # Redact ://user:pass@ -> ://user:***@ or ://:pass@ -> ://:***@
    redacted = re.sub(r"://([^:@]*):([^@]*)@", r"://\1:***@", str(url_str))
    # Redact password=xyz in DSN strings
    redacted = re.sub(r"(password\s*=\s*)([^\s;]+)", r"\1***", redacted, flags=re.IGNORECASE)
    return redacted


def is_loopback_host(host: str | None) -> bool:
    """Checks whether the given host name/address represents a local loopback target."""
    if not host:
        return True  # Omitted host defaults to local loopback/socket
    cleaned = host.strip().lower()
    if cleaned in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    try:
        ip = ipaddress.ip_address(cleaned)
        return ip.is_loopback
    except ValueError:
        return False


def normalize_host(host: str | None) -> str:
    """Normalizes host string: loopback aliases to '127.0.0.1', otherwise lowercased trimmed."""
    if is_loopback_host(host):
        return "127.0.0.1"
    return (host or "").strip().lower()


def normalize_port(port: int | str | None) -> int:
    """Normalizes port: defaults to 5432 for PostgreSQL."""
    if port is None or str(port).strip() == "":
        return DEFAULT_POSTGRES_PORT
    try:
        val = int(port)
        if val <= 0 or val > 65535:
            raise ValueError(f"Port {val} out of range (1-65535)")
        return val
    except ValueError as e:
        raise TestDatabaseSafetyError(f"Invalid port value: {e}") from e


def check_ambient_libpq_env() -> Dict[str, str]:
    """Returns any ambient libpq environment variables currently set that could affect target."""
    found = {}
    for var in CONTROLLED_LIBPQ_ENV_VARS:
        if var in os.environ and os.environ[var].strip():
            found[var] = os.environ[var].strip()
    return found


def sanitize_ambient_libpq_env() -> Dict[str, str]:
    """Removes hazardous libpq environment variables from os.environ and returns removed ones."""
    removed = {}
    for var in CONTROLLED_LIBPQ_ENV_VARS:
        if var in os.environ:
            removed[var] = os.environ.pop(var)
    return removed


# --- Effective Target Validation ---

@dataclass(frozen=True)
class TargetValidationResult:
    test_url_str: str
    redacted_url_str: str
    driver_name: str
    effective_host: str
    effective_port: int
    effective_database: str
    normalized_host: str
    normalized_port: int


def validate_test_database_target(
    test_db_url_str: str,
    main_db_url_str: str | None = None,
) -> TargetValidationResult:
    """
    Pure safety validator for test database targets.
    
    Invariants enforced:
    1. Redacts credentials in all errors - never leaks passwords in tracebacks.
    2. Validates supported PostgreSQL driver schemes; rejects non-PostgreSQL / malformed URLs.
    3. Strictly rejects target query overrides (dbname, host, port, service, etc.) and unsupported DSNs.
    4. Enforces query parameters safe allowlist.
    5. Evaluates effective driver connection args via dialect.create_connect_args without opening network sockets.
    6. Rejects protected / production database names.
    7. Verifies database name matches designated test naming patterns (test_*, *_test, folio_test).
    8. Normalizes default ports and loopback aliases (localhost vs 127.0.0.1 vs 127.0.0.2).
    9. Detects and prevents collisions against primary DATABASE_URL.
    """
    redacted_input = redact_url_credentials(test_db_url_str)

    # 1. Pre-check for multi-host or unsupported DSN patterns
    url_base = test_db_url_str.split("?")[0]
    if "," in url_base:
        raise TestDatabaseSafetyError(
            f"Multi-host TEST_DATABASE_URL is not allowed for test safety: '{redacted_input}'."
        )

    # 2. Parse URL structure
    try:
        test_url = make_url(test_db_url_str)
    except Exception as e:
        raise TestDatabaseSafetyError(f"Invalid or malformed TEST_DATABASE_URL '{redacted_input}': {e}") from e

    # 3. Driver scheme validation
    driver = test_url.drivername.lower()
    if not (driver in SUPPORTED_POSTGRES_SCHEMES or driver.startswith("postgresql")):
        raise TestDatabaseSafetyError(
            f"Unsupported driver '{driver}' in TEST_DATABASE_URL '{redacted_input}'. Only PostgreSQL is supported."
        )

    # Multi-host check on parsed host as well
    if test_url.host and ("," in test_url.host or " " in test_url.host):
        raise TestDatabaseSafetyError(
            f"Multi-host TEST_DATABASE_URL is not allowed for test safety: '{redacted_input}'."
        )

    # 4. Preliminary check on URL database path
    raw_db = test_url.database
    if not raw_db or not raw_db.strip():
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': No target database name specified."
        )

    raw_db_clean = raw_db.strip().lower()
    if raw_db_clean in PROTECTED_DB_NAMES:
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': Target database name '{raw_db}' is a protected/production name."
        )

    if not VALID_IDENTIFIER_REGEX.match(raw_db):
        raise TestDatabaseSafetyError(
            f"Invalid PostgreSQL identifier '{raw_db}' in TEST_DATABASE_URL '{redacted_input}'."
        )

    is_raw_test = (
        raw_db_clean.endswith("_test")
        or raw_db_clean.startswith("test_")
        or raw_db_clean == "folio_test"
        or "test" in raw_db_clean.split("_")
    )
    if not is_raw_test:
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': Target database name '{raw_db}' must end with '_test', "
            f"start with 'test_', or designate a test database to prevent data loss."
        )

    # 5. Query parameters validation (Policy: Effective Driver Target)
    query_params = dict(test_url.query)
    for forbidden in FORBIDDEN_TARGET_QUERY_PARAMS:
        if forbidden in query_params:
            raise TestDatabaseSafetyError(
                f"Forbidden connection-target query override '{forbidden}' detected in TEST_DATABASE_URL: '{redacted_input}'."
            )

    for param in query_params:
        if param.lower() not in ALLOWED_QUERY_PARAMS:
            raise TestDatabaseSafetyError(
                f"Unsupported query parameter '{param}' in TEST_DATABASE_URL: '{redacted_input}'."
            )

    # 6. Effective Driver Connect Args Inspection (Reproduce via connect args, zero connection)
    # If generic 'postgresql' is given, inspect using installed postgresql+psycopg driver if psycopg2 absent
    eval_url = test_url
    if test_url.drivername == "postgresql":
        eval_url = test_url.set(drivername="postgresql+psycopg")

    try:
        # create_engine constructs dialect objects without opening network sockets
        temp_engine = create_engine(eval_url)
        args, kwargs = temp_engine.dialect.create_connect_args(temp_engine.url)
        temp_engine.dispose()
    except Exception as e:
        raise TestDatabaseSafetyError(
            f"Failed to inspect driver connect args for TEST_DATABASE_URL '{redacted_input}': {e}"
        ) from e

    effective_db = kwargs.get("dbname") or test_url.database
    if not effective_db:
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': No target database name specified."
        )

    # Cross-check driver args against URL database path
    if test_url.database and effective_db != test_url.database:
        raise TestDatabaseSafetyError(
            f"Driver effective database '{effective_db}' differs from URL path '{test_url.database}' in '{redacted_input}'."
        )

    effective_host = kwargs.get("host") or test_url.host
    effective_port = kwargs.get("port") or test_url.port

    norm_test_host = normalize_host(effective_host)
    norm_test_port = normalize_port(effective_port)

    # Cross-check effective database name
    db_clean = effective_db.strip().lower()
    if db_clean in PROTECTED_DB_NAMES:
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': Target database name '{effective_db}' is a protected/production name."
        )

    if not VALID_IDENTIFIER_REGEX.match(effective_db):
        raise TestDatabaseSafetyError(
            f"Invalid PostgreSQL identifier '{effective_db}' in TEST_DATABASE_URL '{redacted_input}'."
        )

    if not (
        db_clean.endswith("_test")
        or db_clean.startswith("test_")
        or db_clean == "folio_test"
        or "test" in db_clean.split("_")
    ):
        raise TestDatabaseSafetyError(
            f"Unsafe TEST_DATABASE_URL '{redacted_input}': Target database name '{effective_db}' must end with '_test', "
            f"start with 'test_', or designate a test database to prevent data loss."
        )

    # 7. Collision Detection against Primary DATABASE_URL
    if main_db_url_str:
        redacted_main = redact_url_credentials(main_db_url_str)
        try:
            main_url = make_url(main_db_url_str)
            main_eval_url = main_url
            if main_url.drivername == "postgresql":
                main_eval_url = main_url.set(drivername="postgresql+psycopg")

            main_engine = create_engine(main_eval_url)
            _, main_kwargs = main_engine.dialect.create_connect_args(main_engine.url)
            main_engine.dispose()

            main_effective_db = main_kwargs.get("dbname") or main_url.database
            main_effective_host = main_kwargs.get("host") or main_url.host
            main_effective_port = main_kwargs.get("port") or main_url.port

            norm_main_host = normalize_host(main_effective_host)
            norm_main_port = normalize_port(main_effective_port)
            main_db_clean = (main_effective_db or "").strip().lower()

            if norm_test_host == norm_main_host and norm_test_port == norm_main_port:
                if db_clean == main_db_clean:
                    raise TestDatabaseSafetyError(
                        f"Collision detected: TEST_DATABASE_URL and DATABASE_URL both target database '{effective_db}' "
                        f"on normalized host {norm_test_host}:{norm_test_port}."
                    )

            # Global protection: test target must never equal primary database name on any host
            if db_clean == main_db_clean:
                raise TestDatabaseSafetyError(
                    f"Collision detected: TEST_DATABASE_URL targets database '{effective_db}' which matches primary DATABASE_URL name."
                )

        except TestDatabaseSafetyError:
            raise
        except Exception as e:
            # If main URL is unparseable, warn but do not silently bypass if test targets protected name
            if db_clean in ("folio", "folio_prod"):
                raise TestDatabaseSafetyError(
                    f"Unsafe test database name '{effective_db}' collides with default application database name."
                )

    return TargetValidationResult(
        test_url_str=test_db_url_str,
        redacted_url_str=redacted_input,
        driver_name=driver,
        effective_host=effective_host or "127.0.0.1",
        effective_port=effective_port or DEFAULT_POSTGRES_PORT,
        effective_database=effective_db,
        normalized_host=norm_test_host,
        normalized_port=norm_test_port,
    )


def validate_test_database_safety(test_db_url_str: str, main_db_url_str: str | None = None) -> str:
    """
    Backwards-compatible entrypoint that validates safety and returns the validated test DB URL string.
    Raises TestDatabaseSafetyError (subclass of RuntimeError) on violation.
    """
    result = validate_test_database_target(test_db_url_str, main_db_url_str)
    return result.test_url_str


# --- Test Run Ownership Manifest & Lifecycle ---

@dataclass
class TestRunManifest:
    """
    Manifest recording ownership of databases provisioned by a specific test run.
    Ensures safe teardown and mutation boundaries without blanket terminating other runs.
    Contains no secrets.
    """
    __test__ = False
    run_id: str
    created_at: str
    pid: int
    created_databases: Set[str] = field(default_factory=set)
    owned_endpoints: Dict[str, Tuple[str, int]] = field(default_factory=dict)

    @classmethod
    def create(cls, run_id: str | None = None) -> "TestRunManifest":
        import uuid
        rid = run_id or f"run_{uuid.uuid4().hex[:8]}"
        # Ensure valid identifier characters
        rid = re.sub(r"[^a-zA-Z0-9_]", "_", rid)
        return cls(
            run_id=rid,
            created_at=datetime.utcnow().isoformat() + "Z",
            pid=os.getpid(),
            created_databases=set(),
        )

    def generate_db_name(self, prefix: str = "folio_test") -> str:
        """Generates a unique, valid PostgreSQL database name qualified by this run ID."""
        prefix_clean = re.sub(r"[^a-zA-Z0-9_]", "_", prefix)
        suffix = self.run_id[-40:]
        name = f"{prefix_clean[:62 - len(suffix)]}_{suffix}"
        return name.lower()

    def is_owned(self, dbname: str) -> bool:
        """Verifies whether the given database name was provisioned and owned by this test run."""
        return dbname.strip().lower() in self.created_databases

    def register_owned(self, dbname: str, target: TargetValidationResult | None = None) -> None:
        """Registers a newly created database in this run manifest."""
        self.created_databases.add(dbname.strip().lower())
        if target is not None:
            self.owned_endpoints[dbname.strip().lower()] = ownership_endpoint(target)

    def require_endpoint(self, dbname: str, target: TargetValidationResult) -> None:
        """A database name alone never authorizes a destructive operation on another server."""
        owned = self.owned_endpoints.get(dbname.strip().lower())
        if owned != ownership_endpoint(target):
            raise UnownedDatabaseError(f"Database '{dbname}' is not owned at this server endpoint.")

    def unregister_owned(self, dbname: str) -> None:
        """Removes a destroyed database from this run manifest."""
        self.created_databases.discard(dbname.strip().lower())
        self.owned_endpoints.pop(dbname.strip().lower(), None)

    def to_dict(self) -> Dict[str, Any]:
        """Returns non-secret manifest representation for logging and handoff."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "pid": self.pid,
            "created_databases": sorted(list(self.created_databases)),
        }


# --- Connected Identity Verification & Mutation Guards ---

def verify_connected_identity(connection, expected_dbname: str, target: TargetValidationResult | None = None) -> Dict[str, Any]:
    """
    Queries current connection identity and verifies it strictly matches the expected owned test database.
    
    IMPORTANT: Never issues any DROP or mutation statements if identity check fails.
    """
    from sqlalchemy import text

    row = connection.execute(
        text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")
    ).fetchone()

    if not row:
        raise ConnectedIdentityMismatchError("Failed to retrieve connected server identity from PostgreSQL.")

    connected_db, connected_user, server_addr, server_port = row[0], row[1], row[2], row[3]
    # PostgreSQL's inet::text includes a host mask (127.0.0.1/32, ::1/128).
    server_host = str(server_addr).split("/", 1)[0] if server_addr is not None else None

    if connected_db.strip().lower() != expected_dbname.strip().lower():
        raise ConnectedIdentityMismatchError(
            f"Connected database identity mismatch! Connected to '{connected_db}' (user: '{connected_user}') "
            f"but expected owned test database '{expected_dbname}'. Aborting mutation without DROP!"
        )

    if target is not None:
        import socket
        expected_addresses = {target.effective_host}
        expected_addresses.update(info[4][0] for info in socket.getaddrinfo(target.effective_host, None))
        if server_host is None or server_host not in expected_addresses or server_port != target.normalized_port:
            raise ConnectedIdentityMismatchError("Connected server endpoint mismatch. Aborting mutation without DROP!")

    return {
        "connected_database": connected_db,
        "connected_user": connected_user,
        "server_addr": server_addr,
        "server_port": server_port,
    }


def safe_reset_test_schema(test_engine, manifest: TestRunManifest, expected_dbname: str) -> None:
    """
    Safely resets public schema on a test database:
    1. Asserts database is owned by the current run manifest.
    2. Verifies connected database identity before executing DDL.
    3. Resets schema cleanly.
    """
    if not manifest.is_owned(expected_dbname):
        raise UnownedDatabaseError(
            f"Refusing schema reset: Database '{expected_dbname}' is not registered in current run manifest ({manifest.run_id})."
        )

    from sqlalchemy import text

    target = validate_test_database_target(test_engine.url.render_as_string(hide_password=False))
    manifest.require_endpoint(expected_dbname, target)

    with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        verify_connected_identity(conn, expected_dbname, target)
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def selective_terminate_backends_sql(target_dbname: str) -> str:
    """
    Generates the exact SQL to terminate connections ONLY for target_dbname.
    Strictly prevents blanket termination of other test runs or databases.
    """
    # Escapes single quotes defensively
    safe_name = target_dbname.replace("'", "''")
    return (
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{safe_name}' AND pid <> pg_backend_pid()"
    )


def provision_test_database(
    admin_url_str: str,
    manifest: TestRunManifest,
    requested_dbname: str | None = None,
    target_database: str | None = None,
) -> str:
    """
    Provisions a new PostgreSQL test database owned by the current run manifest:
    1. Validates admin URL (must be PostgreSQL, pointing to 'postgres' or admin DB).
    2. Checks if requested database name already exists in pg_database.
    3. If it exists and is NOT owned by this run manifest: raises UnownedDatabaseError.
    4. If not exists: executes CREATE DATABASE and registers ownership in manifest.
    5. Returns the validated test database URL string.

    Accepts either `requested_dbname` or `target_database` keyword arguments for consistency.
    """
    from sqlalchemy import text

    admin_url = make_url(admin_url_str)
    if not (admin_url.drivername.startswith("postgresql")):
        raise TestDatabaseSafetyError("Admin connection must use PostgreSQL driver.")

    target = requested_dbname or target_database
    target_name = (target or manifest.generate_db_name()).strip().lower()

    if target_name in PROTECTED_DB_NAMES:
        raise TestDatabaseSafetyError(f"Cannot provision protected database name '{target_name}'.")

    if not VALID_IDENTIFIER_REGEX.match(target_name):
        raise TestDatabaseSafetyError(f"Invalid PostgreSQL identifier '{target_name}'.")

    if check_ambient_libpq_env():
        raise AmbientEnvOverrideError("Ambient libpq target overrides must be removed before provisioning.")
    # Validate the effective driver target BEFORE CREATE DATABASE or any other mutation.
    test_url = admin_url.set(database=target_name)
    test_url_str = test_url.render_as_string(hide_password=False)
    validated = validate_test_database_target(test_url_str)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            verify_connected_identity(conn, admin_url.database, validated)
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target_name},
            ).scalar()

            if exists:
                if not manifest.is_owned(target_name):
                    raise UnownedDatabaseError(
                        f"Database '{target_name}' already exists on server and is not owned by current test manifest {manifest.run_id}. "
                        f"Refusing to touch or reuse unowned database."
                    )
                manifest.require_endpoint(target_name, validated)
            else:
                conn.execute(text(f'CREATE DATABASE "{target_name}"'))
                manifest.register_owned(target_name, validated)
    finally:
        admin_engine.dispose()

    # Build validated test URL pointing to the newly provisioned owned database
    return test_url_str


def safe_teardown_test_database(
    admin_url_str: str,
    manifest: TestRunManifest,
    dbname: str,
) -> None:
    """
    Tears down a test database ONLY if explicitly owned by this test run manifest:
    1. Checks manifest ownership. If unowned: aborts with UnownedDatabaseError.
    2. Terminates connections ONLY for dbname (never blanket terminates).
    3. Drops the owned database.
    4. Removes from manifest.
    """
    from sqlalchemy import text

    target_name = dbname.strip().lower()
    if not manifest.is_owned(target_name):
        raise UnownedDatabaseError(
            f"Refusing teardown: Database '{target_name}' is not registered in current run manifest ({manifest.run_id})."
        )

    admin_url = make_url(admin_url_str)
    target = validate_test_database_target(admin_url.set(database=target_name).render_as_string(hide_password=False))
    manifest.require_endpoint(target_name, target)
    if check_ambient_libpq_env():
        raise AmbientEnvOverrideError("Ambient libpq target overrides must be removed before teardown.")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            verify_connected_identity(conn, admin_url.database, target)
            # Selectively terminate connections only for this specific owned database
            conn.execute(text(selective_terminate_backends_sql(target_name)))
            conn.execute(text(f'DROP DATABASE IF EXISTS "{target_name}"'))
            manifest.unregister_owned(target_name)
    finally:
        admin_engine.dispose()

