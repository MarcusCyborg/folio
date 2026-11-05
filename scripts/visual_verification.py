# scripts/visual_verification.py
# Captures visual evidence (Playwright Traces, Videos, and Screenshots) across required viewports,
# transition modes (native View Transitions, fallback, reduced motion), chip exit/reflow, and rapid navigation

import shutil
import socket
import threading
import http.server
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
import tests.frontend.public.test_motion_and_lifecycle as m

EVIDENCE_DIR = PROJECT_ROOT / "test-results" / "motion_evidence"
VIDEO_DIR = EVIDENCE_DIR / "videos"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def capture():
    port = m.get_free_port()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), m.QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    print(f"Server started at {base_url}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ======================================================================
        # 1. Recorded Video + Playwright Trace: Chip Exit/Reflow & Shared-Title Navigation (1440px)
        # ======================================================================
        print("Recording trace & video for chip exit/reflow and navigation (1440px)...", flush=True)
        temp_vid_1 = VIDEO_DIR / "_tmp_nav"
        temp_vid_1.mkdir(parents=True, exist_ok=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(temp_vid_1),
            record_video_size={"width": 1440, "height": 900},
        )
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        m.setup_mock_api(page)

        page.goto(f"{base_url}/#/library?q=quantum&category_id=cat-cs&tag_ids=tag-qc")
        page.wait_for_selector(".document-card-row")
        page.wait_for_timeout(300)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_library.png"), full_page=True)

        # Trigger chip exit animation on 'q' chip and capture mid-exit screenshot
        # Also track reflow animation events to generate verifiable completion evidence
        page.evaluate("""() => {
            window.__visualAnimLog = [];
            const origAnimate = Element.prototype.animate;
            Element.prototype.animate = function(...args) {
                const anim = origAnimate.apply(this, args);
                if (!this.classList.contains('active-filter-chip')) return anim;
                const key = this.getAttribute('data-chip-key');
                const isRemoving = this.classList.contains('chip-removing');
                const entry = {
                    key: key,
                    isRemoving: isRemoving,
                    startTime: performance.now(),
                    cancelled: false,
                    cancelTime: null,
                    finished: false,
                    finishTime: null,
                };
                anim.addEventListener('cancel', () => {
                    entry.cancelled = true;
                    entry.cancelTime = Math.round(performance.now() - entry.startTime);
                });
                anim.addEventListener('finish', () => {
                    entry.finished = true;
                    entry.finishTime = Math.round(performance.now() - entry.startTime);
                });
                window.__visualAnimLog.push(entry);
                return anim;
            };
        }""")

        page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
        page.wait_for_timeout(40)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_chip_removing_mid_animation.png"))
        page.wait_for_timeout(250)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_chip_reflow_finished.png"))

        # Save reflow animation completion log as proof
        anim_log = page.evaluate("() => window.__visualAnimLog || []")
        import json
        with open(EVIDENCE_DIR / "reflow_animation_log.json", "w", encoding="utf-8") as f:
            json.dump(anim_log, f, indent=2)

        # Evidence: Search failure and recovery state
        print("Capturing search failure & retry recovery screenshots...", flush=True)
        search_should_fail = {"val": True}
        def dynamic_search(route):
            if "q=failure" in route.request.url and search_should_fail["val"]:
                route.fulfill(status=500, content_type="application/json", body='{"detail": "Internal retrieval engine failure"}')
            elif "q=failure" in route.request.url:
                route.fulfill(status=200, content_type="application/json", body='''{
                    "items": [{"id": "doc-algo-1", "title": "Quantum Computing Fundamentals", "summary": "Overview", "category": {"id": "cat-cs", "name": "CS"}, "tags": []}],
                    "total": 1, "page": 1, "page_size": 15, "snapshot_total": 1, "engine_used": "bm25", "latency_ms": 11.2, "index_generation": "gen-retry"
                }''')
            else:
                route.continue_()
        page.route("**/api/v1/search*", dynamic_search)

        page.fill("#librarySearchInput", "failure")
        page.click("#librarySearchBtn")
        page.wait_for_selector("#documentsListContainer .notice.notice-error")
        page.wait_for_timeout(100)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_search_failure.png"), full_page=True)

        # Retry recovery
        search_should_fail["val"] = False
        page.locator("#documentsListContainer .notice.notice-error button").click()
        page.wait_for_selector("#documentsListContainer .document-card-row")
        page.wait_for_timeout(100)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_search_retry_success.png"), full_page=True)

        # Navigate to Document Detail via title click (Shared Title View Transition + Prefetch handoff)
        page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
        page.wait_for_selector(".document-detail-article")
        page.evaluate("() => window.scrollTo(0, 400)")
        page.wait_for_timeout(300)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_detail.png"), full_page=True)

        # Like pop animation
        page.locator("#likeBtn").click()
        page.wait_for_timeout(100)
        page.screenshot(path=str(EVIDENCE_DIR / "like_pop_active.png"))

        # Navigate back to Library
        page.locator("#detailBackLink").click()
        page.wait_for_selector(".document-card-row")
        page.wait_for_timeout(250)

        trace_path_1 = EVIDENCE_DIR / "trace_chip_and_navigation.zip"
        ctx.tracing.stop(path=str(trace_path_1))
        video_obj_1 = page.video
        ctx.close()
        if video_obj_1:
            target_vid_1 = EVIDENCE_DIR / "video_chip_exit_and_navigation_1440.webm"
            shutil.move(str(video_obj_1.path()), str(target_vid_1))
        shutil.rmtree(temp_vid_1, ignore_errors=True)

        # ======================================================================
        # 2. Recorded Video + Trace: Fallback Rapid Navigation & Mobile 390px Drawer
        # ======================================================================
        print("Recording trace & video for fallback rapid navigation and mobile 390px...", flush=True)
        temp_vid_2 = VIDEO_DIR / "_tmp_mobile"
        temp_vid_2.mkdir(parents=True, exist_ok=True)
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            record_video_dir=str(temp_vid_2),
            record_video_size={"width": 390, "height": 844},
        )
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        m.setup_mock_api(page)
        page.add_init_script("delete Document.prototype.startViewTransition;")

        page.goto(f"{base_url}/#/library")
        page.wait_for_selector(".document-card-row")
        page.locator("#mobileFilterToggleBtn").click()
        page.wait_for_selector("#librarySidebar.open")
        page.wait_for_timeout(250)
        page.screenshot(path=str(EVIDENCE_DIR / "mobile_390_drawer_open.png"), full_page=True)

        # Rapid navigation Library -> Detail -> Login under fallback mode
        page.evaluate("""() => {
            window.location.hash = '#/documents/doc-algo-1';
            setTimeout(() => { window.location.hash = '#/login'; }, 10);
        }""")
        page.wait_for_selector("#loginForm")
        page.wait_for_timeout(350)
        page.screenshot(path=str(EVIDENCE_DIR / "mobile_390_rapid_fallback_login.png"), full_page=True)

        # Navigate to Detail reading view at 390px
        page.goto(f"{base_url}/#/documents/doc-algo-1")
        page.wait_for_selector(".document-detail-article")
        page.wait_for_timeout(250)
        page.screenshot(path=str(EVIDENCE_DIR / "mobile_390_detail.png"), full_page=True)

        trace_path_2 = EVIDENCE_DIR / "trace_mobile_and_fallback_lifecycle.zip"
        ctx.tracing.stop(path=str(trace_path_2))
        video_obj_2 = page.video
        ctx.close()
        if video_obj_2:
            target_vid_2 = EVIDENCE_DIR / "video_mobile_390_and_fallback.webm"
            shutil.move(str(video_obj_2.path()), str(target_vid_2))
        shutil.rmtree(temp_vid_2, ignore_errors=True)

        # ======================================================================
        # 3. Tablet 768px, Breakpoint 860px, Mobile 360px, and Reduced Motion
        # ======================================================================
        print("Capturing tablet_768_date_accordion.png...", flush=True)
        ctx = browser.new_context(viewport={"width": 768, "height": 1024})
        page = ctx.new_page()
        m.setup_mock_api(page)
        page.goto(f"{base_url}/#/library?date_from=2026-01-01&date_to=2026-03-31")
        page.wait_for_selector(".document-card-row")
        page.wait_for_timeout(200)
        page.screenshot(path=str(EVIDENCE_DIR / "tablet_768_date_accordion.png"), full_page=True)
        ctx.close()

        print("Capturing breakpoint_860_drawer.png...", flush=True)
        ctx = browser.new_context(viewport={"width": 860, "height": 900})
        page = ctx.new_page()
        m.setup_mock_api(page)
        page.goto(f"{base_url}/#/library")
        page.wait_for_selector(".document-card-row")
        page.locator("#mobileFilterToggleBtn").click()
        page.wait_for_selector("#librarySidebar.open")
        page.wait_for_timeout(250)
        page.screenshot(path=str(EVIDENCE_DIR / "breakpoint_860_drawer.png"), full_page=True)
        ctx.close()

        print("Capturing mobile_360_library.png & reduced_motion_1440.png...", flush=True)
        ctx = browser.new_context(viewport={"width": 360, "height": 640}, reduced_motion="reduce")
        page = ctx.new_page()
        m.setup_mock_api(page)
        page.goto(f"{base_url}/#/library?q=quantum")
        page.wait_for_selector(".document-card-row")
        page.wait_for_timeout(150)
        page.screenshot(path=str(EVIDENCE_DIR / "mobile_360_library.png"), full_page=True)
        ctx.close()

        # ======================================================================
        # 4. Real Font Loading Verification (Without Rewrite)
        # ======================================================================
        print("Capturing desktop_1440_fonts_rendered.png & font network audit...", flush=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        m.setup_mock_api(page)
        font_net_log = []
        page.on("response", lambda r: font_net_log.append({"url": r.url, "status": r.status}) if ".woff2" in r.url else None)
        page.goto(f"{base_url}/#/library")
        page.wait_for_selector(".document-card-row")
        page.evaluate("""async () => {
            await Promise.all([
                document.fonts.load('400 16px "Source Sans 3"'),
                document.fonts.load('600 16px "Source Sans 3"'),
                document.fonts.load('700 16px "Source Sans 3"'),
                document.fonts.load('400 16px "Source Serif 4"'),
                document.fonts.load('700 16px "Source Serif 4"')
            ]);
        }""")
        page.wait_for_timeout(150)
        page.screenshot(path=str(EVIDENCE_DIR / "desktop_1440_fonts_rendered.png"), full_page=True)
        with open(EVIDENCE_DIR / "font_loading_log.json", "w", encoding="utf-8") as f:
            json.dump(font_net_log, f, indent=2)
        ctx.close()

        browser.close()

    server.shutdown()
    print("Visual verification videos, traces, and screenshots captured successfully!", flush=True)


if __name__ == '__main__':
    capture()
