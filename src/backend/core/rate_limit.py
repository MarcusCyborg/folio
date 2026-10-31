import time
from collections import defaultdict
from typing import Dict, List
from threading import Lock
from fastapi import Request

from src.backend.core.config import settings

class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter.
    Safely limits failed authentication attempts and registration bursts.
    """
    def __init__(self):
        self._lock = Lock()
        self._failed_logins: Dict[str, List[float]] = defaultdict(list)
        self._registrations: Dict[str, List[float]] = defaultdict(list)

    def check_login_rate_limit(self, identifier: str, max_failed: int = 5, window_seconds: int = 60) -> bool:
        """
        Returns True if request is within limits, False if rate limit is exceeded.
        """
        now = time.time()
        with self._lock:
            attempts = [t for t in self._failed_logins[identifier] if now - t < window_seconds]
            self._failed_logins[identifier] = attempts
            return len(attempts) < max_failed

    def record_failed_login(self, identifier: str):
        now = time.time()
        with self._lock:
            self._failed_logins[identifier].append(now)

    def record_successful_login(self, identifier: str):
        with self._lock:
            self._failed_logins.pop(identifier, None)

    def check_and_record_register(self, client_ip: str, max_attempts: int = 10, window_seconds: int = 60) -> bool:
        now = time.time()
        with self._lock:
            attempts = [t for t in self._registrations[client_ip] if now - t < window_seconds]
            if len(attempts) >= max_attempts:
                self._registrations[client_ip] = attempts
                return False
            attempts.append(now)
            self._registrations[client_ip] = attempts
            return True

    def reset(self):
        """Clears all counters (useful for test resets)."""
        with self._lock:
            self._failed_logins.clear()
            self._registrations.clear()

rate_limiter = InMemoryRateLimiter()

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
