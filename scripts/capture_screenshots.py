import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "screenshots"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "http://127.0.0.1:8002"

def run():
    print(f"Starting screenshot capture targeting {BASE_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. Library homepage (1366x768)
        print("Capturing 01_library_homepage.png (1366x768)...")
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(f"{BASE_URL}/#/library", wait_until="networkidle")
        page.wait_for_selector(".document-card-row", timeout=15000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "01_library_homepage.png"),
            full_page=False,
        )

        # 2. Library desktop (1920x1080)
        print("Capturing 02_library_desktop.png (1920x1080)...")
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "02_library_desktop.png"),
            full_page=False,
        )

        # Reset viewport back to 1366x768 for subsequent shots
        page.set_viewport_size({"width": 1366, "height": 768})

        # 3. Library search results for "deep learning" (1366x768)
        print("Capturing 03_library_search_results.png...")
        page.goto(f"{BASE_URL}/#/library", wait_until="networkidle")
        page.wait_for_selector("#librarySearchInput", timeout=10000)
        page.fill("#librarySearchInput", "deep learning")
        page.press("#librarySearchInput", "Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".document-card-row", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "03_library_search_results.png"),
            full_page=False,
        )

        # 4. Library category filter: "Artificial Intelligence & Machine Learning" (1366x768)
        print("Capturing 04_library_category_filter.png...")
        page.goto(f"{BASE_URL}/#/library", wait_until="networkidle")
        page.wait_for_selector("#categoryFilterList", timeout=10000)
        page.wait_for_timeout(500)
        # Find category button containing Artificial Intelligence
        cat_btn = page.locator("#categoryFilterList button, .category-pill, .category-link").filter(has_text="Artificial Intelligence").first
        cat_btn.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".document-card-row", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "04_library_category_filter.png"),
            full_page=False,
        )

        # 5. Document detail: "Deep learning" (f7a024da-9f22-511a-9694-a0bce374a136) (1366x768)
        print("Capturing 05_document_detail.png...")
        doc_id = "f7a024da-9f22-511a-9694-a0bce374a136"
        page.goto(f"{BASE_URL}/#/documents/{doc_id}", wait_until="networkidle")
        page.wait_for_selector(".document-toc", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "05_document_detail.png"),
            full_page=False,
        )

        # 6. Document detail scrolled down ~600px (1366x768)
        print("Capturing 06_document_detail_scrolled.png...")
        page.evaluate("window.scrollBy(0, 600)")
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "06_document_detail_scrolled.png"),
            full_page=False,
        )

        # 7. Login page (1366x768)
        print("Capturing 07_login_page.png...")
        page.goto(f"{BASE_URL}/#/login", wait_until="networkidle")
        page.wait_for_selector("#loginForm", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "07_login_page.png"),
            full_page=False,
        )

        # 8. Register page (1366x768)
        print("Capturing 08_register_page.png...")
        page.goto(f"{BASE_URL}/#/register", wait_until="networkidle")
        page.wait_for_selector("#registerForm", timeout=10000)
        page.wait_for_timeout(800)
        page.screenshot(
            path=os.path.join(OUTPUT_DIR, "08_register_page.png"),
            full_page=False,
        )

        browser.close()

    print("All 8 public page screenshots captured successfully!")

if __name__ == "__main__":
    run()
