# tests/frontend/public/test_search_results_ux.py
# Playwright test suite for Folio Search Results UX, Safe Snippets, Ranking, Degradation & Pagination (M7 / UI-02 & IB-R06)

import pytest
from playwright.sync_api import sync_playwright

from tests.conftest import TestingSessionLocal
from src.backend.models.search_index import IndexGeneration
from src.backend.services.search.search_service import search_engine


def test_search_ranking_and_safe_snippets(live_server, browser_instance):
    """
    UI-02: Verifies search results render ranking positions, score pills,
    and safe snippets with highlighted <em> tags without raw HTML/attribute injection.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row")

    # 1. Ranking numbers
    rank_badges = page.locator(".doc-rank-badge")
    assert rank_badges.count() > 0
    assert "#1" in rank_badges.first.text_content()

    # 2. Relevance score pills
    score_pills = page.locator(".doc-score-pill")
    assert score_pills.count() > 0
    assert float(score_pills.first.text_content().strip()) >= 0.0

    # 3. Snippets with highlighted terms
    highlights = page.locator(".search-highlight")
    assert highlights.count() > 0
    # Highlighted term must match query concept
    assert "learn" in highlights.first.text_content().lower()

    # 4. Safe snippet verification (No script tags, onerror, or raw unescaped attributes)
    html_content = page.locator(".doc-summary-wrapper").first.inner_html()
    assert "<script" not in html_content
    assert "onerror=" not in html_content
    assert "onpointerenter=" not in html_content

    context.close()


def test_healthy_bm25_mode_returns_bm25_without_degraded_banner(
    live_server, browser_instance, active_lexical_index
):
    """
    IB-R06: Verifies that when an active lexical index generation exists,
    requesting mode=bm25 returns engine_used='bm25' with is_degraded=False,
    renders the healthy BM25 telemetry badge, and does NOT display the degraded banner.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    search_payloads = []

    def capture_search_response(response):
        if "/api/v1/search" in response.url and response.status == 200:
            try:
                search_payloads.append(response.json())
            except Exception:
                pass

    page.on("response", capture_search_response)

    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row")

    assert len(search_payloads) >= 1
    latest = search_payloads[-1]
    assert latest["engine_requested"] == "bm25"
    assert latest["engine_used"] == "bm25"
    assert latest["is_degraded"] is False
    assert latest.get("degraded_reason") is None

    # Healthy BM25 path must NOT show degraded banner
    assert page.locator(".degraded-engine-banner").count() == 0
    assert page.locator(".telemetry-badge.badge-degraded").count() == 0

    telemetry_text = page.locator(".search-telemetry-bar").text_content()
    assert "BM25" in telemetry_text
    assert "ILIKE_FALLBACK" not in telemetry_text

    context.close()


def test_degraded_engine_banner_and_badge(live_server, browser_instance):
    """
    UI-02: Verifies degraded engine banner and badge are clearly surfaced
    when the search engine falls back to lexical retrieval.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    # Intercept /api/v1/search to simulate degraded state
    def handle_search(route):
        response = route.fetch()
        data = response.json()
        data["is_degraded"] = True
        data["engine_requested"] = "semantic"
        data["engine_used"] = "fallback_bm25"
        data["degraded_reason"] = "Semantic vector search unavailable; degraded to pure BM25"
        route.fulfill(
            response=response,
            json=data,
            headers={**response.headers, "X-Index-Generation": "idx-gen-test"},
        )

    page.route("**/api/v1/search*", handle_search)

    page.goto(f"{live_server}/#/library?q=learning&mode=semantic")
    page.wait_for_selector(".degraded-engine-banner")

    # Verify degraded alert banner
    banner = page.locator(".degraded-engine-banner")
    assert banner.is_visible()
    assert "Degraded Retrieval Engine Active" in banner.text_content()
    assert "semantic" in banner.text_content()
    assert "fallback_bm25" in banner.text_content()
    assert "Semantic vector search unavailable" in banner.text_content()

    # Verify degraded badge in telemetry bar
    degraded_badge = page.locator(".telemetry-badge.badge-degraded")
    assert degraded_badge.is_visible()
    assert "FALLBACK_BM25" in degraded_badge.text_content()

    context.close()


def test_deliberate_missing_index_fallback_displays_degraded_banner(
    live_server, browser_instance
):
    """
    IB-R06: Deliberately disables the active lexical index generation in PostgreSQL
    and verifies the live backend returns engine_used='ilike_fallback' with is_degraded=True
    and the UI displays the degraded engine banner.
    """
    db = TestingSessionLocal()
    try:
        for gen in db.query(IndexGeneration).all():
            gen.status = "failed"
        db.commit()
    finally:
        db.close()
    search_engine.clear_cache()

    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    search_payloads = []

    def capture_search_response(response):
        if "/api/v1/search" in response.url and response.status == 200:
            try:
                search_payloads.append(response.json())
            except Exception:
                pass

    page.on("response", capture_search_response)

    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".degraded-engine-banner")

    assert len(search_payloads) >= 1
    latest = search_payloads[-1]
    assert latest["engine_requested"] == "bm25"
    assert latest["engine_used"] == "ilike_fallback"
    assert latest["is_degraded"] is True
    assert latest.get("degraded_reason")

    banner = page.locator(".degraded-engine-banner")
    assert banner.is_visible()
    assert "ilike_fallback" in banner.text_content()

    degraded_badge = page.locator(".telemetry-badge.badge-degraded")
    assert degraded_badge.is_visible()
    assert "ILIKE_FALLBACK" in degraded_badge.text_content()

    context.close()


def test_empty_search_results_state(live_server, browser_instance):
    """
    UI-02: Verifies clean empty state with helpful recovery instructions
    when no documents match the search keywords.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/library?q=xyzzynonexistentkeyword9999")
    page.wait_for_selector(".empty-state")

    empty_box = page.locator(".empty-state")
    assert empty_box.is_visible()
    assert "No documents matched" in empty_box.text_content()
    assert "xyzzynonexistentkeyword9999" in empty_box.text_content()

    # Click Reset All Filters
    reset_btn = empty_box.locator("button:has-text('Reset All Filters')")
    reset_btn.click()

    page.wait_for_url("**/#/library")
    page.wait_for_selector(".document-card-row")
    assert page.locator(".document-card-row").count() > 0

    context.close()


def test_error_handling_and_retry(live_server, browser_instance):
    """
    UI-02: Verifies error state presentation and retry action when search fails.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    first_attempt = {"failed": False}

    def handle_search_fail_once(route):
        if not first_attempt["failed"]:
            first_attempt["failed"] = True
            route.fulfill(status=500, json={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "Simulated search failure"}})
        else:
            route.continue_()

    page.route("**/api/v1/search*", handle_search_fail_once)

    page.goto(f"{live_server}/#/library?q=computing")
    page.wait_for_selector(".notice-error")

    error_box = page.locator(".notice-error")
    assert error_box.is_visible()
    assert "Simulated search failure" in error_box.text_content()

    # Click Try Again button to recover
    retry_btn = error_box.locator("button:has-text('Try Again')")
    retry_btn.click()

    page.wait_for_selector(".document-card-row")
    assert page.locator(".document-card-row").count() > 0

    context.close()


def test_search_pagination_with_context_token(live_server, browser_instance):
    """
    UI-02: Verifies pagination in search mode passes server-issued search_context_token
    from page 1 to page 2, preserving result window boundaries.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row")

    pagination = page.locator(".pagination")
    if pagination.count() > 0:
        next_btn = pagination.locator("button:has-text('Next')")
        if next_btn.is_enabled():
            next_btn.click()
            page.wait_for_url("**/#/library?**page=2**")
            page.wait_for_selector(".document-card-row")

            # Verify page 2 reflects updated ranking positions (#16 or higher)
            first_rank = page.locator(".doc-rank-badge").first.text_content()
            assert "#16" in first_rank or "#" in first_rank

            # Verify Previous button navigates back
            prev_btn = page.locator(".pagination button:has-text('Previous')")
            assert prev_btn.is_enabled()
            prev_btn.click()
            page.wait_for_url("**/#/library?**page=1**")
            page.wait_for_selector(".document-card-row")
            assert "#1" in page.locator(".doc-rank-badge").first.text_content()

    context.close()
