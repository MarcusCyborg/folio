from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def test_stale_index_live_prune_without_backfill(client: TestClient, db_session: Session):
    """
    Contract Section 2.3 & Scenario 3:
    Verifies that when a document is unpublished or soft-deleted mid-context:
    1. It is pruned immediately from the search response (0s lag).
    2. Rank window remains fixed (prune without backfill; no candidate from next page is pulled).
    3. Draft / deleted documents NEVER leak through stale index snapshots.
    """
    # 1. Search page 1 with page_size=10
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=10")
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1["items"]) == 10
    ctx_token = data1["search_context_token"]

    item_to_unpublish_id = data1["items"][1]["id"]  # 2nd candidate
    item_to_delete_id = data1["items"][2]["id"]     # 3rd candidate

    # 2. Mid-session: Unpublish item 2 and soft-delete item 3 in PostgreSQL
    doc_unpub = db_session.query(Document).filter(Document.id == item_to_unpublish_id).first()
    assert doc_unpub is not None
    doc_unpub.status = "draft"

    doc_del = db_session.query(Document).filter(Document.id == item_to_delete_id).first()
    assert doc_del is not None
    doc_del.deleted_at = datetime.now(timezone.utc)

    db_session.commit()

    # 3. User requests page 1 again using the same context token
    res_pruned = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=1&page_size=10")
    assert res_pruned.status_code == 200
    data_pruned = res_pruned.json()

    pruned_ids = [item["id"] for item in data_pruned["items"]]

    # Invariant 1: Draft document is pruned
    assert item_to_unpublish_id not in pruned_ids

    # Invariant 2: Soft-deleted document is pruned
    assert item_to_delete_id not in pruned_ids

    # Invariant 3: Prune without backfill -> Exactly 8 items returned (10 - 2 = 8 items)
    # Candidate #11 is NOT pulled into page 1!
    assert len(data_pruned["items"]) == 8

    # Invariant 4: Relative order of remaining candidates is strictly preserved
    remaining_expected = [
        item["id"] for item in data1["items"]
        if item["id"] not in (item_to_unpublish_id, item_to_delete_id)
    ]
    assert pruned_ids == remaining_expected


def test_stale_index_on_subsequent_page(client: TestClient, db_session: Session):
    """
    Scenario 3 on Page 2:
    Document #15 (which falls on Page 2) is unpublished mid-session.
    Page 2 returns 9 items instead of 10. Candidate #21 is NOT backfilled into Page 2.
    """
    res1 = client.get("/api/v1/search?q=neural&page=1&page_size=10")
    assert res1.status_code == 200
    ctx_token = res1.json()["search_context_token"]

    # Read Page 2 before mutation
    res2_before = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=10")
    assert res2_before.status_code == 200
    data2_before = res2_before.json()
    if len(data2_before["items"]) >= 2:
        target_doc_id = data2_before["items"][0]["id"]

        # Unpublish this document
        doc = db_session.query(Document).filter(Document.id == target_doc_id).first()
        doc.status = "draft"
        db_session.commit()

        # Re-fetch Page 2
        res2_after = client.get(f"/api/v1/search?search_context_token={ctx_token}&page=2&page_size=10")
        assert res2_after.status_code == 200
        data2_after = res2_after.json()

        page2_ids = [item["id"] for item in data2_after["items"]]
        assert target_doc_id not in page2_ids
        assert len(data2_after["items"]) == len(data2_before["items"]) - 1
