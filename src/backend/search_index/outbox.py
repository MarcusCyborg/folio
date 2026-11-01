from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.backend.models.document import Document
from src.backend.models.search_index import DocumentRevision, IndexJob
from src.backend.search_index.hashing import compute_doc_instance_hash


def record_revision_and_outbox_job(
    db: Session,
    doc: Document,
    operation: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
) -> Tuple[DocumentRevision, IndexJob]:
    """
    Records an immutable document revision and enqueues a transactional outbox index job
    in the SAME database transaction as the document mutation.

    Invariant:
    - If doc is published and not soft-deleted, default operation is 'upsert'.
    - If doc is draft, unpublished, or soft-deleted, default operation is 'delete'.
    """
    content_hash = compute_doc_instance_hash(doc)

    # Determine next revision number monotonically
    max_rev = db.query(func.coalesce(func.max(DocumentRevision.revision_num), 0)).filter(
        DocumentRevision.document_id == doc.id
    ).scalar() or 0
    next_rev = max_rev + 1

    revision = DocumentRevision(
        document_id=doc.id,
        revision_num=next_rev,
        content_hash=content_hash,
        title=doc.title,
        summary=doc.summary,
        status=doc.status,
    )
    db.add(revision)

    if operation is None:
        if doc.status == "published" and doc.deleted_at is None:
            operation = "upsert"
        else:
            operation = "delete"

    job = IndexJob(
        document_id=doc.id,
        revision_hash=content_hash,
        operation=operation,
        state="pending",
        attempts=0,
        max_attempts=5,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
    )
    db.add(job)
    return revision, job


def emit_taxonomy_reindex_jobs(
    db: Session,
    doc_ids: List[str],
) -> List[IndexJob]:
    """
    Enqueues reindexing outbox jobs for documents affected by taxonomy updates
    (category or tag rename / slug update) within the same transaction.
    """
    if not doc_ids:
        return []

    docs = db.query(Document).filter(
        Document.id.in_(doc_ids),
        Document.deleted_at.is_(None),
    ).all()

    jobs = []
    now = datetime.now(timezone.utc)
    for doc in docs:
        content_hash = compute_doc_instance_hash(doc)
        op = "upsert" if doc.status == "published" else "delete"
        job = IndexJob(
            document_id=doc.id,
            revision_hash=content_hash,
            operation=op,
            state="pending",
            attempts=0,
            max_attempts=5,
            scheduled_at=now,
        )
        db.add(job)
        jobs.append(job)
    return jobs
