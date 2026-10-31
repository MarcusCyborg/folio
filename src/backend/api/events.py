from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from src.backend.core.database import get_db
from src.backend.core.dependencies import get_session_context, SessionContext
from src.backend.schemas.library import ViewEventRequest, ClickEventRequest
from src.backend.services.library.events_service import record_view, record_click

router = APIRouter(tags=["events"])

@router.post("/documents/{document_id}/views")
def log_document_view(
    data: ViewEventRequest,
    document_id: str = Path(...),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """
    Records a view event idempotently per (actor_key, document_id, navigation_id)
    and atomically increments the document's views_count.
    """
    user_id = ctx.user.id if ctx.user else None
    views_count = record_view(
        db=db,
        doc_id=document_id,
        navigation_id=data.navigation_id,
        actor_key=ctx.actor_key,
        user_id=user_id,
    )
    return {"views_count": views_count}

@router.post("/events/clicks", status_code=status.HTTP_201_CREATED)
def log_result_click(
    data: ClickEventRequest,
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """
    Records a click event linked to an existing search event.
    Copies query_string from search event server-side.
    Idempotent by request_key.
    """
    user_id = ctx.user.id if ctx.user else None
    click_id = record_click(
        db=db,
        search_event_id=data.search_event_id,
        document_id=data.document_id,
        request_key=data.request_key,
        actor_key=ctx.actor_key,
        user_id=user_id,
    )
    return {"id": click_id}
