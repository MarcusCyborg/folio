# tests/frontend/admin/test_admin_flows.py
# Comprehensive automated browser tests for Folio Admin UI flows

import time
import uuid
import pytest
from playwright.sync_api import sync_playwright

SERVER_PORT = 8088
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"

@pytest.fixture(scope="module")
def live_server():
    import threading
    import uvicorn
    from src.backend.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.2)
    yield BASE_URL
    server.should_exit = True
    thread.join(timeout=2)

@pytest.fixture(scope="module")
def browser_instance():
    p = sync_playwright().start()
    browser = p.chromium.launch(channel="chrome", headless=True)
    yield browser
    browser.close()
    p.stop()

def login_user(page, email, password="FolioDemo2026!"):
    page.goto(f"{BASE_URL}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", email)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn", timeout=5000)

def test_admin_entry_and_rbac_guards(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # 1. Unauthenticated guest accessing #/admin shows 403 Forbidden
    page.goto(f"{BASE_URL}/#/admin")
    page.wait_for_selector(".notice-error")
    assert "403 Forbidden" in page.content()
    assert "Return to Library" in page.content()

    # 2. Member (reader@folio.test) accessing #/admin shows 403 Forbidden
    login_user(page, "reader@folio.test")
    page.goto(f"{BASE_URL}/#/admin")
    page.wait_for_selector(".notice-error")
    assert "403 Forbidden" in page.content()

    # Deep linking to #/admin/documents for member shows 403 Forbidden inside admin layout
    page.goto(f"{BASE_URL}/#/admin/documents")
    page.wait_for_selector(".notice-error")
    assert "403 Forbidden" in page.content()

    context.close()

def test_content_manager_permissions(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Log in as Content Manager
    login_user(page, "content@folio.test")

    # Navigate to #/admin -> redirects to first allowed screen (/admin/documents)
    page.goto(f"{BASE_URL}/#/admin")
    page.wait_for_selector(".admin-sidebar")
    assert "#/admin/documents" in page.url

    # Check visible sidebar links
    sidebar_text = page.locator(".admin-sidebar-nav").inner_text()
    assert "Documents" in sidebar_text
    assert "Taxonomy" in sidebar_text
    assert "Users & Staff" not in sidebar_text
    assert "Audit Trail" not in sidebar_text

    # Unauthorized deep link to #/admin/users shows 403
    page.goto(f"{BASE_URL}/#/admin/users")
    page.wait_for_selector(".notice-error")
    assert "403 Forbidden" in page.content()

    context.close()

def test_data_seo_specialist_permissions(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Log in as Data & SEO specialist
    login_user(page, "seo@folio.test")

    # Navigate to #/admin -> redirects to #/admin/seo
    page.goto(f"{BASE_URL}/#/admin")
    page.wait_for_selector(".admin-sidebar")
    assert "#/admin/seo" in page.url

    # Can view documents list, but cannot create or edit body
    page.goto(f"{BASE_URL}/#/admin/documents")
    page.wait_for_selector("table")
    # Verify no create button
    assert page.locator("#createNewDocBtn").count() == 0
    # Table should show "Edit SEO" button instead of write editor
    assert page.locator("text=Edit SEO").count() > 0

    # Deep link to create document shows 403
    page.goto(f"{BASE_URL}/#/admin/documents/new")
    page.wait_for_selector(".notice-error")
    assert "403 Forbidden" in page.content()

    context.close()

def test_super_admin_full_documents_crud_and_dirty_guard(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")

    # 1. Documents Directory & Filter by category/status
    page.goto(f"{BASE_URL}/#/admin/documents")
    page.wait_for_selector("table")
    assert "Research Documents" in page.content()

    # 2. Click Create Document
    page.click("#createNewDocBtn")
    page.wait_for_selector("#docEditorForm")

    # 3. Test Dirty Form Guard
    doc_title = f"Quantum Computing Advancements {uuid.uuid4().hex[:6]}"
    page.fill("#editTitle", doc_title)
    page.wait_for_selector("#dirtyIndicator", state="visible")

    # Attempt to click back link while dirty
    page.click("#editorBackLink")
    page.wait_for_selector(".dialog")
    assert "Unsaved Changes" in page.content()
    # Cancel dialog
    page.click("button:has-text('Cancel')")
    page.wait_for_selector(".dialog", state="detached")

    # 4. Fill form fields
    page.wait_for_selector("#editCategory option", state="attached")
    page.fill("#editSummary", "Experimental evaluation of quantum superconducting circuits at dilution temperatures.")
    page.fill("#editContent", "# Quantum Dilution\n\nCryogenic architecture for low-noise measurement.\n\n- Qubit fidelity: 99.9%\n- Thermal isolation: Complete")
    page.fill("#editAuthor", "Dr. Folio Researcher")
    page.fill("#editSourceUrl", f"https://arxiv.org/abs/2610.{uuid.uuid4().hex[:8]}")
    page.fill("#editLicense", "CC BY 4.0")
    page.fill("#editAttribution", "arXiv / Quantum Consortium")
    page.fill("#editCoverUrl", "https://example.com/quantum_cover.jpg")
    page.fill("#editCoverAlt", "Cryostat cooling apparatus diagram")

    # Select category and tags
    page.select_option("#editCategory", index=0)
    page.wait_for_selector(".tag-chk")
    tag_checkboxes = page.locator(".tag-chk")
    if tag_checkboxes.count() > 0:
      tag_checkboxes.first.check()

    # 5. Check Markdown Preview Tab
    page.click("#tabPreview")
    page.wait_for_selector("#editorPreviewBox")
    preview_html = page.locator("#editorPreviewBox").inner_html()
    assert "Quantum Dilution" in preview_html
    assert "Qubit fidelity: 99.9%" in preview_html
    page.click("#tabWrite")

    # 6. Save as Draft
    page.click("#saveDraftBtn")
    page.wait_for_selector("text=Document successfully saved")

    # Wait for navigation back to documents list
    page.wait_for_selector("table")
    # Verify created document appears with Draft badge
    page.fill("#adminDocSearchInput", doc_title)
    page.click("#adminDocFilterBtn")
    page.wait_for_selector(f"text={doc_title}")
    assert "Draft" in page.content()

    # 7. Edit document and Publish
    page.click(f"text={doc_title}")
    page.wait_for_selector("#docEditorForm")
    page.wait_for_selector("#editCategory option", state="attached")
    page.click("#publishDocBtn")
    page.wait_for_url(f"{BASE_URL}/#/admin/documents")
    page.wait_for_selector("table")
    page.fill("#adminDocSearchInput", doc_title)
    page.click("#adminDocFilterBtn")
    page.wait_for_selector(f"text={doc_title}")
    assert "Published" in page.content()

    context.close()

def test_taxonomy_manager_and_409_conflict_handling(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")
    page.goto(f"{BASE_URL}/#/admin/taxonomy")
    page.wait_for_selector(".taxonomy-grid")

    # 1. Add Category via Modal
    page.click("#addCategoryBtn")
    page.wait_for_selector(".modal-dialog")
    cat_name = f"Quantum Tech {uuid.uuid4().hex[:6]}"
    page.fill("#catModalName", cat_name)
    page.fill("#catModalSlug", f"quantum-tech-{uuid.uuid4().hex[:6]}")
    page.fill("#catModalDesc", "Research on quantum information and hardware systems.")
    page.click("#saveCatModalBtn")
    page.wait_for_selector(f"text={cat_name}")

    # 2. Add Tag via Modal
    page.click("#addTagBtn")
    page.wait_for_selector(".modal-dialog")
    tag_name = f"Superconductivity {uuid.uuid4().hex[:6]}"
    page.fill("#tagModalName", tag_name)
    page.click("#saveTagModalBtn")
    page.wait_for_selector(f"text={tag_name}")

    # 3. Test 409 Conflict Protection when trying to delete an in-use category
    in_use_cat_row = page.locator("tr[data-cat-id]:has(.badge:not(:text('0')))")
    if in_use_cat_row.count() > 0:
      del_btn = in_use_cat_row.first.locator(".del-cat-btn")
      del_btn.click()
      page.wait_for_selector(".dialog")
      page.click(".dialog button:has-text('Delete Category')")
      # Expect error toast due to 409 Conflict
      page.wait_for_selector(".toast-error")
      assert "Cannot delete category" in page.content() or "assigned to documents" in page.content()

    context.close()

def test_moderation_queue_actions_and_suspension(live_server, browser_instance):
    from tests.conftest import TestingSessionLocal
    from src.backend.models.auth import User
    from src.backend.models.document import Document
    from src.backend.models.comment import Comment, Report

    # Ensure test comment and report exist in test database for moderation queue
    with TestingSessionLocal() as s:
        doc = s.query(Document).filter(Document.status == "published").first()
        reader = s.query(User).filter(User.username == "reader").first()
        if doc and reader:
            existing = s.query(Comment).filter(Comment.user_id == reader.id).first()
            if not existing:
                c = Comment(document_id=doc.id, user_id=reader.id, body="Automated research discussion comment for moderation flow", status="visible")
                s.add(c)
                s.flush()
                r = Report(comment_id=c.id, reporter_id=reader.id, reason="spam", details="Suspected commercial link", status="open")
                s.add(r)
                s.commit()

    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")
    page.goto(f"{BASE_URL}/#/admin/comments")
    page.wait_for_selector(".table")

    # Test comments moderation status buttons
    status_buttons = page.locator(".btn-action-status")
    if status_buttons.count() > 0:
      first_btn = status_buttons.first
      first_btn.click()
      page.wait_for_selector("text=Comment marked as")

    # Test suspension modal with audit reason
    page.wait_for_selector(".btn-suspend-user")
    suspend_btn = page.locator(".btn-suspend-user").first
    if suspend_btn.count() > 0:
      suspend_btn.click()
      page.wait_for_selector("#suspendBackdrop")
      page.fill("#suspendReason", "Automated test compliance verification for spam guidelines")
      page.click("#confirmSuspendBtn")
      page.wait_for_selector("text=User commenting suspended")

    # Navigate to Reports Queue
    page.goto(f"{BASE_URL}/#/admin/reports")
    page.wait_for_selector(".admin-toolbar")
    assert "Reports" in page.content()

    context.close()

    # Reset suspension state so subsequent test flows run with unhindered reader
    with TestingSessionLocal() as s:
        u = s.query(User).filter(User.username == "reader").first()
        if u and u.commenting_suspended_until:
            u.commenting_suspended_until = None
            s.commit()

def test_seo_management_and_preview_simulation(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "seo@folio.test")
    page.goto(f"{BASE_URL}/#/admin/seo")
    page.wait_for_selector("table")

    # Open SEO editor modal for the first document
    edit_seo_btn = page.locator(".btn-edit-seo").first
    edit_seo_btn.click()
    page.wait_for_selector("#seoBackdrop")

    # Verify Google SERP Simulation and disclaimer
    assert "Google SERP Simulation" in page.content()
    assert "Search Engine Notice" in page.content()

    # Verify live character counters
    page.fill("#inputSeoTitle", "Top Quantum Machine Learning Algorithms & Architectures")
    page.wait_for_selector("#seoTitleCounter")
    assert "/ 60" in page.locator("#seoTitleCounter").inner_text()

    page.fill("#inputSeoDesc", "Comprehensive guide to quantum state tomography and tensor network representations.")
    page.wait_for_selector("#seoDescCounter")
    assert "/ 160" in page.locator("#seoDescCounter").inner_text()

    page.fill("#inputSeoKeywords", "quantum, machine learning, physics, qml")
    page.fill("#inputCoverAlt", "Quantum circuit schematic diagram")

    # Save SEO metadata
    page.click("#saveSeoBtn")
    page.wait_for_selector("text=SEO metadata updated successfully")

    context.close()

def test_analytics_dashboard_metrics(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")
    page.goto(f"{BASE_URL}/#/admin/analytics")
    page.wait_for_selector(".analytics-totals-grid")

    # Verify metric cards
    content = page.content()
    assert "Published Documents" in content
    assert "Search Requests" in content  # Exact contract label!
    assert "Result Clicks" in content
    assert "Document Views" in content
    assert "Interaction Volume Over Period" in content
    assert "Daily Activity Breakdown" in content

    # Test period buttons
    page.click("button:has-text('Last 7 Days')")
    page.wait_for_selector(".analytics-totals-grid")

    context.close()

def test_users_governance_and_last_super_admin_protection(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")
    page.goto(f"{BASE_URL}/#/admin/users")
    page.wait_for_selector("table")

    # Find the super admin row
    admin_row = page.locator("tr:has-text('admin@folio.test')")
    assert admin_row.count() > 0

    # Attempt to demote the sole active super admin to member
    role_select = admin_row.locator(".user-role-select")
    role_select.select_option("member")

    # Expect error toast with 409 Conflict rejection from backend
    page.wait_for_selector(".toast-error")
    assert "super administrator" in page.content() or "Cannot deactivate or demote" in page.content()

    # Verify select value reverted back to super_admin
    assert role_select.input_value() == "super_admin"

    context.close()

def test_roles_matrix_and_settings(live_server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    login_user(page, "admin@folio.test")

    # 1. Roles Matrix
    page.goto(f"{BASE_URL}/#/admin/roles")
    page.wait_for_selector(".matrix-table")
    assert "Permissions Matrix" in page.content()
    # Check that super_admin checkboxes are disabled and protected
    super_admin_checks = page.locator(".matrix-perm-check[data-role-key='super_admin']")
    assert super_admin_checks.first.is_disabled()

    # Save a non-protected role
    save_cm_btn = page.locator(".btn-save-role-perms[data-role-key='content_manager']")
    if save_cm_btn.count() > 0:
      save_cm_btn.click()
      page.wait_for_selector("text=Permissions saved for content_manager")

    # 2. Audit Trail
    page.goto(f"{BASE_URL}/#/admin/audit")
    page.wait_for_selector(".table")
    assert "Administrative Audit Trail" in page.content()
    inspect_btn = page.locator(".btn-view-diff")
    if inspect_btn.count() > 0:
      inspect_btn.first.click()
      page.wait_for_selector("#diffBackdrop")
      assert "Before State:" in page.content()
      assert "After State:" in page.content()
      page.click("#closeDiffBtn")

    # 3. Global Settings
    page.goto(f"{BASE_URL}/#/admin/settings")
    page.wait_for_selector("#globalSettingsForm")
    page.fill("#settingSiteName", "Folio — Knowledge & Research Library (Admin Verified)")
    page.click("#saveSettingsBtn")
    page.wait_for_selector("text=Settings updated successfully")

    context.close()
