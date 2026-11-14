import uuid
from datetime import datetime, timezone, timedelta, date
import pytest
from src.backend.models.document import Document
from src.backend.models.event import InteractionLog, ViewEvent

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_analytics_exact_calculations_and_zero_fill(client, db_session):
    csrf_seo = auth_login(client, "admin@folio.test")

    # Define test dates in UTC
    target_date1 = date(2026, 10, 10)
    target_date2 = date(2026, 10, 12)
    start_date = date(2026, 10, 9)
    end_date = date(2026, 10, 15)

    doc1 = db_session.query(Document).filter(Document.status == "published").first()
    doc2 = db_session.query(Document).filter(Document.status == "published", Document.id != doc1.id).first()

    # Seed 3 search events on target_date1 (2 for "machine learning", 1 for "quantum")
    t1 = datetime.combine(target_date1, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
    search1 = InteractionLog(
        event_type="search",
        query_string="machine learning",
        timestamp=t1,
        actor_key="actor_1",
        result_doc_ids=[doc1.id]
    )
    search2 = InteractionLog(
        event_type="search",
        query_string="machine learning",
        timestamp=t1 + timedelta(minutes=5),
        actor_key="actor_2",
        result_doc_ids=[doc1.id]
    )
    search3 = InteractionLog(
        event_type="search",
        query_string="quantum computing",
        timestamp=t1 + timedelta(minutes=10),
        actor_key="actor_3",
        result_doc_ids=[doc2.id]
    )
    db_session.add_all([search1, search2, search3])

    # Seed 2 click events (1 on target_date1, 1 on target_date2)
    click1 = InteractionLog(
        event_type="click",
        query_string="machine learning",
        clicked_doc_id=doc1.id,
        timestamp=t1 + timedelta(minutes=6),
        actor_key="actor_2"
    )
    t2 = datetime.combine(target_date2, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14)
    click2 = InteractionLog(
        event_type="click",
        query_string="quantum computing",
        clicked_doc_id=doc2.id,
        timestamp=t2,
        actor_key="actor_3"
    )
    db_session.add_all([click1, click2])

    # Seed 4 view events (2 on target_date1 for doc1, 2 on target_date2 for doc2)
    view1 = ViewEvent(document_id=doc1.id, actor_key="actor_1", navigation_id=str(uuid.uuid4()), timestamp=t1)
    view2 = ViewEvent(document_id=doc1.id, actor_key="actor_2", navigation_id=str(uuid.uuid4()), timestamp=t1 + timedelta(minutes=7))
    view3 = ViewEvent(document_id=doc2.id, actor_key="actor_3", navigation_id=str(uuid.uuid4()), timestamp=t2)
    view4 = ViewEvent(document_id=doc2.id, actor_key="actor_4", navigation_id=str(uuid.uuid4()), timestamp=t2 + timedelta(minutes=1))
    db_session.add_all([view1, view2, view3, view4])
    db_session.commit()

    # Query analytics overview for period [2026-10-09 to 2026-10-15]
    res = client.get(f"/api/v1/admin/analytics/overview?date_from={start_date.isoformat()}&date_to={end_date.isoformat()}")
    assert res.status_code == 200
    data = res.json()

    # 1. Period verification
    assert data["period"]["date_from"] == "2026-10-09"
    assert data["period"]["date_to"] == "2026-10-15"
    assert data["period"]["timezone"] == "UTC"

    # 2. Totals verification
    totals = data["totals"]
    assert totals["search_requests"] == 3
    assert totals["result_clicks"] == 2
    assert totals["document_views"] == 4
    assert totals["published_documents"] >= 100

    # 3. Daily zero-filling and totals consistency
    daily = data["daily"]
    # 7 days from Oct 9 to Oct 15 inclusive = 7 days
    assert len(daily) == 7

    # Dates without events (e.g., Oct 9, Oct 11, Oct 13, Oct 14, Oct 15) must have 0 counts
    zero_day = next(d for d in daily if d["date"] == "2026-10-09")
    assert zero_day["search_requests"] == 0
    assert zero_day["result_clicks"] == 0
    assert zero_day["document_views"] == 0

    # Day 1 (Oct 10): 3 searches, 1 click, 2 views
    day_oct10 = next(d for d in daily if d["date"] == "2026-10-10")
    assert day_oct10["search_requests"] == 3
    assert day_oct10["result_clicks"] == 1
    assert day_oct10["document_views"] == 2

    # Day 2 (Oct 12): 0 searches, 1 click, 2 views
    day_oct12 = next(d for d in daily if d["date"] == "2026-10-12")
    assert day_oct12["search_requests"] == 0
    assert day_oct12["result_clicks"] == 1
    assert day_oct12["document_views"] == 2

    # Verify daily sums strictly match totals
    sum_searches = sum(d["search_requests"] for d in daily)
    sum_clicks = sum(d["result_clicks"] for d in daily)
    sum_views = sum(d["document_views"] for d in daily)
    assert sum_searches == totals["search_requests"]
    assert sum_clicks == totals["result_clicks"]
    assert sum_views == totals["document_views"]

    # 4. Top Queries verification
    top_queries = data["top_queries"]
    assert len(top_queries) >= 2
    assert top_queries[0]["query_string"] == "machine learning"
    assert top_queries[0]["search_requests"] == 2
    assert top_queries[0]["result_clicks"] == 1
    assert top_queries[1]["query_string"] == "quantum computing"
    assert top_queries[1]["search_requests"] == 1
    assert top_queries[1]["result_clicks"] == 1

    # 5. Top Documents verification
    top_docs = data["top_documents"]
    assert len(top_docs) >= 2
    top_doc_ids = [td["id"] for td in top_docs]
    assert doc1.id in top_doc_ids
    assert doc2.id in top_doc_ids

def test_analytics_edge_cases_and_error_handling(client):
    auth_login(client, "admin@folio.test")

    # 1. Inverted date range (date_from > date_to) -> 422
    res_inv = client.get("/api/v1/admin/analytics/overview?date_from=2026-10-20&date_to=2026-10-10")
    assert res_inv.status_code == 422
    assert res_inv.json()["error"]["code"] == "INVALID_DATE_RANGE"

    # 2. Date range > 366 days -> 422
    res_large = client.get("/api/v1/admin/analytics/overview?date_from=2024-01-01&date_to=2025-06-01")
    assert res_large.status_code == 422
    assert res_large.json()["error"]["code"] == "DATE_RANGE_TOO_LARGE"

    # 3. Period with zero events -> returns 200 with 0 totals and zero-filled daily
    res_zero = client.get("/api/v1/admin/analytics/overview?date_from=2020-01-01&date_to=2020-01-05")
    assert res_zero.status_code == 200
    data_zero = res_zero.json()
    assert data_zero["totals"]["search_requests"] == 0
    assert data_zero["totals"]["result_clicks"] == 0
    assert data_zero["totals"]["document_views"] == 0
    assert len(data_zero["daily"]) == 5
    assert all(d["search_requests"] == 0 for d in data_zero["daily"])
    assert data_zero["top_queries"] == []
    assert data_zero["top_documents"] == []
