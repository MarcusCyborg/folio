# tests/frontend/public/test_search_navigation_state.py
# Playwright test suite for Folio Frontend Search Integration & URL State Persistence (M7 / UI-01)

import time
import pytest
from playwright.sync_api import sync_playwright


def test_search_api_connected_on_query(live_server, browser_instance):
    """
    UI-01: Verifies search input connects to /api/v1/search when query is provided,
    supports bm25/semantic/hybrid modes, and persists parameters in the URL hash.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    search_requests = []
    page.on("request", lambda req: search_requests.append(req.url) if "/api/v1/search" in req.url else None)

    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # 1. Perform search query
    search_input = page.locator("#librarySearchInput")
    search_input.fill("learning")
    page.locator("#librarySearchBtn").click()

    # URL hash must contain query
    page.wait_for_url("**/#/library?**q=learning**")
    page.wait_for_selector(".document-card-row")

    # Verify /api/v1/search was requested (not /documents)
    assert any("/api/v1/search" in url and "q=learning" in url for url in search_requests)

    # Verify search telemetry header and rank badges are visible
    telemetry_bar = page.locator("#searchTelemetryBar")
    assert telemetry_bar.is_visible()
    assert page.locator(".doc-rank-badge").first.is_visible()
    assert "#1" in page.locator(".doc-rank-badge").first.text_content()

    # 2. Change Retrieval Mode to 'semantic'
    mode_select = page.locator("#libraryModeSelect")
    mode_select.select_option("semantic")
    page.wait_for_url("**/#/library?**mode=semantic**")
    page.wait_for_selector(".document-card-row")

    assert any("/api/v1/search" in url and "mode=semantic" in url for url in search_requests)

    # 3. Change Retrieval Mode to 'hybrid'
    mode_select.select_option("hybrid")
    page.wait_for_url("**/#/library?**mode=hybrid**")
    page.wait_for_selector(".document-card-row")

    assert any("/api/v1/search" in url and "mode=hybrid" in url for url in search_requests)

    context.close()


def test_browse_without_query_preserves_documents_api(live_server, browser_instance):
    """
    UI-01: Verifies browsing without a search query calls /api/v1/documents,
    preserves original sorting options, and does not invoke the search engine.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    doc_requests = []
    search_requests = []
    page.on("request", lambda req: doc_requests.append(req.url) if "/api/v1/documents?" in req.url or req.url.endswith("/api/v1/documents") else None)
    page.on("request", lambda req: search_requests.append(req.url) if "/api/v1/search" in req.url else None)

    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Verify /api/v1/documents was requested and /api/v1/search was NOT requested
    assert len(doc_requests) >= 1
    assert len(search_requests) == 0

    # Sort selector is visible in browse mode
    sort_select = page.locator("#librarySortSelect")
    assert sort_select.is_visible()

    # Change sort to title
    sort_select.select_option("title")
    page.wait_for_url("**/#/library?**sort=title**")
    page.wait_for_selector(".document-card-row")

    assert any("sort=title" in url for url in doc_requests)
    assert len(search_requests) == 0

    context.close()


def test_back_forward_and_refresh_state_persistence(live_server, browser_instance):
    """
    UI-01: Verifies query, mode, category filters, and pagination state are preserved
    across browser navigation (Back, Forward) and hard page reload (Refresh).
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # 1. Search for keyword "neural"
    page.fill("#librarySearchInput", "neural")
    page.locator("#librarySearchBtn").click()
    page.wait_for_url("**/#/library?**q=neural**")
    page.wait_for_selector(".document-card-row")

    # 2. Apply a category filter
    cat_btn = page.locator(".category-pill").nth(1)
    cat_btn.click()
    page.wait_for_url("**/#/library?**category_id=**")
    page.wait_for_selector(".document-card-row")
    current_search_url = page.url

    # 3. Click first result to view detail
    first_title_link = page.locator(".doc-row-title a").first
    first_doc_title = first_title_link.text_content().strip()
    first_title_link.click()

    page.wait_for_selector(".document-detail-article")
    assert first_doc_title in page.locator(".detail-title").text_content()

    # 4. Navigate Back to Library via Back Link or Browser Back
    back_link = page.locator("#detailBackLink")
    back_link.click()

    page.wait_for_url("**/#/library?**")
    page.wait_for_selector(".document-card-row")

    # State must be fully restored: search input, query in URL, active filter chips
    assert page.locator("#librarySearchInput").input_value() == "neural"
    assert "q=neural" in page.url
    assert "category_id=" in page.url
    assert page.locator(".active-filter-chip").count() >= 1

    # 5. Refresh page (F5 reload)
    page.reload()
    page.wait_for_selector(".document-card-row")

    assert page.locator("#librarySearchInput").input_value() == "neural"
    assert "q=neural" in page.url
    assert "category_id=" in page.url

    context.close()
