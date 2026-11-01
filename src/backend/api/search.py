from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.backend.core.database import get_db
from src.backend.core.dependencies import get_session_context, SessionContext
from src.backend.core.rate_limit import rate_limiter, get_client_ip
from src.backend.core.exceptions import format_error_response
from src.backend.schemas.search import SearchResponse
from src.backend.services.search.search_service import SearchService

router = APIRouter(tags=["search"])
search_service_instance = SearchService()


@router.get("/search", response_model=SearchResponse)
def execute_search(
    request: Request,
    response: Response,
    q: Optional[str] = Query(None, description="Cleaned query string (1-200 characters)"),
    search_context_token: Optional[str] = Query(None, description="Server-issued context token"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    mode: str = Query("bm25", description="Retrieval mode: bm25, semantic, hybrid"),
    category_id: Optional[str] = Query(None, description="Filter by category UUID"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag UUIDs (AND semantics)"),
    date_from: Optional[date] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """
    Folio Search API (Contract v2.1.0):
    - Multi-mode information retrieval: Okapi BM25, Semantic vector search, and Hybrid RRF
    - Server-issued actor-bound search context pagination (TTL 15m)
    - Prune without backfill live PostgreSQL publication & deletion verification (0s lag)
    - Search event logging tracking exact returned Document IDs
    """
    # 1. Rate Limiting Check
    client_ip = get_client_ip(request)
    rate_res = rate_limiter.check_and_record_search_attempt(client_ip)
    if not rate_res.allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=format_error_response(
                "TOO_MANY_REQUESTS",
                f"Too many search requests. Please retry in {rate_res.retry_after} seconds."
            ),
            headers={"Retry-After": str(rate_res.retry_after)},
        )

    # 2. Execute Search
    user_id = ctx.user.id if ctx.user else None
    result = search_service_instance.search(
        db=db,
        query=q,
        search_context_token=search_context_token,
        page=page,
        page_size=page_size,
        mode=mode,
        category_id=category_id,
        tag_ids_raw=tag_ids,
        date_from=date_from,
        date_to=date_to,
        actor_key=ctx.actor_key,
        user_id=user_id,
    )

    # 3. Response Headers
    response.headers["X-Search-Event-Id"] = result.search_event_id
    response.headers["X-Index-Generation"] = result.index_generation

    return result
