# tests/frontend/public/test_interaction_click_logging.py
# Playwright test suite for Folio Interaction Click Logging & View Events (M7 / UI-03)

import pytest
from playwright.sync_api import sync_playwright


def test_single_click_event_dispatch_and_no_reload_duplicate(live_server, browser_instance):
    """
    UI-03 & F5 remediation: Verifies that searching and clicking a result link
    dispatches exactly one click event to /api/v1/events/clicks, and reloading the
    detail page records views but NEVER dispatches a duplicate search click event.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    click_requests = []
    view_requests = []

    def log_request(req):
        if "/api/v1/events/clicks" in req.url and req.method == "POST":
            click_requests.append({
                "url": req.url,
                "post_data": req.post_data_json,
            })
        elif "/views" in req.url and req.method == "POST":
            view_requests.append(req.url)

    page.on("request", log_request)

    # 1. Search for a query
    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row")

    assert len(click_requests) == 0

    # 2. Click the first search result link
    first_result_link = page.locator(".doc-row-title a").first
    first_result_link.click()

    page.wait_for_selector(".document-detail-article")

    # Give small window for async click network request to settle
    page.wait_for_timeout(600)

    # Verify exactly 1 click event was dispatched with required payload fields
    assert len(click_requests) == 1
    click_payload = click_requests[0]["post_data"]
    assert "search_event_id" in click_payload
    assert "document_id" in click_payload
    assert "request_key" in click_payload
    assert click_payload["search_event_id"] is not None
    assert click_payload["document_id"] is not None

    # View event was also recorded
    assert len(view_requests) >= 1

    # 3. Reload the document detail page (F5 refresh)
    initial_click_count = len(click_requests)
    initial_view_count = len(view_requests)

    page.reload()
    page.wait_for_selector(".document-detail-article")
    page.wait_for_timeout(600)

    # CRITICAL INVARIANT: Reloading detail view must NOT log another search click!
    assert len(click_requests) == initial_click_count, (
        f"Expected {initial_click_count} click events, but got {len(click_requests)} after reload (F5 finding regression)."
    )

    # New view event is allowed per reload navigation
    assert len(view_requests) > initial_view_count

    # 4. Navigate back to library catalog via back link
    page.locator("#detailBackLink").click()
    page.wait_for_url("**/#/library?**")
    page.wait_for_selector(".document-card-row")
    page.wait_for_timeout(400)

    # Click count remains unchanged after returning to library
    assert len(click_requests) == initial_click_count

    context.close()
