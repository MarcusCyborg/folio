import os
import sys
import time
import socket
import urllib.request
import threading
from pathlib import Path
import pytest
import uvicorn
from sqlalchemy import create_engine, text, pool
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.config import settings
from src.backend.core.database import get_db
import src.backend.core.database as core_db
from src.backend.main import app
from src.backend.models.base import Base
from src.backend.core.artifact_utils import get_artifact_context
from src.backend.core.test_db_guard import (
    validate_test_database_safety,
    validate_test_database_target,
    TestRunManifest,
    verify_connected_identity,
    safe_reset_test_schema,
    selective_terminate_backends_sql,
    provision_test_database,
    safe_teardown_test_database,
    UnownedDatabaseError,
    TestDatabaseSafetyError,
    ConnectedIdentityMismatchError,
    sanitize_ambient_libpq_env,
)

# Unified artifact context for this test session (remediating IA-07)
artifact_ctx = get_artifact_context()
FAILURE_SCREENSHOTS_DIR = artifact_ctx.get_failures_dir()
FAILURE_TRACES_DIR = artifact_ctx.get_traces_dir()

# Sanitize ambient libpq environment variables to prevent driver target redirection
sanitize_ambient_libpq_env()

# Test run ownership manifest for this pytest session
session_manifest = TestRunManifest.create()

# Validate test database target using pure effective-driver-target safety guard
target_validation = validate_test_database_target(settings.TEST_DATABASE_URL, settings.DATABASE_URL)
test_db_url = target_validation.test_url_str
# Database ownership is ONLY registered after successful CREATE DATABASE in ensure_test_database_exists

test_engine = create_engine(test_db_url, poolclass=pool.NullPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, expire_on_commit=False)

# Rebind core database engine and SessionLocal to guarantee all workers, middleware, and live server use test DB
core_db.engine = test_engine
core_db.SessionLocal = TestingSessionLocal


def is_database_reachable(db_url_str: str, timeout_sec: float = 2.0) -> bool:
    """Fast check whether the database server is responding within timeout_sec."""
    try:
        url = make_url(db_url_str)
        admin_url = url.set(database="postgres")
        engine = create_engine(admin_url, connect_args={"connect_timeout": timeout_sec})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def ensure_test_database_exists(db_url_str: str):
    """
    Connects to administrative database ('postgres') and provisions the test DB if it does not exist.
    Registers ownership in session_manifest ONLY after successful CREATE DATABASE.
    If target DB already existed prior to run, ownership is not registered, causing safe_reset
    to reject unowned DB mutation.
    """
    url = make_url(db_url_str)
    target_db = url.database
    if not target_db:
        raise TestDatabaseSafetyError("No target database specified in test URL.")

    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 2})
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target_db}
            ).scalar()
            if not exists:
                print(f"[conftest] Auto-creating test database '{target_db}'...")
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                session_manifest.register_owned(target_db)
                print(f"[conftest] Test database '{target_db}' created successfully.")
            else:
                # If target already exists prior to run, do not claim ownership or terminate backends
                if session_manifest.is_owned(target_db):
                    conn.execute(text(selective_terminate_backends_sql(target_db)))
                else:
                    print(f"[conftest] Database '{target_db}' already exists and is not owned by run {session_manifest.run_id}.")
    except Exception as e:
        print(f"[conftest] Note on auto-create test DB: {e}")
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database():
    """
    Ensures test database exists, resets public schema safely with connected identity check,
    runs Alembic migrations to head, and seeds clean baseline fixtures. Disposes connections on teardown.
    When PostgreSQL test instance is unavailable, skips live DB tests reporting BLOCKED_ENV.
    """
    if not is_database_reachable(test_db_url):
        pytest.skip(
            f"BLOCKED_ENV: PostgreSQL test instance at {target_validation.redacted_url_str} is not reachable. Live database fixtures skipped.",
            allow_module_level=True,
        )

    ensure_test_database_exists(test_db_url)

    # 1. Reset schema safely with pre-mutation connected identity check (never auto-drops on mismatch)
    safe_reset_test_schema(test_engine, session_manifest, target_validation.effective_database)

    # 2. Run alembic upgrade head
    import argparse
    from alembic.config import Config
    from alembic import command
    alembic_ini_path = PROJECT_ROOT / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_cfg.cmd_opts = argparse.Namespace(x=[f"db_url={test_db_url}"])
    old_db_url_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_db_url
    print("[conftest] Running 'alembic upgrade head' on test database...")
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if old_db_url_env is not None:
            os.environ["DATABASE_URL"] = old_db_url_env
        else:
            os.environ.pop("DATABASE_URL", None)
    print("[conftest] Alembic migrations completed successfully.")

    # 3. Seed baseline fixtures idempotently
    from scripts.seed_folio import run_seed
    print("[conftest] Seeding test database fixtures...")
    run_seed(target=test_engine)
    print("[conftest] Test database seeded and ready.")

    yield

    # Safe teardown
    print("[conftest] Tearing down test database connections...")
    test_engine.dispose()


def reset_browser_test_data(engine):
    """
    Restores database state to pristine baseline after browser tests.
    Guarantees browser tests do not leak mutated state (settings, comments, reports, users, documents)
    to subsequent tests regardless of test execution order.
    """
    import json
    from scripts.seed_folio import DEFAULT_SETTINGS, ROLE_PERMISSIONS_DEFAULTS, DEMO_USERS

    try:
        with engine.begin() as conn:
            # 1. Reset AppSettings to default
            for k, v in DEFAULT_SETTINGS.items():
                val_str = json.dumps(v)
                conn.execute(text("UPDATE app_settings SET value = :v WHERE key = :k"), {"k": k, "v": val_str})

            # 2. Reset DEMO_USERS attributes (active=True, commenting_suspended_until=None)
            conn.execute(text(
                "UPDATE users SET commenting_suspended_until = NULL, is_active = true "
                "WHERE username IN ('admin', 'content_mgr', 'moderator', 'seo_specialist', 'reader')"
            ))
            for _, uname, _, rkey, _ in DEMO_USERS:
                conn.execute(text("UPDATE users SET role_key = :rkey WHERE username = :uname"), {"rkey": rkey, "uname": uname})
            # Delete non-demo users created during tests
            conn.execute(text(
                "DELETE FROM users WHERE username NOT IN ('admin', 'content_mgr', 'moderator', 'seo_specialist', 'reader')"
            ))

            # 3. Clean up test documents and document_tags created by tests
            conn.execute(text(
                "DELETE FROM document_tags WHERE document_id IN (SELECT id FROM documents WHERE title LIKE 'Quantum%')"
            ))
            conn.execute(text("DELETE FROM documents WHERE title LIKE 'Quantum%'"))

            # 4. Clean up test categories created by tests
            conn.execute(text("DELETE FROM categories WHERE slug LIKE 'quantum-tech-%'"))

            # 5. Clean up interaction tables
            conn.execute(text("DELETE FROM reports"))
            conn.execute(text("DELETE FROM sessions WHERE user_id IS NULL"))
    except Exception as e:
        print(f"[conftest] Note on reset_browser_test_data: {e}")


@pytest.fixture(autouse=True)
def isolate_frontend_test_database(request):
    """
    Auto-use fixture ensuring isolated clean database state before and after every frontend test.
    Guarantees test execution order independence.
    """
    is_frontend = "frontend" in str(request.node.fspath)
    if is_frontend and is_database_reachable(test_db_url):
        reset_browser_test_data(test_engine)
        yield
        reset_browser_test_data(test_engine)
    else:
        yield


@pytest.fixture
def db_session():
    """
    Yields a database session isolated with a nested savepoint transaction.
    Any commit within endpoints only commits to the savepoint;
    teardown rolls back the outer transaction, ensuring pristine DB state across all tests.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """Yields a FastAPI TestClient with get_db overridden to use db_session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server_readiness(base_url: str, timeout_sec: float = 15.0) -> bool:
    """Readiness polling loop: checks /health endpoint every 50ms up to timeout."""
    health_url = f"{base_url.rstrip('/')}/health"
    start = time.monotonic()
    while time.monotonic() - start < timeout_sec:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


@pytest.fixture(scope="session")
def live_server(prepare_test_database):
    """
    Centralized frontend test server fixture.
    Runs FastAPI with Uvicorn on an available port, verifies readiness via polling,
    and cleanly tears down on session completion.
    """
    port = int(os.environ.get("FOLIO_TEST_PORT", 0)) or get_free_port()
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    ready = wait_for_server_readiness(base_url, timeout_sec=15.0)
    if not ready:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError(f"Live server at {base_url} failed readiness health check within 15 seconds.")

    print(f"\n[conftest] Live test server ready at {base_url}")
    yield base_url

    print(f"\n[conftest] Shutting down live test server at {base_url}...")
    server.should_exit = True
    thread.join(timeout=3.0)


@pytest.fixture(scope="session")
def browser_instance():
    """
    Centralized browser launcher:
    - Primary: Playwright's installed Chromium.
    - Optional: System browser channels ('chrome', 'msedge') if configured or available.
    - Tracing: Automatically instruments newly created contexts with tracing.start().
    """
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    browser = None
    channel = os.environ.get("FOLIO_BROWSER_CHANNEL")

    if channel:
        try:
            browser = p.chromium.launch(channel=channel, headless=True)
        except Exception as e:
            print(f"[conftest] Warning: Channel '{channel}' failed ({e}); falling back to standard Chromium.")

    if browser is None:
        browser = p.chromium.launch(headless=True)

    # Instrument new_context to start Playwright tracing on every context
    original_new_context = browser.new_context

    def context_factory(*args, **kwargs):
        ctx = original_new_context(*args, **kwargs)
        try:
            ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
            ctx._folio_tracing_active = True
        except Exception as e:
            print(f"[conftest] Note: could not start tracing: {e}")
            ctx._folio_tracing_active = False
        return ctx

    browser.new_context = context_factory

    yield browser

    browser.close()
    p.stop()


# Hook to capture failure screenshots and Playwright traces
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call":
        browser = item.funcargs.get("browser_instance")
        if browser:
            if report.failed:
                # Capture screenshots and save traces for all active contexts
                for c_idx, context in enumerate(browser.contexts):
                    for p_idx, page in enumerate(context.pages):
                        screenshot_path = artifact_ctx.get_failure_screenshot_path(item.name, p_idx)
                        try:
                            page.screenshot(path=str(screenshot_path), full_page=True)
                            print(f"\n[Artifact] Saved failure screenshot to: {screenshot_path}")
                        except Exception as e:
                            print(f"\n[Artifact] Failed to save screenshot: {e}")

                    if getattr(context, "_folio_tracing_active", False):
                        trace_path = artifact_ctx.get_failure_trace_path(item.name, c_idx)
                        try:
                            context.tracing.stop(path=str(trace_path))
                            context._folio_tracing_active = False
                            print(f"\n[Artifact] Saved failure trace to: {trace_path}")
                        except Exception as e:
                            print(f"\n[Artifact] Failed to save trace: {e}")
            else:
                # Passed: stop tracing without saving to conserve disk space
                for context in browser.contexts:
                    if getattr(context, "_folio_tracing_active", False):
                        try:
                            context.tracing.stop()
                            context._folio_tracing_active = False
                        except Exception:
                            pass
