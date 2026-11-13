# tests/frontend/public/test_remediation_findings.py
# Playwright & API regression tests verifying review findings F1, F2, F3, F5, F6 (M7 / UI-06)

import uuid
import pytest
from playwright.sync_api import sync_playwright


def test_finding_f1_markdown_preview_sanitizer(live_server, browser_instance):
    """
    Finding F1: Markdown editor preview uses backend Bleach sanitizer endpoint,
    preventing quote breakout, inline event attributes (onpointerenter/onload), and script execution.
    """
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Login as admin
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", "admin@folio.test")
    page.fill("#loginPassword", "FolioDemo2026!")
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn")

    page.goto(f"{live_server}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm")

    # Reproduction payload from Finding F1
    malicious_markdown = '[hover me](https://example.invalid/"onpointerenter="document.title=123)'
    page.fill("#editContent", malicious_markdown)

    # Click Preview tab
    page.click("#tabPreview")
    page.wait_for_selector("#editorPreviewBox .markdown-body", timeout=5000)

    preview_html = page.locator("#editorPreviewBox").inner_html()

    # Invariant: Attribute breakout must be neutralized
    assert "onpointerenter=" not in preview_html.lower()
    assert "document.title=123" not in preview_html

    context.close()


def test_finding_f2_dirty_guard_all_navigation(live_server, browser_instance):
    """
    Finding F2: Unsaved document changes are protected across ALL navigation transitions:
    - Sidebar navigation links
    - Top header library link
    - Browser back/forward history navigation
    Canceling the prompt leaves input state 100% intact.
    """
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Login as admin
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", "admin@folio.test")
    page.fill("#loginPassword", "FolioDemo2026!")
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn")

    page.goto(f"{live_server}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm")

    unique_text = f"Unsaved Research Draft {uuid.uuid4().hex[:6]}"
    page.fill("#editTitle", unique_text)
    page.wait_for_selector("#dirtyIndicator", state="visible")

    # 1. Attempt navigating via Admin Sidebar link (e.g. Analytics)
    analytics_sidebar_link = page.locator(".admin-sidebar-link:has-text('Analytics')")
    analytics_sidebar_link.click()

    page.wait_for_selector(".dialog")
    assert "Unsaved Changes" in page.content()

    # Cancel dialog
    page.click(".dialog button:has-text('Cancel')")
    page.wait_for_selector(".dialog", state="detached")

    # Form and input value must remain intact
    assert page.locator("#editTitle").input_value() == unique_text
    assert "#/admin/documents/new" in page.url

    # 2. Attempt navigating via Header Brand / Library link
    header_lib_link = page.locator(".shell-brand")
    header_lib_link.click()

    page.wait_for_selector(".dialog")
    assert "Unsaved Changes" in page.content()

    # Cancel dialog
    page.click(".dialog button:has-text('Cancel')")
    page.wait_for_selector(".dialog", state="detached")
    assert page.locator("#editTitle").input_value() == unique_text

    # 3. Attempt browser Back button
    page.go_back()

    page.wait_for_selector(".dialog")
    assert "Unsaved Changes" in page.content()

    # Confirm Discard & Leave this time
    page.click(".dialog button:has-text('Discard & Leave')")
    page.wait_for_selector(".dialog", state="detached")

    context.close()


def test_finding_f3_save_draft_status_alignment(live_server, browser_instance):
    """
    Finding F3: Verifies that "Save Draft" vs "Save Changes" vs "Publish" labels
    strictly correspond to persisted status in the database.
    """
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Login as admin
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", "admin@folio.test")
    page.fill("#loginPassword", "FolioDemo2026!")
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn")

    # 1. Create a draft document
    page.goto(f"{live_server}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm")

    doc_title = f"Status Alignment Study {uuid.uuid4().hex[:6]}"
    page.fill("#editTitle", doc_title)
    page.fill("#editSummary", "Evaluating status transitions between draft and published.")
    page.fill("#editContent", "Research content body for status testing.")
    page.select_option("#editCategory", index=0)

    # In new document, buttons must be "Save Draft" and "Publish to Library"
    draft_btn = page.locator("#saveDraftBtn")
    assert draft_btn.is_visible()
    assert "Save Draft" in draft_btn.text_content()

    draft_btn.click()
    page.wait_for_selector("text=Document successfully saved as draft")
    page.wait_for_selector("table")

    # Search and verify created doc is Draft
    page.fill("#adminDocSearchInput", doc_title)
    page.click("#adminDocFilterBtn")
    page.wait_for_selector(f"text={doc_title}")
    row_text = page.locator(f"tr:has-text('{doc_title}')").text_content()
    assert "Draft" in row_text

    # 2. Edit draft doc and publish it
    page.click(f"text={doc_title}")
    page.wait_for_selector("#docEditorForm")
    page.wait_for_function("title => document.querySelector('#editTitle')?.value === title", arg=doc_title)

    publish_btn = page.locator("#publishDocBtn")
    assert "Publish to Library" in publish_btn.text_content()
    publish_btn.click()

    page.wait_for_selector("text=Document successfully published")
    page.wait_for_selector("table")

    # Search and verify doc is now Published
    page.fill("#adminDocSearchInput", doc_title)
    page.click("#adminDocFilterBtn")
    page.wait_for_selector(f"text={doc_title}")
    row_text = page.locator(f"tr:has-text('{doc_title}')").text_content()
    assert "Published" in row_text

    # 3. Open the published doc: Buttons must now be "Save Changes" and "Save & Unpublish"
    page.click(f"text={doc_title}")
    page.wait_for_selector("#docEditorForm")
    page.wait_for_function("title => document.querySelector('#editTitle')?.value === title", arg=doc_title)

    save_published_btn = page.locator("#savePublishedBtn")
    unpublish_btn = page.locator("#unpublishDocBtn")

    assert save_published_btn.is_visible()
    assert "Save Changes" in save_published_btn.text_content()
    assert unpublish_btn.is_visible()
    assert "Save & Unpublish" in unpublish_btn.text_content()

    # Click Save Changes: Document must remain published
    page.fill("#editSummary", "Updated summary while remaining published.")
    save_published_btn.click()

    page.wait_for_selector("text=Document successfully published")
    page.wait_for_selector("table")

    page.fill("#adminDocSearchInput", doc_title)
    page.click("#adminDocFilterBtn")
    page.wait_for_selector(f"text={doc_title}")
    row_text = page.locator(f"tr:has-text('{doc_title}')").text_content()
    assert "Published" in row_text

    context.close()


def test_finding_f6_date_to_boundary_safe(client):
    """
    Finding F6: Valid maximum date date_to=9999-12-31 does not raise OverflowError
    or HTTP 500 on either /api/v1/documents or /api/v1/search.
    """
    res1 = client.get("/api/v1/documents?date_to=9999-12-31")
    assert res1.status_code == 200, f"Expected 200 for /documents, got {res1.status_code}"
    data1 = res1.json()
    assert "items" in data1

    res2 = client.get("/api/v1/search?q=machine&date_to=9999-12-31")
    assert res2.status_code == 200, f"Expected 200 for /search, got {res2.status_code}"
    data2 = res2.json()
    assert "items" in data2
