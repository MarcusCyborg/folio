from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from src.backend.models.document import Document
from src.backend.models.event import InteractionLog, ViewEvent
from src.backend.core.exceptions import AppException

def record_view(
    db: Session,
    doc_id: str,
    navigation_id: str,
    actor_key: str,
    user_id: Optional[str] = None,
) -> int:
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    existing_view = db.query(ViewEvent).filter(
        ViewEvent.actor_key == actor_key,
        ViewEvent.document_id == doc_id,
        ViewEvent.navigation_id == navigation_id
    ).first()

    if not existing_view:
        view_event = ViewEvent(
            document_id=doc_id,
            user_id=user_id,
            actor_key=actor_key,
            navigation_id=navigation_id,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            db.add(view_event)
            doc.views_count = Document.views_count + 1
            db.commit()
            db.refresh(doc)
        except IntegrityError:
            db.rollback()
            doc = db.query(Document).filter(Document.id == doc_id).first()

    return doc.views_count

def record_click(
    db: Session,
    search_event_id: str,
    document_id: str,
    request_key: str,
    actor_key: str,
    user_id: Optional[str] = None,
) -> str:
    # 1. Idempotent check: if this request_key for this actor_key already succeeded, return existing ID
    existing_click = db.query(InteractionLog).filter(
        InteractionLog.actor_key == actor_key,
        InteractionLog.request_key == request_key
    ).first()
    if existing_click:
        if existing_click.clicked_doc_id == document_id and existing_click.search_event_id == search_event_id:
            return existing_click.id
        raise AppException(
            status_code=409,
            code="REQUEST_KEY_PAYLOAD_MISMATCH",
            message="Same request key cannot be reused with a different document or search event"
        )

    # 2. Verify search event exists, is a search, and matches actor_key
    search_event = db.query(InteractionLog).filter(
        InteractionLog.id == search_event_id,
        InteractionLog.event_type == "search"
    ).first()
    if not search_event:
        raise AppException(status_code=404, code="SEARCH_EVENT_NOT_FOUND", message="Search event not found")

    if search_event.actor_key != actor_key:
        raise AppException(status_code=403, code="ACTOR_MISMATCH", message="Search event does not belong to this session")

    # 3. Verify clicked document was part of the returned results
    result_doc_ids = search_event.result_doc_ids or []
    if document_id not in result_doc_ids:
        raise AppException(
            status_code=422,
            code="DOC_NOT_IN_SEARCH_RESULTS",
            message="Document ID was not in the search results of the specified search event"
        )

    # 4. Verify target document is currently published and not deleted
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Clicked document is not published")

    # 5. Insert separate click event row with server-side copied query_string
    click_log = InteractionLog(
        event_type="click",
        user_id=user_id,
        query_string=search_event.query_string,
        clicked_doc_id=document_id,
        timestamp=datetime.now(timezone.utc),
        search_event_id=search_event.id,
        actor_key=actor_key,
        request_key=request_key,
        result_doc_ids=None,
    )
    db.add(click_log)
    try:
        db.commit()
        return click_log.id
    except IntegrityError:
        db.rollback()
        existing_click = db.query(InteractionLog).filter(
            InteractionLog.actor_key == actor_key,
            InteractionLog.request_key == request_key
        ).first()
        if existing_click:
            if existing_click.clicked_doc_id == document_id and existing_click.search_event_id == search_event_id:
                return existing_click.id
            raise AppException(
                status_code=409,
                code="REQUEST_KEY_PAYLOAD_MISMATCH",
                message="Same request key cannot be reused with a different document or search event"
            )
        raise
