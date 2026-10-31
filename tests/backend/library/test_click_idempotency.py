import uuid
import threading
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TestingSessionLocal
from src.backend.main import app
from src.backend.models.document import Document
from src.backend.models.event import InteractionLog
from src.backend.services.library.events_service import record_click
from src.backend.core.exceptions import AppException


def test_concurrent_click_logging_same_key():
    """
    Test concurrent click logging with same (actor_key, request_key) and same payload:
    - Both threads return the exact same click ID.
    - Creates only 1 row in DB.
    """
    db = TestingSessionLocal()
    try:
        doc = db.query(Document).filter(Document.status == "published", Document.deleted_at.is_(None)).first()
        assert doc is not None, "Need at least one published document for test"
        actor_key = f"concurrent-actor-{uuid.uuid4().hex}"
        
        # Create a search event owned by actor_key with doc.id in result_doc_ids
        search_event = InteractionLog(
            event_type="search",
            query_string="concurrent test search",
            actor_key=actor_key,
            result_doc_ids=[doc.id],
        )
        db.add(search_event)
        db.commit()
        s_id = search_event.id
        req_key = f"concurrent-req-{uuid.uuid4().hex}"
    finally:
        db.close()

    results = []
    errors = []

    def click_worker():
        thread_db = TestingSessionLocal()
        try:
            cid = record_click(
                db=thread_db,
                search_event_id=s_id,
                document_id=doc.id,
                request_key=req_key,
                actor_key=actor_key,
            )
            results.append(cid)
        except Exception as e:
            errors.append(e)
        finally:
            thread_db.close()

    t1 = threading.Thread(target=click_worker)
    t2 = threading.Thread(target=click_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both must succeed without error
    assert len(errors) == 0, f"Encountered unexpected errors during concurrent clicks: {errors}"
    assert len(results) == 2
    assert results[0] == results[1], "Both concurrent requests must return the identical click ID"

    # Verify database contains exactly 1 row
    verify_db = TestingSessionLocal()
    try:
        count = verify_db.query(InteractionLog).filter(
            InteractionLog.actor_key == actor_key,
            InteractionLog.request_key == req_key,
        ).count()
        assert count == 1, f"Expected exactly 1 DB row for idempotency key, found {count}"

        # Clean up test rows
        verify_db.query(InteractionLog).filter(InteractionLog.request_key == req_key).delete()
        verify_db.query(InteractionLog).filter(InteractionLog.id == s_id).delete()
        verify_db.commit()
    finally:
        verify_db.close()


def test_click_logging_retry_payload_mismatch(client, db_session):
    """
    Test click logging retry with same request_key but different document_id:
    Returns HTTP 409 REQUEST_KEY_PAYLOAD_MISMATCH.
    """
    docs = db_session.query(Document).filter(Document.status == "published", Document.deleted_at.is_(None)).limit(2).all()
    assert len(docs) >= 2, "Need at least 2 published documents for test"
    doc1, doc2 = docs[0], docs[1]

    # 1. Search to get search_event_id containing both docs
    res_search = client.get("/api/v1/documents?q=intelligence&page=1&page_size=10")
    assert res_search.status_code == 200
    search_data = res_search.json()
    search_event_id = search_data["search_event_id"]
    assert search_event_id is not None

    # Update search_event in DB session to contain both doc1 and doc2 in results
    se = db_session.query(InteractionLog).filter(InteractionLog.id == search_event_id).first()
    assert se is not None
    se.result_doc_ids = [doc1.id, doc2.id]
    db_session.commit()

    # Get CSRF token
    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]

    req_key = f"retry-mismatch-{uuid.uuid4().hex}"

    # 2. First click on doc1 -> succeeds (201)
    res_click1 = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": doc1.id,
            "request_key": req_key,
        },
    )
    assert res_click1.status_code == 201
    click_id1 = res_click1.json()["id"]

    # 3. Retry with same request_key and same doc1 -> returns same click ID (idempotent)
    res_click_retry = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": doc1.id,
            "request_key": req_key,
        },
    )
    assert res_click_retry.status_code == 201
    assert res_click_retry.json()["id"] == click_id1

    # 4. Retry with same request_key but different document_id (doc2) -> 409 Conflict
    res_mismatch = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": doc2.id,
            "request_key": req_key,
        },
    )
    assert res_mismatch.status_code == 409
    err = res_mismatch.json()["error"]
    assert err["code"] == "REQUEST_KEY_PAYLOAD_MISMATCH"
    assert "Same request key cannot be reused" in err["message"]


def test_click_logging_retry_different_actor(client, db_session):
    """
    Test click logging retry with different actor:
    Returns HTTP 403 ACTOR_MISMATCH.
    """
    doc = db_session.query(Document).filter(Document.status == "published", Document.deleted_at.is_(None)).first()
    assert doc is not None

    # Actor 1 searches
    res_search = client.get("/api/v1/documents?q=intelligence&page=1&page_size=5")
    assert res_search.status_code == 200
    search_event_id = res_search.json()["search_event_id"]
    assert search_event_id is not None

    req_key = f"actor-mismatch-{uuid.uuid4().hex}"

    # Actor 2 creates their own independent session
    with TestClient(app, base_url="http://testserver") as client2:
        sess2 = client2.get("/api/v1/auth/session")
        csrf2 = sess2.json()["csrf_token"]

        # Actor 2 tries to log click referencing Actor 1's search_event_id
        res_mismatch = client2.post(
            "/api/v1/events/clicks",
            headers={"X-CSRF-Token": csrf2},
            json={
                "search_event_id": search_event_id,
                "document_id": doc.id,
                "request_key": req_key,
            },
        )
        assert res_mismatch.status_code == 403
        err = res_mismatch.json()["error"]
        assert err["code"] == "ACTOR_MISMATCH"
        assert "Search event does not belong to this session" in err["message"]
