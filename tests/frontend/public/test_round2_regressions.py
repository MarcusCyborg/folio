# tests/frontend/public/test_round2_regressions.py
# Playwright browser regression tests for Round 2 findings R07, R08, R09, R10, R11, R13

import os
from pathlib import Path
import uuid
import pytest


SCREENSHOT_DIR = Path(__file__).resolve().parents[3] / "test-results" / "round-2"


def _login_ui(page, live_server: str, email: str = "admin@folio.test", password: str = "FolioDemo2026!"):
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", email)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn", timeout=8000)


def test_r07_r08_taxonomy_mobile_layout_and_pagination_over_100_tags(live_server, browser_instance):
    """
    R07 & R08 (F07):
    1. Admin Taxonomy Manager renders cleanly at 360x800, 390x844, 768x1024, and 1440x900
       with zero horizontal page overflow and '+ New Tag' / '+ New Category' fully inside viewport.
    2. Taxonomy Manager paginates and searches across >100 tags cleanly.
    """
    from src.backend.core.database import SessionLocal
    from src.backend.models.taxonomy import Tag

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"R08Tag{uuid.uuid4().hex[:5]}"
    seed_db = SessionLocal()
    try:
        seed_db.add_all([
            Tag(name=f"{prefix} Item {i:03d}", slug=f"{prefix.lower()}-item-{i:03d}")
            for i in range(105)
        ])
        seed_db.commit()
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 360, "height": 800})
    page = context.new_page()

    try:
        _login_ui(page, live_server, "admin@folio.test")
        page.goto(f"{live_server}/#/admin/taxonomy")
        page.wait_for_selector("#tagsListArea table", timeout=8000)

        # Verify responsive geometry across mobile, tablet, and desktop viewports
        for width, height in [(360, 800), (390, 844), (768, 1024), (1440, 900)]:
            page.set_viewport_size({"width": width, "height": height})
            metrics = page.evaluate(
                """() => {
                    const catBtn = document.querySelector('#addCategoryBtn')?.getBoundingClientRect();
                    const tagBtn = document.querySelector('#addTagBtn')?.getBoundingClientRect();
                    return {
                        scrollWidth: document.documentElement.scrollWidth,
                        innerWidth: window.innerWidth,
                        catBtnRight: catBtn ? catBtn.right : -1,
                        tagBtnRight: tagBtn ? tagBtn.right : -1,
                        tagBtnLeft: tagBtn ? tagBtn.left : -1,
                    };
                }"""
            )
            assert metrics["scrollWidth"] <= metrics["innerWidth"], f"Horizontal overflow at {width}px: {metrics}"
            assert 0 <= metrics["catBtnRight"] <= width, f"+ New Category clipped at {width}px: {metrics}"
            assert 0 <= metrics["tagBtnLeft"] and metrics["tagBtnRight"] <= width, f"+ New Tag clipped at {width}px: {metrics}"

            if width == 360:
                page.screenshot(path=str(SCREENSHOT_DIR / "r08-taxonomy-mobile-360.png"), full_page=False)

        # Verify R07 pagination and search across >100 tags
        page.fill("#taxonomyTagSearchInput", prefix)
        page.wait_for_function(
            "p => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '105'",
            arg=prefix,
            timeout=5000,
        )
        assert page.locator("#tagsNextPageBtn").is_enabled()
        page.click("#tagsNextPageBtn")
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 2 of 3')", timeout=5000)
        page.click("#tagsNextPageBtn")
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 3 of 3')", timeout=5000)
        assert page.locator("#tagsListArea tbody tr").count() == 5
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Tag).filter(Tag.slug.like(f"{prefix.lower()}-%")).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r09_taxonomy_load_error_shows_retry_and_recovers(live_server, browser_instance):
    """
    R09 (F11):
    When /api/v1/admin/tags returns HTTP 503, Taxonomy Manager replaces the spinner
    with an accessible error alert and Retry button, and recovers upon clicking Retry.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    _login_ui(page, live_server, "admin@folio.test")

    fail_once = {"should_fail": True}

    def handle_tags_route(route):
        if fail_once["should_fail"]:
            fail_once["should_fail"] = False
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"error":{"code":"SERVICE_UNAVAILABLE","message":"Simulated taxonomy outage"}}',
            )
        else:
            route.continue_()

    page.route("**/api/v1/admin/tags**", handle_tags_route)
    page.goto(f"{live_server}/#/admin/taxonomy")

    # Spinner must disappear and Retry button must appear
    retry_btn = page.locator("#retryTagsLoadBtn")
    retry_btn.wait_for(state="visible", timeout=8000)
    assert page.locator("#tagsListArea .spinner").count() == 0
    assert "Simulated taxonomy outage" in page.locator("#tagsListArea").inner_text()

    # Click Retry -> recovers and loads tags table
    retry_btn.click()
    page.wait_for_selector("#tagsListArea table", timeout=8000)
    assert page.locator("#retryTagsLoadBtn").count() == 0

    context.close()


def test_r10_mention_autocomplete_rapid_input_prevents_stale_selection(live_server, browser_instance, db_session):
    """
    R10 (F10):
    Typing '@adm' opens mention suggestions, then rapidly typing 'xyz' before the 150ms debounce
    and pressing Enter immediately hides the stale popup and does NOT insert '@admin'.
    """
    from src.backend.models.document import Document

    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    _login_ui(page, live_server, "reader@folio.test")
    page.goto(f"{live_server}/#/documents/{doc.id}")
    page.wait_for_selector("#commentBodyInput", timeout=8000)

    textarea = page.locator("#commentBodyInput")
    textarea.focus()
    textarea.type("Hello @adm", delay=20)

    popup = page.locator(".mentions-autocomplete-popup")
    popup.wait_for(state="visible", timeout=5000)
    assert "@admin" in popup.inner_text()

    # Rapidly append 'xyz' (within <150ms debounce) and press Enter
    textarea.type("xyz", delay=10)
    assert not popup.is_visible(), "Stale mention popup must hide immediately on input mismatch"

    page.keyboard.press("Enter")
    current_val = textarea.input_value()
    assert "@admin" not in current_val, f"Stale mention was mistakenly inserted: {current_val!r}"
    assert "@admxyz" in current_val

    context.close()


def test_r11_katex_math_rendering_and_xss_protection(live_server, browser_instance):
    """
    R11 (F08):
    Self-hosted KaTeX renders display and inline equations cleanly in Document Detail
    without external network requests, preserves code blocks, and blocks XSS payloads.
    """
    from datetime import datetime, timezone
    from src.backend.core.database import SessionLocal
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    seed_db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        cat = seed_db.query(Category).first()
        assert cat is not None
        math_doc = Document(
            title=f"Transformer Scaled Dot-Product Attention {uuid.uuid4().hex[:6]}",
            summary="Mathematical formulation of multi-head self-attention.",
            content=(
                "== Scaled Dot-Product Attention ==\n\n"
                "The attention function maps a query and key-value pairs to an output:\n\n"
                "{\\displaystyle {\\text{Attention}}(Q,K,V)={\\text{softmax}}\\left({\\frac {QK^{T}}{\\sqrt {d_{k}}}}\\right)V}\n\n"
                "Inline scaling factor \\(\\frac{1}{\\sqrt{d_k}}\\) prevents softmax saturation.\n\n"
                "```latex\n"
                "{\\displaystyle raw_code_block}\n"
                "```\n\n"
                "XSS probe: $$<img src=x onerror=window.__xssFired=true> x_{1}$$\n"
            ),
            category_id=cat.id,
            status="published",
            created_at=now,
            published_at=now,
        )
        seed_db.add(math_doc)
        seed_db.commit()
        doc_id = math_doc.id
    finally:
        seed_db.close()

    external_hosts = []
    context = browser_instance.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()
    try:
        page.on(
            "request",
            lambda req: external_hosts.append(req.url)
            if req.url.startswith("http") and not req.url.startswith(live_server)
            else None,
        )

        page.goto(f"{live_server}/#/documents/{doc_id}")
        page.wait_for_selector(".document-reading-column .katex", timeout=8000)

        katex_boxes = page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll('.document-reading-column .katex'));
                return nodes.map(n => {
                    const r = n.getBoundingClientRect();
                    return { width: r.width, height: r.height };
                });
            }"""
        )
        assert len(katex_boxes) >= 2
        assert all(b["width"] > 10 and b["height"] > 10 for b in katex_boxes)
        assert page.evaluate("() => Boolean(window.__xssFired)") is False
        assert "raw_code_block" in page.locator(".document-reading-column pre code").inner_text()
        assert external_hosts == [], f"Unexpected external CDN requests: {external_hosts}"

        page.screenshot(path=str(SCREENSHOT_DIR / "r11-katex-math-detail.png"), full_page=False)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Document).filter(Document.id == doc_id).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r13_multi_tab_session_synchronization(live_server, browser_instance):
    """
    R13 (AUTH-03):
    Two open tabs in the same BrowserContext synchronize login and logout immediately
    via BroadcastChannel / storage events without manual tab focus or reload.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    tab_a = context.new_page()
    tab_b = context.new_page()

    # Open both tabs as anonymous guests
    tab_a.goto(f"{live_server}/#/library")
    tab_b.goto(f"{live_server}/#/library")
    tab_a.wait_for_selector("#userMenuContent a[href='#/login']", timeout=8000)
    tab_b.wait_for_selector("#userMenuContent a[href='#/login']", timeout=8000)

    # Sign in as admin in Tab A
    _login_ui(tab_a, live_server, "admin@folio.test")

    # Tab B must update its user badge & logout button automatically without focus/reload
    tab_b.wait_for_selector("#tab_b_nonexistent, #userMenuContent #logoutBtn", timeout=8000)
    assert "Admin" in tab_b.locator("#userMenuContent").inner_text()

    # Navigate Tab B to protected admin screen
    tab_b.goto(f"{live_server}/#/admin/documents")
    tab_b.wait_for_selector(".admin-sidebar", timeout=8000)

    # Sign out in Tab A -> Tab B must log out and exit protected admin screen immediately
    tab_a.click("#logoutBtn")
    tab_a.wait_for_selector("#userMenuContent a[href='#/login']", timeout=8000)

    tab_b.wait_for_selector("#userMenuContent a[href='#/login']", timeout=8000)
    tab_b.wait_for_url("**/#/login**", timeout=8000)

    context.close()
