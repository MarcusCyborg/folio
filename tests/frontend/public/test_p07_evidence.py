# tests/frontend/public/test_p07_evidence.py
# Automated P07 Visual Evidence Capture across Viewports, Search States & Admin Remediations (including IB-R06)

import os
import time
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright

from tests.conftest import TestingSessionLocal
from src.backend.core.artifact_utils import get_artifact_context, get_git_commit_sha
from src.backend.models.search_index import IndexGeneration
from src.backend.services.search.search_service import search_engine


def login_admin(page, live_server, email="admin@folio.test", password="FolioDemo2026!"):
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", email)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn", timeout=5000)


def test_capture_p07_complete_evidence(live_server, browser_instance, active_lexical_index):
    """
    Captures complete P07 visual evidence into the collision-free artifact directory
    managed by artifact_utils, preserving all existing screenshots and baseline assets.
    """
    evidence_dir = get_artifact_context().get_screenshots_dir("p07_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    commit_sha = get_git_commit_sha()

    print(f"\n[P07 Evidence] Capturing visual evidence to: {evidence_dir} (commit: {commit_sha})")

    # 1. Search BM25 Results Desktop (1440x900) — must be healthy BM25, not ILIKE_FALLBACK
    ctx_1440 = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = ctx_1440.new_page()

    bm25_payloads = []
    page.on(
        "response",
        lambda r: bm25_payloads.append(r.json())
        if ("/api/v1/search" in r.url and "mode=bm25" in r.url and r.status == 200)
        else None,
    )

    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row", timeout=10000)
    page.wait_for_timeout(600)
    assert bm25_payloads and bm25_payloads[-1]["engine_used"] == "bm25"
    assert bm25_payloads[-1]["is_degraded"] is False
    assert page.locator(".degraded-engine-banner").count() == 0

    shot_1 = evidence_dir / "01_search_bm25_desktop_1440.png"
    page.screenshot(path=str(shot_1))
    assert shot_1.exists()

    # 2. Search Hybrid Mode Desktop (1440x900)
    page.goto(f"{live_server}/#/library?q=neural&mode=hybrid")
    page.wait_for_selector(".document-card-row", timeout=10000)
    page.wait_for_timeout(600)
    shot_2 = evidence_dir / "02_search_hybrid_desktop_1440.png"
    page.screenshot(path=str(shot_2))
    assert shot_2.exists()

    # 3. Degraded Engine Fallback Banner (1440x900)
    def mock_degraded(route):
        res = route.fetch()
        data = res.json()
        data["is_degraded"] = True
        data["engine_requested"] = "semantic"
        data["engine_used"] = "fallback_bm25"
        data["degraded_reason"] = "Semantic vector search unavailable; degraded to pure BM25"
        route.fulfill(response=res, json=data)

    page.route("**/api/v1/search*", mock_degraded)
    page.goto(f"{live_server}/#/library?q=transformer&mode=semantic")
    page.wait_for_selector(".degraded-engine-banner", timeout=10000)
    page.wait_for_timeout(600)
    shot_3 = evidence_dir / "03_search_degraded_banner_1440.png"
    page.screenshot(path=str(shot_3))
    assert shot_3.exists()
    page.unroute("**/api/v1/search*")

    # 4. Mobile 360px Library View (360x640)
    ctx_360 = browser_instance.new_context(viewport={"width": 360, "height": 640})
    page_360 = ctx_360.new_page()
    page_360.goto(f"{live_server}/#/library")
    page_360.wait_for_selector(".document-card-row", timeout=10000)
    page_360.wait_for_timeout(600)
    shot_4 = evidence_dir / "04_library_mobile_360.png"
    page_360.screenshot(path=str(shot_4))
    assert shot_4.exists()
    ctx_360.close()

    # 5. Mobile 390px Library View with Filter Drawer Open (390x844)
    ctx_390 = browser_instance.new_context(viewport={"width": 390, "height": 844})
    page_390 = ctx_390.new_page()
    page_390.goto(f"{live_server}/#/library")
    page_390.wait_for_selector("#mobileFilterToggleBtn", timeout=10000)
    page_390.click("#mobileFilterToggleBtn")
    page_390.wait_for_selector("#librarySidebar.open", timeout=5000)
    page_390.wait_for_timeout(600)
    shot_5 = evidence_dir / "05_library_mobile_390_filter_drawer.png"
    page_390.screenshot(path=str(shot_5))
    assert shot_5.exists()

    # 6. Document Detail Mobile 390px (390x844)
    page_390.goto(f"{live_server}/#/library")
    page_390.wait_for_selector(".doc-row-title a", timeout=10000)
    page_390.locator(".doc-row-title a").first.click()
    page_390.wait_for_selector(".document-detail-article", timeout=10000)
    page_390.wait_for_timeout(600)
    shot_6 = evidence_dir / "06_detail_mobile_390.png"
    page_390.screenshot(path=str(shot_6))
    assert shot_6.exists()
    ctx_390.close()

    # 7. Tablet 768px Library View (768x1024)
    ctx_768 = browser_instance.new_context(viewport={"width": 768, "height": 1024})
    page_768 = ctx_768.new_page()
    page_768.goto(f"{live_server}/#/library?q=algorithm")
    page_768.wait_for_selector(".document-card-row", timeout=10000)
    page_768.wait_for_timeout(600)
    shot_7 = evidence_dir / "07_library_tablet_768.png"
    page_768.screenshot(path=str(shot_7))
    assert shot_7.exists()
    ctx_768.close()

    # 8. Document Detail Desktop (1440x900)
    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".doc-row-title a", timeout=10000)
    page.locator(".doc-row-title a").first.click()
    page.wait_for_selector(".document-detail-article", timeout=10000)
    page.wait_for_timeout(600)
    shot_8 = evidence_dir / "08_detail_desktop_1440.png"
    page.screenshot(path=str(shot_8))
    assert shot_8.exists()

    # 9. Admin Documents List Responsive Table Mobile (390x844)
    ctx_admin_390 = browser_instance.new_context(viewport={"width": 390, "height": 844})
    page_adm_390 = ctx_admin_390.new_page()
    page_adm_390.goto(f"{live_server}/#/login")
    page_adm_390.wait_for_selector("#loginEmail")
    page_adm_390.fill("#loginEmail", "admin@folio.test")
    page_adm_390.fill("#loginPassword", "FolioDemo2026!")
    page_adm_390.click("#loginSubmitBtn")
    page_adm_390.wait_for_selector(".user-badge, #logoutBtn", timeout=5000)
    page_adm_390.goto(f"{live_server}/#/admin/documents")
    page_adm_390.wait_for_selector(".table-container table", timeout=10000)
    page_adm_390.wait_for_timeout(600)
    shot_9 = evidence_dir / "09_admin_table_mobile_390.png"
    page_adm_390.screenshot(path=str(shot_9))
    assert shot_9.exists()
    ctx_admin_390.close()

    # 10. Admin Document Editor Dirty Guard Modal (1440x900)
    login_admin(page, live_server)
    page.goto(f"{live_server}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm", timeout=10000)
    page.fill("#editTitle", "Quantum Advantage via Sycamore Circuits")
    page.wait_for_selector("#dirtyIndicator", state="visible")
    page.click("#editorBackLink")
    page.wait_for_selector(".dialog", timeout=5000)
    page.wait_for_timeout(500)
    shot_10 = evidence_dir / "10_admin_dirty_guard_1440.png"
    page.screenshot(path=str(shot_10))
    assert shot_10.exists()
    page.click(".dialog button:has-text('Cancel')")

    # 11. Admin Markdown Safe Preview (1440x900)
    page.fill("#editContent", "# Quantum Decoherence\n\n- T1 Relaxation: 20 microseconds\n- Fidelity: 99.9%")
    page.click("#tabPreview")
    page.wait_for_selector("#editorPreviewBox .markdown-body", timeout=5000)
    page.wait_for_timeout(600)
    shot_11 = evidence_dir / "11_admin_safe_preview_1440.png"
    page.screenshot(path=str(shot_11))
    assert shot_11.exists()

    ctx_1440.close()
    print(f"[P07 Evidence] Successfully captured all 11 evidence screenshots in {evidence_dir}!")


def test_ib_r06_healthy_bm25_and_deliberate_fallback_evidence(
    live_server, browser_instance, active_lexical_index
):
    """
    IB-R06: Captures dedicated screenshots in a separate subdirectory ('p07_evidence_ib_r06')
    proving:
    1) Healthy BM25 path returns engine_used='bm25', is_degraded=False, displays BM25 badge,
       and has NO degraded banner.
    2) Deliberate missing-index fallback path returns engine_used='ilike_fallback', is_degraded=True,
       and displays the degraded banner.
    """
    ib_dir = get_artifact_context().get_screenshots_dir("p07_evidence_ib_r06")
    ib_dir.mkdir(parents=True, exist_ok=True)

    ctx = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    payloads = []
    page.on(
        "response",
        lambda r: payloads.append(r.json())
        if ("/api/v1/search" in r.url and r.status == 200)
        else None,
    )

    # 1. Healthy BM25 path
    page.goto(f"{live_server}/#/library?q=learning&mode=bm25")
    page.wait_for_selector(".document-card-row", timeout=10000)
    page.wait_for_timeout(500)

    assert payloads and payloads[-1]["engine_used"] == "bm25"
    assert payloads[-1]["is_degraded"] is False
    assert page.locator(".degraded-engine-banner").count() == 0
    assert page.locator(".telemetry-badge.badge-degraded").count() == 0
    assert "BM25" in page.locator(".search-telemetry-bar").text_content()

    healthy_shot = ib_dir / "01_healthy_bm25_desktop_1440.png"
    page.screenshot(path=str(healthy_shot))
    assert healthy_shot.exists()

    # 2. Deliberate fallback path (disable active lexical index generation in DB)
    db = TestingSessionLocal()
    try:
        for gen in db.query(IndexGeneration).all():
            gen.status = "failed"
        db.commit()
    finally:
        db.close()
    search_engine.clear_cache()

    page.goto(f"{live_server}/#/library?q=neural&mode=bm25")
    page.wait_for_selector(".degraded-engine-banner", timeout=10000)
    page.wait_for_timeout(500)

    assert payloads[-1]["engine_used"] == "ilike_fallback"
    assert payloads[-1]["is_degraded"] is True
    assert page.locator(".degraded-engine-banner").is_visible()
    assert "ILIKE_FALLBACK" in page.locator(".telemetry-badge.badge-degraded").text_content()

    fallback_shot = ib_dir / "02_deliberate_ilike_fallback_banner_1440.png"
    page.screenshot(path=str(fallback_shot))
    assert fallback_shot.exists()

    ctx.close()
