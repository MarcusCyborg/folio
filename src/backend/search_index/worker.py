import uuid
import time
import signal
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Callable, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from src.backend.models.document import Document
from src.backend.models.search_index import IndexJob, IndexGeneration
from src.backend.search_index.hashing import compute_doc_instance_hash
from src.backend.search_index.storage import GenerationStorage
from src.backend.search_index.manager import GenerationManager

logger = logging.getLogger("folio.worker")


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
        semantic_adapter: Optional[Any] = None,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.base_backoff_sec = base_backoff_sec
        self.lock_timeout_sec = lock_timeout_sec
        self._semantic_adapter = semantic_adapter

    def _get_semantic_adapter(self):
        if self._semantic_adapter is None:
            from src.backend.search.semantic import SemanticAdapter
            self._semantic_adapter = SemanticAdapter()
        return self._semantic_adapter

    @classmethod
    def get_metrics(cls, db: Session) -> Dict[str, Any]:
        """Collects worker queue and lag metrics from index_jobs table."""
        now = datetime.now(timezone.utc)
        pending = db.query(func.count(IndexJob.id)).filter(IndexJob.state == "pending").scalar() or 0
        processing = db.query(func.count(IndexJob.id)).filter(IndexJob.state == "processing").scalar() or 0
        failed = db.query(func.count(IndexJob.id)).filter(IndexJob.state == "failed").scalar() or 0
        completed = db.query(func.count(IndexJob.id)).filter(IndexJob.state == "completed").scalar() or 0
        oldest_pending = (
            db.query(IndexJob.created_at)
            .filter(IndexJob.state == "pending")
            .order_by(IndexJob.created_at.asc())
            .first()
        )
        lag_seconds = 0.0
        if oldest_pending and oldest_pending[0]:
            created = oldest_pending[0]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            lag_seconds = max(0.0, (now - created).total_seconds())

        return {
            "pending_jobs": pending,
            "processing_jobs": processing,
            "failed_jobs_dlq": failed,
            "completed_jobs": completed,
            "lag_seconds": round(lag_seconds, 2),
        }

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
                db.refresh(doc)
                db.expire(doc, ["document_tags", "category"])
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
                if (storage.postings_dir / "index_stats.json").exists():
                    from src.backend.search.index import InvertedIndex
                    inv_idx = InvertedIndex.load(storage.postings_dir)
                    combined_text = f"{doc.title} {doc.summary} {doc.content}".strip()
                    tag_ids = [dt.tag_id for dt in doc.document_tags] if doc.document_tags else []
                    inv_idx.upsert_document(
                        doc.id,
                        text=combined_text,
                        title=doc.title,
                        category_id=doc.category_id,
                        tag_ids=tag_ids,
                        created_at=doc.created_at.isoformat() if doc.created_at else None,
                        status="published",
                    )
                    inv_idx.save(storage.postings_dir)
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
                self._get_semantic_adapter().upsert_document(
                    doc_id=doc.id,
                    title=doc.title,
                    summary=doc.summary,
                    content=doc.content,
                    source_url=doc.source_url,
                    revision_hash=job.revision_hash,
                )
            else:
                # Delete operation, draft status, or soft-deleted doc
                if (storage.postings_dir / "index_stats.json").exists():
                    from src.backend.search.index import InvertedIndex
                    inv_idx = InvertedIndex.load(storage.postings_dir)
                    inv_idx.delete_document(job.document_id)
                    inv_idx.save(storage.postings_dir)
                storage.delete_document(job.document_id)
                self._get_semantic_adapter().delete_document(job.document_id)

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

    def run_daemon(
        self,
        poll_interval: float = 1.0,
        batch_size: int = 10,
        stop_event: Optional[Any] = None,
        max_iterations: Optional[int] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> int:
        """
        Runs the worker continuously in a daemon loop.
        Logs worker progress, lag, and dead-letter queue metrics.
        Gracefully halts when stop_event is signaled or max_iterations reached.
        """
        if session_factory is None:
            from src.backend.core.database import SessionLocal
            session_factory = SessionLocal

        logger.info(
            f"Starting IndexWorker daemon [{self.worker_id}] "
            f"(poll_interval={poll_interval}s, batch_size={batch_size})"
        )

        # Initial crash recovery for stale locks
        db = session_factory()
        try:
            recovered = self.recover_stale_locks(db)
            if recovered > 0:
                logger.warning(
                    f"Worker [{self.worker_id}] recovered {recovered} stale locked job(s) from prior crash"
                )
        except Exception as exc:
            logger.error(f"Error during initial lock recovery: {exc}")
        finally:
            db.close()

        total_processed = 0
        iteration = 0
        last_heartbeat = time.monotonic()
        consecutive_errors = 0

        while True:
            if stop_event and stop_event.is_set():
                logger.info(f"Stop signal received. IndexWorker [{self.worker_id}] shutting down gracefully.")
                break

            if max_iterations is not None and iteration >= max_iterations:
                logger.info(f"Reached max iterations ({max_iterations}). IndexWorker exiting.")
                break

            iteration += 1
            processed = 0
            db = session_factory()
            try:
                processed = self.run_once(db, batch_size=batch_size)
                total_processed += processed
                consecutive_errors = 0

                if processed > 0:
                    metrics = self.get_metrics(db)
                    logger.info(
                        f"Worker [{self.worker_id}] processed {processed} job(s). "
                        f"Pending: {metrics['pending_jobs']}, Lag: {metrics['lag_seconds']}s, DLQ: {metrics['failed_jobs_dlq']}"
                    )
            except Exception as exc:
                consecutive_errors += 1
                backoff = min(15.0, 1.0 * (2 ** min(consecutive_errors, 4)))
                logger.error(
                    f"Worker [{self.worker_id}] loop error (attempt {consecutive_errors}): {exc}. "
                    f"Backing off {backoff:.1f}s"
                )
                time.sleep(backoff)
                continue
            finally:
                db.close()

            # Periodic heartbeat (every 30 seconds)
            now_mono = time.monotonic()
            if now_mono - last_heartbeat >= 30.0:
                last_heartbeat = now_mono
                db = session_factory()
                try:
                    metrics = self.get_metrics(db)
                    logger.info(
                        f"Worker [{self.worker_id}] heartbeat: "
                        f"pending={metrics['pending_jobs']}, processing={metrics['processing_jobs']}, "
                        f"dlq={metrics['failed_jobs_dlq']}, lag={metrics['lag_seconds']}s"
                    )
                except Exception:
                    pass
                finally:
                    db.close()

            # Sleep when idle
            if processed == 0:
                if stop_event:
                    stop_event.wait(timeout=poll_interval)
                else:
                    time.sleep(poll_interval)

        return total_processed


def main():
    """CLI entrypoint for running the worker daemon."""
    import argparse
    parser = argparse.ArgumentParser(description="Folio Search Index Lifecycle Worker Daemon")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Poll interval in seconds (default: 1.0)")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for claiming jobs (default: 10)")
    parser.add_argument("--worker-id", type=str, default=None, help="Worker ID (default: auto-generated UUID)")
    parser.add_argument("--once", action="store_true", help="Run a single poll iteration and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    worker = IndexWorker(worker_id=args.worker_id)
    if args.once:
        from src.backend.core.database import SessionLocal
        db = SessionLocal()
        try:
            n = worker.run_once(db, batch_size=args.batch_size)
            print(f"Processed {n} job(s)")
            return 0
        finally:
            db.close()

    stop_event = threading.Event()

    def _sig_handler(signum, frame):
        logger.info(f"Received signal {signum}. Requesting worker stop...")
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    worker.run_daemon(
        poll_interval=args.poll_interval,
        batch_size=args.batch_size,
        stop_event=stop_event,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
