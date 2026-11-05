import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.models.search_index import IndexJob, IndexGeneration
from src.backend.search_index.manager import GenerationManager
from src.backend.search_index.storage import GenerationStorage
from src.backend.search_index.worker import IndexWorker
from src.backend.search_index.hashing import compute_doc_instance_hash


@pytest.fixture(autouse=True)
def setup_active_generation(db_session: Session):
    """Ensures a clean active generation and clean queue for worker tests."""
    db_session.query(IndexJob).delete()
    db_session.commit()
    active = GenerationManager.build_new_generation(db_session, force=True)
    return active


def test_duplicate_job_idempotency(db_session: Session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    worker = IndexWorker(worker_id="test-worker-1")
    doc_hash = compute_doc_instance_hash(doc)

    # Job 1
    job1 = IndexJob(
        document_id=doc.id,
        revision_hash=doc_hash,
        operation="upsert",
        state="pending",
    )
    db_session.add(job1)
    db_session.commit()

    processed1 = worker.run_once(db_session)
    assert processed1 == 1
    db_session.refresh(job1)
    assert job1.state == "completed"

    # Job 2: Duplicate identical job
    job2 = IndexJob(
        document_id=doc.id,
        revision_hash=doc_hash,
        operation="upsert",
        state="pending",
    )
    db_session.add(job2)
    db_session.commit()

    processed2 = worker.run_once(db_session)
    assert processed2 == 1
    db_session.refresh(job2)
    assert job2.state == "completed"

    # Verify active generation storage is valid and contains doc
    active_gen = GenerationManager.get_active_generation(db_session)
    storage = GenerationStorage(active_gen.id)
    manifest = storage.load_manifest()
    assert doc.id in manifest["docs"]
    assert manifest["docs"][doc.id]["revision_hash"] == doc_hash


def test_out_of_order_job_stale_revision_protection(db_session: Session):
    """
    Critical test:
    Document is at Revision 1 -> Job 1 created.
    Document is updated to Revision 2 -> Job 2 created.
    Job 2 runs first and updates the index to Revision 2.
    Job 1 runs afterwards (delayed / out of order).
    Worker MUST detect Job 1 has a stale revision hash, skip updating index,
    and prevent regression to older document state!
    """
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    worker = IndexWorker(worker_id="test-worker-stale")

    # Capture initial revision hash (Revision 1)
    rev1_hash = compute_doc_instance_hash(doc)

    # Simulate an out-of-order Job 1 for Revision 1
    job1 = IndexJob(
        document_id=doc.id,
        revision_hash=rev1_hash,
        operation="upsert",
        state="pending",
    )
    db_session.add(job1)
    db_session.commit()

    # Now mutate document to Revision 2
    doc.title = "Updated Title at Revision 2"
    db_session.commit()
    rev2_hash = compute_doc_instance_hash(doc)
    assert rev1_hash != rev2_hash

    # Job 2 for Revision 2
    job2 = IndexJob(
        document_id=doc.id,
        revision_hash=rev2_hash,
        operation="upsert",
        state="pending",
    )
    db_session.add(job2)
    db_session.commit()

    # Process Job 2 first!
    worker.claim_jobs(db_session)
    db_session.refresh(job2)
    worker.process_job(db_session, job2)
    assert job2.state == "completed"

    active_gen = GenerationManager.get_active_generation(db_session)
    storage = GenerationStorage(active_gen.id)
    manifest = storage.load_manifest()
    assert manifest["docs"][doc.id]["revision_hash"] == rev2_hash
    assert manifest["docs"][doc.id]["title"] == "Updated Title at Revision 2"

    # Now Job 1 executes (out of order, stale!)
    db_session.refresh(job1)
    worker.process_job(db_session, job1)

    assert job1.state == "completed"
    assert "Skipped stale revision" in (job1.error_message or "")

    # Invariant: Index generation MUST STILL contain Revision 2, NOT Revision 1!
    manifest_after = storage.load_manifest()
    assert manifest_after["docs"][doc.id]["revision_hash"] == rev2_hash
    assert manifest_after["docs"][doc.id]["title"] == "Updated Title at Revision 2"


def test_crash_recovery_reclaims_stuck_locks(db_session: Session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    # Simulate crashed worker: job left in 'processing' with locked_at 1 hour ago
    crashed_time = datetime.now(timezone.utc) - timedelta(hours=1)
    job = IndexJob(
        document_id=doc.id,
        revision_hash="some-hash",
        operation="upsert",
        state="processing",
        locked_at=crashed_time,
        locked_by="crashed-worker-99",
        attempts=1,
    )
    db_session.add(job)
    db_session.commit()

    worker = IndexWorker(worker_id="new-worker-alive", lock_timeout_sec=300)
    recovered = worker.recover_stale_locks(db_session)
    assert recovered == 1

    db_session.refresh(job)
    assert job.state == "pending"
    assert job.locked_at is None
    assert job.locked_by is None
    assert "Recovered" in (job.error_message or "")


def test_retry_exponential_backoff_and_dead_letter_queue(db_session: Session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    worker = IndexWorker(worker_id="test-worker-retry", base_backoff_sec=2.0)

    job = IndexJob(
        document_id=doc.id,
        revision_hash="test-hash",
        operation="upsert",
        state="pending",
        attempts=0,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.commit()

    # Attempt 1: Fails
    claimed = worker.claim_jobs(db_session)
    assert len(claimed) >= 1
    worker.process_job(db_session, job, sim_fail=True)
    db_session.refresh(job)
    assert job.state == "pending"
    assert job.attempts == 1
    assert job.scheduled_at is not None
    # Backoff: 2^(1-1) * 2 = 2s
    assert job.scheduled_at > datetime.now(timezone.utc)

    # Attempt 2: Fast forward scheduled_at, fails again
    job.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    worker.claim_jobs(db_session)
    worker.process_job(db_session, job, sim_fail=True)
    db_session.refresh(job)
    assert job.state == "pending"
    assert job.attempts == 2

    # Attempt 3: Fast forward, 3rd failure reaches max_attempts=3 -> transitions to failed (DLQ)
    job.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    worker.claim_jobs(db_session)
    worker.process_job(db_session, job, sim_fail=True)
    db_session.refresh(job)

    assert job.state == "failed"
    assert job.attempts == 3
    assert job.completed_at is not None
    assert "Simulated worker processing failure" in (job.error_message or "")
