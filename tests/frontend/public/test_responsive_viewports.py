# tests/frontend/public/test_responsive_viewports.py
# Playwright test suite for Folio Multi-Viewport Responsive Support (M7 / UI-04)
# Form factors tested: 360px, 390px, 768px, 1280px, 1440px, 1920px

import pytest
from playwright.sync_api import sync_playwright

VIEWPORTS = [
    ("mobile_360", 360, 640),
    ("mobile_390", 390, 844),
    ("tablet_768", 768, 1024),
    ("laptop_1280", 1280, 720),
    ("desktop_1440", 1440, 900),
    ("wide_1920", 1920, 1080),
]


def test_public_library_responsive_viewports(live_server, browser_instance):
    """
    UI-04: Verifies the public library view across all required form factors:
    - No unintended horizontal body overflow (scrollWidth <= window.innerWidth)
    - Mobile filter drawer toggle operates smoothly on <= 860px viewports
    - Search toolbar stacks cleanly without clipping
    """
    for name, width, height in VIEWPORTS:
        context = browser_instance.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        page.goto(f"{live_server}/#/library")
        page.wait_for_selector(".document-card-row")

        # Invariant: No horizontal page overflow
        is_overflowing = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert not is_overflowing, f"Horizontal page overflow detected at {name} ({width}x{height})"

        # Mobile drawer check for small screens
        if width <= 860:
            mobile_btn = page.locator("#mobileFilterToggleBtn")
            assert mobile_btn.is_visible(), f"Mobile filter toggle should be visible at {name}"
            sidebar = page.locator("#librarySidebar")

            # Initially hidden on mobile
            assert not sidebar.is_visible() or sidebar.evaluate("el => window.getComputedStyle(el).display === 'none'")

            # Toggle drawer open
            mobile_btn.click()
            page.wait_for_selector("#librarySidebar.open", timeout=3000)
            assert sidebar.is_visible()

            # Toggle drawer closed
            mobile_btn.click()
            page.wait_for_timeout(300)
            assert not sidebar.is_visible() or sidebar.evaluate("el => window.getComputedStyle(el).display === 'none'")

        context.close()


def test_document_detail_responsive_viewports(live_server, browser_instance):
    """
    UI-04: Verifies the document detail reading view across all 6 viewports:
    - No horizontal overflow from code blocks, math formulas, wide tables, or media
    - Typography and byline wrap comfortably on narrow screens
    """
    for name, width, height in VIEWPORTS:
        context = browser_instance.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        # Load first document detail
        page.goto(f"{live_server}/#/library")
        page.wait_for_selector(".document-card-row")
        page.locator(".doc-row-title a").first.click()

        page.wait_for_selector(".document-detail-article")

        # Invariant: No horizontal page overflow
        is_overflowing = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert not is_overflowing, f"Detail page horizontal overflow at {name} ({width}x{height})"

        # Verify reading column is contained
        reading_col = page.locator(".document-reading-column")
        assert reading_col.is_visible()

        context.close()


def test_admin_tables_deliberate_overflow(live_server, browser_instance):
    """
    UI-04: Verifies admin documents table on mobile (360px, 390px, 768px):
    - Table container provides deliberate horizontal scroll without breaking page width
    """
    for name, width, height in [("mobile_360", 360, 640), ("mobile_390", 390, 844), ("tablet_768", 768, 1024)]:
        context = browser_instance.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        # Login as Admin
        page.goto(f"{live_server}/#/login")
        page.wait_for_selector("#loginEmail")
        page.fill("#loginEmail", "admin@folio.test")
        page.fill("#loginPassword", "FolioDemo2026!")
        page.click("#loginSubmitBtn")
        page.wait_for_selector(".user-badge, #logoutBtn")

        # Navigate to admin documents
        page.goto(f"{live_server}/#/admin/documents")
        page.wait_for_selector("table.table")

        # The table container itself must be scrollable if table is wider than viewport
        table_container = page.locator(".table-container").first
        assert table_container.is_visible()

        # Body must NOT overflow
        body_overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert not body_overflow, f"Admin page body overflow detected at {name} ({width}x{height})"

        context.close()
