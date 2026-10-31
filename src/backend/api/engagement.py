from typing import Optional, List
from fastapi import APIRouter, Depends, Query, Path, Response, status
from sqlalchemy.orm import Session

from src.backend.core.database import get_db
from src.backend.core.dependencies import get_current_user, get_session_context, SessionContext
from src.backend.models.auth import User
from src.backend.schemas.library import (
    CommentPublic,
    CommentCreateRequest,
    CommentUpdateRequest,
    ReportCreateRequest,
    AuthorSummary,
)
from src.backend.schemas.shared import PaginatedResponse
from src.backend.services.library.engagement_service import (
    toggle_like,
    list_comments,
    create_comment,
    update_comment,
    delete_comment,
    search_mentions,
    report_comment,
)

router = APIRouter(tags=["engagement"])

@router.put("/documents/{document_id}/like")
def like_document(
    document_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Likes a published document idempotently."""
    liked_by_me, likes_count = toggle_like(db, document_id, current_user.id, like_action=True)
    return {"liked_by_me": liked_by_me, "likes_count": likes_count}

@router.delete("/documents/{document_id}/like")
def unlike_document(
    document_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unlikes a published document idempotently."""
    liked_by_me, likes_count = toggle_like(db, document_id, current_user.id, like_action=False)
    return {"liked_by_me": liked_by_me, "likes_count": likes_count}

@router.get("/documents/{document_id}/comments", response_model=PaginatedResponse[CommentPublic])
def get_document_comments(
    document_id: str = Path(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Lists visible comments for a published document, sorted oldest first."""
    current_user_id = ctx.user.id if ctx.user else None
    items, total = list_comments(db, document_id, current_user_id=current_user_id, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }

@router.post("/documents/{document_id}/comments", response_model=CommentPublic, status_code=status.HTTP_201_CREATED)
def post_comment(
    data: CommentCreateRequest,
    document_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Posts a new comment and derives @mentions server-side."""
    return create_comment(db, document_id, current_user, data.body)

@router.patch("/comments/{comment_id}", response_model=CommentPublic)
def edit_comment(
    data: CommentUpdateRequest,
    comment_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edits owner's comment body, re-derives @mentions, and validates status."""
    return update_comment(db, comment_id, current_user, data.body)

@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_comment(
    comment_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-deletes owner's comment."""
    delete_comment(db, comment_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/users/mentions", response_model=List[AuthorSummary])
def mention_lookup(
    q: str = Query(..., min_length=2, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Autocomplete for user tagging without leaking email addresses or role data."""
    return search_mentions(db, q, page=page, page_size=page_size)

@router.post("/comments/{comment_id}/reports", status_code=status.HTTP_201_CREATED)
def create_comment_report(
    data: ReportCreateRequest,
    comment_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submits a moderation report on a visible comment."""
    return report_comment(db, comment_id, current_user, data.reason, data.details)
