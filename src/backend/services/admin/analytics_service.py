from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from src.backend.models.document import Document
from src.backend.models.event import InteractionLog, ViewEvent
from src.backend.models.auth import User
from src.backend.core.audit import write_audit
from src.backend.core.exceptions import AppException
from src.backend.schemas.admin import SEOMetadataUpdate
from src.backend.search_index.outbox import record_revision_and_outbox_job

def admin_update_document_seo(
    db: Session,
    doc_id: str,
    data: SEOMetadataUpdate,
    actor: User,
) -> dict:
    doc = db.query(Document).filter(Document.id == doc_id, Document.deleted_at.is_(None)).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    before_state = {
        "seo_title": doc.seo_title,
        "seo_description": doc.seo_description,
        "cover_image_alt": doc.cover_image_alt
    }

    if "seo_title" in data.model_fields_set:
        doc.seo_title = data.seo_title.strip() if (data.seo_title and data.seo_title.strip()) else None
    if "seo_description" in data.model_fields_set:
        doc.seo_description = data.seo_description.strip() if (data.seo_description and data.seo_description.strip()) else None
    if "cover_image_alt" in data.model_fields_set:
        doc.cover_image_alt = data.cover_image_alt.strip() if (data.cover_image_alt and data.cover_image_alt.strip()) else None
    if "seo_keywords" in data.model_fields_set:
        doc.seo_keywords = data.seo_keywords if data.seo_keywords is not None else []

    doc.updated_at = datetime.now(timezone.utc)

    write_audit(
        db,
        actor=actor,
        action="seo.update",
        entity_type="document",
        entity_id=doc.id,
        before=before_state,
        after={
            "seo_title": doc.seo_title,
            "seo_description": doc.seo_description,
            "cover_image_alt": doc.cover_image_alt,
        }
    )
    if doc.status == "published" and doc.deleted_at is None:
        record_revision_and_outbox_job(db, doc, operation="upsert")
    db.commit()

    return {
        "id": doc.id,
        "seo_title": doc.seo_title,
        "seo_description": doc.seo_description,
        "seo_keywords": doc.seo_keywords or [],
        "cover_image_alt": doc.cover_image_alt,
    }

def admin_get_analytics_overview(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict:
    today_utc = datetime.now(timezone.utc).date()
    if not date_to:
        date_to = today_utc
    if not date_from:
        date_from = date_to - timedelta(days=30)

    if date_from > date_to:
        raise AppException(status_code=422, code="INVALID_DATE_RANGE", message="date_from must be earlier than or equal to date_to")

    delta_days = (date_to - date_from).days
    if delta_days > 366:
        raise AppException(status_code=422, code="DATE_RANGE_TOO_LARGE", message="Maximum analytics period is 366 days")

    dt_start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    try:
        dt_end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    except OverflowError:
        dt_end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)

    # 1. Totals
    published_docs_count = db.query(Document).filter(
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).count()

    search_requests_count = db.query(InteractionLog).filter(
        InteractionLog.event_type == "search",
        InteractionLog.timestamp >= dt_start,
        InteractionLog.timestamp < dt_end,
    ).count()

    result_clicks_count = db.query(InteractionLog).filter(
        InteractionLog.event_type == "click",
        InteractionLog.timestamp >= dt_start,
        InteractionLog.timestamp < dt_end,
    ).count()

    document_views_count = db.query(ViewEvent).filter(
        ViewEvent.timestamp >= dt_start,
        ViewEvent.timestamp < dt_end,
    ).count()

    totals = {
        "published_documents": published_docs_count,
        "search_requests": search_requests_count,
        "result_clicks": result_clicks_count,
        "document_views": document_views_count,
    }

    # 2. Daily time series with zero-filling
    daily_map = {}
    curr = date_from
    while curr <= date_to:
        d_str = curr.isoformat()
        daily_map[d_str] = {"date": d_str, "search_requests": 0, "result_clicks": 0, "document_views": 0}
        curr += timedelta(days=1)

    # Date expression: enforce UTC date extraction
    is_postgres = (db.bind and db.bind.dialect.name == "postgresql")
    if is_postgres:
        log_date_expr = func.date(func.timezone("UTC", InteractionLog.timestamp))
        view_date_expr = func.date(func.timezone("UTC", ViewEvent.timestamp))
    else:
        log_date_expr = func.date(InteractionLog.timestamp)
        view_date_expr = func.date(ViewEvent.timestamp)

    # Aggregate search requests
    daily_searches = (
        db.query(
            log_date_expr.label("d"),
            func.count(InteractionLog.id).label("c")
        )
        .filter(
            InteractionLog.event_type == "search",
            InteractionLog.timestamp >= dt_start,
            InteractionLog.timestamp < dt_end
        )
        .group_by(log_date_expr)
        .all()
    )
    for d, c in daily_searches:
        d_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        if d_str in daily_map:
            daily_map[d_str]["search_requests"] = c

    # Aggregate result clicks
    daily_clicks = (
        db.query(
            log_date_expr.label("d"),
            func.count(InteractionLog.id).label("c")
        )
        .filter(
            InteractionLog.event_type == "click",
            InteractionLog.timestamp >= dt_start,
            InteractionLog.timestamp < dt_end
        )
        .group_by(log_date_expr)
        .all()
    )
    for d, c in daily_clicks:
        d_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        if d_str in daily_map:
            daily_map[d_str]["result_clicks"] = c

    # Aggregate views
    daily_views = (
        db.query(
            view_date_expr.label("d"),
            func.count(ViewEvent.id).label("c")
        )
        .filter(
            ViewEvent.timestamp >= dt_start,
            ViewEvent.timestamp < dt_end
        )
        .group_by(view_date_expr)
        .all()
    )
    for d, c in daily_views:
        d_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        if d_str in daily_map:
            daily_map[d_str]["document_views"] = c

    daily_list = sorted(daily_map.values(), key=lambda x: x["date"])

    # 3. Top queries (max 10)
    top_queries_rows = (
        db.query(
            InteractionLog.query_string,
            func.count(InteractionLog.id).label("search_count")
        )
        .filter(
            InteractionLog.event_type == "search",
            InteractionLog.timestamp >= dt_start,
            InteractionLog.timestamp < dt_end,
            InteractionLog.query_string.isnot(None),
            InteractionLog.query_string != ""
        )
        .group_by(InteractionLog.query_string)
        .order_by(desc("search_count"), InteractionLog.query_string.asc())
        .limit(10)
        .all()
    )
    top_queries = []
    for q_str, s_count in top_queries_rows:
        clicks_for_q = db.query(InteractionLog).filter(
            InteractionLog.event_type == "click",
            InteractionLog.query_string == q_str,
            InteractionLog.timestamp >= dt_start,
            InteractionLog.timestamp < dt_end
        ).count()
        top_queries.append({
            "query_string": q_str,
            "search_requests": s_count,
            "result_clicks": clicks_for_q,
        })

    # 4. Top documents (max 10)
    # Using subqueries so documents with either views or clicks in period are ranked stably
    views_sub = (
        db.query(
            ViewEvent.document_id.label("doc_id"),
            func.count(ViewEvent.id).label("view_count")
        )
        .filter(ViewEvent.timestamp >= dt_start, ViewEvent.timestamp < dt_end)
        .group_by(ViewEvent.document_id)
        .subquery()
    )
    clicks_sub = (
        db.query(
            InteractionLog.clicked_doc_id.label("doc_id"),
            func.count(InteractionLog.id).label("click_count")
        )
        .filter(
            InteractionLog.event_type == "click",
            InteractionLog.clicked_doc_id.isnot(None),
            InteractionLog.timestamp >= dt_start,
            InteractionLog.timestamp < dt_end
        )
        .group_by(InteractionLog.clicked_doc_id)
        .subquery()
    )

    top_docs_rows = (
        db.query(
            Document.id,
            Document.title,
            func.coalesce(views_sub.c.view_count, 0).label("views"),
            func.coalesce(clicks_sub.c.click_count, 0).label("clicks"),
        )
        .outerjoin(views_sub, Document.id == views_sub.c.doc_id)
        .outerjoin(clicks_sub, Document.id == clicks_sub.c.doc_id)
        .filter(
            (func.coalesce(views_sub.c.view_count, 0) > 0) | (func.coalesce(clicks_sub.c.click_count, 0) > 0)
        )
        .order_by(
            desc(func.coalesce(views_sub.c.view_count, 0) + func.coalesce(clicks_sub.c.click_count, 0)),
            Document.title.asc(),
            Document.id.asc()
        )
        .limit(10)
        .all()
    )

    top_docs = [
        {
            "id": row.id,
            "title": row.title,
            "document_views": row.views,
            "result_clicks": row.clicks,
        }
        for row in top_docs_rows
    ]

    return {
        "period": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "timezone": "UTC",
        },
        "totals": totals,
        "daily": daily_list,
        "top_queries": top_queries,
        "top_documents": top_docs,
    }
