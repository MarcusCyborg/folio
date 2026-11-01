# tests/frontend/admin/test_admin_screenshots.py
# Automated visual verification and desktop viewport capture

import os
import time
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright

from src.backend.core.artifact_utils import get_artifact_context

SERVER_PORT = 8089
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module", autouse=True)
def configure_server(live_server):
    global BASE_URL
    BASE_URL = live_server


def login_user(page, email, password="FolioDemo2026!"):
    page.goto(f"{BASE_URL}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", email)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn", timeout=5000)


def test_capture_admin_screens_and_viewports(live_server, browser_instance):
    output_dir = get_artifact_context().get_screenshots_dir("admin")

    # 1. Standard 1440x900 Desktop captures
    context_1440 = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context_1440.new_page()

    # Documents List
    login_user(page, "admin@folio.test")
    page.goto(f"{BASE_URL}/#/admin/documents")
    page.wait_for_selector(".admin-toolbar")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_documents_1440x900.png"))

    # Document Editor with Markdown Preview
    page.goto(f"{BASE_URL}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm")
    page.fill("#editTitle", "Quantum Advantage via Sycamore Architectures")
    page.fill("#editSummary", "Detailed theoretical benchmarks of cross-entropy benchmarking on noisy quantum processors.")
    page.fill("#editContent", "# Quantum Advantage\n\nCross-entropy benchmarking demonstrates circuit supremacy.\n\n- Qubit fidelity: 99.8%\n- Entangling gate error: < 0.5%")
    page.click("#tabPreview")
    page.wait_for_selector("#editorPreviewBox")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_editor_preview_1440x900.png"))

    # Taxonomy Management - discard editor dirty guard when navigating
    page.goto(f"{BASE_URL}/#/admin/taxonomy")
    if page.locator("button:has-text('Discard & Leave')").count() > 0:
        page.click("button:has-text('Discard & Leave')")
    page.wait_for_selector(".taxonomy-grid")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_taxonomy_1440x900.png"))

    # Moderation Comments
    page.goto(f"{BASE_URL}/#/admin/comments")
    page.wait_for_selector(".table, .empty-state")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_comments_1440x900.png"))

    # Moderation Reports
    page.goto(f"{BASE_URL}/#/admin/reports")
    page.wait_for_selector(".admin-toolbar")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_reports_1440x900.png"))

    # SEO Management & SERP Modal
    page.goto(f"{BASE_URL}/#/admin/seo")
    page.wait_for_selector("table")
    page.locator(".btn-edit-seo").first.click()
    page.wait_for_selector("#seoBackdrop")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_seo_serp_1440x900.png"))
    page.click("#closeSeoBtn")

    # Analytics Dashboard
    page.goto(f"{BASE_URL}/#/admin/analytics")
    page.wait_for_selector(".analytics-totals-grid")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_analytics_1440x900.png"))

    # User Directory
    page.goto(f"{BASE_URL}/#/admin/users")
    page.wait_for_selector("table")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_users_1440x900.png"))

    # Roles & Permissions Matrix
    page.goto(f"{BASE_URL}/#/admin/roles")
    page.wait_for_selector(".matrix-table")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_roles_matrix_1440x900.png"))

    # Audit Trail
    page.goto(f"{BASE_URL}/#/admin/audit")
    page.wait_for_selector(".table")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_audit_logs_1440x900.png"))

    # Global Settings
    page.goto(f"{BASE_URL}/#/admin/settings")
    page.wait_for_selector("#globalSettingsForm")
    time.sleep(0.5)
    page.screenshot(path=str(output_dir / "admin_settings_1440x900.png"))

    context_1440.close()

    # 2. 403 Forbidden screen capture for unauthorized user
    context_member = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    p_member = context_member.new_page()
    login_user(p_member, "reader@folio.test")
    p_member.goto(f"{BASE_URL}/#/admin")
    p_member.wait_for_selector(".notice-error")
    time.sleep(0.4)
    p_member.screenshot(path=str(output_dir / "admin_403_forbidden_1440x900.png"))
    context_member.close()

    # 3. Viewport 1280x720 (Standard Laptop)
    context_1280 = browser_instance.new_context(viewport={"width": 1280, "height": 720})
    p_1280 = context_1280.new_page()
    login_user(p_1280, "admin@folio.test")
    p_1280.goto(f"{BASE_URL}/#/admin/documents")
    p_1280.wait_for_selector(".admin-toolbar")
    time.sleep(0.4)
    p_1280.screenshot(path=str(output_dir / "admin_documents_1280x720.png"))
    p_1280.goto(f"{BASE_URL}/#/admin/analytics")
    p_1280.wait_for_selector(".analytics-totals-grid")
    time.sleep(0.4)
    p_1280.screenshot(path=str(output_dir / "admin_analytics_1280x720.png"))
    context_1280.close()

    # 4. Viewport 1366x768 (Common Laptop)
    context_1366 = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    p_1366 = context_1366.new_page()
    login_user(p_1366, "admin@folio.test")
    p_1366.goto(f"{BASE_URL}/#/admin/documents")
    p_1366.wait_for_selector(".admin-toolbar")
    time.sleep(0.4)
    p_1366.screenshot(path=str(output_dir / "admin_documents_1366x768.png"))
    context_1366.close()

    # 5. Viewport 1920x1080 (Full HD Desktop)
    context_1920 = browser_instance.new_context(viewport={"width": 1920, "height": 1080})
    p_1920 = context_1920.new_page()
    login_user(p_1920, "admin@folio.test")
    p_1920.goto(f"{BASE_URL}/#/admin/documents")
    p_1920.wait_for_selector(".admin-toolbar")
    time.sleep(0.4)
    p_1920.screenshot(path=str(output_dir / "admin_documents_1920x1080.png"))
    p_1920.goto(f"{BASE_URL}/#/admin/analytics")
    p_1920.wait_for_selector(".analytics-totals-grid")
    time.sleep(0.4)
    p_1920.screenshot(path=str(output_dir / "admin_analytics_1920x1080.png"))
    context_1920.close()

    # 6. Laptop 125% Zoom Simulation (Device scale factor 1.25, 1536x864 logical)
    context_zoom = browser_instance.new_context(viewport={"width": 1536, "height": 864}, device_scale_factor=1.25)
    p_zoom = context_zoom.new_page()
    login_user(p_zoom, "admin@folio.test")
    p_zoom.goto(f"{BASE_URL}/#/admin/documents")
    p_zoom.wait_for_selector(".admin-toolbar")
    time.sleep(0.4)
    p_zoom.screenshot(path=str(output_dir / "admin_documents_125zoom_1536x864.png"))
    context_zoom.close()

    # Verify screenshots exist in the run-isolated output directory
    screenshots = list(output_dir.glob("*.png"))
    assert len(screenshots) >= 15
