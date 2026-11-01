import uuid
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Callable
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.backend.models.document import Document
from src.backend.models.search_index import IndexJob, IndexGeneration
from src.backend.search_index.hashing import compute_doc_instance_hash
from src.backend.search_index.storage import GenerationStorage
from src.backend.search_index.manager import GenerationManager


class IndexWorker:
    """
    Lifecycle worker responsible for claiming outbox index jobs,
    applying stale-revision protection, retry with exponential backoff,
    and recovering from crashes.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        base_backoff_sec: float = 1.0,
        lock_timeout_sec: float = 300.0,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.base_backoff_sec = base_backoff_sec
        self.lock_timeout_sec = lock_timeout_sec

    def recover_stale_locks(self, db: Session) -> int:
        """
        Crash recovery: Reclaims jobs that were locked by a crashed worker
        where lock_timeout_sec has elapsed since locked_at.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.lock_timeout_sec)

        stuck_jobs = (
            db.query(IndexJob)
            .filter(
                IndexJob.state == "processing",
                IndexJob.locked_at < cutoff,
            )
            .all()
        )

        recovered_count = 0
        for job in stuck_jobs:
            job.state = "pending"
            job.locked_at = None
            job.locked_by = None
            job.scheduled_at = now
            job.error_message = "Recovered after worker crash / lock timeout"
            recovered_count += 1

        if recovered_count > 0:
            db.commit()
        return recovered_count

    def claim_jobs(self, db: Session, batch_size: int = 10) -> List[IndexJob]:
        """
        Claims a batch of pending jobs atomically using row-level locking (FOR UPDATE SKIP LOCKED).
        """
        # First recover any orphaned locks from prior crashes
        self.recover_stale_locks(db)

        now = datetime.now(timezone.utc)

        # Build query for pending jobs ready to be executed
        query = (
            db.query(IndexJob)
            .filter(
                IndexJob.state == "pending",
                (IndexJob.scheduled_at.is_(None)) | (IndexJob.scheduled_at <= now),
            )
            .order_by(IndexJob.created_at.asc())
        )

        # Use SKIP LOCKED if on PostgreSQL
        bind = db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        jobs = query.limit(batch_size).all()
        if not jobs:
            return []

        for job in jobs:
            job.state = "processing"
            job.locked_at = now
            job.locked_by = self.worker_id
            job.attempts += 1
            job.started_at = now

        db.commit()
        return jobs

    def process_job(
        self,
        db: Session,
        job: IndexJob,
        sim_fail: bool = False,
    ) -> bool:
        """
        Processes a single claimed IndexJob.
        Enforces stale-revision protection and idempotent application.
        """
        now = datetime.now(timezone.utc)
        try:
            if sim_fail:
                raise RuntimeError("Simulated worker processing failure")

            doc = db.query(Document).filter(Document.id == job.document_id).first()

            # Stale-Revision Protection:
            # If doc exists in DB, compare its current hash with job.revision_hash.
            # If they don't match, this job is stale (a newer revision already exists).
            if doc:
                current_hash = compute_doc_instance_hash(doc)
                if job.revision_hash != current_hash:
                    # Newer revision supercedes this job: mark completed safely without applying stale state
                    job.state = "completed"
                    job.completed_at = now
                    job.locked_at = None
                    job.locked_by = None
                    job.error_message = "Skipped stale revision"
                    db.commit()
                    return True

            active_gen = GenerationManager.get_active_generation(db)
            if not active_gen:
                # No active generation built yet; re-queue job
                raise RuntimeError("No active index generation currently exists to synchronize")

            storage = GenerationStorage(active_gen.id)

            if job.operation == "upsert" and doc and doc.status == "published" and doc.deleted_at is None:
                tag_slugs = [dt.tag.slug for dt in doc.document_tags if dt.tag] if doc.document_tags else []
                category_slug = doc.category.slug if doc.category else ""
                storage.upsert_document(
                    doc.id,
                    {
                        "title": doc.title,
                        "summary": doc.summary,
                        "category_slug": category_slug,
                        "tags": tag_slugs,
                        "revision_hash": job.revision_hash,
                        "updated_at": (doc.updated_at or now).isoformat(),
                    },
                )
            else:
                # Delete operation, draft status, or soft-deleted doc
                storage.delete_document(job.document_id)

            # Mark completed
            job.state = "completed"
            job.completed_at = now
            job.locked_at = None
            job.locked_by = None
            job.error_message = None

            # Keep active generation doc_count in sync
            manifest = storage.load_manifest()
            if manifest:
                active_gen.doc_count = manifest.get("doc_count", active_gen.doc_count)
                active_gen.updated_at = now

            db.commit()
            return True

        except Exception as exc:
            db.rollback()
            # Handle failure with exponential backoff or dead-letter queue
            self._handle_failure(db, job, exc)
            return False

    def _handle_failure(self, db: Session, job: IndexJob, exc: Exception):
        now = datetime.now(timezone.utc)
        job.error_message = str(exc)
        job.locked_at = None
        job.locked_by = None

        if job.attempts < job.max_attempts:
            job.state = "pending"
            # Exponential backoff: 2^(attempts-1) * base_backoff
            backoff_sec = self.base_backoff_sec * (2 ** (job.attempts - 1))
            job.scheduled_at = now + timedelta(seconds=backoff_sec)
        else:
            job.state = "failed"  # Dead-letter queue
            job.completed_at = now

        try:
            db.commit()
        except Exception:
            db.rollback()

    def run_once(self, db: Session, batch_size: int = 10) -> int:
        """Runs a single poll-and-process iteration. Returns number of jobs processed."""
        jobs = self.claim_jobs(db, batch_size=batch_size)
        processed = 0
        for job in jobs:
            success = self.process_job(db, job)
            if success:
                processed += 1
        return processed
