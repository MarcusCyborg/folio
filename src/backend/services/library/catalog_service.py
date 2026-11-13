import re
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, desc, asc

from src.backend.models.document import Document, DocumentTag, DocumentLike
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.comment import Comment
from src.backend.models.system import AppSetting
from src.backend.models.event import InteractionLog
from src.backend.core.sanitizer import render_and_sanitize_markdown
from src.backend.core.wiki_content import clean_wikipedia_content
from src.backend.core.exceptions import AppException
from src.backend.schemas.library import DocumentSummary, DocumentDetail, Taxon

def get_public_settings(db: Session) -> dict:
    settings = db.query(AppSetting).all()
    setting_map = {s.key: s.value for s in settings}
    return {
        "site_name": setting_map.get("site_name", "Folio: Knowledge & Research Library"),
        "site_description": setting_map.get("site_description", "Curated research repository"),
        "registration_enabled": setting_map.get("registration_enabled", True),
        "comments_enabled": setting_map.get("comments_enabled", True),
    }

def escape_sql_wildcards(val: str) -> str:
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def get_categories_list(db: Session, page: int = 1, page_size: int = 20) -> Tuple[List[dict], int]:
    query = (
        db.query(
            Category,
            func.count(
                func.nullif(
                    and_(Document.status == "published", Document.deleted_at.is_(None)),
                    False
                )
            ).label("published_doc_count")
        )
        .outerjoin(Document, Category.id == Document.category_id)
        .group_by(Category.id)
        .order_by(Category.name.asc(), Category.id.asc())
    )
    total = db.query(Category).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    results = [
        {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "published_document_count": count,
        }
        for cat, count in items
    ]
    return results, total

def get_tags_list(db: Session, q: Optional[str] = None, page: int = 1, page_size: int = 20) -> Tuple[List[Tag], int]:
    query = db.query(Tag)
    if q and q.strip():
        safe_q = escape_sql_wildcards(q.strip())
        query = query.filter(Tag.name.ilike(f"%{safe_q}%"))
    total = query.count()
    items = query.order_by(Tag.name.asc(), Tag.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return items, total

def list_published_documents(
    db: Session,
    q: Optional[str] = None,
    category_id: Optional[str] = None,
    tag_ids: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 20,
    actor_key: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Tuple[List[dict], int, Optional[str]]:
    # Validation
    if date_from and date_to and date_from > date_to:
        raise AppException(status_code=422, code="INVALID_DATE_RANGE", message="date_from must be earlier than date_to")

    # Base query: published, not deleted
    query = db.query(Document).filter(
        Document.status == "published",
        Document.deleted_at.is_(None)
    )

    # Keyword filter
    clean_q = q.strip() if q else ""
    if clean_q:
        safe_kw = f"%{escape_sql_wildcards(clean_q)}%"
        query = query.filter(
            or_(
                Document.title.ilike(safe_kw),
                Document.summary.ilike(safe_kw),
                Document.content.ilike(safe_kw)
            )
        )

    # Category filter
    if category_id:
        query = query.filter(Document.category_id == category_id)

    # Multi-tag filter (AND semantics: document must have all selected tags)
    if tag_ids:
        t_ids = [t.strip() for t in tag_ids.split(",") if t.strip()]
        for tid in t_ids:
            query = query.filter(
                Document.id.in_(
                    db.query(DocumentTag.document_id).filter(DocumentTag.tag_id == tid)
                )
            )

    # Date filters (UTC boundaries)
    if date_from:
        dt_from = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(Document.created_at >= dt_from)
    if date_to:
        try:
            next_day = date_to + timedelta(days=1)
            dt_to = datetime.combine(next_day, datetime.min.time(), tzinfo=timezone.utc)
            query = query.filter(Document.created_at < dt_to)
        except OverflowError:
            dt_to = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
            query = query.filter(Document.created_at <= dt_to)

    # Ordering with stable tie-breaker (R04 / F03: support newest, oldest, title/title_asc, title_desc, popular)
    if sort == "oldest":
        query = query.order_by(Document.created_at.asc(), Document.id.asc())
    elif sort in ("title", "title_asc"):
        query = query.order_by(func.lower(Document.title).asc(), Document.title.asc(), Document.id.asc())
    elif sort == "title_desc":
        query = query.order_by(func.lower(Document.title).desc(), Document.title.desc(), Document.id.asc())
    elif sort == "popular":
        likes_subq = (
            db.query(
                DocumentLike.document_id.label("doc_id"),
                func.count(DocumentLike.id).label("likes_cnt"),
            )
            .group_by(DocumentLike.document_id)
            .subquery()
        )
        likes_expr = func.coalesce(likes_subq.c.likes_cnt, 0)
        views_expr = func.coalesce(Document.views_count, 0)
        popularity_expr = (likes_expr * 3) + views_expr
        query = query.outerjoin(likes_subq, Document.id == likes_subq.c.doc_id).order_by(
            popularity_expr.desc(),
            likes_expr.desc(),
            views_expr.desc(),
            Document.created_at.desc(),
            Document.id.asc(),
        )
    else:  # newest
        query = query.order_by(Document.created_at.desc(), Document.id.desc())

    total = query.count()
    docs = query.offset((page - 1) * page_size).limit(page_size).all()

    # Pre-fetch likes and comments count for page
    doc_ids = [d.id for d in docs]
    likes_counts = dict(
        db.query(DocumentLike.document_id, func.count(DocumentLike.id))
        .filter(DocumentLike.document_id.in_(doc_ids))
        .group_by(DocumentLike.document_id)
        .all()
    ) if doc_ids else {}

    comments_counts = dict(
        db.query(Comment.document_id, func.count(Comment.id))
        .filter(Comment.document_id.in_(doc_ids), Comment.status == "visible")
        .group_by(Comment.document_id)
        .all()
    ) if doc_ids else {}

    results = []
    for d in docs:
        tags_list = [
            Taxon(id=dt.tag.id, name=dt.tag.name, slug=dt.tag.slug)
            for dt in d.document_tags
        ]
        results.append({
            "id": d.id,
            "title": d.title,
            "summary": d.summary,
            "author": d.author,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "published_at": d.published_at,
            "views_count": d.views_count,
            "likes_count": likes_counts.get(d.id, 0),
            "comments_count": comments_counts.get(d.id, 0),
            "category": Taxon(id=d.category.id, name=d.category.name, slug=d.category.slug),
            "category_id": d.category_id,
            "tags": tags_list,
            "cover_image_url": d.cover_image_url,
            "cover_image_alt": d.cover_image_alt,
            "source_url": d.source_url,
        })

    # Search logging semantics
    search_event_id = None
    if clean_q and actor_key:
        result_ids = [d.id for d in docs]
        log = InteractionLog(
            event_type="search",
            user_id=user_id,
            query_string=clean_q,
            clicked_doc_id=None,
            timestamp=datetime.now(timezone.utc),
            search_event_id=None,
            actor_key=actor_key,
            request_key=None,
            result_doc_ids=result_ids,
        )
        db.add(log)
        db.commit()
        search_event_id = log.id

    return results, total, search_event_id

def get_published_document_detail(db: Session, doc_id: str, user_id: Optional[str] = None) -> dict:
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()

    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    likes_count = db.query(DocumentLike).filter(DocumentLike.document_id == doc.id).count()
    comments_count = db.query(Comment).filter(Comment.document_id == doc.id, Comment.status == "visible").count()
    
    liked_by_me = False
    if user_id:
        liked_by_me = db.query(DocumentLike).filter(
            DocumentLike.document_id == doc.id,
            DocumentLike.user_id == user_id
        ).first() is not None

    content = clean_wikipedia_content(doc.content, doc.source_url)
    rendered_html = render_and_sanitize_markdown(content)

    tags_list = [
        Taxon(id=dt.tag.id, name=dt.tag.name, slug=dt.tag.slug)
        for dt in doc.document_tags
    ]

    return {
        "id": doc.id,
        "title": doc.title,
        "summary": doc.summary,
        "content": content,
        "rendered_content": rendered_html,
        "author": doc.author,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "published_at": doc.published_at,
        "views_count": doc.views_count,
        "likes_count": likes_count,
        "comments_count": comments_count,
        "category": Taxon(id=doc.category.id, name=doc.category.name, slug=doc.category.slug),
        "category_id": doc.category_id,
        "tags": tags_list,
        "cover_image_url": doc.cover_image_url,
        "cover_image_alt": doc.cover_image_alt,
        "source_url": doc.source_url,
        "source_license": doc.source_license,
        "source_attribution": doc.source_attribution,
        "seo_title": doc.seo_title,
        "seo_description": doc.seo_description,
        "seo_keywords": doc.seo_keywords,
        "liked_by_me": liked_by_me,
    }
