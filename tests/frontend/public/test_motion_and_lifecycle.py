# tests/frontend/public/test_motion_and_lifecycle.py
# Comprehensive Playwright test suite for Folio Motion Tokens, In-Place Library Updates,
# View Transitions, Stale Render Guards, Prefetch Handoff, Chip Exit/Reflow & Focus,
# Reduced Motion, and Responsive Layouts

import os
import sys
import json
import socket
import threading
import http.server
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIR = PROJECT_ROOT / "src" / "frontend"


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        # 1. Serve favicon cleanly without 404 console noise
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def frontend_server():
    port = get_free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def setup_mock_api(page, *, simulate_like_fail=False, allow_expected_500=False):
    """
    Sets up deterministic route handlers for Folio public API endpoints and installs
    strict runtime error assertions (pageerror, unhandledrejection, unexpected 404s).
    Automatically verifies zero pageerrors and zero unhandled rejections when context closes.
    """
    page_errors = []
    unhandled_rejections = []
    unexpected_404s = []

    page._folio_page_errors = page_errors
    page._folio_unhandled_rejections = unhandled_rejections
    page._folio_unexpected_404s = unexpected_404s

    page.add_init_script("""
        window.__folioUnhandledRejections = [];
        window.addEventListener('unhandledrejection', (event) => {
            const reason = event.reason ? (event.reason.stack || event.reason.message || String(event.reason)) : 'unknown rejection';
            window.__folioUnhandledRejections.push(reason);
        });
    """)

    def on_console(msg):
        print(f"[Browser Console] {msg.type}: {msg.text}", flush=True)

    def on_pageerror(err):
        err_str = str(err)
        print(f"[Browser PageError] {err_str}", flush=True)
        page_errors.append(err_str)

    def on_response(resp):
        if resp.status == 404:
            unexpected_404s.append(resp.url)

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)

    # Wrap page.context.close so every test automatically fails if any pageerror,
    # unhandledrejection, or unexpected 404 occurred during the test lifecycle.
    ctx = page.context
    orig_close = ctx.close

    def strict_close():
        try:
            if not page.is_closed():
                js_rejections = page.evaluate("() => window.__folioUnhandledRejections || []")
                for r in js_rejections:
                    if r not in unhandled_rejections:
                        unhandled_rejections.append(r)
        except Exception:
            pass
        orig_close()
        assert len(page_errors) == 0, f"Unexpected pageerror(s) detected: {page_errors}"
        assert len(unhandled_rejections) == 0, f"Unexpected unhandledrejection(s) detected: {unhandled_rejections}"
        assert len(unexpected_404s) == 0, f"Unexpected 404 resource(s) detected: {unexpected_404s}"

    ctx.close = strict_close

    # Settings
    page.route("**/api/v1/settings/public", lambda r: r.fulfill(
        status=200,
        content_type="application/json",
        body='{"site_name": "Folio", "site_description": "Knowledge & Research Library", "registration_enabled": true, "comments_enabled": true}'
    ))

    # Auth session
    def handle_session(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"user": {"id": "user-1", "username": "scholar", "display_name": "Dr. Marie Curie", "role_key": "scholar"}, "csrf_token": "test-csrf"}'
        )

    page.route("**/api/v1/auth/session", handle_session)
    page.route("**/api/v1/auth/me", handle_session)

    # Categories
    page.route("**/api/v1/categories*", lambda r: r.fulfill(
        status=200,
        content_type="application/json",
        body='''{
            "items": [
                {"id": "cat-cs", "name": "Computer Science", "published_document_count": 42},
                {"id": "cat-math", "name": "Mathematics & Logic", "published_document_count": 28},
                {"id": "cat-phys", "name": "Theoretical Physics", "published_document_count": 19}
            ],
            "total": 3,
            "page": 1,
            "page_size": 50
        }'''
    ))

    # Documents catalog
    def handle_docs(route):
        url = route.request.url
        cat_id = "cat-cs" if "category_id=cat-cs" in url else "cat-math"
        body = f'''{{
            "items": [
                {{
                    "id": "doc-algo-1",
                    "title": "Quantum Computing Fundamentals & Circuit Complexity",
                    "summary": "An extensive overview of quantum gate logic, Shor algorithm, and circuit depth.",
                    "category": {{"id": "{cat_id}", "name": "Computer Science"}},
                    "author": "Richard Feynman",
                    "created_at": "2026-01-15T10:00:00Z",
                    "published_at": "2026-01-15T10:00:00Z",
                    "views_count": 1420,
                    "likes_count": 88,
                    "tags": [{{"id": "tag-qc", "name": "Quantum"}}],
                    "score": 0.954
                }},
                {{
                    "id": "doc-algo-2",
                    "title": "Neural Network Generalization Bounds and PAC-Bayes Theory",
                    "summary": "Mathematical foundations for statistical generalization bounds in deep representations.",
                    "category": {{"id": "cat-math", "name": "Mathematics & Logic"}},
                    "author": "Leslie Valiant",
                    "created_at": "2026-02-10T12:00:00Z",
                    "published_at": "2026-02-10T12:00:00Z",
                    "views_count": 890,
                    "likes_count": 52,
                    "tags": [{{"id": "tag-ml", "name": "Machine Learning"}}],
                    "score": 0.821
                }}
            ],
            "total": 2,
            "page": 1,
            "page_size": 15
        }}'''
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/api/v1/documents?*", handle_docs)
    page.route("**/api/v1/documents", handle_docs)

    # Search API
    def handle_search(route):
        url = route.request.url
        if "q=quantum" in url:
            q_term = "quantum"
            doc_id = "doc-algo-1"
            doc_title = "Quantum Computing Fundamentals & Circuit Complexity"
        else:
            q_term = "neural"
            doc_id = "doc-algo-2"
            doc_title = "Neural Network Generalization Bounds and PAC-Bayes Theory"

        body = f'''{{
            "items": [
                {{
                    "id": "{doc_id}",
                    "title": "{doc_title}",
                    "summary": "An extensive overview of {q_term} research and theoretical foundations.",
                    "snippet": "An extensive overview of <em class=\\"search-highlight\\">{q_term}</em> gate logic.",
                    "category": {{"id": "cat-cs", "name": "Computer Science"}},
                    "author": "Richard Feynman",
                    "created_at": "2026-01-15T10:00:00Z",
                    "published_at": "2026-01-15T10:00:00Z",
                    "views_count": 1420,
                    "likes_count": 88,
                    "tags": [{{"id": "tag-qc", "name": "Quantum"}}],
                    "score": 0.982,
                    "rank": 1
                }}
            ],
            "total": 1,
            "snapshot_total": 1,
            "page": 1,
            "page_size": 15,
            "search_event_id": "evt-test-1234",
            "search_context_token": "token-test-5678",
            "latency_ms": 14.2,
            "engine_used": "bm25",
            "is_degraded": false
        }}'''
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/api/v1/search*", handle_search)

    # Single Document Detail: doc-algo-1
    page.route("**/api/v1/documents/doc-algo-1", lambda r: r.fulfill(
        status=200,
        content_type="application/json",
        body='''{
            "id": "doc-algo-1",
            "title": "Quantum Computing Fundamentals & Circuit Complexity",
            "summary": "An extensive overview of quantum gate logic, Shor algorithm, and circuit depth.",
            "rendered_content": "<h2 id=\\"section-1\\">Introduction to Qubits</h2><p>Quantum bits represent superposition states of |0> and |1> simultaneously.</p><div style=\\"height:600px;\\">Spacer paragraph for scroll testing.</div><h2 id=\\"section-2\\">Quantum Fourier Transform</h2><p>The quantum Fourier transform enables exponential speedup in phase estimation.</p><div style=\\"height:600px;\\">Second spacer paragraph.</div><h2 id=\\"section-3\\">Complexity Classes</h2><p>BQP versus NP characterization remains one of the premier open problems.</p><div style=\\"height:600px;\\">Third spacer.</div>",
            "category": {"id": "cat-cs", "name": "Computer Science"},
            "author": "Richard Feynman",
            "created_at": "2026-01-15T10:00:00Z",
            "published_at": "2026-01-15T10:00:00Z",
            "views_count": 1420,
            "likes_count": 88,
            "liked_by_me": false,
            "comments_count": 3,
            "tags": [{"id": "tag-qc", "name": "Quantum"}]
        }'''
    ))

    # Single Document Detail: doc-algo-2
    page.route("**/api/v1/documents/doc-algo-2", lambda r: r.fulfill(
        status=200,
        content_type="application/json",
        body='''{
            "id": "doc-algo-2",
            "title": "Neural Network Generalization Bounds and PAC-Bayes Theory",
            "summary": "Mathematical foundations for statistical generalization bounds in deep representations.",
            "rendered_content": "<h2 id=\\"nn-sec-1\\">PAC-Bayes Bounds</h2><p>Statistical learning theory provides rigorous generalization guarantees.</p><div style=\\"height:600px;\\">NN Spacer paragraph.</div><h2 id=\\"nn-sec-2\\">Rademacher Complexity</h2><p>Empirical complexity measures of hypothesis classes.</p>",
            "category": {"id": "cat-math", "name": "Mathematics & Logic"},
            "author": "Leslie Valiant",
            "created_at": "2026-02-10T12:00:00Z",
            "published_at": "2026-02-10T12:00:00Z",
            "views_count": 890,
            "likes_count": 52,
            "liked_by_me": false,
            "comments_count": 0,
            "tags": [{"id": "tag-ml", "name": "Machine Learning"}]
        }'''
    ))

    # Like / Unlike
    def handle_like(route):
        if simulate_like_fail:
            route.fulfill(status=500, content_type="application/json", body='{"message": "Like service timeout"}')
            return
        if route.request.method == "PUT":
            route.fulfill(status=200, content_type="application/json", body='{"liked_by_me": true, "likes_count": 89}')
        else:
            route.fulfill(status=200, content_type="application/json", body='{"liked_by_me": false, "likes_count": 88}')

    page.route("**/api/v1/documents/*/like", handle_like)

    # Views & Click telemetry
    page.route("**/api/v1/documents/*/views", lambda r: r.fulfill(status=200, content_type="application/json", body='{"status": "ok"}'))
    page.route("**/api/v1/events/clicks", lambda r: r.fulfill(status=200, content_type="application/json", body='{"status": "ok"}'))
    page.route("**/api/v1/documents/*/comments*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"items": [], "total": 0, "page": 1, "page_size": 10}'))


# ==============================================================================
# FINDING A — P1: TÌM KIẾM TRONG INITIAL LOAD LÀM LIBRARY BỊ KẸT (A1–A5)
# ==============================================================================

def _run_a1_scenario(frontend_server, playwright_instance, reduced_motion: bool):
    context = playwright_instance.new_context(
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce" if reduced_motion else "no-preference",
    )
    page = context.new_page()
    setup_mock_api(page)

    held_initial_docs = []

    def hold_initial_docs(route):
        held_initial_docs.append(route)

    page.route("**/api/v1/documents?*", hold_initial_docs)

    # 1. Open #/library; categories finish loading while initial documents request is held
    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".category-pill[data-cat-id='cat-cs']")
    assert len(held_initial_docs) == 1

    # 2. Submit search "quantum" while initial documents request is still pending
    search_input = page.locator("#librarySearchInput")
    search_input.fill("quantum")
    page.locator("#librarySearchBtn").click()

    # 3. Search response returns; verify Library is NOT stuck in "Searching for 'quantum'..."
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']", timeout=3000)

    # 4. If the old initial documents request resolves late, it must not overwrite search state
    for r in held_initial_docs:
        try:
            r.fulfill(
                status=200,
                content_type="application/json",
                body='{"items": [{"id": "doc-stale", "title": "Stale Initial Doc", "category": {"id": "cat-cs", "name": "CS"}, "tags": []}], "total": 1, "page": 1, "page_size": 15}'
            )
        except Exception:
            pass

    page.wait_for_timeout(100)

    assert "#/library?q=quantum" in page.url
    assert search_input.input_value() == "quantum"
    assert page.title() == 'Search: "quantum" — Folio'
    assert "Found 1 result for \"quantum\"" in page.locator("#resultsCountText").text_content()
    assert page.locator("#documentsListContainer").get_attribute("aria-busy") == "false"
    assert not page.locator("#documentsListContainer").evaluate("el => el.classList.contains('is-updating')")
    cards_text = page.locator("#documentsListContainer").text_content()
    assert "Quantum Computing Fundamentals" in cards_text
    assert "Stale Initial Doc" not in cards_text

    # 5. Verify continued interactivity (clicking a category updates route and results)
    page.locator(".category-pill[data-cat-id='cat-cs']").click()
    page.wait_for_function("() => window.location.hash.includes('category_id=cat-cs')")
    assert "category_id=cat-cs" in page.url

    context.close()


def test_a1_a5_search_during_initial_load_normal_and_reduced_motion(frontend_server, playwright_instance):
    """
    Finding A (A1 & A5):
    Categories load, initial documents held; user submits query; search response arrives ->
    results render, pending state clears, document.title stays accurate, page stays interactive.
    Tested with both normal motion and prefers-reduced-motion: reduce.
    """
    _run_a1_scenario(frontend_server, playwright_instance, reduced_motion=False)
    _run_a1_scenario(frontend_server, playwright_instance, reduced_motion=True)


def test_a2_query_change_while_categories_pending(frontend_server, playwright_instance):
    """
    Finding A (A2):
    Change query/filter while /categories AND initial /documents are both still pending.
    After releasing requests, final state (URL, input, title, category pills, chips, cards)
    matches current URL.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    held_categories = []
    held_docs = []
    held_search = []

    page.route("**/api/v1/categories*", lambda r: held_categories.append(r))
    page.route("**/api/v1/documents?*", lambda r: held_docs.append(r))
    page.route("**/api/v1/search*", lambda r: held_search.append(r))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector("#librarySearchInput")
    assert len(held_categories) >= 1

    # Change query while categories are still pending
    page.evaluate("() => window.location.hash = '#/library?q=quantum&category_id=cat-cs'")
    page.wait_for_function("() => window.location.hash.includes('q=quantum')")

    # Release search first, then categories
    for _ in range(20):
        if len(held_search) > 0:
            break
        page.wait_for_timeout(20)
    assert len(held_search) > 0

    for r in held_search:
        r.fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "items": [{
                    "id": "doc-algo-1",
                    "title": "Quantum Computing Fundamentals & Circuit Complexity",
                    "summary": "Quantum gate logic",
                    "snippet": "Overview of <em class=\\"search-highlight\\">quantum</em> gates.",
                    "category": {"id": "cat-cs", "name": "Computer Science"},
                    "author": "Richard Feynman",
                    "created_at": "2026-01-15T10:00:00Z",
                    "published_at": "2026-01-15T10:00:00Z",
                    "views_count": 1420,
                    "likes_count": 88,
                    "tags": [],
                    "score": 0.98,
                    "rank": 1
                }],
                "total": 1, "snapshot_total": 1, "page": 1, "page_size": 15,
                "search_event_id": "evt-a2", "search_context_token": "tok-a2",
                "latency_ms": 10.5, "engine_used": "bm25", "is_degraded": false
            }'''
        )

    for r in held_categories:
        r.fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "items": [
                    {"id": "cat-cs", "name": "Computer Science", "published_document_count": 42},
                    {"id": "cat-math", "name": "Mathematics & Logic", "published_document_count": 28}
                ],
                "total": 2, "page": 1, "page_size": 50
            }'''
        )

    for r in held_docs:
        try:
            r.fulfill(status=200, content_type="application/json", body='{"items": [], "total": 0, "page": 1, "page_size": 15}')
        except Exception:
            pass

    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")
    page.wait_for_selector(".category-pill[data-cat-id='cat-cs'].active")

    assert "#/library?q=quantum&category_id=cat-cs" in page.url
    assert page.locator("#librarySearchInput").input_value() == "quantum"
    assert page.title() == 'Search: "quantum" — Folio'
    assert "Computer Science" in page.locator("#activeFiltersBar").text_content()
    assert page.locator("#documentsListContainer").get_attribute("aria-busy") == "false"

    context.close()


def test_a3_leave_library_before_initial_load_completes(frontend_server, playwright_instance):
    """
    Finding A (A3):
    Leave Library for #/login before initial load (categories/documents) finishes;
    when old responses return, the new page (#/login) must not have its DOM, title, or state mutated.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    held_categories = []
    held_docs = []

    page.route("**/api/v1/categories*", lambda r: held_categories.append(r))
    page.route("**/api/v1/documents?*", lambda r: held_docs.append(r))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector("#librarySearchInput")

    # Navigate to #/login while Library initial load is still pending
    page.evaluate("() => window.location.hash = '#/login'")
    page.wait_for_selector("#loginForm")
    assert page.title() == "Sign In — Folio"

    # Release old responses
    for r in held_categories:
        try:
            r.fulfill(status=200, content_type="application/json", body='{"items": [{"id": "cat-cs", "name": "CS", "published_document_count": 1}], "total": 1, "page": 1, "page_size": 50}')
        except Exception:
            pass
    for r in held_docs:
        try:
            r.fulfill(status=200, content_type="application/json", body='{"items": [{"id": "doc-algo-1", "title": "Quantum", "category": {"id": "cat-cs", "name": "CS"}, "tags": []}], "total": 1, "page": 1, "page_size": 15}')
        except Exception:
            pass

    page.wait_for_timeout(150)

    assert "#/login" in page.url
    assert page.title() == "Sign In — Folio"
    assert page.locator("#loginForm").is_visible()
    assert page.locator(".library-layout").count() == 0

    context.close()


def test_a4_out_of_order_search_responses_latest_wins(frontend_server, playwright_instance):
    """
    Finding A (A4):
    Query A ('quantum') then Query B ('neural'); fulfill B first, then fulfill A -> B wins.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    held_a = []
    held_b = []

    def handle_search_race(route):
        if "q=quantum" in route.request.url:
            held_a.append(route)
        elif "q=neural" in route.request.url:
            held_b.append(route)
        else:
            route.continue_()

    page.route("**/api/v1/search*", handle_search_race)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Trigger Query A
    page.locator("#librarySearchInput").fill("quantum")
    page.locator("#librarySearchBtn").click()
    page.wait_for_function("() => window.location.hash.includes('q=quantum')")

    # Trigger Query B while A is pending
    page.locator("#librarySearchInput").fill("neural")
    page.locator("#librarySearchBtn").click()
    page.wait_for_function("() => window.location.hash.includes('q=neural')")

    for _ in range(20):
        if len(held_b) > 0:
            break
        page.wait_for_timeout(20)
    assert len(held_b) == 1

    # Fulfill B first
    held_b[0].fulfill(
        status=200,
        content_type="application/json",
        body='''{
            "items": [{"id": "doc-algo-2", "title": "Neural Network Generalization Bounds", "summary": "PAC-Bayes", "category": {"id": "cat-math", "name": "Math"}, "tags": [], "score": 0.95, "rank": 1}],
            "total": 1, "snapshot_total": 1, "page": 1, "page_size": 15, "engine_used": "bm25", "is_degraded": false
        }'''
    )
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-2']")

    # Fulfill A second (stale response)
    for r in held_a:
        try:
            r.fulfill(
                status=200,
                content_type="application/json",
                body='''{
                    "items": [{"id": "doc-algo-1", "title": "Quantum Stale Winner", "summary": "Stale", "category": {"id": "cat-cs", "name": "CS"}, "tags": [], "score": 0.99, "rank": 1}],
                    "total": 1, "snapshot_total": 1, "page": 1, "page_size": 15, "engine_used": "bm25", "is_degraded": false
                }'''
            )
        except Exception:
            pass

    page.wait_for_timeout(120)

    assert "#/library?q=neural" in page.url
    assert page.locator("#librarySearchInput").input_value() == "neural"
    assert page.title() == 'Search: "neural" — Folio'
    assert "Neural Network Generalization Bounds" in page.locator("#documentsListContainer").text_content()
    assert "Quantum Stale Winner" not in page.locator("#documentsListContainer").text_content()
    assert page.locator("#documentsListContainer").get_attribute("aria-busy") == "false"

    context.close()


# ==============================================================================
# FINDING B — P1: CALLBACK MOUNT CŨ GHI ĐÈ NAVIGATION MỚI (B1–B5)
# ==============================================================================

def test_b1_fallback_transition_stale_mount_does_not_overwrite_login(frontend_server, playwright_instance):
    """
    Finding B (B1):
    View Transitions API is absent (typeof document.startViewTransition === 'undefined').
    Navigate Library -> Detail -> Login while fallback fadeOut is in progress.
    After fallback animation finishes, URL and DOM must be Login (#loginForm), with NO detail-page-container.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.add_init_script("delete Document.prototype.startViewTransition;")

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    vt_type = page.evaluate("() => typeof document.startViewTransition")
    assert vt_type == "undefined", f"Expected undefined, got {vt_type}"

    # Navigate to Detail and then 10ms later to Login while fallback fadeOut is active
    page.evaluate("""() => {
        window.location.hash = '#/documents/doc-algo-1';
        setTimeout(() => {
            window.location.hash = '#/login';
        }, 10);
    }""")

    page.wait_for_selector("#loginForm")
    # Wait past full fallback fadeOut + fadeIn duration (300ms+) to ensure old callback completed
    page.wait_for_timeout(350)

    assert "#/login" in page.url
    assert page.title() == "Sign In — Folio"
    assert page.locator("#loginForm").is_visible()
    assert page.locator(".detail-page-container").count() == 0
    assert "Loading document..." not in page.locator("#app").text_content()

    context.close()


def test_b2_rapid_navigation_detail_a_detail_b_library(frontend_server, playwright_instance):
    """
    Finding B (B2):
    Rapidly navigate Detail A -> Detail B -> Library; final state after all transitions settle is Library.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.add_init_script("delete Document.prototype.startViewTransition;")

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.evaluate("""() => {
        window.location.hash = '#/documents/doc-algo-1';
        setTimeout(() => { window.location.hash = '#/documents/doc-algo-2'; }, 10);
        setTimeout(() => { window.location.hash = '#/library'; }, 25);
    }""")

    page.wait_for_function("() => window.location.hash === '#/library'")
    page.wait_for_selector(".document-card-row")
    page.wait_for_timeout(350)

    assert "#/library" in page.url
    assert page.title() == "Library Catalog — Folio"
    assert page.locator(".library-layout").count() == 1
    assert page.locator(".detail-page-container").count() == 0

    context.close()


def test_b3_native_view_transition_superseded_by_new_navigation(frontend_server, playwright_instance):
    """
    Finding B (B3):
    With real View Transitions API active, starting a new navigation while the previous transition
    is still in flight cleanly skips/supersedes the old transition without pageerrors or stale DOM.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    vt_type = page.evaluate("() => typeof document.startViewTransition")
    assert vt_type == "function"

    # Trigger Detail A transition, then immediately Detail B, then Login
    page.evaluate("""() => {
        window.location.hash = '#/documents/doc-algo-1';
        Promise.resolve().then(() => {
            window.location.hash = '#/documents/doc-algo-2';
        });
        setTimeout(() => {
            window.location.hash = '#/login';
        }, 15);
    }""")

    page.wait_for_selector("#loginForm")
    page.wait_for_timeout(400)

    assert "#/login" in page.url
    assert page.title() == "Sign In — Folio"
    assert page.locator("#loginForm").is_visible()
    assert page.locator(".detail-page-container").count() == 0

    context.close()


def test_b4_reduced_motion_no_stale_commit(frontend_server, playwright_instance):
    """
    Finding B (B4):
    Under prefers-reduced-motion: reduce, rapid navigations never produce stale DOM commits.
    """
    context = playwright_instance.new_context(
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.evaluate("""() => {
        window.location.hash = '#/documents/doc-algo-1';
        window.location.hash = '#/login';
        window.location.hash = '#/documents/doc-algo-2';
    }""")

    page.wait_for_selector(".document-detail-article")
    page.wait_for_timeout(150)

    assert "#/documents/doc-algo-2" in page.url
    assert "Neural Network Generalization Bounds" in page.locator(".detail-title").text_content()
    assert page.locator("#loginForm").count() == 0
    assert page.locator(".detail-page-container").count() == 1

    context.close()


def test_b5_mount_callback_not_executed_twice_on_error(frontend_server, playwright_instance):
    """
    Finding B (B5):
    When a route render throws an error during View Transition or fallback, executeMount / render
    is invoked strictly once (never twice), and the error reaches the router error boundary.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Test withViewTransition directly in browser module context for both native VT and fallback
    result = page.evaluate("""async () => {
        const motion = await import('/core/motion.js');
        let nativeCount = 0;
        let nativeCaught = null;
        try {
            await motion.withViewTransition(() => {
                nativeCount++;
                throw new Error('Synthetic render failure');
            });
        } catch (err) {
            nativeCaught = err.message;
        }

        const savedSVT = document.startViewTransition;
        delete Document.prototype.startViewTransition;
        let fallbackCount = 0;
        let fallbackCaught = null;
        const dummy = document.createElement('div');
        document.body.appendChild(dummy);
        try {
            await motion.withViewTransition(() => {
                fallbackCount++;
                throw new Error('Synthetic fallback failure');
            }, { fallbackContainer: dummy });
        } catch (err) {
            fallbackCaught = err.message;
        } finally {
            dummy.remove();
            if (savedSVT) Document.prototype.startViewTransition = savedSVT;
        }

        return { nativeCount, nativeCaught, fallbackCount, fallbackCaught };
    }""")

    assert result["nativeCount"] == 1, f"Expected native updateFn to run once, ran {result['nativeCount']}"
    assert result["nativeCaught"] == "Synthetic render failure"
    assert result["fallbackCount"] == 1, f"Expected fallback updateFn to run once, ran {result['fallbackCount']}"
    assert result["fallbackCaught"] == "Synthetic fallback failure"

    context.close()


# ==============================================================================
# FINDING C — P2: PREFETCH BỊ HỦY TRƯỚC KHI DETAIL NHẬN REQUEST (C1–C5)
# ==============================================================================

def test_c1_single_click_opens_detail_with_one_get_and_no_pageerror(frontend_server, playwright_instance):
    """
    Finding C (C1):
    Clicking a document title in Library issues strictly ONE GET /api/v1/documents/doc-algo-1 request
    (reusing the prefetched promise) with zero pageerrors and zero unhandled rejections.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    detail_requests = []

    def track_detail(route):
        detail_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "id": "doc-algo-1",
                "title": "Quantum Computing Fundamentals & Circuit Complexity",
                "summary": "Quantum gate logic",
                "rendered_content": "<h2>Section 1</h2><p>Body</p>",
                "category": {"id": "cat-cs", "name": "Computer Science"},
                "author": "Richard Feynman",
                "created_at": "2026-01-15T10:00:00Z",
                "published_at": "2026-01-15T10:00:00Z",
                "views_count": 1420,
                "likes_count": 88,
                "liked_by_me": false,
                "comments_count": 0,
                "tags": []
            }'''
        )

    page.route("**/api/v1/documents/doc-algo-1", track_detail)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    page.wait_for_selector(".document-detail-article")
    page.wait_for_timeout(150)

    assert len(detail_requests) == 1, f"Expected exactly 1 GET /documents/doc-algo-1, got {len(detail_requests)}"
    assert "Quantum Computing Fundamentals" in page.locator(".detail-title").text_content()

    context.close()


def test_c2_abandoned_prefetch_does_not_overwrite_or_throw_pageerror(frontend_server, playwright_instance):
    """
    Finding C (C2):
    Click document link (starting prefetch), then immediately abandon navigation to #/login
    while prefetch is pending. Must not overwrite #/login and must not emit any pageerror.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    held_detail = []
    page.route("**/api/v1/documents/doc-algo-1", lambda r: held_detail.append(r))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    page.evaluate("() => window.location.hash = '#/login'")
    page.wait_for_selector("#loginForm")

    for r in held_detail:
        try:
            r.fulfill(
                status=200,
                content_type="application/json",
                body='{"id": "doc-algo-1", "title": "Quantum", "summary": "S", "rendered_content": "<p>Body</p>", "created_at": "2026-01-15T10:00:00Z", "views_count": 1, "likes_count": 1}'
            )
        except Exception:
            pass

    page.wait_for_timeout(250)
    assert "#/login" in page.url
    assert page.locator("#loginForm").is_visible()
    assert page.locator(".detail-page-container").count() == 0

    context.close()


def test_c3_detail_request_error_renders_error_state_and_retry_works(frontend_server, playwright_instance):
    """
    Finding C (C3):
    When prefetched/detail request fails with HTTP 500, Detail renders an explicit error state
    (not null/blank) and clicking Retry succeeds once the endpoint recovers.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page, allow_expected_500=True)

    should_fail = {"value": True}

    def detail_handler(route):
        if should_fail["value"]:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error": {"code": "INTERNAL_ERROR", "message": "Database temporarily unavailable"}}'
            )
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='''{
                    "id": "doc-algo-1",
                    "title": "Quantum Computing Fundamentals & Circuit Complexity",
                    "summary": "Recovered summary",
                    "rendered_content": "<p>Recovered content body</p>",
                    "category": {"id": "cat-cs", "name": "Computer Science"},
                    "author": "Richard Feynman",
                    "created_at": "2026-01-15T10:00:00Z",
                    "published_at": "2026-01-15T10:00:00Z",
                    "views_count": 1420,
                    "likes_count": 88,
                    "liked_by_me": false,
                    "comments_count": 0,
                    "tags": []
                }'''
            )

    page.route("**/api/v1/documents/doc-algo-1", detail_handler)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    page.wait_for_selector(".detail-page-container .notice-error")
    assert "Could not load research document" in page.locator(".detail-page-container .notice-error").text_content()

    # Recover server and click Retry
    should_fail["value"] = False
    page.locator(".detail-page-container .notice-error button").click()
    page.wait_for_selector(".document-detail-article")
    assert "Quantum Computing Fundamentals" in page.locator(".detail-title").text_content()

    context.close()


def test_c4_c5_telemetry_single_fire_and_no_late_abandoned_view(frontend_server, playwright_instance):
    """
    Finding C (C4 & C5):
    - Rapid navigation A -> B does not send late view telemetry for abandoned A.
    - Normal search result click -> Detail logs strictly 1 click event and 1 view event (no duplication).
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    click_events = []
    view_events = []
    held_doc_a = []

    page.route("**/api/v1/events/clicks", lambda r: (click_events.append(r.request.post_data_json), r.fulfill(status=200, content_type="application/json", body='{"status":"ok"}')))
    page.route("**/api/v1/documents/*/views", lambda r: (view_events.append(r.request.url), r.fulfill(status=200, content_type="application/json", body='{"status":"ok"}')))
    page.route("**/api/v1/documents/doc-algo-1", lambda r: held_doc_a.append(r))

    # Search so search_event_id is present on cards
    page.goto(f"{frontend_server}/#/library?q=quantum")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")

    # Click Doc A (logs 1 click event, starts Doc A fetch which is held)
    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    assert len(click_events) == 1
    assert click_events[0]["document_id"] == "doc-algo-1"

    # Immediately navigate to Doc B before Doc A finishes
    page.evaluate("() => window.location.hash = '#/documents/doc-algo-2'")
    page.wait_for_selector(".document-detail-article")

    # Release Doc A late
    for r in held_doc_a:
        try:
            r.fulfill(
                status=200,
                content_type="application/json",
                body='{"id": "doc-algo-1", "title": "Quantum", "summary": "S", "rendered_content": "<p>Body</p>", "created_at": "2026-01-15T10:00:00Z", "views_count": 1, "likes_count": 1}'
            )
        except Exception:
            pass

    page.wait_for_timeout(150)

    doc_a_views = [u for u in view_events if "doc-algo-1/views" in u]
    doc_b_views = [u for u in view_events if "doc-algo-2/views" in u]
    assert len(doc_a_views) == 0, f"Abandoned Doc A must not fire view telemetry: {view_events}"
    assert len(doc_b_views) == 1, f"Completed Doc B must fire exactly 1 view telemetry event: {view_events}"

    context.close()


# ==============================================================================
# FINDING D — P2: CHIP EXIT/REFLOW CHƯA HOẠT ĐỘNG THỰC TẾ (D1–D6)
# ==============================================================================

def test_d1_remove_one_chip_preserves_focus_and_dom_identity(frontend_server, playwright_instance):
    """
    Finding D (D1):
    When removing one chip among multiple chips:
    - Focus moves immediately to the nearest remaining valid chip button (never drops to BODY).
    - Remaining unchanged chips keep their exact DOM node identity.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs&tag_ids=tag-qc")
    page.wait_for_selector(".active-filter-chip[data-chip-key='category_id']")

    # Tag remaining chips with custom DOM properties to prove node identity preservation
    page.evaluate("""() => {
        const catChip = document.querySelector(".active-filter-chip[data-chip-key='category_id']");
        const tagChip = document.querySelector(".active-filter-chip[data-chip-key='tag_ids']");
        if (catChip) catChip.__domIdentity = 'same-cat-node';
        if (tagChip) tagChip.__domIdentity = 'same-tag-node';
    }""")

    q_remove_btn = page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn")
    q_remove_btn.focus()
    page.keyboard.press("Enter")

    # Focus must immediately be on the category chip's remove button, never BODY
    active_info = page.evaluate("""() => ({
        tag: document.activeElement?.tagName,
        chipKey: document.activeElement?.closest('.active-filter-chip')?.getAttribute('data-chip-key'),
        catIdentity: document.querySelector(".active-filter-chip[data-chip-key='category_id']")?.__domIdentity,
        tagIdentity: document.querySelector(".active-filter-chip[data-chip-key='tag_ids']")?.__domIdentity,
    })""")

    assert active_info["tag"] == "BUTTON"
    assert active_info["chipKey"] == "category_id"
    assert active_info["catIdentity"] == "same-cat-node", "Unchanged category chip DOM node was recreated!"
    assert active_info["tagIdentity"] == "same-tag-node", "Unchanged tag chip DOM node was recreated!"

    # Wait for exit animation of 'q' chip to complete
    page.wait_for_function("() => !document.querySelector(\".active-filter-chip[data-chip-key='q']\")")

    context.close()


def test_d2_remove_last_query_chip_clears_url_and_focuses_input(frontend_server, playwright_instance):
    """
    Finding D (D2):
    Removing the last query chip immediately updates URL to #/library, clears search input,
    focuses #librarySearchInput, and removes the chip after exit animation.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum")
    page.wait_for_selector(".active-filter-chip[data-chip-key='q']")

    remove_btn = page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn")
    remove_btn.focus()
    page.keyboard.press("Enter")

    page.wait_for_function("() => !window.location.hash.includes('q=')")
    assert page.locator("#librarySearchInput").input_value() == ""
    assert page.evaluate("() => document.activeElement?.id") == "librarySearchInput"

    # Wait for exit animation to finish and hide bar
    page.wait_for_function("() => document.querySelectorAll('.active-filter-chip').length === 0")
    assert page.locator("#activeFiltersBar").evaluate("el => getComputedStyle(el).display === 'none'")

    context.close()


def test_d3_adding_new_filter_only_animates_new_chip_entrance(frontend_server, playwright_instance):
    """
    Finding D (D3):
    Adding a new filter while an existing chip is present preserves the existing chip node
    without re-triggering its entrance animation, while only the newly added chip runs entrance.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum")
    page.wait_for_selector(".active-filter-chip[data-chip-key='q']")
    # Wait for initial entrance (140ms) to finish
    page.wait_for_timeout(200)

    page.evaluate("""() => {
        const qChip = document.querySelector(".active-filter-chip[data-chip-key='q']");
        qChip.__existingNode = true;
    }""")

    # Click category to add a new filter chip
    page.locator(".category-pill[data-cat-id='cat-cs']").click()
    page.wait_for_selector(".active-filter-chip[data-chip-key='category_id']")

    chip_state = page.evaluate("""() => {
        const qChip = document.querySelector(".active-filter-chip[data-chip-key='q']");
        const catChip = document.querySelector(".active-filter-chip[data-chip-key='category_id']");
        return {
            qSameNode: Boolean(qChip && qChip.__existingNode),
            qEntering: qChip ? qChip.classList.contains('chip-entering') : null,
            catEntering: catChip ? catChip.classList.contains('chip-entering') : null,
        };
    }""")

    assert chip_state["qSameNode"] is True, "Existing query chip node must be preserved"
    assert chip_state["qEntering"] is False, "Existing query chip must not re-run entrance animation"
    assert chip_state["catEntering"] is True, "Newly added category chip must run entrance animation"

    context.close()


def test_d4_rapid_multi_chip_removal_consistent_no_ghost_chips(frontend_server, playwright_instance):
    """
    Finding D (D4):
    Rapidly removing multiple chips in succession keeps URL, DOM, and focus consistent
    and leaves zero ghost chips after animations complete.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum&mode=vector&category_id=cat-cs&tag_ids=tag-qc")
    page.wait_for_selector(".active-filter-chip[data-chip-key='tag_ids']")

    # Rapidly remove 'q' and 'category_id' via keyboard
    first_btn = page.locator(".active-filter-chip:not(.chip-removing) .chip-remove-btn").first
    first_btn.focus()
    page.keyboard.press("Enter")
    # Note: removing 'q' exits search mode so 'mode' chip also exits; focus is now on 'category_id'
    page.keyboard.press("Enter")

    # Wait for all exit animations to finish
    page.wait_for_function("() => document.querySelectorAll('.active-filter-chip.chip-removing').length === 0")
    page.wait_for_timeout(50)

    remaining_keys = page.evaluate("""() =>
        Array.from(document.querySelectorAll('.active-filter-chip')).map(el => el.getAttribute('data-chip-key'))
    """)
    assert remaining_keys == ["tag_ids"], f"Expected only ['tag_ids'] to remain, got {remaining_keys}"
    assert "tag_ids=tag-qc" in page.url
    assert "q=" not in page.url
    assert "category_id=" not in page.url
    assert page.evaluate("() => document.activeElement?.closest('.active-filter-chip')?.getAttribute('data-chip-key')") == "tag_ids"

    context.close()


def test_d5_reduced_motion_and_live_toggle_during_chip_exit(frontend_server, playwright_instance):
    """
    Finding D (D5):
    - Toggling prefers-reduced-motion: reduce while a chip is mid-exit immediately finalizes removal.
    - When already in reduced motion, removing a chip removes its DOM node synchronously without waiting.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs&tag_ids=tag-qc")
    page.wait_for_selector(".active-filter-chip[data-chip-key='q']")

    # 1. Start removing 'q' chip under normal motion
    page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
    assert page.locator(".active-filter-chip.chip-removing").count() == 1

    # 2. Toggle reduced motion ON while chip is mid-exit -> must finalize immediately
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("() => document.querySelectorAll('.active-filter-chip.chip-removing').length === 0")
    assert page.locator(".active-filter-chip[data-chip-key='q']").count() == 0

    # 3. Remove 'category_id' while already in reduced motion -> synchronous removal (0 exiting nodes)
    page.locator(".active-filter-chip[data-chip-key='category_id'] .chip-remove-btn").click()
    assert page.locator(".active-filter-chip[data-chip-key='category_id']").count() == 0
    assert page.locator(".active-filter-chip.chip-removing").count() == 0

    context.close()


def test_d6_chip_exit_animation_real_evidence(frontend_server, playwright_instance):
    """
    Finding D (D6):
    Proves that chip removal runs a real exit animation in the browser:
    1. Immediately after removal is triggered, the node remains in DOM with .chip-removing,
       pointer-events: none, and an active WAAPI animation interpolating opacity/transform.
    2. After ~200ms, the node is completely removed from the DOM.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs")
    page.wait_for_selector(".active-filter-chip[data-chip-key='q']")
    page.wait_for_timeout(180)

    page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
    page.wait_for_timeout(30)

    mid_exit = page.evaluate("""() => {
        const el = document.querySelector(".active-filter-chip[data-chip-key='q']");
        if (!el) return null;
        const style = window.getComputedStyle(el);
        const anims = typeof el.getAnimations === 'function' ? el.getAnimations() : [];
        return {
            hasRemovingClass: el.classList.contains('chip-removing'),
            pointerEvents: style.pointerEvents,
            opacity: parseFloat(style.opacity),
            animCount: anims.length,
            btnDisabled: el.querySelector('.chip-remove-btn')?.disabled ?? false,
        };
    }""")

    assert mid_exit is not None, "Chip was removed synchronously instead of animating exit!"
    assert mid_exit["hasRemovingClass"] is True
    assert mid_exit["pointerEvents"] == "none"
    assert mid_exit["btnDisabled"] is True
    assert mid_exit["animCount"] >= 1, "Expected active WAAPI exit animation on removing chip"
    assert 0.0 <= mid_exit["opacity"] < 1.0, f"Expected mid-exit opacity < 1.0, got {mid_exit['opacity']}"

    # Wait for 140ms exit animation to finish and verify node is detached from DOM
    page.wait_for_function("() => !document.querySelector(\".active-filter-chip[data-chip-key='q']\")")
    assert page.locator(".active-filter-chip[data-chip-key='q']").count() == 0

    context.close()


# ==============================================================================
# SECTION 6 ADDITIONAL QUALITY REQUIREMENTS:
# - Shared title present in BOTH old and new snapshots during View Transition
# - Back/Forward with long document list restores actual window.scrollY and activeElement
# ==============================================================================

def test_regression_shared_element_title_captured_in_snapshot(frontend_server, playwright_instance):
    """
    Area C & Section 6 (Shared Title Source & Destination Snapshot):
    Instruments document.startViewTransition to verify that BOTH oldNames (source Library card link)
    and newNames (destination Detail heading right after synchronous mount callback) contain
    strictly one 'folio-doc-title'.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.add_init_script("""
        window.__vtSnapshots = [];
        const originalSVT = document.startViewTransition;
        if (originalSVT) {
            document.startViewTransition = function(callback) {
                const collectNames = () => {
                    const names = [];
                    document.querySelectorAll('*').forEach(el => {
                        if (el.style && el.style.viewTransitionName) {
                            names.push(el.style.viewTransitionName);
                        }
                    });
                    return names;
                };
                const oldNames = collectNames();
                return originalSVT.call(document, async () => {
                    await callback();
                    const newNames = collectNames();
                    window.__vtSnapshots.push({
                        oldNames,
                        newNames,
                        hash: window.location.hash,
                    });
                });
            };
        }
    """)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-algo-1']")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    page.wait_for_selector(".document-detail-article")

    snapshots = page.evaluate("() => window.__vtSnapshots")
    detail_snaps = [s for s in snapshots if "doc-algo-1" in s["hash"]]
    assert len(detail_snaps) >= 1, f"Expected detail transition snapshot, got {snapshots}"
    detail_snap = detail_snaps[-1]
    assert detail_snap["oldNames"].count("folio-doc-title") == 1, f"Expected 1 source folio-doc-title, got {detail_snap['oldNames']}"
    assert detail_snap["newNames"].count("folio-doc-title") == 1, f"Expected 1 destination folio-doc-title, got {detail_snap['newNames']}"

    context.close()


def test_back_forward_long_list_scroll_and_focus_restoration(frontend_server, playwright_instance):
    """
    Section 6 Mandatory Test:
    With a long list of 15 documents in Library, scroll down to a lower card (scrollY > 500),
    click the card to open Detail, then navigate Back to Library.
    Asserts actual window.scrollY and document.activeElement (focused card link) are restored.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    # Serve 15 documents so the page has significant vertical scroll
    items = []
    for i in range(1, 16):
        doc_id = f"doc-algo-{i}" if i <= 2 else f"doc-long-{i}"
        items.append({
            "id": doc_id,
            "title": f"Research Monograph #{i}: Advanced Computational Foundations",
            "summary": "Detailed mathematical analysis and experimental verification across multiple domains of computer science.",
            "category": {"id": "cat-cs", "name": "Computer Science"},
            "author": "Richard Feynman",
            "created_at": "2026-01-15T10:00:00Z",
            "published_at": "2026-01-15T10:00:00Z",
            "views_count": 100 * i,
            "likes_count": 10 * i,
            "tags": [{"id": "tag-qc", "name": "Quantum"}],
        })
    long_docs_body = json.dumps({"items": items, "total": 15, "page": 1, "page_size": 15})
    page.route("**/api/v1/documents?*", lambda r: r.fulfill(status=200, content_type="application/json", body=long_docs_body))

    page.route("**/api/v1/documents/doc-long-12", lambda r: r.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "id": "doc-long-12",
            "title": "Research Monograph #12: Advanced Computational Foundations",
            "summary": "Detailed mathematical analysis",
            "rendered_content": "<h2>Section 1</h2><p>Content</p>",
            "category": {"id": "cat-cs", "name": "Computer Science"},
            "author": "Richard Feynman",
            "created_at": "2026-01-15T10:00:00Z",
            "published_at": "2026-01-15T10:00:00Z",
            "views_count": 1200,
            "likes_count": 120,
            "liked_by_me": False,
            "comments_count": 0,
            "tags": [],
        })
    ))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row[data-doc-id='doc-long-12']")

    # Scroll card #12 into view so it is scrolled down significantly
    target_link = page.locator(".document-card-row[data-doc-id='doc-long-12'] .doc-row-title a")
    target_link.scroll_into_view_if_needed()

    # Click card #12 to navigate to Detail (records scroll position in history/sessionStorage)
    target_link.click()
    page.wait_for_selector(".document-detail-article")
    assert "#/documents/doc-long-12" in page.url

    # The scroll position recorded when the card was clicked
    saved_scroll_y = page.evaluate("() => parseInt(sessionStorage.getItem('folio_library_scroll') || '0', 10)")
    assert saved_scroll_y > 500, f"Expected saved scrollY > 500 on long list, got {saved_scroll_y}"

    # Navigate Back via #detailBackLink
    page.locator("#detailBackLink").click()
    page.wait_for_selector(".document-card-row[data-doc-id='doc-long-12']")
    page.wait_for_timeout(100)

    restored_scroll_y = page.evaluate("() => window.scrollY")
    active_doc_id = page.evaluate("() => document.activeElement?.closest('.document-card-row')?.getAttribute('data-doc-id')")
    active_tag = page.evaluate("() => document.activeElement?.tagName")

    assert abs(restored_scroll_y - saved_scroll_y) <= 25, f"Expected scrollY ~{saved_scroll_y}, got {restored_scroll_y}"
    assert active_tag == "A", f"Expected focused element to be card title <a>, got {active_tag}"
    assert active_doc_id == "doc-long-12", f"Expected focus on doc-long-12, got {active_doc_id}"

    context.close()


# ==============================================================================
# Existing Core Regression & Invariant Tests (Preserved & Strengthened)
# ==============================================================================

def test_regression_stale_response_does_not_overwrite_navigated_document(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    deferred_route_a = []
    view_events_fired = []

    def log_view(route):
        view_events_fired.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"status": "ok"}')

    page.route("**/api/v1/documents/*/views", log_view)
    page.route("**/api/v1/documents/doc-algo-1", lambda r: deferred_route_a.append(r))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()
    page.evaluate("() => window.location.hash = '#/documents/doc-algo-2'")

    page.wait_for_selector(".detail-title", state="visible")
    page.wait_for_function("() => document.title.includes('Neural Network Generalization Bounds')")

    assert len(deferred_route_a) > 0
    for r in deferred_route_a:
        try:
            r.fulfill(
                status=200,
                content_type="application/json",
                body='''{
                    "id": "doc-algo-1",
                    "title": "Quantum Computing Fundamentals & Circuit Complexity",
                    "summary": "Quantum gate logic",
                    "rendered_content": "<h2>Quantum Should Not Be Rendered</h2>",
                    "category": {"id": "cat-cs", "name": "CS"},
                    "author": "Richard Feynman",
                    "created_at": "2026-01-15T10:00:00Z",
                    "published_at": "2026-01-15T10:00:00Z",
                    "views_count": 1420,
                    "likes_count": 88
                }'''
            )
        except Exception:
            pass

    page.wait_for_timeout(200)

    assert "#/documents/doc-algo-2" in page.url
    assert "Neural Network Generalization Bounds" in page.locator(".detail-title").text_content()
    assert "Neural Network Generalization Bounds" in page.title()
    assert "Quantum Should Not Be Rendered" not in page.content()

    doc_a_views_after = [v for v in view_events_fired if "doc-algo-1/views" in v]
    assert len(doc_a_views_after) == 0

    context.close()


def test_regression_slow_network_does_not_timeout_view_transition(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    deferred_doc = []
    page.route("**/api/v1/documents/doc-algo-1", lambda r: deferred_doc.append(r))

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.locator(".document-card-row[data-doc-id='doc-algo-1'] .doc-row-title a").click()

    page.wait_for_selector("#detailLoading", state="visible")
    assert page.locator("#detailBackLink").is_visible()

    assert len(deferred_doc) == 1
    for r in deferred_doc:
        r.fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "id": "doc-algo-1",
                "title": "Quantum Computing Fundamentals & Circuit Complexity",
                "summary": "Quantum gate logic",
                "rendered_content": "<h2>Loaded Content</h2>",
                "category": {"id": "cat-cs", "name": "CS"},
                "author": "Richard Feynman",
                "created_at": "2026-01-15T10:00:00Z",
                "published_at": "2026-01-15T10:00:00Z",
                "views_count": 1420,
                "likes_count": 88
            }'''
        )

    page.wait_for_selector(".document-detail-article", state="visible")
    assert "Quantum Computing Fundamentals" in page.locator(".detail-title").text_content()

    context.close()


def test_regression_multi_chip_keyboard_removal_preserves_focus(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs")
    page.wait_for_selector(".active-filter-chip")

    first_remove_btn = page.locator(".active-filter-chip .chip-remove-btn").first
    first_remove_btn.focus()
    page.keyboard.press("Enter")

    page.wait_for_function("() => document.activeElement.tagName !== 'BODY'")
    active_tag = page.evaluate("() => document.activeElement.tagName")
    assert active_tag != "BODY"

    is_chip_btn = page.evaluate("() => document.activeElement.classList.contains('chip-remove-btn')")
    assert is_chip_btn

    context.close()


def test_regression_single_chip_keyboard_removal_clears_search_input(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library?q=quantum")
    page.wait_for_selector(".active-filter-chip")

    search_input = page.locator("#librarySearchInput")
    assert search_input.input_value() == "quantum"

    remove_btn = page.locator(".active-filter-chip .chip-remove-btn").first
    remove_btn.focus()
    page.keyboard.press("Enter")

    page.wait_for_function("() => !window.location.hash.includes('q=')")
    page.wait_for_function("() => document.getElementById('librarySearchInput').value === ''")
    assert search_input.input_value() == ""

    page.wait_for_function("() => document.activeElement.id === 'librarySearchInput'")
    assert page.evaluate("() => document.activeElement.id") == "librarySearchInput"

    context.close()


def test_regression_mobile_close_and_resize_inert_state(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    mobile_toggle = page.locator("#mobileFilterToggleBtn")
    sidebar = page.locator("#librarySidebar")

    mobile_toggle.click()
    assert sidebar.evaluate("el => el.classList.contains('open')")
    assert not sidebar.evaluate("el => el.hasAttribute('inert')")

    mobile_toggle.click()
    assert not sidebar.evaluate("el => el.classList.contains('open')")
    assert sidebar.evaluate("el => el.hasAttribute('inert')")

    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_function("() => !document.getElementById('librarySidebar').hasAttribute('inert')")

    assert not sidebar.evaluate("el => el.hasAttribute('inert')")
    first_pill = sidebar.locator(".category-pill").first
    first_pill.click()
    page.wait_for_selector(".document-card-row")

    context.close()


def test_regression_reset_filters_button_selector_and_visibility(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    assert page.locator("#clearAllFiltersBtn").count() == 0

    page.locator(".category-pill[data-cat-id='cat-cs']").click()
    page.wait_for_selector("#clearAllFiltersBtn")

    reset_btn = page.locator("#clearAllFiltersBtn")
    assert reset_btn.is_visible()

    reset_btn.click()
    page.wait_for_function("() => document.getElementById('clearAllFiltersBtn') === null")
    assert page.locator("#clearAllFiltersBtn").count() == 0

    context.close()


def test_regression_indicator_after_reduced_motion_toggle(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector("#categoryIndicator")

    page.locator(".category-pill[data-cat-id='cat-cs']").click()
    page.wait_for_timeout(250)

    page.emulate_media(reduced_motion="reduce")

    page.locator(".category-pill[data-cat-id='cat-phys']").click()
    page.wait_for_timeout(100)

    active_pill = page.locator(".category-pill[data-cat-id='cat-phys']")
    pill_box = active_pill.bounding_box()
    ind_box = page.locator("#categoryIndicator").bounding_box()

    assert abs(ind_box["y"] - pill_box["y"]) < 5

    context.close()


def test_regression_second_pending_fade_lowers_opacity(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.locator("#librarySearchInput").fill("quantum")
    page.locator("#librarySearchBtn").click()
    page.wait_for_selector(".doc-rank-badge")

    deferred_search = []
    page.route(lambda url: "q=neural" in url, lambda r: deferred_search.append(r))

    page.locator("#librarySearchInput").fill("neural")
    page.locator("#librarySearchBtn").click()

    page.wait_for_selector(".documents-list.is-updating")
    opacity = float(page.evaluate("() => window.getComputedStyle(document.getElementById('documentsListContainer')).opacity"))
    assert opacity <= 0.65

    if deferred_search:
        deferred_search[0].fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "items": [{"id": "doc-algo-2", "title": "Neural Networks", "category": {"id": "cat-math", "name": "Math"}, "tags": [], "score": 0.9}],
                "total": 1, "page": 1, "page_size": 15, "engine_used": "bm25"
            }'''
        )

    page.wait_for_selector(".documents-list:not(.is-updating)")
    page.wait_for_function("() => !document.getElementById('documentsListContainer').classList.contains('documents-list-fade')")
    final_opacity = float(page.evaluate("() => window.getComputedStyle(document.getElementById('documentsListContainer')).opacity"))
    assert final_opacity == 1.0

    context.close()


def test_regression_view_transitions_fallback_real_absence(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.add_init_script("delete Document.prototype.startViewTransition;")

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    api_type = page.evaluate("() => typeof document.startViewTransition")
    assert api_type == "undefined"

    page.locator(".document-card-row .doc-row-title a").first.click()
    page.wait_for_selector(".document-detail-article")
    assert page.locator(".detail-title").is_visible()

    context.close()


def test_regression_reading_progress_numeric_interpolation(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/documents/doc-algo-1")
    page.wait_for_selector(".document-reading-column")

    progress_bar = page.locator("#readingProgressBar")
    assert progress_bar.count() > 0

    def get_scalex():
        return page.evaluate("""() => {
            const el = document.getElementById('readingProgressBar');
            if (!el) return -1;
            const match = el.style.transform.match(/scaleX\\(([^)]+)\\)/);
            return match ? parseFloat(match[1]) : 0;
        }""")

    assert get_scalex() == 0.0

    page.evaluate("() => window.scrollTo(0, (document.body.scrollHeight - window.innerHeight) * 0.5)")
    page.wait_for_timeout(100)
    mid_scale = get_scalex()
    assert 0.1 <= mid_scale <= 0.85

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(100)
    end_scale = get_scalex()
    assert end_scale >= 0.8

    context.close()


def test_regression_like_button_duplicate_guard_and_failure(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page, simulate_like_fail=True)

    page.goto(f"{frontend_server}/#/documents/doc-algo-1")
    page.wait_for_selector("#likeBtn")

    like_btn = page.locator("#likeBtn")
    heart_svg = page.locator("#likeBtn .heart-icon")

    assert not like_btn.evaluate("el => el.classList.contains('liked')")
    assert heart_svg.get_attribute("fill") == "none"

    like_btn.click()
    page.wait_for_selector(".toast.toast-error")

    assert not like_btn.evaluate("el => el.classList.contains('liked')")
    assert not like_btn.is_disabled()

    context.close()


def test_in_place_query_update_preserves_focus_and_input(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    search_input = page.locator("#librarySearchInput")
    search_input.focus()
    search_input.fill("quantum")

    page.evaluate("() => { document.getElementById('librarySearchInput').dataset.persisted = 'true'; }")
    page.locator("#librarySearchBtn").click()

    page.wait_for_url("**/#/library?**q=quantum**")
    page.wait_for_selector(".doc-rank-badge")

    is_persisted = page.evaluate("() => document.getElementById('librarySearchInput').dataset.persisted === 'true'")
    assert is_persisted
    assert search_input.input_value() == "quantum"

    context.close()


def test_back_forward_navigation_state_persistence(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    page.locator("#librarySearchInput").fill("quantum")
    page.locator("#librarySearchBtn").click()
    page.wait_for_function("() => window.location.hash.includes('q=quantum')")

    cat_button = page.locator(".category-pill").nth(1)
    cat_button.click()
    page.wait_for_function("() => window.location.hash.includes('category_id=')")

    page.go_back()
    page.wait_for_function("() => !window.location.hash.includes('category_id=') && window.location.hash.includes('q=quantum')")
    assert page.locator("#librarySearchInput").input_value() == "quantum"

    page.go_forward()
    page.wait_for_function("() => window.location.hash.includes('category_id=')")

    context.close()


def test_date_accordion_inert_when_closed(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector("#dateFilterAccordion", state="attached")

    accordion = page.locator("#dateFilterAccordion")
    inner = page.locator("#dateFilterInner")
    toggle_btn = page.locator("#toggleDateFilterBtn")

    assert not accordion.evaluate("el => el.classList.contains('is-open')")
    assert inner.evaluate("el => el.hasAttribute('inert')")

    toggle_btn.click()
    assert accordion.evaluate("el => el.classList.contains('is-open')")
    assert not inner.evaluate("el => el.hasAttribute('inert')")

    toggle_btn.click()
    assert inner.evaluate("el => el.hasAttribute('inert')")

    context.close()


def test_toc_smooth_scroll_and_heading_highlight(frontend_server, playwright_instance):
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.goto(f"{frontend_server}/#/documents/doc-algo-1")
    page.wait_for_selector(".document-toc")

    toc_link = page.locator(".toc-item a").first
    target_href = toc_link.get_attribute("href")
    target_id = target_href.replace("#", "")

    toc_link.click()
    page.wait_for_timeout(300)

    target_heading = page.locator(f"#{target_id}")
    assert target_heading.evaluate("el => el.classList.contains('heading-target-flash')")

    context.close()


VIEWPORTS = [
    ("mobile_360", 360, 640),
    ("mobile_390", 390, 844),
    ("tablet_768", 768, 1024),
    ("desktop_1440", 1440, 900),
]


def test_responsive_viewports_no_overflow(frontend_server, playwright_instance):
    for name, width, height in VIEWPORTS:
        context = playwright_instance.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        setup_mock_api(page)

        page.goto(f"{frontend_server}/#/library")
        page.wait_for_selector(".document-card-row")

        is_overflowing = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert not is_overflowing, f"Horizontal page overflow detected on Library at {name} ({width}x{height})"

        if width <= 860:
            mobile_btn = page.locator("#mobileFilterToggleBtn")
            assert mobile_btn.is_visible()
            mobile_btn.click()
            sidebar = page.locator("#librarySidebar")
            assert sidebar.evaluate("el => el.classList.contains('open')")

        page.goto(f"{frontend_server}/#/documents/doc-algo-1")
        page.wait_for_selector(".document-detail-article")

        is_detail_overflowing = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert not is_detail_overflowing, f"Horizontal page overflow detected on Detail at {name} ({width}x{height})"

        context.close()


# ==============================================================================
# ADDITIONAL REFINED TESTS FOR ISSUES 1, 2, AND 3
# ==============================================================================

def test_issue1_search_failure_ui_state_and_retry_recovery(frontend_server, playwright_instance):
    """
    Issue 1: Consistent UI state during search failure & retry recovery
    A. Successful initial search -> Subsequent search returns HTTP 500:
       - Error notice rendered in docsList (.notice.notice-error, "Try Again" button).
       - aria-busy is false, is-updating is removed.
       - statsText does NOT retain stale 'Searching for "failure"...' and is cleared.
       - searchTelemetryBar is hidden / cleared.
       - pagination is cleared so user cannot navigate invalid pages.
    B. Retry after failure succeeds:
       - Clicking 'Try Again' re-triggers fetch for current query.
       - Error notice disappears, results are rendered.
       - Stats, telemetry, and pagination are updated with new response.
    C. Stale / aborted responses do not overwrite newer state.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    search_fail = {"should_fail": False}

    def custom_search_handler(route):
        url = route.request.url
        if "q=failure" in url and search_fail["should_fail"]:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail": "Internal database error"}'
            )
        elif "q=failure" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='''{
                    "items": [{
                        "id": "doc-algo-1",
                        "title": "Quantum Computing Fundamentals & Circuit Complexity",
                        "summary": "Overview",
                        "category": {"id": "cat-cs", "name": "Computer Science"},
                        "score": 0.88,
                        "tags": []
                    }],
                    "total": 1,
                    "page": 1,
                    "page_size": 15,
                    "snapshot_total": 1,
                    "engine_used": "bm25",
                    "latency_ms": 12.5,
                    "index_generation": "gen-retry-active"
                }'''
            )
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='''{
                    "items": [{
                        "id": "doc-algo-1",
                        "title": "Quantum Computing Fundamentals & Circuit Complexity",
                        "summary": "Overview",
                        "category": {"id": "cat-cs", "name": "Computer Science"},
                        "score": 0.954,
                        "tags": []
                    }],
                    "total": 1,
                    "page": 1,
                    "page_size": 15,
                    "snapshot_total": 1,
                    "engine_used": "bm25",
                    "latency_ms": 14.2,
                    "index_generation": "gen-quantum-active"
                }'''
            )

    page.route("**/api/v1/search*", custom_search_handler)

    # 1. Successful initial search
    page.goto(f"{frontend_server}/#/library?q=quantum")
    page.wait_for_selector(".document-card-row")

    initial_stats = page.locator("#resultsCountText").text_content()
    assert 'Found 1 result for "quantum"' in initial_stats
    telemetry = page.locator("#searchTelemetryBar")
    assert telemetry.evaluate("el => el.style.display !== 'none' && el.textContent.includes('BM25')")

    # 2. Trigger HTTP 500 on subsequent search "failure"
    search_fail["should_fail"] = True
    page.fill("#librarySearchInput", "failure")
    page.click("#librarySearchBtn")

    # Wait for error notice to appear in DOM
    page.wait_for_selector("#documentsListContainer .notice.notice-error")

    docs_list = page.locator("#documentsListContainer")
    assert docs_list.get_attribute("aria-busy") == "false"
    assert not docs_list.evaluate("el => el.classList.contains('is-updating')")

    # Verify stale "Searching for..." stats is removed
    stats_after_fail = page.locator("#resultsCountText").text_content()
    assert "Searching for" not in stats_after_fail
    assert stats_after_fail.strip() == ""

    # Verify previous telemetry is removed/hidden
    assert telemetry.evaluate("el => el.style.display === 'none' || el.innerHTML.trim() === ''")

    # Verify pagination is cleared
    pagination = page.locator("#libraryPaginationContainer")
    assert pagination.evaluate("el => el.innerHTML.trim() === ''")

    # 3. Retry after failure succeeds
    search_fail["should_fail"] = False
    retry_btn = page.locator("#documentsListContainer .notice.notice-error button")
    assert retry_btn.count() == 1
    retry_btn.click()

    page.wait_for_selector("#documentsListContainer .document-card-row")
    assert page.locator("#documentsListContainer .notice.notice-error").count() == 0

    recovered_stats = page.locator("#resultsCountText").text_content()
    assert 'Found 1 result for "failure"' in recovered_stats
    assert telemetry.evaluate("el => el.style.display !== 'none' && el.textContent.includes('BM25')")

    context.close()


def test_retry_from_old_query_cannot_supersede_pending_search(frontend_server, playwright_instance):
    for width, motion in [(1440, "no-preference"), (390, "reduce")]:
        context = playwright_instance.new_context(
            viewport={"width": width, "height": 900}, reduced_motion=motion
        )
        page = context.new_page()
        setup_mock_api(page)
        pending = []
        requests = []

        def search(route):
            requests.append(route.request.url)
            if "q=failure" in route.request.url:
                route.fulfill(status=500, json={"detail": "Temporary failure"})
            else:
                pending.append(route)

        page.route("**/api/v1/search*", search)
        page.goto(f"{frontend_server}/#/library?q=failure")
        page.wait_for_selector(".notice-error button")
        page.evaluate("() => { window.oldRetry = document.querySelector('.notice-error button').onclick; }")
        page.fill("#librarySearchInput", "newquery")
        with page.expect_request("**/api/v1/search*q=newquery*"):
            page.click("#librarySearchBtn")
        page.wait_for_function("document.querySelector('#resultsCountText').textContent.includes('newquery')")
        assert page.locator("#documentsListContainer .notice-error").count() == 0

        # Invoke the captured callback even though its button has been removed.
        page.evaluate("window.oldRetry()")
        assert page.locator("#librarySearchInput").input_value() == "newquery"
        assert 'Searching for "newquery"' in page.locator("#resultsCountText").text_content()
        assert len(pending) == 1
        pending[0].fulfill(json={
            "items": [], "total": 0, "page": 1, "page_size": 15,
            "engine_used": "bm25", "latency_ms": 8,
        })
        page.wait_for_function("document.querySelector('#documentsListContainer').getAttribute('aria-busy') === 'false'")
        assert "q=newquery" in page.url
        assert "Searching" not in page.locator("#resultsCountText").text_content()
        assert "newquery" in page.locator("#activeFiltersBar").text_content()
        assert len(requests) == 2
        context.close()


def test_retry_callback_is_single_use_and_expires_on_navigation(frontend_server, playwright_instance):
    context = playwright_instance.new_context()
    page = context.new_page()
    setup_mock_api(page)
    pending = []
    requests = []

    def search(route):
        requests.append(route.request.url)
        if len(requests) == 1:
            route.fulfill(status=500, json={"detail": "Temporary failure"})
        else:
            pending.append(route)

    page.route("**/api/v1/search*", search)
    page.goto(f"{frontend_server}/#/library?q=failure")
    page.wait_for_selector(".notice-error button")
    page.evaluate("() => { window.oldRetry = document.querySelector('.notice-error button').onclick; }")
    with page.expect_request("**/api/v1/search*"):
        page.locator(".notice-error button").click()
    page.evaluate("window.oldRetry(); window.oldRetry();")
    assert page.locator("#documentsListContainer .notice-error").count() == 0
    assert page.locator("#documentsListContainer").get_attribute("aria-busy") == "true"
    assert page.locator("#librarySearchInput").evaluate("el => el === document.activeElement")
    pending[0].fulfill(status=500, json={"detail": "Still unavailable"})
    page.wait_for_selector(".notice-error button")
    page.evaluate("() => { window.retryBeforeLeave = document.querySelector('.notice-error button').onclick; }")
    assert len(requests) == 2
    with page.expect_request("**/api/v1/search*"):
        page.locator(".notice-error button").click()
    pending[1].fulfill(json={
        "items": [], "total": 0, "page": 1, "page_size": 15, "engine_used": "bm25",
    })
    page.wait_for_function("document.querySelector('#documentsListContainer').getAttribute('aria-busy') === 'false'")
    page.evaluate("location.hash = '#/login'")
    page.wait_for_function("!document.querySelector('#librarySearchInput')")
    page.evaluate("window.oldRetry(); window.retryBeforeLeave();")
    assert page.url.endswith("#/login")
    assert len(requests) == 3
    context.close()


def test_issue2_filter_chip_reflow_completion_and_idempotence(frontend_server, playwright_instance):
    """
    Issue 2: Filter chip reflow animation is NOT prematurely cancelled by repeated syncs,
    and runs to completion (finished) with idempotent reconciliation.
    A. Removal of a chip among multiple chips:
       - Removed chip runs exit animation.
       - Remaining chips preserve DOM node identity.
       - Surviving chips execute FLIP reflow animation (dx != 0).
       - Reflow animation reaches 'finished' playState without being cancelled at ~27ms.
    B. Consecutive rapid filter changes:
       - Retargets smoothly from visual coordinates without ghost chips or errors.
    C. Route leave during animation:
       - All animations cancelled and cleaned up properly.
    D. Reduced motion:
       - Instant reconciliation without affirmative positive duration animation.
    """
    # --- Sub-test A: Normal motion with reflow completion & DOM identity preservation ---
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    page.add_init_script("""
        window.__trackedChipAnimations = [];
        const origAnimate = Element.prototype.animate;
        Element.prototype.animate = function(...args) {
            const isChip = this.classList.contains('active-filter-chip');
            if (!isChip) return origAnimate.apply(this, args);
            const anim = origAnimate.apply(this, args);
            const key = this.getAttribute('data-chip-key');
            const isRemoving = this.classList.contains('chip-removing');
            const entry = {
                key: key,
                isRemoving: isRemoving,
                cancelled: false,
                finished: false,
                cancelTime: null,
                finishTime: null,
                startTime: performance.now(),
                keyframes: args[0],
            };
            anim.addEventListener('cancel', () => {
                entry.cancelled = true;
                entry.cancelTime = performance.now() - entry.startTime;
            });
            anim.addEventListener('finish', () => {
                entry.finished = true;
                entry.finishTime = performance.now() - entry.startTime;
            });
            window.__trackedChipAnimations.push(entry);
            return anim;
        };
    """)

    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs&tag_ids=tag-qc")
    page.wait_for_selector(".active-filter-chip[data-chip-key='q']")
    page.wait_for_selector(".active-filter-chip[data-chip-key='category_id']")
    page.wait_for_selector(".active-filter-chip[data-chip-key='tag_ids']")
    page.wait_for_timeout(200)

    # Save DOM node references to test identity preservation
    page.evaluate("""() => {
        window.__catChipNode = document.querySelector(".active-filter-chip[data-chip-key='category_id']");
        window.__tagChipNode = document.querySelector(".active-filter-chip[data-chip-key='tag_ids']");
        window.__trackedChipAnimations = []; // Reset after initial entrance
    }""")

    # Click remove on 'q' chip
    page.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()

    # Wait for animations to finish naturally (~200ms)
    page.wait_for_timeout(250)

    # Verify DOM identity preserved on surviving chips
    identity_preserved = page.evaluate("""() => {
        const curCat = document.querySelector(".active-filter-chip[data-chip-key='category_id']");
        const curTag = document.querySelector(".active-filter-chip[data-chip-key='tag_ids']");
        return {
            catSame: curCat === window.__catChipNode,
            tagSame: curTag === window.__tagChipNode,
        };
    }""")
    assert identity_preserved["catSame"] is True, "Category chip DOM node was replaced instead of preserved!"
    assert identity_preserved["tagSame"] is True, "Tag chip DOM node was replaced instead of preserved!"

    # Verify exit and reflow animation completion
    tracked = page.evaluate("() => window.__trackedChipAnimations")
    exit_anims = [a for a in tracked if a["isRemoving"] and a["key"] == "q"]
    reflow_anims = [a for a in tracked if not a["isRemoving"] and a["key"] in ("category_id", "tag_ids")]

    assert len(exit_anims) >= 1, "Exit animation for removed chip 'q' was not tracked!"
    assert exit_anims[0]["finished"] is True, "Exit animation did not reach finished state!"

    assert len(reflow_anims) >= 1, "Reflow animation for surviving chips was not created!"
    for r in reflow_anims:
        assert r["cancelled"] is False, f"Reflow animation was prematurely cancelled at {r['cancelTime']}ms!"
        assert r["finished"] is True, "Reflow animation did not complete to finished state!"

    context.close()

    # --- Sub-test B: Consecutive rapid chip removals retarget cleanly ---
    context_b = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page_b = context_b.new_page()
    setup_mock_api(page_b)

    page_b.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs&tag_ids=tag-qc")
    page_b.wait_for_selector(".active-filter-chip[data-chip-key='tag_ids']")
    page_b.wait_for_timeout(180)

    # Rapid removal of 'q' then 'category_id' within 40ms
    page_b.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
    page_b.wait_for_timeout(40)
    cat_btn = page_b.locator(".active-filter-chip[data-chip-key='category_id']:not(.chip-removing) .chip-remove-btn")
    if cat_btn.count() > 0:
        cat_btn.click()

    page_b.wait_for_timeout(250)
    # Only tag_ids should remain
    remaining_chips = page_b.locator(".active-filter-chip:not(.chip-removing)")
    assert remaining_chips.count() == 1
    assert remaining_chips.get_attribute("data-chip-key") == "tag_ids"
    context_b.close()

    # --- Sub-test C: Route cleanup during active animation ---
    context_c = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page_c = context_c.new_page()
    setup_mock_api(page_c)

    page_c.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs")
    page_c.wait_for_selector(".active-filter-chip[data-chip-key='q']")
    page_c.wait_for_timeout(180)

    # Trigger chip removal and immediately navigate away mid-animation (~30ms)
    page_c.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
    page_c.wait_for_timeout(30)
    page_c.goto(f"{frontend_server}/#/documents/doc-algo-1")
    page_c.wait_for_selector(".document-detail-article")
    page_c.wait_for_timeout(150)
    context_c.close()

    # --- Sub-test D: prefers-reduced-motion immediate removal ---
    context_d = playwright_instance.new_context(
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce"
    )
    page_d = context_d.new_page()
    setup_mock_api(page_d)

    page_d.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs")
    page_d.wait_for_selector(".active-filter-chip[data-chip-key='q']")
    page_d.wait_for_timeout(180)

    page_d.locator(".active-filter-chip[data-chip-key='q'] .chip-remove-btn").click()
    # In reduced motion, chip is removed immediately without animation duration
    assert page_d.locator(".active-filter-chip[data-chip-key='q']").count() == 0
    assert page_d.locator(".active-filter-chip[data-chip-key='category_id']").count() == 1
    context_d.close()


def test_chip_exit_waits_for_animation_clock(frontend_server, playwright_instance):
    context = playwright_instance.new_context()
    page = context.new_page()
    setup_mock_api(page)
    page.goto(f"{frontend_server}/#/library?q=quantum&category_id=cat-cs")
    page.wait_for_selector(".document-card-row")
    page.evaluate("""() => {
        const original = Element.prototype.animate;
        Element.prototype.animate = function(...args) {
            const animation = original.apply(this, args);
            if (this.matches('.active-filter-chip[data-chip-key="q"].chip-removing')) {
                animation.pause();
                window.pausedExit = animation;
                window.exitingQueryChip = this;
            }
            return animation;
        };
    }""")
    page.locator(".active-filter-chip[data-chip-key='q'] button").click()
    # Deliberately exceed the former wall-clock cleanup timer while WAAPI is paused.
    page.wait_for_timeout(250)
    assert page.evaluate("window.exitingQueryChip.isConnected")
    page.evaluate("window.pausedExit.play()")
    page.wait_for_function("!window.exitingQueryChip.isConnected")
    assert page.locator(".active-filter-chip[data-chip-key='category_id']").count() == 1
    context.close()


def test_issue3_font_loading_without_rewrite(frontend_server, playwright_instance):
    """
    Issue 3: Fonts are loaded directly via static files without path rewrite.
    - No requests to /assets/fonts/assets/fonts/ (which indicates doubled relative paths).
    - All .woff2 font requests succeed with HTTP 200.
    - FontFace for 'Source Sans 3' and 'Source Serif 4' load successfully without status = 'error'.
    """
    context = playwright_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    setup_mock_api(page)

    font_requests = []
    doubled_font_requests = []

    def on_response(resp):
        if ".woff2" in resp.url:
            font_requests.append((resp.url, resp.status))
            if "/assets/fonts/assets/fonts/" in resp.url:
                doubled_font_requests.append(resp.url)

    page.on("response", on_response)

    page.goto(f"{frontend_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Actively load each required family/weight in the browser
    js_test_fonts = """async () => {
        const tests = [
            '400 16px "Source Sans 3"',
            '600 16px "Source Sans 3"',
            '700 16px "Source Sans 3"',
            '400 16px "Source Serif 4"',
            '700 16px "Source Serif 4"',
        ];
        const loaded = [];
        for (const t of tests) {
            const faces = await document.fonts.load(t);
            for (const f of faces) {
                loaded.push({ family: f.family, weight: f.weight, status: f.status });
            }
        }
        const errorFaces = [];
        document.fonts.forEach(f => {
            if (f.status === 'error') {
                errorFaces.push({ family: f.family, weight: f.weight, status: f.status });
            }
        });
        return { loaded, errorFaces };
    }"""

    font_results = page.evaluate(js_test_fonts)

    assert len(doubled_font_requests) == 0, f"Detected doubled font path requests: {doubled_font_requests}"
    assert len(font_requests) > 0, "Expected at least one real .woff2 font network request"
    for url, status in font_requests:
        assert status == 200, f"Font request {url} failed with status {status}"

    assert len(font_results["errorFaces"]) == 0, f"FontFaces with error status: {font_results['errorFaces']}"
    assert len(font_results["loaded"]) > 0, "No FontFaces were loaded"

    context.close()
