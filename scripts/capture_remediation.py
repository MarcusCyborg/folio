import os
from playwright.sync_api import sync_playwright

os.makedirs('docs/verification/remediation/after', exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()

    # 1. Library 1366x768
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.goto('http://127.0.0.1:8002/#/library', wait_until='networkidle')
    page.wait_for_selector('.document-card-row', timeout=10000)
    page.wait_for_timeout(800)
    page.screenshot(path='docs/verification/remediation/after/library_1366x768.png')

    # 2. Library 1440x900
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.wait_for_timeout(500)
    page.screenshot(path='docs/verification/remediation/after/library_1440x900.png')

    # 3. Library 1280x720
    page.set_viewport_size({'width': 1280, 'height': 720})
    page.wait_for_timeout(500)
    page.screenshot(path='docs/verification/remediation/after/library_1280x720.png')

    # 4. Library 1920x1080
    page.set_viewport_size({'width': 1920, 'height': 1080})
    page.wait_for_timeout(500)
    page.screenshot(path='docs/verification/remediation/after/library_1920x1080.png')

    # 5. Document Detail with TOC & technical diagram (Deep learning)
    page.goto('http://127.0.0.1:8002/#/documents/f7a024da-9f22-511a-9694-a0bce374a136', wait_until='networkidle')
    page.wait_for_selector('.document-toc', timeout=10000)
    page.wait_for_timeout(800)
    page.screenshot(path='docs/verification/remediation/after/document_detail_with_toc_1440x900.png')

    # 6. Admin Login and Admin Documents table
    page.goto('http://127.0.0.1:8002/#/login', wait_until='networkidle')
    page.fill('#loginEmail', 'admin@folio.test')
    page.fill('#loginPassword', 'FolioDemo2026!')
    page.click('#loginSubmitBtn')
    page.wait_for_selector('#shellUserMenu .user-badge', timeout=10000)

    # Admin Documents (with wide title and action dropdown)
    page.goto('http://127.0.0.1:8002/#/admin/documents', wait_until='networkidle')
    page.wait_for_selector('.admin-sidebar-nav-container', timeout=10000)
    page.wait_for_selector('.action-dropdown-trigger', timeout=10000)
    page.wait_for_timeout(800)
    # Click first action dropdown to show the menu in screenshot
    page.locator('.action-dropdown-trigger').first.click()
    page.wait_for_timeout(300)
    page.screenshot(path='docs/verification/remediation/after/admin_documents_1440x900.png')

    # Admin Editor
    first_edit_link = page.locator('tbody tr td a.btn-primary').first.get_attribute('href')
    if first_edit_link:
        page.goto(f'http://127.0.0.1:8002/{first_edit_link}', wait_until='networkidle')
        page.wait_for_selector('#editTitle', timeout=10000)
        page.wait_for_timeout(600)
        page.screenshot(path='docs/verification/remediation/after/admin_editor_1440x900.png')
        # Click Preview tab to capture safe preview
        page.click('#tabPreview')
        page.wait_for_selector('.markdown-body', timeout=10000)
        page.wait_for_timeout(600)
        page.screenshot(path='docs/verification/remediation/after/admin_editor_preview_1440x900.png')

    # Admin Analytics (with fixed 240px plot, readable Y-axis and thinned ticks)
    page.goto('http://127.0.0.1:8002/#/admin/analytics', wait_until='networkidle')
    page.wait_for_selector('.analytics-totals-grid', timeout=10000)
    page.wait_for_timeout(1000)
    page.screenshot(path='docs/verification/remediation/after/admin_analytics_1440x900.png')

    browser.close()

print('All after remediation screenshots captured successfully!')
