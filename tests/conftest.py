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
test_db_url = make_url(target_validation.test_url_str).set(
    database=session_manifest.generate_db_name(target_validation.effective_database)
).render_as_string(hide_password=False)
target_validation = validate_test_database_target(test_db_url, settings.DATABASE_URL)
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
    return provision_test_database(
        url.set(database="postgres").render_as_string(hide_password=False),
        session_manifest, requested_dbname=url.database,
    )


def build_active_lexical_index_for_engine(engine) -> str:
    """Builds a fresh active lexical index generation for the given SQLAlchemy engine and resets reader cache."""
    from src.backend.search_index.manager import GenerationManager
    from src.backend.services.search.search_service import search_engine

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    idx_db = session_factory()
    try:
        gen = GenerationManager.build_new_generation(idx_db, force=True)
        gen_id = gen.id
    finally:
        idx_db.close()
    search_engine.clear_cache()
    return gen_id


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

    try:
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
    finally:
        test_engine.dispose()
        if session_manifest.is_owned(target_validation.effective_database):
            safe_teardown_test_database(
                make_url(test_db_url).set(database="postgres").render_as_string(hide_password=False),
                session_manifest, target_validation.effective_database,
            )


def reset_browser_test_data(engine, manifest=None, build_index: bool = True):
    """
    Restores database state to pristine baseline after browser tests.
    Guarantees browser tests do not leak mutated state (settings, comments, reports, users, documents)
    to subsequent tests regardless of test execution order, and builds an active lexical index generation
    so healthy BM25 requests do not inadvertently degrade to ILIKE_FALLBACK.
    """
    from scripts.seed_folio import run_seed
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            target = validate_test_database_target(engine.url.render_as_string(hide_password=False))
            if manifest is None or not manifest.is_owned(target.effective_database):
                raise UnownedDatabaseError("Browser reset requires an owned run database.")
            manifest.require_endpoint(target.effective_database, target)
            verify_connected_identity(conn, target.effective_database, target)
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    run_seed(target=engine)
    if build_index:
        build_active_lexical_index_for_engine(engine)


@pytest.fixture
def active_lexical_index():
    """Ensures an active lexical index generation is built and ready for the live test database."""
    return build_active_lexical_index_for_engine(test_engine)


@pytest.fixture(autouse=True)
def isolate_frontend_test_database(request):
    """
    Auto-use fixture ensuring isolated clean database state before and after every frontend test.
    Guarantees test execution order independence.
    """
    is_frontend = "frontend" in str(request.node.fspath)
    if is_frontend and is_database_reachable(test_db_url):
        stop_live_server()
        reset_browser_test_data(test_engine, session_manifest)
        start_live_server()
        yield
        browser = request.node.funcargs.get("browser_instance")
        if browser:
            for context in browser.contexts:
                context.close()
        stop_live_server()
        reset_browser_test_data(test_engine, session_manifest)
    else:
        yield


@pytest.fixture
def db_session():
    """
    Yields a database session isolated with a nested savepoint transaction.
    Any commit within endpoints only commits to the savepoint;
    teardown rolls back the outer transaction, ensuring pristine DB state across all tests.
    """
    from src.backend.core.rate_limit import rate_limiter

    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        try:
            rate_limiter.reset()
        except Exception:
            pass


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


_live_server_state = {}


def start_live_server():
    state = _live_server_state
    if not state or state.get("running"):
        return
    config = uvicorn.Config(app, host="127.0.0.1", port=state["port"], log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    state.update(server=server, thread=thread, running=True)
    thread.start()
    if not wait_for_server_readiness(state["base_url"]):
        stop_live_server()
        raise RuntimeError("Live test server failed readiness polling")


def stop_live_server():
    state = _live_server_state
    if state.get("running"):
        state["server"].should_exit = True
        state["thread"].join(timeout=10)
        if state["thread"].is_alive():
            raise RuntimeError("Server did not drain; refusing browser database reset")
        state["running"] = False


@pytest.fixture(scope="session")
def live_server(prepare_test_database):
    port = int(os.environ.get("FOLIO_TEST_PORT", 0)) or get_free_port()
    base_url = f"http://127.0.0.1:{port}"
    _live_server_state.update(port=port, base_url=base_url, running=False)
    start_live_server()
    try:
        yield base_url
    finally:
        stop_live_server()
        _live_server_state.clear()


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
