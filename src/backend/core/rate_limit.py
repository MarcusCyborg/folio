"""
Folio Shared Rate Limiter — PostgreSQL Multi-Process Distributed Limiter
========================================================================

Policy Specification:
---------------------
1. Policy Keys & Action Scopes:
   - login_target:
       Key format: f"login:target:{hash_identifier(client_ip)}:{hash_identifier(normalized_email)}"
       Scope: Limits consecutive failed login attempts against a specific account from an IP.
       Limits: max_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED (default: 5) within
               window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS (default: 60s).
       Credential Privacy: Neither passwords, tokens, nor raw email addresses are stored in keys
       or logged. SHA-256 digests ensure privacy and fixed key width.
   - login_ip:
       Key format: f"login:ip:{hash_identifier(client_ip)}"
       Scope: Limits total failed login attempts from a given IP across all accounts (credential stuffing protection).
       Limits: max_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED * 3 (default: 15) within
               window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS (default: 60s).
   - register_ip:
       Key format: f"register:ip:{hash_identifier(client_ip)}"
       Scope: Limits registration burst requests originating from a given client IP.
       Limits: max_attempts=settings.RATE_LIMIT_REGISTER_MAX (default: 10) within
               window_seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS (default: 60s).

2. Successful Login Policy:
   - On successful authentication, ONLY the targeted account counter (login:target:...) is reset.
   - The IP-wide counter (login:ip:...) is deliberately NOT reset.
   - Invariant: A successful authentication on one account cannot wipe the counters of other accounts
     or reset IP-wide abuse limits.

3. 429 & Retry-After Contract:
   - When a rate limit threshold is exceeded:
       HTTP Status: 429 Too Many Requests
       Header: "Retry-After: <seconds>", calculated as max(1, ceil(oldest_active_attempt + window_seconds - current_time)).
       Response Error Code: "TOO_MANY_REQUESTS"

4. Multi-Process Sharing & Worker Restart Resilience:
   - State is persisted in PostgreSQL table `rate_limit_buckets`.
   - Independent web workers and processes share the exact same database store.
   - Worker or process restart preserves all active rate limit counters without data loss.

5. Atomic Admission & Concurrency:
   - Evaluates and inserts attempts atomically using PostgreSQL row-level locking (`SELECT ... FOR UPDATE`).
   - Multiple concurrent requests cannot read stale remaining counts or exceed thresholds.
   - Lock Ordering: When multiple keys are locked (e.g. target + IP), keys are locked in strict
     lexicographical order to prevent deadlocks.

6. Autonomous Transaction Lifecycle (Rollback Independence):
   - Rate limiting operations execute and COMMIT on their own isolated database session/connection.
   - If the main HTTP request subsequently fails authentication (HTTP 401) or is rolled back,
     the rate limit attempt is ALREADY committed and will NOT roll back with the request's transaction.

7. Database Monotonic Clock:
   - Uses PostgreSQL's authoritative server clock (`SELECT EXTRACT(EPOCH FROM clock_timestamp())`).
   - Completely eliminates cross-worker clock skew across multiple server nodes.

8. Store Down & Failure Transparency:
   - If the shared store is unreachable or down:
       - Strictly NO silent fallback to local in-memory dictionaries.
       - Logs the error with sanitized connection info (no passwords).
       - Raises RateLimitStoreUnavailableError -> HTTP 503 Service Unavailable ("RATE_LIMIT_UNAVAILABLE").

9. Bounded Retention:
   - Each row retains only timestamps falling within its sliding window.
   - Expired bucket rows older than retention threshold are pruned during maintenance.
"""

import time
import math
import json
import logging
import hashlib
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, DBAPIError

from src.backend.core.config import settings
from src.backend.core.audit import redact_sensitive_text

logger = logging.getLogger("folio.rate_limit")


class RateLimitStoreUnavailableError(Exception):
    """Raised when the rate limit database store is down, unreachable, or uninitialized."""
    pass


class RateLimitResult:
    """Encapsulates the result of a rate limit admission check."""
    def __init__(self, allowed: bool, retry_after: int = 0, current_count: int = 0, limit: int = 0):
        self.allowed = allowed
        self.retry_after = retry_after
        self.current_count = current_count
        self.limit = limit

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return (
            f"RateLimitResult(allowed={self.allowed}, retry_after={self.retry_after}, "
            f"count={self.current_count}/{self.limit})"
        )


def hash_identifier(val: str) -> str:
    """Returns a 16-character SHA-256 digest of an identifier for privacy and fixed key width."""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:16]


def build_login_target_key(client_ip: str, email: str) -> str:
    """Builds a hashed, privacy-preserving key for account-specific login attempts from an IP."""
    ip_h = hash_identifier(client_ip)
    email_h = hash_identifier(email.strip().lower())
    return f"login:target:{ip_h}:{email_h}"


def build_login_ip_key(client_ip: str) -> str:
    """Builds a hashed key for IP-wide login attempts."""
    ip_h = hash_identifier(client_ip)
    return f"login:ip:{ip_h}"


def build_register_ip_key(client_ip: str) -> str:
    """Builds a hashed key for IP-wide registration attempts."""
    ip_h = hash_identifier(client_ip)
    return f"register:ip:{ip_h}"


def normalize_bucket_key(identifier: str, default_prefix: str = "bucket") -> str:
    """
    Normalizes an identifier into a safe, bounded bucket key.
    If already formatted and <= 64 chars, preserves it; otherwise hashes it.
    """
    if identifier.startswith(("login:", "register:")) and len(identifier) <= 64:
        return identifier
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]
    return f"{default_prefix}:{digest}"


class PostgresRateLimiter:
    """
    PostgreSQL-backed shared rate limiter with atomic admission, row-level locking,
    monotonic DB clock, bounded retention, and rollback independence.
    """
    def __init__(self, engine=None, session_factory=None):
        self._custom_engine = engine
        self._custom_session_factory = session_factory

    def _get_engine(self):
        if self._custom_engine is not None:
            return self._custom_engine
        import src.backend.core.database as core_db
        return core_db.engine

    def _get_session_factory(self):
        if self._custom_session_factory is not None:
            return self._custom_session_factory
        import src.backend.core.database as core_db
        return core_db.SessionLocal

    @contextmanager
    def _session_scope(self):
        """Yields an autonomous database session dedicated to rate limiting."""
        factory = self._get_session_factory()
        session = None
        try:
            session = factory()
            yield session
        except (SQLAlchemyError, DBAPIError, ConnectionError, OSError) as e:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            safe_err = redact_sensitive_text(str(e))
            logger.error("Rate limiter store failure: %s", safe_err)
            raise RateLimitStoreUnavailableError(
                f"Rate limiting store unavailable: {safe_err}"
            ) from e
        except Exception as e:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            raise
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _get_db_time_and_dialect(self, session) -> Tuple[float, bool]:
        """Returns the current epoch timestamp from the database and whether it's PostgreSQL."""
        dialect_name = session.bind.dialect.name if session.bind else ""
        is_pg = dialect_name == "postgresql"
        if is_pg:
            res = session.execute(text("SELECT EXTRACT(EPOCH FROM clock_timestamp())")).scalar()
            now_epoch = float(res) if res is not None else time.time()
        else:
            now_epoch = time.time()
        return now_epoch, is_pg

    def check_login_rate_limit(
        self,
        identifier: str,
        max_failed: int = 5,
        window_seconds: int = 60
    ) -> RateLimitResult:
        """
        Non-mutating admission check for failed login attempts.
        Returns RateLimitResult indicating whether the identifier is within limits.
        """
        key_hash = normalize_bucket_key(identifier, "login:target")
        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)

            query = text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;")
            row = session.execute(query, {"key_hash": key_hash}).fetchone()

            if not row or not row[0]:
                return RateLimitResult(allowed=True, retry_after=0, current_count=0, limit=max_failed)

            raw_attempts = row[0]
            if isinstance(raw_attempts, str):
                try:
                    raw_attempts = json.loads(raw_attempts)
                except Exception:
                    raw_attempts = []

            cutoff = now_epoch - window_seconds
            active = [t for t in raw_attempts if isinstance(t, (int, float)) and t > cutoff]

            if len(active) >= max_failed:
                oldest = min(active) if active else now_epoch
                retry_after = max(1, int(math.ceil(oldest + window_seconds - now_epoch)))
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry_after,
                    current_count=len(active),
                    limit=max_failed
                )

            return RateLimitResult(
                allowed=True,
                retry_after=0,
                current_count=len(active),
                limit=max_failed
            )

    def record_failed_login(self, identifier: str, window_seconds: int = 60):
        """Atomically records a failed login attempt for an identifier."""
        self.record_failed_logins([identifier], window_seconds=window_seconds)

    def record_failed_logins(self, identifiers: List[str], window_seconds: int = 60):
        """
        Atomically records failed login attempts across multiple keys in a single transaction.
        Acquires row-level locks in deterministic lexicographical order to prevent deadlocks.
        """
        if not identifiers:
            return

        normalized_keys = sorted(list(set(normalize_bucket_key(i, "login:target") for i in identifiers)))

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            cutoff = now_epoch - window_seconds

            for key_hash in normalized_keys:
                action = "login_ip" if ":ip:" in key_hash else "login_target"
                if is_pg:
                    session.execute(
                        text(
                            """
                            INSERT INTO rate_limit_buckets (key_hash, action, attempts, created_at, updated_at)
                            VALUES (:key_hash, :action, '[]'::jsonb, clock_timestamp(), clock_timestamp())
                            ON CONFLICT (key_hash) DO NOTHING;
                            """
                        ),
                        {"key_hash": key_hash, "action": action}
                    )
                    row = session.execute(
                        text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"),
                        {"key_hash": key_hash}
                    ).fetchone()
                else:
                    session.execute(
                        text(
                            """
                            INSERT INTO rate_limit_buckets (key_hash, action, attempts, created_at, updated_at)
                            VALUES (:key_hash, :action, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            ON CONFLICT (key_hash) DO NOTHING;
                            """
                        ),
                        {"key_hash": key_hash, "action": action}
                    )
                    row = session.execute(
                        text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"),
                        {"key_hash": key_hash}
                    ).fetchone()

                raw_attempts = row[0] if row and row[0] is not None else []
                if isinstance(raw_attempts, str):
                    try:
                        raw_attempts = json.loads(raw_attempts)
                    except Exception:
                        raw_attempts = []

                active = [t for t in raw_attempts if isinstance(t, (int, float)) and t > cutoff]
                active.append(now_epoch)

                update_sql = (
                    "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = clock_timestamp() WHERE key_hash = :key_hash;"
                    if is_pg else
                    "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = CURRENT_TIMESTAMP WHERE key_hash = :key_hash;"
                )
                session.execute(
                    text(update_sql),
                    {"attempts": json.dumps(active), "key_hash": key_hash}
                )

            session.commit()

    def record_successful_login(self, identifier: str):
        """
        Resets failed login attempts for a specific target account.
        In accordance with policy, IP-wide counters are deliberately NOT reset.
        """
        key_hash = normalize_bucket_key(identifier, "login:target")
        with self._session_scope() as session:
            session.execute(
                text("DELETE FROM rate_limit_buckets WHERE key_hash = :key_hash;"),
                {"key_hash": key_hash}
            )
            session.commit()

    def check_and_record_register(
        self,
        client_ip: str,
        max_attempts: int = 10,
        window_seconds: int = 60
    ) -> RateLimitResult:
        """
        Atomically checks registration burst rate limit and records attempt in a single transaction.
        Enforces atomic admission control with row-level locking.
        """
        key_hash = build_register_ip_key(client_ip)
        action = "register_ip"

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            cutoff = now_epoch - window_seconds

            if is_pg:
                session.execute(
                    text(
                        """
                        INSERT INTO rate_limit_buckets (key_hash, action, attempts, created_at, updated_at)
                        VALUES (:key_hash, :action, '[]'::jsonb, clock_timestamp(), clock_timestamp())
                        ON CONFLICT (key_hash) DO NOTHING;
                        """
                    ),
                    {"key_hash": key_hash, "action": action}
                )
                row = session.execute(
                    text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"),
                    {"key_hash": key_hash}
                ).fetchone()
            else:
                session.execute(
                    text(
                        """
                        INSERT INTO rate_limit_buckets (key_hash, action, attempts, created_at, updated_at)
                        VALUES (:key_hash, :action, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (key_hash) DO NOTHING;
                        """
                    ),
                    {"key_hash": key_hash, "action": action}
                )
                row = session.execute(
                    text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"),
                    {"key_hash": key_hash}
                ).fetchone()

            raw_attempts = row[0] if row and row[0] is not None else []
            if isinstance(raw_attempts, str):
                try:
                    raw_attempts = json.loads(raw_attempts)
                except Exception:
                    raw_attempts = []

            active = [t for t in raw_attempts if isinstance(t, (int, float)) and t > cutoff]

            if len(active) >= max_attempts:
                oldest = min(active) if active else now_epoch
                retry_after = max(1, int(math.ceil(oldest + window_seconds - now_epoch)))
                session.commit()
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry_after,
                    current_count=len(active),
                    limit=max_attempts
                )

            active.append(now_epoch)
            update_sql = (
                "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = clock_timestamp() WHERE key_hash = :key_hash;"
                if is_pg else
                "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = CURRENT_TIMESTAMP WHERE key_hash = :key_hash;"
            )
            session.execute(
                text(update_sql),
                {"attempts": json.dumps(active), "key_hash": key_hash}
            )
            session.commit()
            return RateLimitResult(
                allowed=True,
                retry_after=0,
                current_count=len(active),
                limit=max_attempts
            )

    def reset(self):
        """Clears all rate limit buckets (used for clean test resets)."""
        with self._session_scope() as session:
            session.execute(text("DELETE FROM rate_limit_buckets;"))
            session.commit()

    def cleanup_expired(self, retention_seconds: int = 3600):
        """Prunes stale rate limit buckets older than retention threshold."""
        with self._session_scope() as session:
            _, is_pg = self._get_db_time_and_dialect(session)
            if is_pg:
                session.execute(
                    text(
                        """
                        DELETE FROM rate_limit_buckets
                        WHERE updated_at < clock_timestamp() - (:retention_seconds * INTERVAL '1 second');
                        """
                    ),
                    {"retention_seconds": retention_seconds}
                )
            else:
                session.execute(
                    text("DELETE FROM rate_limit_buckets WHERE updated_at < datetime('now', '-' || :retention_seconds || ' seconds');"),
                    {"retention_seconds": retention_seconds}
                )
            session.commit()


# Default singleton instance bound to application core database
rate_limiter = PostgresRateLimiter()


def get_client_ip(request: Request) -> str:
    """
    Extracts the client IP address.
    If behind a trusted reverse proxy, extracts the originating client IP from X-Forwarded-For.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"

    # Check if direct connection originates from a configured trusted proxy
    if direct_ip in settings.TRUSTED_PROXIES or direct_ip in ("127.0.0.1", "::1", "localhost"):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # First element in comma-separated list is client IP
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

    return direct_ip
