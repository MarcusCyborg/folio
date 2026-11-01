import hashlib
from datetime import datetime
from typing import Optional, List, Union
from src.backend.models.document import Document


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
    del_str = ""
    if deleted_at:
        del_str = deleted_at.isoformat() if isinstance(deleted_at, datetime) else str(deleted_at)

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
    """Convenience helper extracting values from a Document ORM instance."""
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
