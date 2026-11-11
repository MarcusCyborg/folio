from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.main import app
from src.backend.models.search_index import SearchContext
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def test_multi_page_navigation_with_context(client: TestClient):
    """
    Contract Requirement 2 & Scenario 1:
    Page 1 returns items with rank 1..10 and search_context_token.
    Page 2 with search_context_token returns items with consecutive rank 11..20.
    """
    # 1. Page 1
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=10")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["page"] == 1
    assert len(data1["items"]) == 10
    ctx_token = data1["search_context_token"]
    assert ctx_token

    first_page_ids = [item["id"] for item in data1["items"]]
    assert data1["items"][0]["rank"] == 1
    assert data1["items"][9]["rank"] == 10

    # 2. Page 2 with context token
    res2 = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=10")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["page"] == 2
    second_page_ids = [item["id"] for item in data2["items"]]

    # Zero overlap between page 1 and page 2
    assert set(first_page_ids).isdisjoint(set(second_page_ids))

    if data2["items"]:
        assert data2["items"][0]["rank"] == 11


def test_missing_context_token_on_subsequent_pages(client: TestClient):
    """Contract: Requesting page >= 2 without search_context_token returns 400 MISSING_SEARCH_CONTEXT_TOKEN."""
    res = client.get("/api/v1/search?q=neural&page=2&page_size=10")
    assert res.status_code == 400
    assert "MISSING_SEARCH_CONTEXT_TOKEN" in res.text


def test_context_parameter_mismatch_rejection(client: TestClient):
    """
    Contract Section 2.3:
    If client passes search_context_token but changes query or mode,
    the server rejects with HTTP 400 CONTEXT_PARAMETER_MISMATCH.
    """
    res1 = client.get("/api/v1/search?q=neural+networks&page=1&page_size=10")
    assert res1.status_code == 200
    ctx_token = res1.json()["search_context_token"]

    # 1. Alter query
    res_alt_q = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&q=quantum+computing")
    assert res_alt_q.status_code == 400
    assert "CONTEXT_PARAMETER_MISMATCH" in res_alt_q.text

    # 2. Alter mode
    res_alt_mode = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&mode=semantic")
    assert res_alt_mode.status_code == 400
    assert "CONTEXT_PARAMETER_MISMATCH" in res_alt_mode.text

    # 3. Alter page_size
    res_alt_ps = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=50")
    assert res_alt_ps.status_code == 400
    assert "CONTEXT_PARAMETER_MISMATCH" in res_alt_ps.text


def test_context_actor_mismatch_rejection(client: TestClient):
    """
    Contract Section 2.3:
    Search context token is actor-bound. Cross-actor access returns 403 CONTEXT_ACTOR_MISMATCH.
    """
    # Client 1 performs search
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=10")
    assert res1.status_code == 200
    ctx_token = res1.json()["search_context_token"]

    # Client 2 (independent session/cookie/actor) attempts to access Client 1's context
    with TestClient(app, base_url="http://testserver") as client2:
        res2 = client2.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=10")
        assert res2.status_code == 403
        assert "CONTEXT_ACTOR_MISMATCH" in res2.text


def test_context_expiration_lifecycle(client: TestClient, db_session: Session):
    """
    Contract Section 2.3 & Scenario 2:
    When a context expires (now > expires_at), subsequent page returns
    HTTP 410 GONE with code SEARCH_CONTEXT_EXPIRED and reissue_search=true.
    """
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=10")
    assert res1.status_code == 200
    ctx_token = res1.json()["search_context_token"]

    # Manually expire the context record in the database
    ctx_row = db_session.query(SearchContext).filter(SearchContext.token == ctx_token).first()
    assert ctx_row is not None
    ctx_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    # Subsequent page attempt returns 410 Gone
    res2 = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=10")
    assert res2.status_code == 410
    err_data = res2.json()
    assert "SEARCH_CONTEXT_EXPIRED" in str(err_data)
    assert "reissue_search" in str(err_data)


def test_page_beyond_available_candidates(client: TestClient):
    """Contract: Requesting a page beyond candidate window returns items: [] and has_more=false."""
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=20")
    assert res1.status_code == 200
    ctx_token = res1.json()["search_context_token"]

    res_beyond = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=999&page_size=20")
    assert res_beyond.status_code == 200
    data = res_beyond.json()
    assert data["items"] == []
    assert data["has_more"] is False


def test_r3_06_ilike_fallback_paginates_past_1000_results_with_filters(client: TestClient, db_session: Session):
    """
    R3-06:
    When SQL ILIKE fallback matches >1000 published documents (e.g., 1001),
    snapshot_total and snapshot_candidate_count both reflect all 1001 matching documents,
    page 10 (100 items) reports has_more=True, page 11 (1 item) returns rank 1001 with has_more=False,
    zero duplicates/gaps occur across all 11 pages, draft/deleted docs stay excluded,
    and fixed-rank live publication pruning still omits newly unpublished items without backfill.
    """
    import uuid
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category, Tag
    from src.backend.models.document import DocumentTag
    from src.backend.search_index.manager import GenerationManager

    cat = db_session.query(Category).first()
    tag = db_session.query(Tag).first()
    assert cat is not None and tag is not None

    marker = f"R3Scale1001_{uuid.uuid4().hex[:8]}"
    base_dt = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    published_rows = []
    published_ids = []
    for i in range(1001):
        doc_id = str(uuid.uuid4())
        published_ids.append(doc_id)
        dt = base_dt - timedelta(seconds=i)
        published_rows.append(
            {
                "id": doc_id,
                "title": f"{marker} Entry {i:04d}",
                "summary": f"Summary for {marker}",
                "content": f"Body text matching {marker}",
                "category_id": cat.id,
                "status": "published",
                "created_at": dt,
                "published_at": dt,
                "views_count": 0,
            }
        )

    # Extra noise rows that match marker text/category/tag but MUST be excluded
    draft_id = str(uuid.uuid4())
    deleted_id = str(uuid.uuid4())
    extra_rows = [
        {
            "id": draft_id,
            "title": f"{marker} Draft Excluded",
            "summary": "draft",
            "content": marker,
            "category_id": cat.id,
            "status": "draft",
            "created_at": base_dt,
            "published_at": None,
            "views_count": 0,
        },
        {
            "id": deleted_id,
            "title": f"{marker} Deleted Excluded",
            "summary": "deleted",
            "content": marker,
            "category_id": cat.id,
            "status": "published",
            "created_at": base_dt,
            "published_at": base_dt,
            "deleted_at": base_dt,
            "views_count": 0,
        },
    ]

    db_session.bulk_insert_mappings(Document, published_rows + extra_rows)
    db_session.bulk_insert_mappings(
        DocumentTag,
        [{"document_id": did, "tag_id": tag.id} for did in published_ids + [draft_id, deleted_id]],
    )
    db_session.commit()

    with patch.object(GenerationManager, "get_active_generation", return_value=None):
        res_p1 = client.get(
            f"/api/v1/search?q={marker}&mode=bm25&page=1&page_size=100&category_id={cat.id}&tag_ids={tag.id}"
        )
        assert res_p1.status_code == 200
        d1 = res_p1.json()
        assert d1["engine_used"] == "ilike_fallback"
        assert d1["snapshot_total"] == 1001
        assert d1["snapshot_candidate_count"] == 1001
        assert d1["has_more"] is True
        assert len(d1["items"]) == 100

        token = d1["search_context_token"]
        seen_ids = [item["id"] for item in d1["items"]]
        last_page_data = None

        for p in range(2, 12):
            res_p = client.get(
                f"/api/v1/search?search_context_token={token}&page={p}&page_size=100"
            )
            assert res_p.status_code == 200
            dp = res_p.json()
            seen_ids.extend(item["id"] for item in dp["items"])
            if p == 10:
                assert len(dp["items"]) == 100
                assert dp["has_more"] is True
            elif p == 11:
                last_page_data = dp

        assert last_page_data is not None
        assert len(last_page_data["items"]) == 1
        assert last_page_data["items"][0]["rank"] == 1001
        assert last_page_data["has_more"] is False
        assert len(seen_ids) == 1001
        assert len(set(seen_ids)) == 1001
        assert set(seen_ids) == set(published_ids)
        assert draft_id not in seen_ids
        assert deleted_id not in seen_ids

        # Live publication guard still omits the 1001st doc on fixed-rank re-fetch
        doc_1001 = db_session.query(Document).filter(Document.id == last_page_data["items"][0]["id"]).first()
        doc_1001.status = "draft"
        db_session.commit()

        res_p11_after = client.get(
            f"/api/v1/search?search_context_token={token}&page=11&page_size=100"
        )
        assert res_p11_after.status_code == 200
        assert res_p11_after.json()["items"] == []
        assert res_p11_after.json()["has_more"] is False
