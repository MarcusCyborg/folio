import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Query, Depends, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.core.exceptions import (
    AppException,
    format_error_response,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    unhandled_exception_handler,
)
from src.backend.core.rate_limit import RateLimitStoreUnavailableError
from src.backend.core.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    OriginVerificationMiddleware,
)

# API Routers
from src.backend.api.auth import router as auth_router
from src.backend.api.library import router as library_router
from src.backend.api.engagement import router as engagement_router
from src.backend.api.events import router as events_router
from src.backend.api.admin import router as admin_router
from src.backend.api.search import router as search_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Executes fail-fast production security configuration validation on boot.
    """
    settings.validate_production()
    try:
        yield
    finally:
        from src.backend.services.search.search_service import shutdown_search_executors
        shutdown_search_executors(wait=False)

app = FastAPI(
    title="Folio: Knowledge & Research Library API",
    description="Enterprise Document & Research Repository API",
    version="2.0.0",
    lifespan=lifespan,
)

async def rate_limit_store_unavailable_handler(request: Request, exc: RateLimitStoreUnavailableError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=format_error_response(
            "RATE_LIMIT_UNAVAILABLE",
            "Rate limiting service is temporarily unavailable. Please try again later."
        ),
    )

# Exception Handlers (including production unhandled 500 redaction)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RateLimitStoreUnavailableError, rate_limit_store_unavailable_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Observability and Security Middlewares
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginVerificationMiddleware)

# Standardized CORS Middleware (strictly excludes '*' when credentials are enabled)
safe_cors_origins = [orig for orig in settings.CORS_ALLOWED_ORIGINS if orig != "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=safe_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Core Phase 1 Health Check (Backward-Compatible)
@app.get("/health", tags=["ops"])
def health_check(response: Response, db: Session = Depends(get_db)):
    """
    Lightweight health check.
    Verifies database connectivity without initializing heavy ML models.
    In production, hides internal database exception details.
    """
    db_status = "ok"
    try:
        db.execute(text("SELECT 1;"))
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if settings.APP_ENV in ("production", "staging"):
            db_status = "unavailable"
        else:
            db_status = f"error: {str(e)}"

        return {
            "status": "error",
            "database": db_status,
            "legacy_search": "enabled" if settings.ENABLE_LEGACY_SEARCH else "disabled",
        }

    return {
        "status": "ok",
        "database": db_status,
        "legacy_search": "enabled" if settings.ENABLE_LEGACY_SEARCH else "disabled",
    }


# Phase 2 / SRE Liveness Probe
@app.get("/health/live", tags=["ops"])
def liveness_check():
    """
    Kubernetes / Docker lightweight liveness probe.
    Returns 200 immediately to confirm web process is alive and responsive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app": "folio",
        "version": "2.0.0",
        "env": settings.APP_ENV,
    }


# Phase 2 / SRE Comprehensive Readiness Probe
@app.get("/health/ready", tags=["ops"])
def readiness_check(response: Response, db: Session = Depends(get_db)):
    """
    Comprehensive readiness probe distinguishing:
    1. Database connectivity (503 if unreachable).
    2. Search index status & generation integrity (BM25 vs ILIKE fallback).
    3. Worker queue lag & dead-letter failed jobs.
    4. Semantic backend availability & degradation reason.
    Returns 200 when service can serve traffic (even with degraded search fallbacks).
    """
    # 1. Database Check
    try:
        db.execute(text("SELECT 1;"))
        db_status = "ok"
    except Exception as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unavailable",
            "database": "unavailable",
            "error": "Database connectivity failed" if settings.APP_ENV in ("production", "staging") else str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # 2. Search Index & Generation Status
    search_info = {
        "engine": "ilike_fallback",
        "status": "degraded",
        "generation_id": None,
        "generation_num": None,
        "doc_count": 0,
        "is_degraded": True,
        "degraded_reason": "No active lexical index generation or postings file missing",
    }
    try:
        from src.backend.search_index.manager import GenerationManager
        from src.backend.search_index.storage import GenerationStorage

        active_gen = GenerationManager.get_active_generation(db)
        if active_gen:
            if settings.INDEX_STORAGE_BACKEND == "database":
                from src.backend.search_index.database_storage import load_index, source_signature
                load_index(active_gen)
                index_available = active_gen.manifest.get("source_signature") == source_signature(db)
            else:
                storage = GenerationStorage(active_gen.id)
                index_available = (storage.postings_dir / "index_stats.json").exists()
            if index_available:
                search_info = {
                    "engine": "bm25",
                    "status": "ready",
                    "generation_id": active_gen.id,
                    "generation_num": active_gen.generation_num,
                    "doc_count": active_gen.doc_count,
                    "is_degraded": False,
                    "degraded_reason": None,
                }
            else:
                search_info["degraded_reason"] = (
                    f"Generation {active_gen.generation_num} needs rebuilding or its postings are unavailable"
                )
    except Exception as exc:
        search_info["degraded_reason"] = f"Failed to inspect index generation: {str(exc)}"

    # 3. Worker & Outbox Stats
    worker_info = {
        "status": "unknown",
        "pending_jobs": 0,
        "processing_jobs": 0,
        "completed_jobs": 0,
        "failed_jobs_dlq": 0,
        "lag_seconds": 0.0,
    }
    try:
        from src.backend.search_index.manager import GenerationManager
        idx_status = GenerationManager.get_index_status(db)
        outbox = idx_status.get("outbox_jobs", {})
        pending = outbox.get("pending", 0)
        failed = outbox.get("failed", 0)
        lag = idx_status.get("index_lag_seconds", 0.0)

        w_status = "healthy"
        if lag > 120.0 or pending > 500:
            w_status = "lagging"
        elif failed > 0:
            w_status = "degraded"

        worker_info = {
            "status": w_status,
            "pending_jobs": pending,
            "processing_jobs": outbox.get("processing", 0),
            "completed_jobs": outbox.get("completed", 0),
            "failed_jobs_dlq": failed,
            "lag_seconds": lag,
        }
    except Exception as exc:
        worker_info["error"] = str(exc)

    # 4. Semantic Backend Status (OPS-06 / R3-04: bounded lightweight check using shared executor)
    semantic_info = {
        "status": "unavailable",
        "reason": "Semantic engine not initialized",
    }
    try:
        from src.backend.services.search.search_service import (
            check_semantic_readiness_with_timeout,
            semantic_adapter,
        )

        sem_avail, sem_reason = check_semantic_readiness_with_timeout(
            adapter=semantic_adapter,
            timeout_sec=2.0,
        )
        semantic_info = {
            "status": "available" if sem_avail else "unavailable",
            "reason": sem_reason,
        }
    except Exception as exc:
        semantic_info = {
            "status": "unavailable",
            "reason": str(exc),
        }

    return {
        "status": "ready",
        "database": db_status,
        "search": search_info,
        "worker": worker_info,
        "semantic": semantic_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# Optional Legacy Search Engine Service (Cached & Lazy Initialized)
_legacy_search_service = None

def get_legacy_search_service():
    global _legacy_search_service
    if not settings.ENABLE_LEGACY_SEARCH:
        raise AppException(
            status_code=503,
            code="LEGACY_SEARCH_DISABLED",
            message="Legacy semantic search engine is currently disabled by configuration (ENABLE_LEGACY_SEARCH=false)"
        )
    if _legacy_search_service is None:
        try:
            from src.backend.search_service import SearchService
            _legacy_search_service = SearchService()
        except Exception as e:
            raise AppException(
                status_code=503,
                code="LEGACY_SEARCH_UNAVAILABLE",
                message=f"Legacy search service dependencies or vector dataset unavailable: {str(e)}"
            )
    return _legacy_search_service

@app.get("/search")
def search_wiki_legacy(
    q: str = Query(..., description="Type a natural query"),
    k: int = Query(5, ge=1, le=20, description="Default: 5 documents"),
):
    """
    Legacy search endpoint preserved from WikiSearchEngine.
    Only initialized when ENABLE_LEGACY_SEARCH=true.
    """
    service = get_legacy_search_service()
    return service.search(query=q, top_k=k)

# Mount all Phase 1 API Routers under /api/v1
app.include_router(auth_router, prefix="/api/v1")
app.include_router(library_router, prefix="/api/v1")
app.include_router(engagement_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")

# Admin documents preview alias at /admin/documents/preview
from src.backend.core.dependencies import require_permission
from src.backend.models.auth import User
from src.backend.schemas.admin import DocumentPreviewRequest, DocumentPreviewResponse
from src.backend.core.sanitizer import render_and_sanitize_markdown

@app.post("/admin/documents/preview", response_model=DocumentPreviewResponse, tags=["admin"])
def preview_document_alias(
    data: DocumentPreviewRequest,
    current_user: User = Depends(require_permission("documents:write")),
):
    return {"rendered_content": render_and_sanitize_markdown(data.content)}

# Mount Frontend Static Files at root AFTER API registration
FRONTEND_DIR = os.path.join(settings.PROJECT_ROOT, "src", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
