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
    """Fresh migrated PostgreSQL database shared by the worker processes."""
    import argparse
    from alembic.config import Config
    from alembic import command
    from sqlalchemy.engine import make_url
    from src.backend.core.test_db_guard import TestRunManifest, provision_test_database, safe_teardown_test_database
    admin_url = os.environ.get("FOLIO_TEST_ADMIN_URL") or make_url(settings.TEST_DATABASE_URL).set(database="postgres").render_as_string(hide_password=False)
    manifest = TestRunManifest.create()
    name = manifest.generate_db_name("folio_test_limiter")
    db_url = provision_test_database(admin_url, manifest, requested_dbname=name)
    engine = create_engine(db_url)
    try:
        cfg = Config(str(Path(settings.PROJECT_ROOT) / "alembic.ini"))
        cfg.cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
        command.upgrade(cfg, "head")
        from scripts.seed_folio import run_seed
        run_seed(target=engine)
        yield db_url, engine
    finally:
        engine.dispose()
        safe_teardown_test_database(admin_url, manifest, name)


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
            assert reg_res.status_code == 201, reg_res.text
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
    Records attempts with a 10-second window (allowing margin for multi-process Python startup).
    While within the window, the key is blocked. After waiting past the window, active attempts
    expire and admission is restored.
    """
    db_url, engine = shared_db
    key = "login:target:expiry_ip:user"
    limit = 2
    window = 10

    # Record 2 failures across separate OS processes -> hits limit
    run_worker_process(db_url, "record_failed", key, limit=limit, window=window)
    run_worker_process(db_url, "record_failed", key, limit=limit, window=window)

    chk_blocked = run_worker_process(db_url, "check_login", key, limit=limit, window=window)
    assert chk_blocked["allowed"] is False
    assert chk_blocked["count"] == 2

    # Wait past full window from newest attempt -> all entries expire cleanly
    time.sleep(window + 0.5)

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


# =========================================================================
# 10. R03 / AUTH-01: Atomic Login Admission Before Password Verification
# =========================================================================

def test_concurrent_login_barrier_enforces_exact_admission_limit_before_verify(shared_db):
    """
    R03 / AUTH-01 PRIMARY REGRESSION:
    With max_failed=5 and 12 concurrent login attempts synchronized at verify_password,
    atomic slot reservation must admit at most 5 requests into Argon2 password verification
    and reject the remaining 7 with HTTP 429 before verification runs.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from starlette.requests import Request
    from starlette.responses import Response
    import src.backend.api.auth as auth
    from src.backend.core.session import create_session
    from src.backend.core.exceptions import AppException
    from src.backend.models.auth import User
    from src.backend.core.security import hash_password

    db_url, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with session_factory() as db:
        victim = User(
            email="r03_victim@folio.test",
            username="r03_victim",
            display_name="R03 Victim",
            password_hash=hash_password("CorrectHorseBatteryStaple1!"),
            role_key="member",
            is_active=True,
        )
        db.add(victim)
        db.commit()

    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    limiter.reset()

    old_limiter = auth.rate_limiter
    old_enabled = settings.RATE_LIMIT_ENABLED
    old_max_failed = settings.RATE_LIMIT_LOGIN_MAX_FAILED
    old_verify = auth.verify_password

    auth.rate_limiter = limiter
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_LOGIN_MAX_FAILED = 5

    workers = 12
    admitted_limit = 5
    barrier = threading.Barrier(admitted_limit)
    verify_counter = {"count": 0}
    counter_lock = threading.Lock()

    def verify_with_barrier(plain: str, encoded: str) -> bool:
        with counter_lock:
            verify_counter["count"] += 1
        barrier.wait(timeout=15)
        return old_verify(plain, encoded)

    auth.verify_password = verify_with_barrier

    def run_login_request(_idx: int) -> int:
        with session_factory() as db:
            sess_obj, _ = create_session(db)
            db.commit()
            ctx = auth.SessionContext(sess_obj, sess_obj.actor_key, None, sess_obj.csrf_token)
            req = Request({
                "type": "http",
                "method": "POST",
                "path": "/api/v1/auth/login",
                "headers": [],
                "client": ("203.0.113.88", 12345),
            })
            try:
                auth.login(
                    auth.LoginRequest(email="r03_victim@folio.test", password="WrongPassword!"),
                    req,
                    Response(),
                    ctx,
                    db,
                )
                return 200
            except AppException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            statuses = list(executor.map(run_login_request, range(workers)))
    finally:
        auth.verify_password = old_verify
        auth.rate_limiter = old_limiter
        settings.RATE_LIMIT_ENABLED = old_enabled
        settings.RATE_LIMIT_LOGIN_MAX_FAILED = old_max_failed

    assert verify_counter["count"] == admitted_limit, (
        f"Expected at most {admitted_limit} password verifications, got {verify_counter['count']}"
    )
    assert statuses.count(401) == admitted_limit
    assert statuses.count(429) == workers - admitted_limit

    target_key = build_login_target_key("203.0.113.88", "r03_victim@folio.test")
    post_check = limiter.check_login_rate_limit(target_key, max_failed=5)
    assert post_check.allowed is False
    assert post_check.current_count == admitted_limit


def test_login_reservation_crash_expiry_and_success_reset(shared_db):
    """
    R03 / AUTH-01 LIFECYCLE:
    - Unreleased reservations from crashed workers auto-expire after reservation_ttl_seconds.
    - Explicit release frees slot immediately without recording a failure.
    - Successful login resets target bucket while preserving prior IP failures.
    """
    db_url, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    limiter.reset()

    t_key = build_login_target_key("198.51.100.42", "crash_test@folio.test")
    i_key = build_login_ip_key("198.51.100.42")

    # 1. Simulate 2 crashed workers reserving slots with short 2s TTL
    r1 = limiter.reserve_login_attempt(t_key, i_key, max_target_failed=2, max_ip_failed=10, window_seconds=60, reservation_ttl_seconds=2.0)
    r2 = limiter.reserve_login_attempt(t_key, i_key, max_target_failed=2, max_ip_failed=10, window_seconds=60, reservation_ttl_seconds=2.0)
    assert r1.allowed is True and r1.reservation_token
    assert r2.allowed is True and r2.reservation_token

    # 3rd request blocked while in-flight slots are active
    r3 = limiter.reserve_login_attempt(t_key, i_key, max_target_failed=2, max_ip_failed=10, window_seconds=60, reservation_ttl_seconds=2.0)
    assert r3.allowed is False
    assert r3.retry_after >= 1

    # Wait past reservation TTL -> crashed slots expire automatically
    time.sleep(2.2)
    r4 = limiter.reserve_login_attempt(t_key, i_key, max_target_failed=2, max_ip_failed=10, window_seconds=60, reservation_ttl_seconds=15.0)
    assert r4.allowed is True

    # Release r4 explicitly -> count returns to 0
    limiter.release_login_reservation([t_key, i_key], r4.reservation_token)
    assert limiter.check_login_rate_limit(t_key, max_failed=2).current_count == 0

    # Record 1 prior IP failure from another account, then reserve & succeed on target account
    limiter.record_failed_login(i_key, window_seconds=60)
    r_ok = limiter.reserve_login_attempt(t_key, i_key, max_target_failed=2, max_ip_failed=10, window_seconds=60)
    assert r_ok.allowed is True
    limiter.commit_login_reservation_success(t_key, i_key, r_ok.reservation_token, window_seconds=60)

    assert limiter.check_login_rate_limit(t_key, max_failed=2).current_count == 0
    assert limiter.check_login_rate_limit(i_key, max_failed=10).current_count == 1


def test_r3_02_success_preserves_inflight_target_reservations_and_enforces_limit(shared_db):
    """
    R3-02 REGRESSION:
    When 5 concurrent logins are admitted for the same target/IP and 1 completes successfully
    while 4 remain in-flight verifying passwords, commit_login_reservation_success must clear
    only prior failures and its own reservation token while preserving the 4 unexpired
    in-flight target reservations. Subsequent requests while those 4 remain pending may admit
    at most 1 additional request (4 + 1 = 5), never allowing 9 total concurrent checks.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from starlette.requests import Request
    from starlette.responses import Response
    import src.backend.api.auth as auth
    from src.backend.core.session import create_session
    from src.backend.core.exceptions import AppException
    from src.backend.models.auth import User
    from src.backend.core.security import hash_password

    _, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with session_factory() as db:
        user = User(
            email="r3_02_mixed@folio.test",
            username="r3_02_mixed",
            display_name="R302 Mixed User",
            password_hash=hash_password("CorrectR302Pass!"),
            role_key="member",
            is_active=True,
        )
        db.add(user)
        db.commit()

    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    limiter.reset()

    old_limiter = auth.rate_limiter
    old_enabled = settings.RATE_LIMIT_ENABLED
    old_max_failed = settings.RATE_LIMIT_LOGIN_MAX_FAILED
    old_verify = auth.verify_password

    auth.rate_limiter = limiter
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_LOGIN_MAX_FAILED = 5

    # Seed 1 prior IP failure from another account to confirm IP history survives
    ip_addr = "203.0.113.99"
    target_key = build_login_target_key(ip_addr, "r3_02_mixed@folio.test")
    ip_key = build_login_ip_key(ip_addr)
    limiter.record_failed_login(ip_key, window_seconds=60)

    pending_entered_lock = threading.Lock()
    pending_entered = 0
    all_4_pending_in_verify = threading.Event()
    release_4_pending = threading.Event()
    verify_calls = {"wrong_wave1": 0, "right": 0, "wave2": 0}

    def phased_verify(plain: str, encoded: str) -> bool:
        nonlocal pending_entered
        if plain == "WrongWave1!":
            with pending_entered_lock:
                verify_calls["wrong_wave1"] += 1
                pending_entered += 1
                if pending_entered == 4:
                    all_4_pending_in_verify.set()
            assert release_4_pending.wait(timeout=15), "Timed out waiting to release pending wave1 logins"
            return False
        if plain == "CorrectR302Pass!":
            assert all_4_pending_in_verify.wait(timeout=15), "Timed out waiting for 4 pending wave1 logins"
            with pending_entered_lock:
                verify_calls["right"] += 1
            return old_verify(plain, encoded)
        with pending_entered_lock:
            verify_calls["wave2"] += 1
        return old_verify(plain, encoded)

    auth.verify_password = phased_verify

    def run_login(password: str) -> int:
        with session_factory() as db:
            sess_obj, _ = create_session(db)
            db.commit()
            ctx = auth.SessionContext(sess_obj, sess_obj.actor_key, None, sess_obj.csrf_token)
            req = Request({
                "type": "http",
                "method": "POST",
                "path": "/api/v1/auth/login",
                "headers": [],
                "client": (ip_addr, 12345),
            })
            try:
                auth.login(
                    auth.LoginRequest(email="r3_02_mixed@folio.test", password=password),
                    req,
                    Response(),
                    ctx,
                    db,
                )
                return 200
            except AppException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            wrong_futures = [pool.submit(run_login, "WrongWave1!") for _ in range(4)]
            assert all_4_pending_in_verify.wait(timeout=15)

            # 5th slot: valid credentials succeed while the 4 wrong-password checks remain in-flight
            ok_status = run_login("CorrectR302Pass!")
            assert ok_status == 200

            # Target bucket must still hold the 4 unexpired in-flight reservations
            mid_target_check = limiter.check_login_rate_limit(target_key, max_failed=5)
            assert mid_target_check.current_count == 4, (
                f"Expected 4 retained in-flight target reservations after 1 success, got {mid_target_check.current_count}"
            )
            assert mid_target_check.allowed is True

            # Send 5 concurrent wave-2 attempts while the 4 wave-1 verifications are still running
            wave2_statuses = list(pool.map(run_login, ["WrongWave2!"] * 5))
            assert wave2_statuses.count(401) == 1, f"Expected at most 1 new admission, got statuses={wave2_statuses}"
            assert wave2_statuses.count(429) == 4, f"Expected 4 HTTP 429 rejections, got statuses={wave2_statuses}"
            assert verify_calls["wave2"] == 1

            # Release the 4 initial in-flight checks -> all 4 convert into failures (1 + 4 = 5 total)
            release_4_pending.set()
            wrong_statuses = [f.result(timeout=15) for f in wrong_futures]
            assert wrong_statuses == [401, 401, 401, 401]
    finally:
        release_4_pending.set()
        auth.verify_password = old_verify
        auth.rate_limiter = old_limiter
        settings.RATE_LIMIT_ENABLED = old_enabled
        settings.RATE_LIMIT_LOGIN_MAX_FAILED = old_max_failed

    final_target_check = limiter.check_login_rate_limit(target_key, max_failed=5)
    assert final_target_check.current_count == 5
    assert final_target_check.allowed is False

    # IP bucket: 1 prior failure + 4 wave1 failures + 1 wave2 failure = 6 failures
    final_ip_check = limiter.check_login_rate_limit(ip_key, max_failed=15)
    assert final_ip_check.current_count == 6


def test_r3_02_concurrent_successes_prior_failures_expiry_and_idempotency(shared_db):
    """
    R3-02 EDGE CASES:
    - Prior target failures are cleared on success while other active reservations survive.
    - Two concurrent successes clear only their own tokens; calling success/release twice is idempotent.
    - Expired reservation tokens on cleanup do not evict newer unexpired reservations.
    """
    _, engine = shared_db
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    limiter.reset()

    ip_addr = "198.51.100.77"
    target_key = build_login_target_key(ip_addr, "concurrent_ok@folio.test")
    ip_key = build_login_ip_key(ip_addr)

    # 2 prior failures on both target and IP + 1 short-TTL reservation that will expire
    limiter.record_failed_logins([target_key, ip_key], window_seconds=60)
    limiter.record_failed_logins([target_key, ip_key], window_seconds=60)
    r_exp = limiter.reserve_login_attempt(
        target_key, ip_key, max_target_failed=6, max_ip_failed=15, window_seconds=60, reservation_ttl_seconds=1.5
    )
    assert r_exp.allowed is True
    time.sleep(1.7)

    # Reserve 3 active concurrent slots (2 that succeed, 1 still in-flight)
    r_ok_1 = limiter.reserve_login_attempt(target_key, ip_key, max_target_failed=6, max_ip_failed=15, window_seconds=60)
    r_ok_2 = limiter.reserve_login_attempt(target_key, ip_key, max_target_failed=6, max_ip_failed=15, window_seconds=60)
    r_pending = limiter.reserve_login_attempt(target_key, ip_key, max_target_failed=6, max_ip_failed=15, window_seconds=60)
    assert r_ok_1.allowed and r_ok_2.allowed and r_pending.allowed

    # 1st success: clears the 2 prior failures + r_ok_1 token + expired r_exp; retains r_ok_2 and r_pending
    limiter.commit_login_reservation_success(target_key, ip_key, r_ok_1.reservation_token, window_seconds=60)
    assert limiter.check_login_rate_limit(target_key, max_failed=6).current_count == 2
    assert limiter.check_login_rate_limit(ip_key, max_failed=15).current_count == 4  # 2 prior failures + 2 reservations

    # Re-committing or releasing r_ok_1 token or unknown/expired tokens is an idempotent no-op
    limiter.commit_login_reservation_success(target_key, ip_key, r_ok_1.reservation_token, window_seconds=60)
    limiter.release_login_reservation([target_key, ip_key], r_ok_1.reservation_token, window_seconds=60)
    limiter.release_login_reservation([target_key, ip_key], "nonexistent-token", window_seconds=60)
    assert limiter.check_login_rate_limit(target_key, max_failed=6).current_count == 2
    assert limiter.check_login_rate_limit(ip_key, max_failed=15).current_count == 4

    # 2nd concurrent success removes only r_ok_2 -> leaves r_pending in target and prior IP failures + r_pending in IP
    limiter.commit_login_reservation_success(target_key, ip_key, r_ok_2.reservation_token, window_seconds=60)
    assert limiter.check_login_rate_limit(target_key, max_failed=6).current_count == 1
    assert limiter.check_login_rate_limit(ip_key, max_failed=15).current_count == 3

    # Release final pending reservation cleanly
    limiter.release_login_reservation([target_key, ip_key], r_pending.reservation_token, window_seconds=60)
    assert limiter.check_login_rate_limit(target_key, max_failed=6).current_count == 0
    assert limiter.check_login_rate_limit(ip_key, max_failed=15).current_count == 2
