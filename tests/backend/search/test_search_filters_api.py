import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def test_category_filter_exact_match(client: TestClient, db_session: Session):
    """Contract Section 2.4: category_id filters documents by category."""
    cat = db_session.query(Category).first()
    assert cat is not None

    res = client.get(f"/api/v1/search?q=a&category_id={cat.id}&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["category"] is not None
        assert item["category"]["id"] == cat.id


def test_category_filter_unknown_valid_uuid(client: TestClient):
    """Contract Section 2.4: Valid UUID not present in categories returns empty items with 200 OK."""
    random_uuid = str(uuid.uuid4())
    res = client.get(f"/api/v1/search?q=neural&category_id={random_uuid}&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["snapshot_total"] == 0
    assert data["has_more"] is False


def test_category_filter_malformed_uuid(client: TestClient):
    """Contract Section 2.4: Malformed string (not UUID) returns 422."""
    res = client.get("/api/v1/search?q=neural&category_id=not-a-valid-uuid")
    assert res.status_code == 422
    assert "INVALID_CATEGORY_ID" in res.text


def test_tag_filter_strict_and_semantics(client: TestClient, db_session: Session):
    """Contract Section 2.4: tag_ids applies strict AND semantics."""
    tags = db_session.query(Tag).limit(2).all()
    assert len(tags) >= 2
    t1, t2 = tags[0], tags[1]

    # Search with both tags
    tag_param = f"{t1.id},{t2.id}"
    res = client.get(f"/api/v1/search?q=a&tag_ids={tag_param}&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()

    for item in data["items"]:
        item_tag_ids = {t["id"] for t in item["tags"]}
        assert t1.id in item_tag_ids
        assert t2.id in item_tag_ids


def test_tag_filter_unknown_valid_uuid(client: TestClient):
    """Contract Section 2.4: Unknown valid tag UUID returns empty items with 200 OK."""
    random_uuid = str(uuid.uuid4())
    res = client.get(f"/api/v1/search?q=neural&tag_ids={random_uuid}&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["snapshot_total"] == 0


def test_tag_filter_malformed_uuid(client: TestClient):
    """Contract Section 2.4: Malformed tag UUID returns 422."""
    res = client.get("/api/v1/search?q=neural&tag_ids=invalid-tag-123")
    assert res.status_code == 422
    assert "INVALID_TAG_ID" in res.text


def test_date_range_filters(client: TestClient, db_session: Session):
    """Contract Section 2.4: date_from and date_to filter against created_at."""
    docs = db_session.query(Document).filter(Document.status == "published").all()
    assert docs
    dates = [d.created_at.date() for d in docs]
    min_date = min(dates)
    max_date = max(dates)

    # Valid range
    res = client.get(f"/api/v1/search?q=a&date_from={min_date.isoformat()}&date_to={max_date.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data

    # Invalid range: date_from > date_to returns 422 INVALID_DATE_RANGE
    inv_res = client.get(f"/api/v1/search?q=a&date_from={max_date.isoformat()}&date_to={min_date.isoformat()}")
    if min_date < max_date:
        assert inv_res.status_code == 422
        assert "INVALID_DATE_RANGE" in inv_res.text
