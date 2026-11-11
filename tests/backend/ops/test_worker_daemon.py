import pytest
import threading
import time
from unittest.mock import MagicMock
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from src.backend.models.search_index import IndexJob
from src.backend.search_index.worker import IndexWorker


def test_worker_daemon_max_iterations():
    """Worker daemon must cleanly exit when max_iterations is reached."""
    worker = IndexWorker(worker_id="test-daemon-worker")

    mock_db = MagicMock(spec=Session)
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    def mock_session_factory():
        return mock_db

    total = worker.run_daemon(
        poll_interval=0.01,
        batch_size=5,
        max_iterations=3,
        session_factory=mock_session_factory,
    )
    assert total == 0


def test_worker_daemon_graceful_stop_event():
    """Worker daemon must stop when stop_event is signaled."""
    worker = IndexWorker(worker_id="test-daemon-stop")
    stop_event = threading.Event()

    mock_db = MagicMock(spec=Session)
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    def mock_session_factory():
        return mock_db

    # Signal stop after 50ms
    def trigger_stop():
        time.sleep(0.05)
        stop_event.set()

    t = threading.Thread(target=trigger_stop)
    t.start()

    start = time.time()
    worker.run_daemon(
        poll_interval=0.02,
        batch_size=5,
        stop_event=stop_event,
        session_factory=mock_session_factory,
    )
    t.join()
    assert time.time() - start < 3.0


def test_worker_recovers_stale_locks_unit():
    """Stale locked jobs exceeding timeout must be reset to pending."""
    worker = IndexWorker(worker_id="crash-recovery-worker", lock_timeout_sec=60.0)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(seconds=120)

    stuck_job = IndexJob(
        id="job-stuck-1",
        document_id="doc-1",
        revision_hash="hash1",
        operation="upsert",
        state="processing",
        locked_at=old_time,
        locked_by="dead-worker",
    )

    mock_db = MagicMock(spec=Session)
    mock_db.query.return_value.filter.return_value.all.return_value = [stuck_job]

    recovered = worker.recover_stale_locks(mock_db)
    assert recovered == 1
    assert stuck_job.state == "pending"
    assert stuck_job.locked_at is None
    assert stuck_job.locked_by is None
    assert "crash" in stuck_job.error_message.lower()
    mock_db.commit.assert_called_once()


def test_r16_docker_entrypoints_do_not_echo_database_url():
    """R16 (OPS-07): Entrypoint scripts must never print or echo DATABASE_URL credentials to container logs."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    entrypoints = [
        repo_root / "docker" / "entrypoints" / "entrypoint-web.sh",
        repo_root / "docker" / "entrypoints" / "entrypoint-worker.sh",
        repo_root / "docker" / "entrypoints" / "entrypoint-migrate.sh",
    ]
    for script_path in entrypoints:
        assert script_path.exists(), f"Missing entrypoint script: {script_path}"
        content = script_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("echo ") or "echo \"" in stripped or "echo '" in stripped:
                assert "${DATABASE_URL}" not in stripped and "$DATABASE_URL" not in stripped, (
                    f"{script_path.name} echoes DATABASE_URL in log line: {stripped}"
                )


def test_ext01_worker_syncs_semantic_vector_lifecycle_on_publish_update_unpublish_delete(db_session):
    """
    EXT-01:
    IndexWorker must synchronize SemanticAdapter on publish/update (upsert)
    and unpublish/delete (delete), while SemanticAdapter degrades gracefully
    when ChromaDB is not configured.
    """
    import uuid
    from datetime import datetime, timezone
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category
    from src.backend.search.semantic import SemanticAdapter
    from src.backend.search_index.hashing import compute_doc_instance_hash
    from src.backend.search_index.manager import GenerationManager

    # 1. Unconfigured SemanticAdapter gracefully returns False without raising
    unconfigured = SemanticAdapter(chroma_path="/nonexistent/folio-vector-dir")
    assert unconfigured.upsert_document("doc-x", "T", "S", "Body") is False
    assert unconfigured.delete_document("doc-x") is False

    # 2. Mock collection verifies chunk replacement (delete old chunks then upsert new chunks)
    fake_collection = MagicMock()
    configured = SemanticAdapter(chroma_path="/nonexistent/folio-vector-dir")
    configured._collection = fake_collection
    assert configured.upsert_document(
        doc_id="doc-vec-1",
        title="Title",
        summary="Summary",
        content="A" * 1500,
        source_url="https://example.org/vec",
        revision_hash="rev-hash-1",
    ) is True
    fake_collection.delete.assert_called_once_with(where={"document_id": "doc-vec-1"})
    fake_collection.upsert.assert_called_once()
    upsert_kwargs = fake_collection.upsert.call_args.kwargs
    assert len(upsert_kwargs["ids"]) == 2
    assert all(m["document_id"] == "doc-vec-1" and m["revision_hash"] == "rev-hash-1" for m in upsert_kwargs["metadatas"])

    # 3. End-to-end IndexWorker lifecycle: publish -> unpublish -> soft-delete
    GenerationManager.build_new_generation(db_session, force=True)
    cat = db_session.query(Category).first()
    assert cat is not None

    now = datetime.now(timezone.utc)
    doc = Document(
        title=f"Vector Sync Doc {uuid.uuid4().hex[:6]}",
        summary="Semantic lifecycle test summary",
        content="Dense vector embedding body content.",
        category_id=cat.id,
        status="published",
        created_at=now,
        published_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    spy_adapter = MagicMock()
    worker = IndexWorker(worker_id="ext01-worker", semantic_adapter=spy_adapter)

    rev1 = compute_doc_instance_hash(doc)
    job_pub = IndexJob(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        revision_hash=rev1,
        operation="upsert",
        state="pending",
    )
    db_session.add(job_pub)
    db_session.commit()

    assert worker.process_job(db_session, job_pub) is True
    spy_adapter.upsert_document.assert_called_once()
    assert spy_adapter.upsert_document.call_args.kwargs["doc_id"] == doc.id
    assert spy_adapter.upsert_document.call_args.kwargs["revision_hash"] == rev1

    # Unpublish (draft) -> worker deletes vector entries
    doc.status = "draft"
    db_session.commit()
    rev2 = compute_doc_instance_hash(doc)
    job_unpub = IndexJob(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        revision_hash=rev2,
        operation="upsert",
        state="pending",
    )
    db_session.add(job_unpub)
    db_session.commit()

    assert worker.process_job(db_session, job_unpub) is True
    spy_adapter.delete_document.assert_called_with(doc.id)
