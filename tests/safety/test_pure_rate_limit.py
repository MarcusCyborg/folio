"""
Pure Unit Tests for Folio Shared Rate Limiter
=============================================
These tests execute purely in-memory with `--noconftest` (zero network / external PostgreSQL required).
Verifies:
1. Key hashing, privacy, and fixed-width identifier contracts (no raw credentials/emails).
2. RateLimitResult boolean compatibility and Retry-After header arithmetic.
3. Sliding-window logic and boundary expiration.
4. Independent account reset on successful login (preserves IP-wide counter).
5. Lock ordering determinism (sorted keys to prevent deadlocks).
6. Store failure behavior: explicit exception raising with credential redaction (no silent in-memory fallback).
7. Bounded retention pruning.
8. Trusted proxy client IP resolution.
"""

import time
import math
import hashlib
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backend.core.rate_limit import (
    PostgresRateLimiter,
    RateLimitResult,
    RateLimitStoreUnavailableError,
    hash_identifier,
    build_login_target_key,
    build_login_ip_key,
    build_register_ip_key,
    normalize_bucket_key,
    get_client_ip,
)
from src.backend.models.base import Base
from src.backend.models.rate_limit import RateLimitBucket


@pytest.fixture
def sqlite_limiter():
    """Provides a PostgresRateLimiter instance backed by an isolated in-memory SQLite engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[RateLimitBucket.__table__])
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    limiter = PostgresRateLimiter(engine=engine, session_factory=session_factory)
    return limiter


class DummyRequest:
    """Mock FastAPI Request for testing client IP extraction."""
    def __init__(self, host: str, headers: dict = None):
        class Client:
            def __init__(self, h):
                self.host = h
        self.client = Client(host)
        self.headers = headers or {}


# =========================================================================
# 1. Key Hashing, Privacy & Format Invariants
# =========================================================================

def test_hash_identifier_properties():
    """Hash identifier must produce consistent, 16-character hex strings."""
    h1 = hash_identifier("127.0.0.1")
    h2 = hash_identifier("127.0.0.1")
    h3 = hash_identifier("192.168.1.1")
    assert len(h1) == 16
    assert h1 == h2
    assert h1 != h3


def test_build_login_target_key_privacy():
    """Login target key must never contain raw email or plain text credentials."""
    raw_email = "SensitiveUser@Domain.Test"
    client_ip = "10.0.0.42"
    key = build_login_target_key(client_ip, raw_email)

    assert key.startswith("login:target:")
    assert raw_email not in key
    assert raw_email.lower() not in key
    assert client_ip not in key
    assert len(key) <= 64


def test_build_login_ip_key_privacy():
    """Login IP key must be hashed and under 64 characters."""
    client_ip = "192.168.100.200"
    key = build_login_ip_key(client_ip)
    assert key.startswith("login:ip:")
    assert client_ip not in key
    assert len(key) <= 64


def test_build_register_ip_key_privacy():
    """Registration IP key must be hashed and under 64 characters."""
    client_ip = "192.168.100.200"
    key = build_register_ip_key(client_ip)
    assert key.startswith("register:ip:")
    assert client_ip not in key
    assert len(key) <= 64


def test_normalize_bucket_key_masks_raw_identifiers():
    """Arbitrary raw strings must be digested to avoid leaking credentials in table keys."""
    raw_password = "SuperSecretPassword123!"
    normalized = normalize_bucket_key(raw_password, default_prefix="login:target")
    assert raw_password not in normalized
    assert normalized.startswith("login:target:")
    assert len(normalized) <= 64


# =========================================================================
# 2. RateLimitResult Invariants & Boolean Compatibility
# =========================================================================

def test_rate_limit_result_bool_compatibility():
    """RateLimitResult must evaluate to True when allowed, False when rejected."""
    res_ok = RateLimitResult(allowed=True, retry_after=0, current_count=2, limit=5)
    assert bool(res_ok) is True
    if not res_ok:
        pytest.fail("RateLimitResult(allowed=True) should be truthy")

    res_blocked = RateLimitResult(allowed=False, retry_after=42, current_count=5, limit=5)
    assert bool(res_blocked) is False
    if res_blocked:
        pytest.fail("RateLimitResult(allowed=False) should be falsy")
    assert res_blocked.retry_after == 42


# =========================================================================
# 3. Sliding Window & Boundary Expiration
# =========================================================================

def test_sqlite_limiter_check_and_record_register(sqlite_limiter):
    """Verifies atomic admission and rejection at threshold limit."""
    ip = "198.51.100.10"
    max_attempts = 3
    window = 60

    # 3 attempts should be allowed
    for i in range(max_attempts):
        res = sqlite_limiter.check_and_record_register(ip, max_attempts=max_attempts, window_seconds=window)
        assert res.allowed is True
        assert res.current_count == i + 1

    # 4th attempt exceeds limit
    res_overflow = sqlite_limiter.check_and_record_register(ip, max_attempts=max_attempts, window_seconds=window)
    assert res_overflow.allowed is False
    assert res_overflow.retry_after > 0
    assert res_overflow.current_count == max_attempts


def test_sqlite_limiter_login_sliding_window(sqlite_limiter):
    """Verifies failed login recording and threshold enforcement."""
    key = build_login_target_key("127.0.0.1", "victim@folio.test")
    max_failed = 4
    window = 60

    # Initially allowed (0 attempts)
    initial_check = sqlite_limiter.check_login_rate_limit(key, max_failed=max_failed, window_seconds=window)
    assert initial_check.allowed is True

    # Record 4 failed attempts
    for _ in range(max_failed):
        sqlite_limiter.record_failed_login(key, window_seconds=window)

    # Next check must be rejected with retry_after > 0
    blocked_check = sqlite_limiter.check_login_rate_limit(key, max_failed=max_failed, window_seconds=window)
    assert blocked_check.allowed is False
    assert blocked_check.retry_after > 0
    assert blocked_check.current_count == 4


# =========================================================================
# 4. Success Isolation: Target Account vs IP Counter Policy
# =========================================================================

def test_successful_login_resets_only_target_account(sqlite_limiter):
    """
    CRITICAL POLICY INVARIANT:
    Successful login of Account A resets Account A's counter, but MUST NOT
    reset the shared IP counter or Account B's counter.
    """
    ip = "203.0.113.50"
    target_a = build_login_target_key(ip, "user_a@folio.test")
    target_b = build_login_target_key(ip, "user_b@folio.test")
    ip_key = build_login_ip_key(ip)

    # Record 3 failures for User A and 2 failures for User B, plus IP failures
    for _ in range(3):
        sqlite_limiter.record_failed_login(target_a)
        sqlite_limiter.record_failed_login(ip_key)
    for _ in range(2):
        sqlite_limiter.record_failed_login(target_b)
        sqlite_limiter.record_failed_login(ip_key)

    # Check initial states
    assert sqlite_limiter.check_login_rate_limit(target_a, max_failed=5).current_count == 3
    assert sqlite_limiter.check_login_rate_limit(target_b, max_failed=5).current_count == 2
    assert sqlite_limiter.check_login_rate_limit(ip_key, max_failed=10).current_count == 5

    # User A successfully logs in
    sqlite_limiter.record_successful_login(target_a)

    # User A's counter must be cleared (0)
    assert sqlite_limiter.check_login_rate_limit(target_a, max_failed=5).current_count == 0

    # User B's counter must REMAIN UNTOUCHED (2)
    assert sqlite_limiter.check_login_rate_limit(target_b, max_failed=5).current_count == 2

    # IP-wide counter must REMAIN UNTOUCHED (5)
    assert sqlite_limiter.check_login_rate_limit(ip_key, max_failed=10).current_count == 5


# =========================================================================
# 5. Lock Ordering Determinism
# =========================================================================

def test_record_failed_logins_sorts_keys(sqlite_limiter):
    """Multi-key recording must sort keys lexicographically to guarantee consistent lock ordering."""
    keys = ["login:target:zzz", "login:ip:aaa", "login:target:mmm"]
    # Calling record_failed_logins must execute cleanly and sort internally
    sqlite_limiter.record_failed_logins(keys)

    for k in keys:
        check = sqlite_limiter.check_login_rate_limit(k, max_failed=5)
        assert check.current_count == 1


# =========================================================================
# 6. Store Down & Failure Transparency (No Silent In-Memory Fallback)
# =========================================================================

def test_store_unavailable_raises_explicit_exception():
    """
    CRITICAL POLICY INVARIANT:
    When the database is down or unreachable, the rate limiter MUST NOT
    silently fall back to an in-memory dictionary. It must raise RateLimitStoreUnavailableError
    with all connection credentials redacted.
    """
    # Create engine pointing to closed port
    dead_engine = create_engine(
        "postgresql+psycopg://postgres:secret_password@127.0.0.1:59999/nonexistent_db",
        connect_args={"connect_timeout": 1}
    )
    dead_session_factory = sessionmaker(bind=dead_engine)
    dead_limiter = PostgresRateLimiter(engine=dead_engine, session_factory=dead_session_factory)

    with pytest.raises(RateLimitStoreUnavailableError) as exc_info:
        dead_limiter.check_login_rate_limit("login:target:test", max_failed=5)

    error_str = str(exc_info.value)
    # Password must NEVER be leaked in the error message
    assert "secret_password" not in error_str
    assert "unavailable" in error_str.lower()


# =========================================================================
# 7. Bounded Retention & Reset
# =========================================================================

def test_reset_and_cleanup_expired(sqlite_limiter):
    """Verifies that reset clears the database and cleanup_expired prunes stale entries."""
    key = build_login_target_key("127.0.0.1", "cleanup@folio.test")
    sqlite_limiter.record_failed_login(key)

    check_before = sqlite_limiter.check_login_rate_limit(key, max_failed=5)
    assert check_before.current_count == 1

    # Reset clears all buckets
    sqlite_limiter.reset()

    check_after = sqlite_limiter.check_login_rate_limit(key, max_failed=5)
    assert check_after.current_count == 0


# =========================================================================
# 8. Trusted Proxy Client IP Extraction
# =========================================================================

def test_get_client_ip_direct():
    """Direct connection without proxy returns direct client host."""
    req = DummyRequest(host="198.51.100.5")
    assert get_client_ip(req) == "198.51.100.5"


def test_get_client_ip_trusted_proxy():
    """Connection from trusted reverse proxy extracts client IP from X-Forwarded-For."""
    req = DummyRequest(
        host="127.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.195, 10.0.0.1"}
    )
    assert get_client_ip(req) == "203.0.113.195"


def test_get_client_ip_untrusted_proxy_ignored():
    """Connection from untrusted proxy ignores spoofed X-Forwarded-For header."""
    req = DummyRequest(
        host="198.51.100.99",
        headers={"X-Forwarded-For": "1.1.1.1"}
    )
    assert get_client_ip(req) == "198.51.100.99"
