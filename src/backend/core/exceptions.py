import logging
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.backend.core.config import settings
from src.backend.core.audit import redact_sensitive_text

logger = logging.getLogger("folio.security")

class AppException(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: Optional[Dict[str, List[str]]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.headers = headers

def format_error_response(code: str, message: str, fields: Optional[Dict[str, List[str]]] = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or {}
        }
    }

async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(exc.code, exc.message, exc.fields),
        headers=exc.headers,
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, "ERROR")
    message = str(exc.detail) if exc.detail else "An error occurred"
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(code, message),
        headers=getattr(exc, "headers", None),
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    fields: Dict[str, List[str]] = {}
    for err in exc.errors():
        loc = err.get("loc", [])
        field_name = str(loc[-1]) if loc else "general"
        msg = err.get("msg", "Invalid value")
        if field_name not in fields:
            fields[field_name] = []
        fields[field_name].append(msg)
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=format_error_response("VALIDATION_ERROR", "Request validation failed", fields),
    )

async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catches unhandled server exceptions (500).
    In production and staging, redacts error details to prevent leaking stack traces,
    database connection strings, or system paths.
    """
    safe_error_msg = redact_sensitive_text(str(exc))
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        safe_error_msg,
        exc_info=(settings.APP_ENV in ("development", "test")),
    )

    if settings.APP_ENV in ("production", "staging"):
        # Strict zero-leak response for production
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=format_error_response(
                "INTERNAL_SERVER_ERROR",
                "An unexpected internal server error occurred."
            ),
        )

    # In development/test, return descriptive error for debugging
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=format_error_response(
            "INTERNAL_SERVER_ERROR",
            f"Internal error: {safe_error_msg}"
        ),
    )
