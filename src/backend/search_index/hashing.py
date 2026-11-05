import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Union
from sqlalchemy.orm import object_session
from src.backend.models.document import Document, DocumentTag


def _normalize_deleted_at(deleted_at: Optional[Union[datetime, str]]) -> str:
    """
    Normalizes deleted_at so pre-commit timezone-aware UTC datetimes and
    post-commit PostgreSQL TIMESTAMP WITHOUT TIME ZONE datetimes hash identically.
    """
    if not deleted_at:
        return ""
    if isinstance(deleted_at, str):
        s = deleted_at.strip()
        if not s:
            return ""
        try:
            deleted_at = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return s
    if isinstance(deleted_at, datetime):
        if deleted_at.tzinfo is not None:
            deleted_at = deleted_at.astimezone(timezone.utc).replace(tzinfo=None)
        return deleted_at.isoformat()
    return str(deleted_at)


def compute_document_hash(
    title: str,
    summary: str,
    content: str,
    category_id: Optional[str],
    tag_ids: Optional[List[str]],
    status: str,
    deleted_at: Optional[Union[datetime, str]] = None,
) -> str:
    """
    Computes a deterministic SHA-256 hash representing a document's indexed state.
    Used for stale-revision protection, outbox synchronization, and change detection.
    """
    del_str = _normalize_deleted_at(deleted_at)

    sorted_tags = sorted(tag_ids or [])
    tag_component = ",".join(sorted_tags)

    parts = [
        (title or "").strip(),
        (summary or "").strip(),
        (content or "").strip(),
        category_id or "",
        tag_component,
        (status or "").strip().lower(),
        del_str,
    ]
    raw = "\x1f".join(parts)  # ASCII unit separator
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_doc_instance_hash(doc: Document) -> str:
    """
    Convenience helper extracting values from a Document ORM instance.
    When bound to a SQLAlchemy session, flushes pending mutations in the transaction
    and queries DocumentTag rows directly to avoid stale identity-map relationship state.
    """
    sess = object_session(doc)
    if sess is not None and doc.id:
        if sess.new or sess.dirty or sess.deleted:
            sess.flush()
        tag_rows = (
            sess.query(DocumentTag.tag_id)
            .filter(DocumentTag.document_id == doc.id)
            .all()
        )
        tag_ids = [row[0] for row in tag_rows]
    else:
        tag_ids = [dt.tag_id for dt in doc.document_tags] if doc.document_tags else []

    return compute_document_hash(
        title=doc.title,
        summary=doc.summary,
        content=doc.content,
        category_id=doc.category_id,
        tag_ids=tag_ids,
        status=doc.status,
        deleted_at=doc.deleted_at,
    )
