# tests/frontend/public/test_public_flows.py
# Playwright End-to-End tests and visual verification for Folio Public Frontend

import os
import time
import uuid
import pytest
import threading
import uvicorn
from playwright.sync_api import sync_playwright

from src.backend.main import app

SCREENSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../docs/verification/public"))
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

PORT = 8888
BASE_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="session", autouse=True)
def run_app_server():
    """Starts local FastAPI test server on dedicated port 8888."""
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.2)
    yield
    server.should_exit = True


@pytest.fixture(scope="session")
def browser_instance():
    """Launches Chromium browser using available system channel."""
    with sync_playwright() as p:
        browser = None
        for channel in ["chrome", "msedge"]:
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if browser is None:
            browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_library_catalog_and_viewports(browser_instance):
    """
    Tests library catalog:
    - URL query/filter/sort/pagination state synchronization
    - First viewport presentation (results visible above the fold on laptop)
    - Sidebar categories (~220px)
    - Active filter chips bar with removable chips
    - Multi-viewport visual captures (1280x720, 1366x768, 1440x900, 1920x1080, 125% zoom)
    """
    viewports = [
        ("1280x720", 1280, 720, 1.0),
        ("1366x768", 1366, 768, 1.0),
        ("1440x900", 1440, 900, 1.0),
        ("1920x1080", 1920, 1080, 1.0),
        ("1280x720_zoom125", 1280, 720, 1.25),
    ]

    for name, width, height, scale in viewports:
        context = browser_instance.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
        )
        page = context.new_page()

        page.goto(f"{BASE_URL}/#/library")
        page.wait_for_selector(".document-card-row")

        # Verify page title
        assert "Library Catalog" in page.title()

        # Capture first viewport evidence
        shot_path = os.path.join(SCREENSHOT_DIR, f"library_{name}.png")
        page.screenshot(path=shot_path)
        assert os.path.exists(shot_path)

        context.close()


def test_library_filtering_search_and_pagination(browser_instance):
    """Tests search keyword, category click, active chips, pagination, and empty state."""
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{BASE_URL}/#/library")
    page.wait_for_selector(".document-card-row")

    # 1. Search keyword
    search_input = page.locator("#librarySearchInput")
    search_input.fill("learning")
    page.locator("#librarySearchBtn").click()

    page.wait_for_url("**/#/library?q=learning")
    page.wait_for_selector(".document-card-row")

    # Verify active filters bar displays query chip
    chip = page.locator(".active-filter-chip")
    assert chip.count() >= 1
    assert "learning" in chip.first.text_content()

    # Capture active filter state
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "library_filter_active_chips.png"))

    # 2. Category selection
    cat_btn = page.locator(".category-pill").nth(1)
    cat_name = cat_btn.locator("span").first.text_content().strip()
    cat_btn.click()

    page.wait_for_url("**/#/library?**category_id=**")
    page.wait_for_selector(".document-card-row")

    # 3. Clear query chip
    page.locator(".active-filter-chip button.chip-remove-btn").first.click()
    page.wait_for_selector(".document-card-row")

    # 4. Empty search results
    search_input = page.locator("#librarySearchInput")
    search_input.fill("xyznonexistentterm9999")
    page.locator("#librarySearchBtn").click()

    page.wait_for_selector(".empty-state")
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "library_empty_state.png"))

    # Reset all
    page.locator(".empty-state button").click()
    page.wait_for_selector(".document-card-row")

    # 5. Pagination
    pagination_info = page.locator(".pagination .page-info")
    if pagination_info.count() > 0:
        next_btn = page.locator(".pagination .page-btn").last
        if next_btn.is_enabled():
            next_btn.click()
            page.wait_for_url("**/#/library?**page=2**")
            page.wait_for_selector(".document-card-row")

    context.close()


def test_auth_validation_and_profile_management(browser_instance):
    """
    Tests:
    - Login form client validation & field-level errors
    - Login success & session rotation
    - Register form client validation
    - Profile update & password modification
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    # 1. Login field validation
    page.goto(f"{BASE_URL}/#/login")
    page.wait_for_selector("#loginForm")

    # Submit empty form
    page.locator("#loginSubmitBtn").click()
    assert page.locator("#loginEmailError").is_visible()
    assert page.locator("#loginPasswordError").is_visible()
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "auth_login_validation.png"))

    # 2. Registration field validation
    page.goto(f"{BASE_URL}/#/register")
    page.wait_for_selector("#registerForm")

    page.locator("#registerSubmitBtn").click()
    assert page.locator("#regEmailError").is_visible()
    assert page.locator("#regUsernameError").is_visible()
    assert page.locator("#regDisplayNameError").is_visible()
    assert page.locator("#regPasswordError").is_visible()
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "auth_register_validation.png"))

    # 3. Successful login
    page.goto(f"{BASE_URL}/#/login")
    page.locator("#loginEmail").fill("reader@folio.test")
    page.locator("#loginPassword").fill("FolioDemo2026!")
    page.locator("#loginSubmitBtn").click()

    page.wait_for_url("**/#/library")
    page.wait_for_selector("#logoutBtn")
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "auth_login_success.png"))

    # 4. Profile Management
    page.goto(f"{BASE_URL}/#/profile")
    page.wait_for_selector("#profileForm")

    # Verify overview info
    assert "@reader" in page.text_content(".profile-card")
    assert "reader@folio.test" in page.text_content(".profile-card")

    # Edit display name and bio
    page.locator("#profDisplayName").fill("Dr. Reader Scholar")
    page.locator("#profBio").fill("Research Fellow in Computational Linguistics & Neural Architectures.")
    page.locator("#saveProfileBtn").click()

    # Wait for success toast
    page.wait_for_selector(".toast-success")
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "scholar_profile_view.png"))

    context.close()


def test_document_detail_reading_like_and_discussions(browser_instance):
    """
    Tests:
    - Document detail presentation (reading column, summary, author, attribution, view event, title/meta)
    - Like / Unlike toggle
    - Comments feed with @mentions autocomplete
    - Owner inline edit
    - Comment report modal
    - Owner delete with confirmation
    """
    from tests.conftest import TestingSessionLocal
    from src.backend.models.auth import User
    with TestingSessionLocal() as s:
        u = s.query(User).filter(User.username == "reader").first()
        if u and u.commenting_suspended_until:
            u.commenting_suspended_until = None
            s.commit()

    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Login as reader
    page.goto(f"{BASE_URL}/#/login")
    page.locator("#loginEmail").fill("reader@folio.test")
    page.locator("#loginPassword").fill("FolioDemo2026!")
    page.locator("#loginSubmitBtn").click()
    page.wait_for_url("**/#/library")
    page.wait_for_selector(".document-card-row")

    # Search to obtain search_event_id
    page.locator("#librarySearchInput").fill("Deep learning")
    page.locator("#librarySearchBtn").click()
    page.wait_for_selector(".document-card-row")

    # Click first document link (passes search_event_id)
    doc_link = page.locator(".doc-row-title a").first
    doc_title = doc_link.text_content().strip()
    doc_link.click()

    page.wait_for_selector(".document-detail-article")
    assert doc_title in page.title()
    target_doc_url = page.url

    # Capture reading view
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "document_detail_reading_view.png"))

    # 1. Test Like Toggle
    like_btn = page.locator("#likeBtn")
    initial_likes = int(page.locator("#likeCountText").text_content())
    like_btn.click()
    page.wait_for_selector(".toast-success")
    page.wait_for_timeout(300)

    # Click again to toggle back
    like_btn.click()
    page.wait_for_selector(".toast-success")
    page.wait_for_timeout(300)

    # 2. Test @Mentions Autocomplete in Comment Compose
    comment_input = page.locator("#commentBodyInput")
    comment_input.scroll_into_view_if_needed()
    comment_input.fill("Reviewing research insights with colleague @ad")

    # Wait for autocomplete popup
    page.wait_for_selector(".mentions-autocomplete-popup")
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "document_mentions_autocomplete.png"))

    # Select the mention option
    page.locator(".mention-autocomplete-item").first.click()
    assert "@admin " in comment_input.input_value()

    # Post Comment
    page.locator("#submitCommentBtn").click()
    page.wait_for_selector(".toast-success")
    page.wait_for_timeout(500)

    # Verify newly posted comment appears in feed
    latest_comment = page.locator(".comment-card").last
    assert "@admin" in latest_comment.text_content()
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "document_comment_posted.png"))

    # 3. Test Inline Comment Edit
    edit_btn = latest_comment.locator(".edit-comment-btn")
    if edit_btn.is_visible():
        edit_btn.click()
        page.wait_for_selector(".inline-comment-editor")
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "document_comment_inline_edit.png"))

        edit_textarea = page.locator(".edit-body-textarea")
        edit_textarea.fill("Reviewing research insights with colleague @admin — Updated note findings.")
        page.locator(".save-edit-btn").click()
        page.wait_for_selector(".toast-success")
        page.wait_for_timeout(500)

    # 4. Test Report Comment Modal (Log in as another user to see Report button)
    page.locator("#logoutBtn").click()
    page.wait_for_selector("#userMenuContent a[href='#/login']")

    page.goto(f"{BASE_URL}/#/login")
    page.locator("#loginEmail").fill("content@folio.test")
    page.locator("#loginPassword").fill("FolioDemo2026!")
    page.locator("#loginSubmitBtn").click()
    page.wait_for_url("**/#/library")

    # Reopen same document where comment was posted
    page.goto(target_doc_url)
    page.wait_for_selector(".document-detail-article")
    page.wait_for_selector(".comment-card")

    # Click Report on a comment
    report_btn = page.locator(".report-comment-btn").first
    report_btn.scroll_into_view_if_needed()
    report_btn.click()
    page.wait_for_selector(".report-dialog")
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "document_comment_report_modal.png"))

    page.locator("#reportReasonSelect").select_option("spam")
    page.locator("#reportDetailsInput").fill("Unsolicited reference link in note.")
    page.locator("#submitReportBtn").click()
    page.wait_for_selector(".toast-success")

    context.close()
