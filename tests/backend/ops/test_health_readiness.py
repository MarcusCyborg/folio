import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from src.backend.main import app
from src.backend.models.search_index import IndexJob
from src.backend.search_index.worker import IndexWorker


def test_liveness_probe(client):
    """Liveness probe must return 200 immediately without database or model checks."""
    res = client.get("/health/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "alive"
    assert data["app"] == "folio"
    assert "timestamp" in data
    assert "version" in data


def test_legacy_health_check_backward_compatibility(client):
    """GET /health must maintain full backward compatibility for Phase 1 contract."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["legacy_search"] == "disabled"


def test_readiness_probe_structure_and_fallback(client):
    """Readiness probe returns 200 with structured diagnostics for DB, search, worker, semantic."""
    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["database"] == "ok"
    assert "search" in data
    assert "worker" in data
    assert "semantic" in data
    assert "timestamp" in data

    # Verify search diagnostics structure
    search = data["search"]
    assert "engine" in search
    assert "status" in search
    assert "is_degraded" in search

    # Verify worker diagnostics structure
    worker = data["worker"]
    assert "status" in worker
    assert "pending_jobs" in worker
    assert "failed_jobs_dlq" in worker
    assert "lag_seconds" in worker

    # Verify semantic diagnostics structure
    semantic = data["semantic"]
    assert "status" in semantic
    assert "reason" in semantic


def test_readiness_probe_database_unavailable():
    """Readiness probe must return HTTP 503 when database connectivity fails."""
    mock_db = MagicMock(spec=Session)
    mock_db.execute.side_effect = OperationalError("connection refused", {}, None)

    from src.backend.core.database import get_db

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_c:
            res = test_c.get("/health/ready")
            assert res.status_code == 503
            data = res.json()
            assert data["status"] == "unavailable"
            assert data["database"] == "unavailable"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_worker_metrics_calculation_unit():
    """IndexWorker.get_metrics correctly aggregates pending, processing, dlq, and lag."""
    mock_db = MagicMock(spec=Session)

    # Mock query counts
    query_mock = MagicMock()
    mock_db.query.return_value = query_mock
    filter_mock = MagicMock()
    query_mock.filter.return_value = filter_mock
    filter_mock.scalar.side_effect = [5, 2, 1, 100]  # pending, processing, failed, completed

    # Mock oldest pending created_at
    order_mock = MagicMock()
    filter_mock.order_by.return_value = order_mock
    now = datetime.now(timezone.utc)
    order_mock.first.return_value = (now,)

    metrics = IndexWorker.get_metrics(mock_db)
    assert metrics["pending_jobs"] == 5
    assert metrics["processing_jobs"] == 2
    assert metrics["failed_jobs_dlq"] == 1
    assert metrics["completed_jobs"] == 100
    assert isinstance(metrics["lag_seconds"], float)
