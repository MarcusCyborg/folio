import os
import sys
import time
import argparse
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.artifact_utils import get_artifact_context

def wait_for_server(base_url: str, timeout_sec: float = 15.0) -> bool:
    """Polls server readiness endpoint until responsive or timeout."""
    health_url = f"{base_url.rstrip('/')}/health"
    start = time.monotonic()
    print(f"Checking server readiness at {health_url}...")
    while time.monotonic() - start < timeout_sec:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    print(f"Server at {base_url} is ready!")
                    return True
        except Exception:
            time.sleep(0.1)
    return False

def launch_browser(playwright_ctx):
    """Launches Playwright Chromium with optional system channel fallback."""
    channel = os.environ.get("FOLIO_BROWSER_CHANNEL")
    if channel:
        try:
            return playwright_ctx.chromium.launch(channel=channel, headless=True)
        except Exception as e:
            print(f"Warning: Channel '{channel}' failed to launch ({e}); falling back to standard Chromium.")
    return playwright_ctx.chromium.launch(headless=True)

def run(base_url: str = None, output_dir: str = None):
    base_url = (base_url or os.environ.get("FOLIO_BASE_URL") or "http://127.0.0.1:8002").rstrip("/")
    if output_dir:
        out_path = Path(output_dir).resolve()
    elif os.environ.get("FOLIO_SCREENSHOT_DIR"):
        out_path = Path(os.environ["FOLIO_SCREENSHOT_DIR"]).resolve()
    else:
        out_path = get_artifact_context().get_screenshots_dir("public")
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"Starting screenshot capture targeting {base_url} -> {out_path}...")

    if not wait_for_server(base_url, timeout_sec=15.0):
        print(f"Error: Server at {base_url} is not responding. Please ensure the server is started.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = launch_browser(p)

        # 1. Library homepage (1366x768)
        print("Capturing 01_library_homepage.png (1366x768)...")
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(f"{base_url}/#/library", wait_until="networkidle")
        page.wait_for_selector(".document-card-row", timeout=15000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "01_library_homepage.png"),
            full_page=False,
        )

        # 2. Library desktop (1920x1080)
        print("Capturing 02_library_desktop.png (1920x1080)...")
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "02_library_desktop.png"),
            full_page=False,
        )

        # Reset viewport back to 1366x768 for subsequent shots
        page.set_viewport_size({"width": 1366, "height": 768})

        # 3. Library search results for "deep learning" (1366x768)
        print("Capturing 03_library_search_results.png...")
        page.goto(f"{base_url}/#/library", wait_until="networkidle")
        page.wait_for_selector("#librarySearchInput", timeout=10000)
        page.fill("#librarySearchInput", "deep learning")
        page.press("#librarySearchInput", "Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".document-card-row", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "03_library_search_results.png"),
            full_page=False,
        )

        # 4. Library category filter: "Artificial Intelligence & Machine Learning" (1366x768)
        print("Capturing 04_library_category_filter.png...")
        page.goto(f"{base_url}/#/library", wait_until="networkidle")
        page.wait_for_selector("#categoryFilterList", timeout=10000)
        page.wait_for_timeout(500)
        cat_btn = page.locator("#categoryFilterList button, .category-pill, .category-link").filter(has_text="Artificial Intelligence").first
        cat_btn.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".document-card-row", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "04_library_category_filter.png"),
            full_page=False,
        )

        # 5. Document detail: "Deep learning" (f7a024da-9f22-511a-9694-a0bce374a136) (1366x768)
        print("Capturing 05_document_detail.png...")
        doc_id = "f7a024da-9f22-511a-9694-a0bce374a136"
        page.goto(f"{base_url}/#/documents/{doc_id}", wait_until="networkidle")
        page.wait_for_selector(".document-toc", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "05_document_detail.png"),
            full_page=False,
        )

        # 6. Document detail scrolled down ~600px (1366x768)
        print("Capturing 06_document_detail_scrolled.png...")
        page.evaluate("window.scrollBy(0, 600)")
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "06_document_detail_scrolled.png"),
            full_page=False,
        )

        # 7. Login page (1366x768)
        print("Capturing 07_login_page.png...")
        page.goto(f"{base_url}/#/login", wait_until="networkidle")
        page.wait_for_selector("#loginForm", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "07_login_page.png"),
            full_page=False,
        )

        # 8. Register page (1366x768)
        print("Capturing 08_register_page.png...")
        page.goto(f"{base_url}/#/register", wait_until="networkidle")
        page.wait_for_selector("#registerForm", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(out_path / "08_register_page.png"),
            full_page=False,
        )

        browser.close()

    print(f"All 8 public page screenshots captured successfully in {out_path}!")

def main():
    parser = argparse.ArgumentParser(description="Capture visual verification screenshots for Folio public pages")
    parser.add_argument("-u", "--base-url", default=None, help="Target application URL (default: http://127.0.0.1:8002)")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory path (default: test-results/artifacts/<worktree>/<commit>/<run_id>/screenshots/public)")
    args = parser.parse_args()

    run(base_url=args.base_url, output_dir=args.output_dir)

if __name__ == "__main__":
    main()
