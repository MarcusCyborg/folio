from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session

from src.backend.core.database import get_db
from src.backend.core.dependencies import get_session_context, SessionContext
from src.backend.schemas.shared import PublicSettingsResponse, PaginatedResponse, Taxon
from src.backend.schemas.library import DocumentSummary, DocumentDetail, DocumentListResponse
from src.backend.services.library.catalog_service import (
    get_public_settings,
    get_categories_list,
    get_tags_list,
    list_published_documents,
    get_published_document_detail,
)

router = APIRouter(tags=["library"])

@router.get("/settings/public", response_model=PublicSettingsResponse)
def read_public_settings(db: Session = Depends(get_db)):
    """Returns public site configuration flags."""
    return get_public_settings(db)

@router.get("/categories")
def list_categories(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lists categories with published document counts."""
    items, total = get_categories_list(db, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }

@router.get("/tags", response_model=PaginatedResponse[Taxon])
def list_tags(
    q: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lists tags with optional name filtering."""
    items, total = get_tags_list(db, q=q, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {
        "items": [Taxon(id=t.id, name=t.name, slug=t.slug) for t in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }

@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    q: Optional[str] = Query(None, max_length=200),
    category_id: Optional[str] = Query(None, max_length=50),
    tag_ids: Optional[str] = Query(None, max_length=500),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    sort: str = Query("newest", pattern="^(newest|oldest|title|title_asc|title_desc|popular)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """
    Lists published documents with pagination, keyword search, and filters.
    Records a search event log when keyword query 'q' is present.
    """
    user_id = ctx.user.id if ctx.user else None
    items, total, search_event_id = list_published_documents(
        db=db,
        q=q,
        category_id=category_id,
        tag_ids=tag_ids,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        page=page,
        page_size=page_size,
        actor_key=ctx.actor_key,
        user_id=user_id,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    clean_q = q.strip() if q else ""
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "query": clean_q if clean_q else None,
        "search_event_id": search_event_id,
    }

@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str = Path(...),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """
    Retrieves full metadata and rendered/sanitized HTML content for a published document.
    Does NOT increment views_count.
    """
    user_id = ctx.user.id if ctx.user else None
    return get_published_document_detail(db, document_id, user_id=user_id)
