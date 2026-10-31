from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.backend.core.config import settings
from src.backend.core.exceptions import format_error_response

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
