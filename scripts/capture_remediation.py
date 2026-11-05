import os
import sys
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.artifact_utils import get_artifact_context

def main():
    parser = argparse.ArgumentParser(description="Capture visual verification screenshots for Folio remediation")
    parser.add_argument("-u", "--base-url", default=None, help="Target application URL (default: http://127.0.0.1:8002)")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory path (default: test-results/artifacts/<worktree>/<commit>/<run_id>/screenshots/remediation)")
    args = parser.parse_args()

    base_url = (args.base_url or os.environ.get("FOLIO_BASE_URL") or "http://127.0.0.1:8002").rstrip("/")
    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
    elif os.environ.get("FOLIO_SCREENSHOT_DIR"):
        out_dir = Path(os.environ["FOLIO_SCREENSHOT_DIR"]).resolve()
    else:
        out_dir = get_artifact_context().get_screenshots_dir("remediation")
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Library 1366x768
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.goto(f'{base_url}/#/library', wait_until='networkidle')
        page.wait_for_selector('.document-card-row', timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / 'library_1366x768.png'))

        # 2. Library 1440x900
        page.set_viewport_size({'width': 1440, 'height': 900})
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'library_1440x900.png'))

        # 3. Library 1280x720
        page.set_viewport_size({'width': 1280, 'height': 720})
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'library_1280x720.png'))

        # 4. Library 1920x1080
        page.set_viewport_size({'width': 1920, 'height': 1080})
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'library_1920x1080.png'))

        # 5. Document Detail with TOC & technical diagram (Deep learning)
        page.goto(f'{base_url}/#/documents/f7a024da-9f22-511a-9694-a0bce374a136', wait_until='networkidle')
        page.wait_for_selector('.document-toc', timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / 'document_detail_with_toc_1440x900.png'))

        # 6. Admin Login and Admin Documents table
        page.goto(f'{base_url}/#/login', wait_until='networkidle')
        page.fill('#loginEmail', 'admin@folio.test')
        page.fill('#loginPassword', 'FolioDemo2026!')
        page.click('#loginSubmitBtn')
        page.wait_for_selector('#shellUserMenu .user-badge', timeout=10000)

        # Admin Documents (with wide title and action dropdown)
        page.goto(f'{base_url}/#/admin/documents', wait_until='networkidle')
        page.wait_for_selector('.admin-sidebar-nav-container', timeout=10000)
        page.wait_for_selector('.action-dropdown-trigger', timeout=10000)
        page.wait_for_timeout(800)
        # Click first action dropdown to show the menu in screenshot
        page.locator('.action-dropdown-trigger').first.click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / 'admin_documents_1440x900.png'))

        # Admin Editor
        first_edit_link = page.locator('tbody tr td a.btn-primary').first.get_attribute('href')
        if first_edit_link:
            page.goto(f'{base_url}/{first_edit_link}', wait_until='networkidle')
            page.wait_for_selector('#editTitle', timeout=10000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(out_dir / 'admin_editor_1440x900.png'))
            # Click Preview tab to capture safe preview
            page.click('#tabPreview')
            page.wait_for_selector('.markdown-body', timeout=10000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(out_dir / 'admin_editor_preview_1440x900.png'))

        # Admin Analytics (with fixed 240px plot, readable Y-axis and thinned ticks)
        page.goto(f'{base_url}/#/admin/analytics', wait_until='networkidle')
        page.wait_for_selector('.analytics-totals-grid', timeout=10000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / 'admin_analytics_1440x900.png'))

        browser.close()

    print(f'All after remediation screenshots captured successfully in {out_dir}!')

if __name__ == '__main__':
    main()
