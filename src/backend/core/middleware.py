import re
import time
import uuid
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.backend.core.config import settings
from src.backend.core.exceptions import format_error_response

logger = logging.getLogger("folio.access")
SENSITIVE_KEY_PATTERN = re.compile(r"(password|secret|token|key|cookie|auth)", re.IGNORECASE)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured HTTP request logging with X-Request-ID propagation,
    precise latency tracking, client IP resolution via trusted reverse proxies,
    and strict redaction of sensitive credentials and tokens.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Propagate or generate request ID
        req_id = request.headers.get("x-request-id")
        if not req_id or not re.match(r"^[a-zA-Z0-9\-_]{1,64}$", req_id.strip()):
            req_id = uuid.uuid4().hex
        else:
            req_id = req_id.strip()

        request.state.request_id = req_id

        # 2. Extract Client IP using trusted proxies
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for and (client_ip in settings.TRUSTED_PROXIES or "*" in settings.TRUSTED_PROXIES):
            client_ip = forwarded_for.split(",")[0].strip()

        # 3. Time execution
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "request_failed",
                extra={
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": client_ip,
                    "latency_ms": latency_ms,
                },
            )
            raise

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = req_id

        # 4. Redact sensitive query parameters
        query_str = request.url.query
        if query_str and SENSITIVE_KEY_PATTERN.search(query_str):
            query_str = "[REDACTED]"

        logger.info(
            "request_completed",
            extra={
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "query": query_str,
                "status_code": status_code,
                "client_ip": client_ip,
                "latency_ms": latency_ms,
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Appends security headers to all HTTP responses.
    Configured to ensure full compatibility with Folio frontend ES modules,
    Paper/Ink styles, local SVGs, self-hosted WOFF2 fonts, and external cover images.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Baseline Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        # Content Security Policy (CSP) compatible with real assets
        if request.url.path in ("/docs", "/docs/oauth2-redirect", "/redoc"):
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://cdn.jsdelivr.net; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        else:
            csp = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        response.headers["Content-Security-Policy"] = csp

        # HTTP Strict Transport Security (HSTS) when running in HTTPS / Secure Cookie mode
        if settings.COOKIE_SECURE or settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class OriginVerificationMiddleware(BaseHTTPMiddleware):
    """
    Validates Origin header on state-modifying HTTP methods (POST, PUT, PATCH, DELETE).
    Defends against cross-origin CSRF attacks prior to CSRF token validation.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin:
                clean_origin = origin.rstrip("/")
                # Allowed origins include configured CORS origins + request base url
                allowed_origins = {o.rstrip("/") for o in settings.CORS_ALLOWED_ORIGINS}
                request_base = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
                allowed_origins.add(request_base)

                if clean_origin not in allowed_origins:
                    return JSONResponse(
                        status_code=403,
                        content=format_error_response(
                            "CSRF_FORBIDDEN",
                            "Cross-origin request rejected: untrusted origin"
                        ),
                    )

        return await call_next(request)
