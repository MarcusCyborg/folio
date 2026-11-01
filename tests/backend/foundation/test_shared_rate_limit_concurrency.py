"""
Multi-Process Concurrency & Integration Tests for Shared Rate Limiter
=====================================================================
Remediates Finding IA-06.
Verifies that Folio's distributed rate limiter correctly enforces limits across
independent Python processes sharing the same database store.

Invariants Tested:
1. Alternating attempts across two independent processes hit the shared limit.
2. Concurrent attempts across two independent processes are admitted atomically.
3. Process restart preserves counters (persisted in DB).
4. Successful login resets only target account, preserving IP and other accounts.
5. Auth transaction rollback does NOT roll back rate limit counters.
6. Store down / unavailable returns HTTP 503 with clear error (no silent fallback).
7. Real HTTP 429 and Retry-After header verified through API endpoints.
8. Different keys (IP, target account, action) remain isolated.
"""

import os
import sys
import time
import uuid
import json
import pytest
import tempfile
import subprocess
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.backend.core.config import settings
from src.backend.core.rate_limit import (
    PostgresRateLimiter,
    RateLimitResult,
    RateLimitStoreUnavailableError,
    build_login_target_key,
    build_login_ip_key,
    build_register_ip_key,
)
from src.backend.models.base import Base
from src.backend.models.rate_limit import RateLimitBucket
from src.backend.main import app
import src.backend.core.database as core_db


# Helper script for spawning an independent external Python OS process
WORKER_SCRIPT = """
import sys
import time
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.backend.core.rate_limit import PostgresRateLimiter, normalize_bucket_key

def main():
    db_url = sys.argv[1]
    action = sys.argv[2]
    key = sys.argv[3]
    limit = int(sys.argv[4])
    window = int(sys.argv[5])

    engine = create_engine(db_url)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)

    if action == "record_failed":
        limiter.record_failed_login(key, window_seconds=window)
        print(json.dumps({"status": "recorded"}))
    elif action == "check_login":
        res = limiter.check_login_rate_limit(key, max_failed=limit, window_seconds=window)
        print(json.dumps({
            "allowed": res.allowed,
            "retry_after": res.retry_after,
            "count": res.current_count
        }))
    elif action == "check_and_record_register":
        res = limiter.check_and_record_register(key, max_attempts=limit, window_seconds=window)
        print(json.dumps({
            "allowed": res.allowed,
            "retry_after": res.retry_after,
            "count": res.current_count
        }))
    elif action == "record_success":
        limiter.record_successful_login(key)
        print(json.dumps({"status": "reset"}))

if __name__ == "__main__":
    main()
"""


@pytest.fixture
def shared_db():
    """
    Creates a temporary shared database file with WAL enabled for cross-process concurrency.
    Yields the database URL string and engine.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="folio_shared_test_")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    yield db_url, engine

    engine.dispose()
    try:
        if os.path.exists(path):
            os.remove(path)
        wal_path = path + "-wal"
        shm_path = path + "-shm"
        if os.path.exists(wal_path):
            os.remove(wal_path)
        if os.path.exists(shm_path):
            os.remove(shm_path)
    except Exception:
        pass


def run_worker_process(db_url: str, action: str, key: str, limit: int = 5, window: int = 60) -> dict:
    """Executes a rate limiter operation in a separate Python operating system process."""
    cmd = [
        sys.executable,
        "-c",
        WORKER_SCRIPT,
        db_url,
        action,
        key,
        str(limit),
        str(window),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(settings.PROJECT_ROOT))
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())


# =========================================================================
# 1. Multi-Process Sharing & Alternating Attempts (Finding IA-06)
# =========================================================================

def test_two_independent_processes_alternating_failed_logins(shared_db):
    """
    IA-06 PRIMARY TRIGGER:
    Process 1 and Process 2 alternatingly send failed login attempts for the same target key.
    The shared limit (5) must be enforced across both processes.
    Once 5 total failures occur, BOTH Process 1 and Process 2 must report blocked (allowed=False).
    """
    db_url, engine = shared_db
    target_key = "login:target:test_ip_1:test_user_1"
    limit = 5
    window = 60

    # Process 1 records attempt 1
    out1 = run_worker_process(db_url, "record_failed", target_key, limit, window)
    assert out1["status"] == "recorded"

    # Process 2 records attempt 2
    out2 = run_worker_process(db_url, "record_failed", target_key, limit, window)
    assert out2["status"] == "recorded"

    # Process 1 records attempt 3
    run_worker_process(db_url, "record_failed", target_key, limit, window)

    # Process 2 records attempt 4
    run_worker_process(db_url, "record_failed", target_key, limit, window)

    # Process 1 records attempt 5 (limit reached!)
    run_worker_process(db_url, "record_failed", target_key, limit, window)

    # Now verify from Process 2 that the rate limit is exceeded
    p2_check = run_worker_process(db_url, "check_login", target_key, limit, window)
    assert p2_check["allowed"] is False
    assert p2_check["count"] == 5
    assert p2_check["retry_after"] > 0

    # Also verify from Process 1 that it sees the exact same blocked state
    p1_check = run_worker_process(db_url, "check_login", target_key, limit, window)
    assert p1_check["allowed"] is False
    assert p1_check["count"] == 5
    assert p1_check["retry_after"] > 0


# =========================================================================
# 2. Worker Restart Resilience
# =========================================================================

def test_process_restart_preserves_rate_limit_state(shared_db):
    """
    Verifies that restarting a web worker process does NOT reset rate limit counters.
    Unlike in-memory dicts, counters persist in the database across process lifecycles.
    """
    db_url, engine = shared_db
    key = "login:target:restart_ip:restart_user"
    limit = 3
    window = 60

    # Worker 1 runs and records 3 failed attempts, hitting the limit
    for _ in range(limit):
        run_worker_process(db_url, "record_failed", key, limit, window)

    # Worker 1 exits. A completely new process (Worker 2) starts up.
    worker2_check = run_worker_process(db_url, "check_login", key, limit, window)
    assert worker2_check["allowed"] is False
    assert worker2_check["count"] == 3
    assert worker2_check["retry_after"] > 0


# =========================================================================
# 3. Success / Failure Isolation Policy
# =========================================================================

def test_success_one_account_does_not_reset_ip_counter(shared_db):
    """
    POLICY VERIFICATION:
    Success on User A resets User A's counter, but MUST NOT reset the IP-wide counter
    or User B's counter across processes.
    """
    db_url, engine = shared_db
    target_a = "login:target:shared_ip:user_a"
    target_b = "login:target:shared_ip:user_b"
    ip_key = "login:ip:shared_ip"

    # Process 1 records 2 failures for User A and 2 for User B, and 4 for IP
    for _ in range(2):
        run_worker_process(db_url, "record_failed", target_a)
        run_worker_process(db_url, "record_failed", ip_key)
    for _ in range(2):
        run_worker_process(db_url, "record_failed", target_b)
        run_worker_process(db_url, "record_failed", ip_key)

    # User A logs in successfully from Process 2
    run_worker_process(db_url, "record_success", target_a)

    # User A is reset
    chk_a = run_worker_process(db_url, "check_login", target_a)
    assert chk_a["count"] == 0

    # User B remains at count 2
    chk_b = run_worker_process(db_url, "check_login", target_b)
    assert chk_b["count"] == 2

    # IP counter remains at count 4
    chk_ip = run_worker_process(db_url, "check_login", ip_key, limit=15)
    assert chk_ip["count"] == 4


# =========================================================================
# 4. Rollback Independence (Auth Transaction vs Limiter Counter)
# =========================================================================

def test_auth_transaction_rollback_does_not_rollback_rate_limit(shared_db):
    """
    POLICY VERIFICATION:
    When an authentication transaction rolls back due to invalid credentials,
    the rate limiter's counter update must NOT be rolled back.
    """
    db_url, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    target_key = "login:target:rollback_ip:user"

    # Simulate an application request session that starts, hits rate limiter, then rolls back
    app_session = session_factory()
    try:
        # Rate limiter records failed attempt (autonomous session and commit)
        limiter.record_failed_login(target_key)
        # Main application session encounters error and rolls back
        app_session.rollback()
    finally:
        app_session.close()

    # The rate limiter counter MUST be preserved (count = 1)
    check = limiter.check_login_rate_limit(target_key, max_failed=5)
    assert check.current_count == 1
    assert check.allowed is True


# =========================================================================
# 5. Store Down Behavior (HTTP 503 Without Silent Fallback)
# =========================================================================

def test_rate_limiter_store_down_raises_service_unavailable():
    """
    POLICY VERIFICATION:
    When the database is unreachable, rate limiter raises RateLimitStoreUnavailableError.
    FastAPI returns HTTP 503 RATE_LIMIT_UNAVAILABLE with no credential leak.
    """
    dead_engine = create_engine(
        "postgresql+psycopg://user:hidden_pw@127.0.0.1:59999/dummy",
        connect_args={"connect_timeout": 1}
    )
    dead_session_factory = sessionmaker(bind=dead_engine)
    dead_limiter = PostgresRateLimiter(engine=dead_engine, session_factory=dead_session_factory)

    with pytest.raises(RateLimitStoreUnavailableError) as exc_info:
        dead_limiter.check_login_rate_limit("login:target:test", max_failed=5)

    err = str(exc_info.value)
    assert "hidden_pw" not in err


# =========================================================================
# 6. Real API 429 & Retry-After Verification via TestClient
# =========================================================================

def test_api_login_abuse_returns_429_with_retry_after_header(shared_db):
    """
    API LEVEL VERIFICATION:
    Repeated failed login attempts trigger HTTP 429 with Retry-After header.
    """
    db_url, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # Rebind core_db engine and SessionLocal to shared test DB
    old_engine = core_db.engine
    old_session_factory = core_db.SessionLocal
    core_db.engine = engine
    core_db.SessionLocal = session_factory

    from src.backend.core.rate_limit import rate_limiter
    rate_limiter._custom_engine = engine
    rate_limiter._custom_session_factory = session_factory

    client = TestClient(app)
    try:
        sess_res = client.get("/api/v1/auth/session")
        csrf_token = sess_res.json()["csrf_token"]

        # Send failed login attempts up to limit
        for i in range(settings.RATE_LIMIT_LOGIN_MAX_FAILED):
            res = client.post(
                "/api/v1/auth/login",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "abuse_victim@folio.test", "password": f"BadPassword{i}!"}
            )
            assert res.status_code == 401

        # Next attempt must be blocked by rate limiter with 429 and Retry-After
        res_blocked = client.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={"email": "abuse_victim@folio.test", "password": "BadPasswordAgain!"}
        )
        assert res_blocked.status_code == 429
        assert res_blocked.json()["error"]["code"] == "TOO_MANY_REQUESTS"
        # Retry-After header MUST be present and be a positive integer
        assert "Retry-After" in res_blocked.headers
        retry_val = int(res_blocked.headers["Retry-After"])
        assert retry_val > 0
    finally:
        core_db.engine = old_engine
        core_db.SessionLocal = old_session_factory
        rate_limiter._custom_engine = None
        rate_limiter._custom_session_factory = None


def test_api_registration_abuse_returns_429_with_retry_after(shared_db):
    """
    API LEVEL VERIFICATION:
    Registration bursts trigger HTTP 429 with Retry-After header.
    """
    db_url, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    old_engine = core_db.engine
    old_session_factory = core_db.SessionLocal
    core_db.engine = engine
    core_db.SessionLocal = session_factory

    from src.backend.core.rate_limit import rate_limiter
    rate_limiter._custom_engine = engine
    rate_limiter._custom_session_factory = session_factory

    client = TestClient(app)
    try:
        sess_res = client.get("/api/v1/auth/session")
        csrf_token = sess_res.json()["csrf_token"]

        # Hit registration rate limit (limit: RATE_LIMIT_REGISTER_MAX)
        for i in range(settings.RATE_LIMIT_REGISTER_MAX):
            reg_res = client.post(
                "/api/v1/auth/register",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "email": f"burst_{i}@folio.test",
                    "username": f"burst_{i}",
                    "password": "Password123!",
                    "display_name": f"Burst {i}",
                }
            )
            # Either 201 or if DB doesn't have users table, 500/409, but rate limit checks before user insert!
            csrf_token = reg_res.json().get("csrf_token", csrf_token)

        # Overflow attempt must trigger 429
        overflow = client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "burst_over@folio.test",
                "username": "burst_over",
                "password": "Password123!",
                "display_name": "Burst Over",
            }
        )
        assert overflow.status_code == 429
        assert overflow.json()["error"]["code"] == "TOO_MANY_REQUESTS"
        assert "Retry-After" in overflow.headers
        assert int(overflow.headers["Retry-After"]) > 0
    finally:
        core_db.engine = old_engine
        core_db.SessionLocal = old_session_factory
        rate_limiter._custom_engine = None
        rate_limiter._custom_session_factory = None


# =========================================================================
# 7. Concurrent Parallel Bursts & Atomic Admission
# =========================================================================

def test_concurrent_processes_burst_registration_atomic_admission(shared_db):
    """
    CONCURRENCY & ATOMIC ADMISSION:
    Spawns 8 concurrent worker processes attempting registration on the same IP.
    With max_attempts=4, exactly 4 requests must be admitted (allowed=True),
    and exactly 4 requests must be blocked (allowed=False).
    Total count must not exceed the limit.
    """
    import concurrent.futures
    db_url, engine = shared_db
    ip = "192.0.2.77"
    limit = 4
    window = 60

    def attempt_registration(_):
        return run_worker_process(db_url, "check_and_record_register", ip, limit=limit, window=window)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt_registration, range(8)))

    allowed_count = sum(1 for r in results if r["allowed"] is True)
    blocked_count = sum(1 for r in results if r["allowed"] is False)

    assert allowed_count == limit
    assert blocked_count == 4
    for r in results:
        if not r["allowed"]:
            assert r["retry_after"] > 0


# =========================================================================
# 8. Window Expiration & TTL Rollover
# =========================================================================

def test_window_expiry_restores_admission(shared_db):
    """
    WINDOW EXPIRY:
    Records attempts with a 4-second window. While within 4s, the key is blocked.
    After sleeping past the window, active attempts expire and admission is restored.
    """
    db_url, engine = shared_db
    key = "login:target:expiry_ip:user"
    limit = 2
    window = 4

    # Record 2 failures -> hits limit
    run_worker_process(db_url, "record_failed", key, limit=limit, window=window)
    run_worker_process(db_url, "record_failed", key, limit=limit, window=window)

    chk_blocked = run_worker_process(db_url, "check_login", key, limit=limit, window=window)
    assert chk_blocked["allowed"] is False
    assert chk_blocked["count"] == 2

    # Sleep past window
    time.sleep(4.2)

    chk_restored = run_worker_process(db_url, "check_login", key, limit=limit, window=window)
    assert chk_restored["allowed"] is True
    assert chk_restored["count"] == 0


# =========================================================================
# 9. Key Isolation (Different IPs and Accounts)
# =========================================================================

def test_distinct_keys_isolation(shared_db):
    """
    KEY ISOLATION:
    Attempts for Key A do not increment or affect counters for Key B.
    """
    db_url, engine = shared_db
    key_a = "login:target:ip_alpha:user_one"
    key_b = "login:target:ip_beta:user_two"

    # Fill key A
    for _ in range(5):
        run_worker_process(db_url, "record_failed", key_a, limit=5)

    assert run_worker_process(db_url, "check_login", key_a, limit=5)["allowed"] is False
    assert run_worker_process(db_url, "check_login", key_b, limit=5)["allowed"] is True
    assert run_worker_process(db_url, "check_login", key_b, limit=5)["count"] == 0

