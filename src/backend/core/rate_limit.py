"""
Folio Shared Rate Limiter — PostgreSQL Multi-Process Distributed Limiter
========================================================================

Policy Specification:
---------------------
1. Policy Keys & Action Scopes:
   - login_target:
       Key format: f"login:target:{hash_identifier(client_ip)}:{hash_identifier(normalized_email)}"
       Scope: Limits consecutive failed + in-flight login attempts against a specific account from an IP.
       Limits: max_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED (default: 5) within
               window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS (default: 60s).
       Credential Privacy: Neither passwords, tokens, nor raw email addresses are stored in keys
       or logged. SHA-256 digests ensure privacy and fixed key width.
   - login_ip:
       Key format: f"login:ip:{hash_identifier(client_ip)}"
       Scope: Limits total failed + in-flight login attempts from a given IP across all accounts.
       Limits: max_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED * 3 (default: 15) within
               window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS (default: 60s).
   - register_ip:
       Key format: f"register:ip:{hash_identifier(client_ip)}"
       Scope: Limits registration burst requests originating from a given client IP.
       Limits: max_attempts=settings.RATE_LIMIT_REGISTER_MAX (default: 10) within
               window_seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS (default: 60s).

2. Atomic Login Admission & Slot Reservation (R03 / AUTH-01):
   - Before expensive Argon2id password verification runs, `reserve_login_attempt()` atomically
     evaluates active failures + unexpired in-flight reservations across both `login_target` and
     `login_ip` buckets using deterministic lexicographical row-level locking (`SELECT ... FOR UPDATE`).
   - If either bucket has reached its limit, the request is immediately rejected with HTTP 429
     before touching password verification.
   - If admitted, a short-lived reservation token (`exp = now + reservation_ttl_seconds`) is
     committed immediately so database row locks are NEVER held during Argon2id CPU hashing.
   - On failed password verification: `commit_login_reservation_failure()` converts the in-flight
     reservation into a full-window failure timestamp.
   - On successful authentication: `commit_login_reservation_success()` atomically locks both
     buckets, clears committed failure timestamps and its own reservation token from
     `login_target` (preserving unexpired concurrent in-flight reservations), and removes ONLY
     its own reservation token from `login_ip` (preserving prior IP-wide failure history and
     concurrent IP reservations).
   - On unexpected error or worker crash: `release_login_reservation()` releases the slot in
     `finally:`, and any unclosed reservation from a hard crash auto-expires at `exp`.
"""

import time
import math
import json
import uuid
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

DEFAULT_LOGIN_RESERVATION_TTL_SECONDS = 15.0


class RateLimitStoreUnavailableError(Exception):
    """Raised when the rate limit database store is down, unreachable, or uninitialized."""
    pass


class RateLimitResult:
    """Encapsulates the result of a rate limit admission check."""
    def __init__(
        self,
        allowed: bool,
        retry_after: int = 0,
        current_count: int = 0,
        limit: int = 0,
        reservation_token: Optional[str] = None,
    ):
        self.allowed = allowed
        self.retry_after = retry_after
        self.current_count = current_count
        self.limit = limit
        self.reservation_token = reservation_token

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return (
            f"RateLimitResult(allowed={self.allowed}, retry_after={self.retry_after}, "
            f"count={self.current_count}/{self.limit}, reserved={bool(self.reservation_token)})"
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


def build_search_ip_key(client_ip: str) -> str:
    """Builds a hashed key for IP-wide search requests."""
    ip_h = hash_identifier(client_ip)
    return f"search:ip:{ip_h}"


def normalize_bucket_key(identifier: str, default_prefix: str = "bucket") -> str:
    """
    Normalizes an identifier into a safe, bounded bucket key.
    If already formatted and <= 64 chars, preserves it; otherwise hashes it.
    """
    if identifier.startswith(("login:", "register:", "search:")) and len(identifier) <= 64:
        return identifier
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]
    return f"{default_prefix}:{digest}"


def _parse_raw_attempts(raw_attempts: Any) -> List[Any]:
    if not raw_attempts:
        return []
    if isinstance(raw_attempts, str):
        try:
            raw_attempts = json.loads(raw_attempts)
        except Exception:
            return []
    return list(raw_attempts) if isinstance(raw_attempts, list) else []


def _filter_active_entries(raw_attempts: Any, now_epoch: float, window_seconds: float) -> List[Any]:
    """
    Filters bucket entries to retain:
    1. Committed failure float timestamps within (now_epoch - window_seconds, +inf).
    2. Unexpired in-flight reservation dicts {'token': ..., 'ts': ..., 'exp': ...} with exp > now_epoch.
    """
    cutoff = now_epoch - window_seconds
    active: List[Any] = []
    for entry in _parse_raw_attempts(raw_attempts):
        if isinstance(entry, (int, float)):
            if float(entry) > cutoff:
                active.append(float(entry))
        elif isinstance(entry, dict):
            exp = entry.get("exp")
            ts = entry.get("ts", 0)
            if isinstance(exp, (int, float)) and float(exp) > now_epoch and float(ts) > cutoff:
                active.append(entry)
    return active


def _compute_retry_after(active_entries: List[Any], now_epoch: float, window_seconds: float) -> int:
    """Calculates seconds until at least one active failure or reservation expires."""
    expiries: List[float] = []
    for entry in active_entries:
        if isinstance(entry, (int, float)):
            expiries.append(float(entry) + float(window_seconds))
        elif isinstance(entry, dict) and isinstance(entry.get("exp"), (int, float)):
            expiries.append(float(entry["exp"]))
    if not expiries:
        return 1
    earliest_expiry = min(expiries)
    return max(1, int(math.ceil(earliest_expiry - now_epoch)))


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

    def _lock_and_read_bucket(self, session, key_hash: str, action: str, is_pg: bool) -> List[Any]:
        row = None
        for _ in range(3):
            if is_pg:
                session.execute(
                    text(
                        """
                        INSERT INTO rate_limit_buckets (key_hash, action, attempts, created_at, updated_at)
                        VALUES (:key_hash, :action, '[]'::jsonb, clock_timestamp(), clock_timestamp())
                        ON CONFLICT (key_hash) DO NOTHING;
                        """
                    ),
                    {"key_hash": key_hash, "action": action},
                )
                row = session.execute(
                    text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"),
                    {"key_hash": key_hash},
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
                    {"key_hash": key_hash, "action": action},
                )
                row = session.execute(
                    text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"),
                    {"key_hash": key_hash},
                ).fetchone()
            if row is not None:
                break

        return _parse_raw_attempts(row[0] if row else [])

    def _write_bucket(self, session, key_hash: str, entries: List[Any], is_pg: bool):
        update_sql = (
            "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = clock_timestamp() WHERE key_hash = :key_hash;"
            if is_pg
            else "UPDATE rate_limit_buckets SET attempts = :attempts, updated_at = CURRENT_TIMESTAMP WHERE key_hash = :key_hash;"
        )
        session.execute(
            text(update_sql),
            {"attempts": json.dumps(entries), "key_hash": key_hash},
        )

    def reserve_login_attempt(
        self,
        target_identifier: str,
        ip_identifier: str,
        max_target_failed: int = 5,
        max_ip_failed: int = 15,
        window_seconds: int = 60,
        reservation_ttl_seconds: float = DEFAULT_LOGIN_RESERVATION_TTL_SECONDS,
    ) -> RateLimitResult:
        """
        Atomically evaluates and reserves an in-flight login admission slot across both
        target account and client IP buckets BEFORE password verification.
        Releases all DB row locks immediately upon commit so Argon2id hashing runs lock-free.
        """
        target_key = normalize_bucket_key(target_identifier, "login:target")
        ip_key = normalize_bucket_key(ip_identifier, "login:ip")
        buckets_meta = [
            (target_key, "login_target", max_target_failed),
            (ip_key, "login_ip", max_ip_failed),
        ]
        # Deduplicate & sort keys deterministically to prevent deadlocks
        unique_sorted_keys = sorted({k for k, _, _ in buckets_meta})
        action_by_key = {k: act for k, act, _ in buckets_meta}

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            active_by_key: Dict[str, List[Any]] = {}

            for key_hash in unique_sorted_keys:
                raw = self._lock_and_read_bucket(session, key_hash, action_by_key[key_hash], is_pg)
                active_by_key[key_hash] = _filter_active_entries(raw, now_epoch, window_seconds)

            target_active = active_by_key[target_key]
            ip_active = active_by_key[ip_key]

            target_exceeded = len(target_active) >= max_target_failed
            ip_exceeded = len(ip_active) >= max_ip_failed

            if target_exceeded or ip_exceeded:
                retry_candidates = []
                if target_exceeded:
                    retry_candidates.append(_compute_retry_after(target_active, now_epoch, window_seconds))
                if ip_exceeded:
                    retry_candidates.append(_compute_retry_after(ip_active, now_epoch, window_seconds))
                session.commit()
                return RateLimitResult(
                    allowed=False,
                    retry_after=max(retry_candidates) if retry_candidates else 1,
                    current_count=len(target_active) if target_exceeded else len(ip_active),
                    limit=max_target_failed if target_exceeded else max_ip_failed,
                    reservation_token=None,
                )

            token = uuid.uuid4().hex
            effective_ttl = min(float(window_seconds), max(1.0, float(reservation_ttl_seconds)))
            reservation_entry = {
                "token": token,
                "ts": now_epoch,
                "exp": now_epoch + effective_ttl,
            }

            for key_hash in unique_sorted_keys:
                entries = list(active_by_key[key_hash])
                entries.append(reservation_entry)
                self._write_bucket(session, key_hash, entries, is_pg)

            session.commit()
            return RateLimitResult(
                allowed=True,
                retry_after=0,
                current_count=len(active_by_key[target_key]) + 1,
                limit=max_target_failed,
                reservation_token=token,
            )

    def commit_login_reservation_failure(
        self,
        identifiers: List[str],
        reservation_token: Optional[str],
        window_seconds: int = 60,
    ):
        """
        Converts an in-flight login reservation into a persistent failed attempt timestamp
        valid for the full rate-limit window.
        """
        if not identifiers:
            return
        normalized_keys = sorted(set(normalize_bucket_key(i, "login:target") for i in identifiers))

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            for key_hash in normalized_keys:
                action = "login_ip" if ":ip:" in key_hash else "login_target"
                raw = self._lock_and_read_bucket(session, key_hash, action, is_pg)
                active = _filter_active_entries(raw, now_epoch, window_seconds)

                updated: List[Any] = []
                replaced = False
                for entry in active:
                    if reservation_token and isinstance(entry, dict) and entry.get("token") == reservation_token:
                        updated.append(float(entry.get("ts", now_epoch)))
                        replaced = True
                    else:
                        updated.append(entry)

                if not replaced:
                    updated.append(now_epoch)

                self._write_bucket(session, key_hash, updated, is_pg)

            session.commit()

    def commit_login_reservation_success(
        self,
        target_identifier: str,
        ip_identifier: str,
        reservation_token: Optional[str],
        window_seconds: int = 60,
    ):
        """
        Finalizes a successful login under deterministic row locks:
        - `login:target:...`: clears committed failure timestamps and this request's own
          `reservation_token`, while preserving all other unexpired in-flight reservations.
        - `login:ip:...`: removes ONLY this request's `reservation_token`, while preserving
          prior IP failures and other unexpired in-flight reservations.
        """
        target_key = normalize_bucket_key(target_identifier, "login:target")
        ip_key = normalize_bucket_key(ip_identifier, "login:ip")
        keys_sorted = sorted({target_key, ip_key})

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            for key_hash in keys_sorted:
                row = session.execute(
                    text(
                        "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"
                        if is_pg
                        else "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"
                    ),
                    {"key_hash": key_hash},
                ).fetchone()
                if not row:
                    continue

                active = _filter_active_entries(row[0], now_epoch, window_seconds)
                if key_hash == target_key:
                    remaining = [
                        entry
                        for entry in active
                        if isinstance(entry, dict)
                        and not (reservation_token and entry.get("token") == reservation_token)
                    ]
                else:
                    remaining = [
                        entry
                        for entry in active
                        if not (
                            reservation_token
                            and isinstance(entry, dict)
                            and entry.get("token") == reservation_token
                        )
                    ]
                self._write_bucket(session, key_hash, remaining, is_pg)

            session.commit()

    def release_login_reservation(
        self,
        identifiers: List[str],
        reservation_token: Optional[str],
        window_seconds: int = 60,
    ):
        """Releases an in-flight login reservation without recording a failure (used on unexpected errors)."""
        if not identifiers or not reservation_token:
            return
        normalized_keys = sorted(set(normalize_bucket_key(i, "login:target") for i in identifiers))

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            for key_hash in normalized_keys:
                row = session.execute(
                    text(
                        "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"
                        if is_pg
                        else "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"
                    ),
                    {"key_hash": key_hash},
                ).fetchone()
                if row:
                    active = _filter_active_entries(row[0], now_epoch, window_seconds)
                    remaining = [
                        entry
                        for entry in active
                        if not (isinstance(entry, dict) and entry.get("token") == reservation_token)
                    ]
                    self._write_bucket(session, key_hash, remaining, is_pg)

            session.commit()

    def check_login_rate_limit(
        self,
        identifier: str,
        max_failed: int = 5,
        window_seconds: int = 60
    ) -> RateLimitResult:
        """
        Non-mutating admission check for failed + in-flight login attempts.
        Returns RateLimitResult indicating whether the identifier is within limits.
        """
        key_hash = normalize_bucket_key(identifier, "login:target")
        with self._session_scope() as session:
            now_epoch, _ = self._get_db_time_and_dialect(session)

            query = text("SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;")
            row = session.execute(query, {"key_hash": key_hash}).fetchone()

            if not row or not row[0]:
                return RateLimitResult(allowed=True, retry_after=0, current_count=0, limit=max_failed)

            active = _filter_active_entries(row[0], now_epoch, window_seconds)

            if len(active) >= max_failed:
                retry_after = _compute_retry_after(active, now_epoch, window_seconds)
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

            for key_hash in normalized_keys:
                action = "login_ip" if ":ip:" in key_hash else "login_target"
                raw_attempts = self._lock_and_read_bucket(session, key_hash, action, is_pg)
                active = _filter_active_entries(raw_attempts, now_epoch, window_seconds)
                active.append(now_epoch)
                self._write_bucket(session, key_hash, active, is_pg)

            session.commit()

    def record_successful_login(self, identifier: str, window_seconds: Optional[int] = None):
        """
        Resets failed login attempts for a specific target account while preserving
        any unexpired in-flight reservations.
        In accordance with policy, IP-wide counters are deliberately NOT reset.
        """
        effective_window = float(
            window_seconds
            if window_seconds is not None
            else getattr(settings, "RATE_LIMIT_LOGIN_WINDOW_SECONDS", 60)
        )
        key_hash = normalize_bucket_key(identifier, "login:target")
        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            row = session.execute(
                text(
                    "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash FOR UPDATE;"
                    if is_pg
                    else "SELECT attempts FROM rate_limit_buckets WHERE key_hash = :key_hash;"
                ),
                {"key_hash": key_hash},
            ).fetchone()
            if row:
                active = _filter_active_entries(row[0], now_epoch, effective_window)
                remaining = [entry for entry in active if isinstance(entry, dict)]
                self._write_bucket(session, key_hash, remaining, is_pg)
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
            raw_attempts = self._lock_and_read_bucket(session, key_hash, action, is_pg)
            active = _filter_active_entries(raw_attempts, now_epoch, window_seconds)

            if len(active) >= max_attempts:
                retry_after = _compute_retry_after(active, now_epoch, window_seconds)
                session.commit()
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry_after,
                    current_count=len(active),
                    limit=max_attempts
                )

            active.append(now_epoch)
            self._write_bucket(session, key_hash, active, is_pg)
            session.commit()
            return RateLimitResult(
                allowed=True,
                retry_after=0,
                current_count=len(active),
                limit=max_attempts
            )

    def check_and_record_search_attempt(
        self,
        client_ip: str,
        max_attempts: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> RateLimitResult:
        """
        Atomically checks and records a search request attempt for client_ip.
        """
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return RateLimitResult(allowed=True, retry_after=0, current_count=0, limit=999)

        max_attempts = max_attempts or getattr(settings, "RATE_LIMIT_SEARCH_MAX", 60)
        window_seconds = window_seconds or getattr(settings, "RATE_LIMIT_SEARCH_WINDOW_SECONDS", 60)
        key_hash = build_search_ip_key(client_ip)
        action = "search_ip"

        with self._session_scope() as session:
            now_epoch, is_pg = self._get_db_time_and_dialect(session)
            raw_attempts = self._lock_and_read_bucket(session, key_hash, action, is_pg)
            active = _filter_active_entries(raw_attempts, now_epoch, window_seconds)

            if len(active) >= max_attempts:
                retry_after = _compute_retry_after(active, now_epoch, window_seconds)
                session.commit()
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry_after,
                    current_count=len(active),
                    limit=max_attempts
                )

            active.append(now_epoch)
            self._write_bucket(session, key_hash, active, is_pg)
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
