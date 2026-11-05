import uuid
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TestingSessionLocal
from src.backend.main import app
from src.backend.models.document import Document
from src.backend.models.event import InteractionLog, ViewEvent
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def get_csrf_token(client: TestClient) -> str:
    res = client.get("/api/v1/auth/session")
    return res.json()["csrf_token"]


def test_click_membership_verification(client: TestClient, db_session: Session):
    """
    Contract Section 5:
    1. Search returns Document A and Document B.
    2. Click on Document A succeeds (201 Created).
    3. Click on Document C (not in search results) is rejected with 422 DOC_NOT_IN_SEARCH_RESULTS.
    """
    res = client.get("/api/v1/search?q=neural&page=1&page_size=5")
    assert res.status_code == 200
    search_data = res.json()
    search_event_id = search_data["search_event_id"]
    returned_items = search_data["items"]
    assert len(returned_items) >= 2

    valid_doc_id = returned_items[0]["id"]

    # Find a document that was NOT returned in this search
    returned_set = {item["id"] for item in returned_items}
    excluded_doc = (
        db_session.query(Document)
        .filter(
            Document.status == "published",
            Document.deleted_at.is_(None),
            ~Document.id.in_(returned_set),
        )
        .first()
    )
    assert excluded_doc is not None

    csrf = get_csrf_token(client)
    headers = {"X-CSRF-Token": csrf}

    # 1. Click on member document -> 201 Created
    req_key1 = f"click-req-{uuid.uuid4().hex}"
    click_res1 = client.post(
        "/api/v1/events/clicks",
        headers=headers,
        json={
            "search_event_id": search_event_id,
            "document_id": valid_doc_id,
            "request_key": req_key1,
        },
    )
    assert click_res1.status_code == 201
    assert "id" in click_res1.json()

    # 2. Click on non-member document -> 422 DOC_NOT_IN_SEARCH_RESULTS
    req_key2 = f"click-req-{uuid.uuid4().hex}"
    click_res2 = client.post(
        "/api/v1/events/clicks",
        headers=headers,
        json={
            "search_event_id": search_event_id,
            "document_id": excluded_doc.id,
            "request_key": req_key2,
        },
    )
    assert click_res2.status_code == 422
    assert "DOC_NOT_IN_SEARCH_RESULTS" in click_res2.text


def test_click_actor_session_mismatch(client: TestClient):
    """
    Contract Section 5:
    Session actor must match parent search event's actor_key.
    Cross-actor click returns HTTP 403 ACTOR_MISMATCH.
    """
    res = client.get("/api/v1/search?q=neural&page=1&page_size=5")
    assert res.status_code == 200
    search_data = res.json()
    search_event_id = search_data["search_event_id"]
    valid_doc_id = search_data["items"][0]["id"]

    # Client 2 (independent session/cookie/actor) attempts to click
    with TestClient(app, base_url="http://testserver") as client2:
        csrf2 = get_csrf_token(client2)
        req_key = f"req-{uuid.uuid4().hex}"
        click_res = client2.post(
            "/api/v1/events/clicks",
            headers={"X-CSRF-Token": csrf2},
            json={
                "search_event_id": search_event_id,
                "document_id": valid_doc_id,
                "request_key": req_key,
            },
        )
        assert click_res.status_code == 403
        assert "ACTOR_MISMATCH" in click_res.text


def test_click_on_unpublished_document(client: TestClient, db_session: Session):
    """Contract Section 5: Clicked document must currently be published and not deleted."""
    res = client.get("/api/v1/search?q=neural&page=1&page_size=5")
    assert res.status_code == 200
    search_data = res.json()
    search_event_id = search_data["search_event_id"]
    target_doc_id = search_data["items"][0]["id"]

    # Mid-session unpublication
    doc = db_session.query(Document).filter(Document.id == target_doc_id).first()
    doc.status = "draft"
    db_session.commit()

    csrf = get_csrf_token(client)
    req_key = f"req-{uuid.uuid4().hex}"
    click_res = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": target_doc_id,
            "request_key": req_key,
        },
    )
    assert click_res.status_code == 404
    assert "DOCUMENT_NOT_FOUND" in click_res.text


def test_click_request_key_idempotency_and_payload_mismatch(client: TestClient):
    """
    Contract Section 5:
    - Same request_key + same document_id -> returns existing click ID (idempotent).
    - Same request_key + different document_id -> returns 409 REQUEST_KEY_PAYLOAD_MISMATCH.
    """
    res = client.get("/api/v1/search?q=neural&page=1&page_size=5")
    assert res.status_code == 200
    search_data = res.json()
    search_event_id = search_data["search_event_id"]
    doc1 = search_data["items"][0]["id"]
    doc2 = search_data["items"][1]["id"]

    csrf = get_csrf_token(client)
    headers = {"X-CSRF-Token": csrf}
    req_key = f"idemp-key-{uuid.uuid4().hex}"

    # First request -> 201 Created
    c1 = client.post(
        "/api/v1/events/clicks",
        headers=headers,
        json={
            "search_event_id": search_event_id,
            "document_id": doc1,
            "request_key": req_key,
        },
    )
    assert c1.status_code == 201
    click_id = c1.json()["id"]

    # Repeated request with same key & same payload -> returns same click_id
    c2 = client.post(
        "/api/v1/events/clicks",
        headers=headers,
        json={
            "search_event_id": search_event_id,
            "document_id": doc1,
            "request_key": req_key,
        },
    )
    assert c2.status_code in (200, 201)
    assert c2.json()["id"] == click_id

    # Repeated request with same key but DIFFERENT document_id -> 409 REQUEST_KEY_PAYLOAD_MISMATCH
    c3 = client.post(
        "/api/v1/events/clicks",
        headers=headers,
        json={
            "search_event_id": search_event_id,
            "document_id": doc2,
            "request_key": req_key,
        },
    )
    assert c3.status_code == 409
    assert "REQUEST_KEY_PAYLOAD_MISMATCH" in c3.text


def test_concurrent_duplicate_click_handling():
    """
    Contract Section 5 & Requirement 7:
    Concurrent click requests with identical (actor_key, request_key)
    resolve idempotently with 0 race condition errors and exactly 1 DB row.
    """
    from src.backend.services.library.events_service import record_click

    db = TestingSessionLocal()
    try:
        doc = db.query(Document).filter(Document.status == "published", Document.deleted_at.is_(None)).first()
        actor = f"actor-{uuid.uuid4().hex}"
        s_event = InteractionLog(
            event_type="search",
            query_string="concurrent test",
            actor_key=actor,
            result_doc_ids=[doc.id],
        )
        db.add(s_event)
        db.commit()
        s_id = s_event.id
        req_key = f"conc-key-{uuid.uuid4().hex}"
    finally:
        db.close()

    results = []
    errors = []

    def click_thread():
        thread_db = TestingSessionLocal()
        try:
            cid = record_click(
                db=thread_db,
                search_event_id=s_id,
                document_id=doc.id,
                request_key=req_key,
                actor_key=actor,
            )
            results.append(cid)
        except Exception as e:
            errors.append(e)
        finally:
            thread_db.close()

    t1 = threading.Thread(target=click_thread)
    t2 = threading.Thread(target=click_thread)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
    assert len(results) == 2
    assert results[0] == results[1]

    verify_db = TestingSessionLocal()
    try:
        count = verify_db.query(InteractionLog).filter(
            InteractionLog.actor_key == actor,
            InteractionLog.request_key == req_key,
        ).count()
        assert count == 1

        # Cleanup
        verify_db.query(InteractionLog).filter(InteractionLog.request_key == req_key).delete()
        verify_db.query(InteractionLog).filter(InteractionLog.id == s_id).delete()
        verify_db.commit()
    finally:
        verify_db.close()


def test_detail_refresh_does_not_log_click(client: TestClient, db_session: Session):
    """
    Contract Requirement 3:
    Navigating to or refreshing document detail (/api/v1/documents/{id})
    and recording document view (/api/v1/documents/{id}/views) MUST NEVER
    create click interaction logs.
    """
    doc = db_session.query(Document).filter(Document.status == "published", Document.deleted_at.is_(None)).first()
    assert doc is not None

    clicks_before = db_session.query(InteractionLog).filter(InteractionLog.event_type == "click").count()

    # 1. Fetch document detail
    res_detail = client.get(f"/api/v1/documents/{doc.id}")
    assert res_detail.status_code == 200

    # 2. Record document view
    csrf = get_csrf_token(client)
    nav_id = str(uuid.uuid4())
    res_view = client.post(
        f"/api/v1/documents/{doc.id}/views",
        headers={"X-CSRF-Token": csrf},
        json={"navigation_id": nav_id},
    )
    assert res_view.status_code == 200

    # 3. Refresh detail again
    res_detail2 = client.get(f"/api/v1/documents/{doc.id}")
    assert res_detail2.status_code == 200

    # Verify no click was created!
    clicks_after = db_session.query(InteractionLog).filter(InteractionLog.event_type == "click").count()
    assert clicks_after == clicks_before
