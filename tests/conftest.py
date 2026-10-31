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
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.config import settings
from src.backend.core.database import get_db
import src.backend.core.database as core_db
from src.backend.main import app
from src.backend.models.base import Base

# Artifact directories for test failures
TEST_RESULTS_DIR = PROJECT_ROOT / "test-results"
FAILURE_SCREENSHOTS_DIR = TEST_RESULTS_DIR / "screenshots"
FAILURE_TRACES_DIR = TEST_RESULTS_DIR / "traces"
FAILURE_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
FAILURE_TRACES_DIR.mkdir(parents=True, exist_ok=True)

def validate_test_database_safety(test_db_url_str: str, main_db_url_str: str | None = None) -> str:
    """
    Strict safety guard for TEST_DATABASE_URL:
    - Parses URL structure to isolate target database name.
    - Prevents targeting root, development, or production databases.
    - Ensures target database name explicitly designates a test database.
    - Prevents accidental collision with primary DATABASE_URL.
    """
    try:
        test_url = make_url(test_db_url_str)
    except Exception as e:
        raise RuntimeError(f"Invalid TEST_DATABASE_URL '{test_db_url_str}': {e}") from e

    target_db = test_url.database
    if not target_db:
        raise RuntimeError(f"Unsafe TEST_DATABASE_URL '{test_db_url_str}': No target database name specified.")

    # Guard 1: Must be explicitly designated as a test database name
    target_db_clean = target_db.strip().lower()
    if not (target_db_clean.endswith("_test") or target_db_clean.startswith("test_") or target_db_clean == "folio_test"):
        raise RuntimeError(
            f"Unsafe TEST_DATABASE_URL '{test_db_url_str}': Target database name '{target_db}' must end with '_test', "
            f"start with 'test_', or equal 'folio_test' to prevent data loss."
        )

    # Guard 2: Prohibit reserved/production names
    forbidden_dbs = {"postgres", "template0", "template1", "folio", "folio_prod", "production", "prod"}
    if target_db_clean in forbidden_dbs:
        raise RuntimeError(
            f"Unsafe TEST_DATABASE_URL '{test_db_url_str}': Target database name '{target_db}' is a protected/production name."
        )

    # Guard 3: Must not collide with primary DATABASE_URL
    if main_db_url_str:
        try:
            main_url = make_url(main_db_url_str)
            if (
                test_url.host == main_url.host
                and test_url.port == main_url.port
                and target_db_clean == (main_url.database or "").strip().lower()
            ):
                raise RuntimeError(
                    f"Unsafe TEST_DATABASE_URL collision: TEST_DATABASE_URL and DATABASE_URL both target database '{target_db}' on {test_url.host}."
                )
        except RuntimeError:
            raise
        except Exception:
            pass

    return test_db_url_str


# Validate safety guard before creating test engine
test_db_url = validate_test_database_safety(settings.TEST_DATABASE_URL, settings.DATABASE_URL)
test_engine = create_engine(test_db_url, poolclass=pool.NullPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, expire_on_commit=False)

# Rebind core database engine and SessionLocal to guarantee all workers, middleware, and live server use test DB
core_db.engine = test_engine
core_db.SessionLocal = TestingSessionLocal


def ensure_test_database_exists(db_url_str: str):
    """Connects to administrative database ('postgres') and provisions the test DB if it does not exist."""
    url = make_url(db_url_str)
    target_db = url.database
    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target_db}
            ).scalar()
            if not exists:
                print(f"[conftest] Auto-creating test database '{target_db}'...")
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                print(f"[conftest] Test database '{target_db}' created successfully.")
            else:
                # Terminate any lingering connections to prevent lock deadlocks during schema reset
                conn.execute(
                    text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"),
                    {"name": target_db}
                )
    except Exception as e:
        print(f"[conftest] Note on auto-create test DB: {e}")
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database():
    """
    Ensures test database exists, resets public schema, runs Alembic migrations to head,
    and seeds clean baseline fixtures. Disposes connections on teardown.
    """
    ensure_test_database_exists(test_db_url)

    # 1. Reset schema for clean migration
    with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

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

    yield browser

    browser.close()
    p.stop()


# Hook to capture failure screenshots and Playwright traces
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # Check if browser_instance or page is in fixtures
        browser = item.funcargs.get("browser_instance")
        if browser:
            for c_idx, context in enumerate(browser.contexts):
                for p_idx, page in enumerate(context.pages):
                    screenshot_path = FAILURE_SCREENSHOTS_DIR / f"{item.name}_{c_idx}_{p_idx}_failed.png"
                    try:
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        print(f"\n[Artifact] Saved failure screenshot to: {screenshot_path}")
                    except Exception as e:
                        print(f"\n[Artifact] Failed to save screenshot: {e}")
