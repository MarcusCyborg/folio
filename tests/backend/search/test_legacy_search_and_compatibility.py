from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.core.rate_limit import rate_limiter, RateLimitResult


def test_legacy_search_endpoint_disabled_by_default(client: TestClient):
    """
    Contract Section 7:
    Legacy /search endpoint is kept behind ENABLE_LEGACY_SEARCH toggle.
    When ENABLE_LEGACY_SEARCH=false, returns HTTP 503 LEGACY_SEARCH_DISABLED.
    """
    res = client.get("/search?q=neural")
    assert res.status_code == 503
    assert "LEGACY_SEARCH_DISABLED" in res.text


def test_browse_documents_backward_compatibility(client: TestClient):
    """
    Contract Section 7:
    Browse API GET /api/v1/documents remains 100% backward compatible
    with sorting, pagination, and filters.
    """
    res = client.get("/api/v1/documents?page=1&page_size=10&sort=newest")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "page" in data and data["page"] == 1
    assert "page_size" in data and data["page_size"] == 10
    assert "total" in data
    assert "total_pages" in data


def test_search_rate_limiting_abuse_protection(client: TestClient):
    """
    Requirement 6:
    Rate limiting protects /api/v1/search from abuse.
    Returns HTTP 429 with Retry-After header when threshold exceeded.
    """
    with patch.object(
        rate_limiter,
        "check_and_record_search_attempt",
        return_value=RateLimitResult(allowed=False, retry_after=30, current_count=61, limit=60),
    ):
        res = client.get("/api/v1/search?q=neural")
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        assert res.headers["Retry-After"] == "30"
        assert "TOO_MANY_REQUESTS" in res.text
