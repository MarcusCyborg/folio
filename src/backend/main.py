import os
from typing import Optional
from fastapi import FastAPI, Query, Depends, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)

# API Routers
from src.backend.api.auth import router as auth_router
from src.backend.api.library import router as library_router
from src.backend.api.engagement import router as engagement_router
from src.backend.api.events import router as events_router
from src.backend.api.admin import router as admin_router

app = FastAPI(
    title="Folio — Knowledge & Research Library API",
    description="Enterprise Document & Research Repository API",
    version="2.0.0",
)

# Exception Handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core Phase 1 Health Check
@app.get("/health")
def health_check(response: Response, db: Session = Depends(get_db)):
    """
    Lightweight health check.
    Verifies database connectivity without initializing heavy ML models.
    """
    db_status = "ok"
    try:
        db.execute(text("SELECT 1;"))
    except Exception as e:
        db_status = f"error: {str(e)}"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
api_v1_router = FastAPI()
app.include_router(auth_router, prefix="/api/v1")
app.include_router(library_router, prefix="/api/v1")
app.include_router(engagement_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

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
