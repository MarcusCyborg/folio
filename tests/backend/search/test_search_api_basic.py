import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.models.event import InteractionLog
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    """Ensures at least one active generation is built from live DB documents."""
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def test_basic_search_envelope_and_headers(client: TestClient, db_session: Session):
    """
    Contract Requirement 1 & 3:
    Validates GET /api/v1/search response envelope, headers, snippet highlighting,
    and search event persistence in interaction_logs.
    """
    res = client.get("/api/v1/search?q=neural+networks&page=1&page_size=10&mode=bm25")
    assert res.status_code == 200, f"Search failed: {res.text}"

    data = res.json()

    # 1. Response Envelope
    assert "items" in data
    assert "page" in data and data["page"] == 1
    assert "page_size" in data and data["page_size"] == 10
    assert "search_context_token" in data and len(data["search_context_token"]) == 36
    assert "expires_at" in data
    assert "snapshot_total" in data
    assert "snapshot_candidate_count" in data
    assert "is_approximate_total" in data and data["is_approximate_total"] is False
    assert "has_more" in data
    assert data["query"] == "neural networks"
    assert data["mode"] == "bm25"
    assert data["engine_requested"] == "bm25"
    assert data["engine_used"] in ("bm25", "fallback_bm25", "ilike_fallback")
    assert isinstance(data["latency_ms"], (int, float))
    assert data["latency_ms"] >= 0.0

    # 2. Response Headers
    assert "X-Search-Event-Id" in res.headers
    assert res.headers["X-Search-Event-Id"] == data["search_event_id"]
    assert "X-Index-Generation" in res.headers

    # 3. Items format
    items = data["items"]
    assert len(items) <= 10
    if items:
        first = items[0]
        assert "id" in first and len(first["id"]) == 36
        assert "title" in first and first["title"]
        assert "summary" in first
        assert "snippet" in first
        assert "score" in first and isinstance(first["score"], (int, float))
        assert "rank" in first and first["rank"] == 1
        assert "author" in first
        assert "created_at" in first
        assert "views_count" in first
        assert "likes_count" in first

        # Check snippet highlighting (em tag)
        snippet = first["snippet"]
        assert "<em>" in snippet or "&lt;" in snippet or len(snippet) > 0

    # 4. Search Event Database Persistence
    event = db_session.query(InteractionLog).filter(InteractionLog.id == data["search_event_id"]).first()
    assert event is not None
    assert event.event_type == "search"
    assert event.query_string == "neural networks"
    assert event.result_doc_ids == [item["id"] for item in items]
    assert event.clicked_doc_id is None
    assert event.search_event_id is None


def test_empty_query_validation(client: TestClient):
    """Contract: Whitespace-only or empty query returns 422 EMPTY_QUERY."""
    res1 = client.get("/api/v1/search?q=")
    assert res1.status_code == 422
    assert "EMPTY_QUERY" in res1.text

    res2 = client.get("/api/v1/search?q=%20%20%20")
    assert res2.status_code == 422
    assert "EMPTY_QUERY" in res2.text


def test_query_too_long_validation(client: TestClient):
    """Contract: Query > 200 characters returns 422 QUERY_TOO_LONG."""
    long_q = "neural " * 35  # > 200 characters
    res = client.get(f"/api/v1/search?q={long_q}")
    assert res.status_code == 422
    assert "QUERY_TOO_LONG" in res.text


def test_invalid_mode_validation(client: TestClient):
    """Contract: Invalid mode returns 422 INVALID_MODE."""
    res = client.get("/api/v1/search?q=neural&mode=quantum_mode")
    assert res.status_code == 422
    assert "INVALID_MODE" in res.text


def test_no_results_search(client: TestClient):
    """Contract: Terms with zero matches return 200 OK with empty items and snapshot_total=0."""
    res = client.get("/api/v1/search?q=xyztermnotexist987654321")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["snapshot_total"] == 0
    assert data["has_more"] is False
