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
