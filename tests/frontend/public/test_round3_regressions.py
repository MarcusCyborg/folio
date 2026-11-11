# tests/frontend/public/test_round3_regressions.py
# Playwright browser regression tests for Round 3 findings (R3-03, R3-07)

import uuid
from pathlib import Path
import pytest


def _login_ui(page, live_server: str, email: str = "admin@folio.test", password: str = "FolioDemo2026!"):
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", email)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn", timeout=8000)


def _attach_runtime_guards(page):
    page_errors = []
    unhandled_rejections = []
    page.add_init_script(
        """
        window.__r3UnhandledRejections = [];
        window.addEventListener('unhandledrejection', (ev) => {
            const msg = ev.reason ? (ev.reason.stack || ev.reason.message || String(ev.reason)) : 'unknown';
            window.__r3UnhandledRejections.push(msg);
        });
        """
    )
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    return page_errors, unhandled_rejections


def _assert_no_runtime_errors(page, page_errors):
    js_rej = page.evaluate("() => window.__r3UnhandledRejections || []")
    assert page_errors == [], f"Unexpected pageerror(s): {page_errors}"
    assert js_rej == [], f"Unexpected unhandledrejection(s): {js_rej}"


def test_r3_03_delete_last_tag_on_page_2_clamps_to_page_1(live_server, browser_instance):
    """
    R3-03 (Primary Delete Case):
    With 51 matching tags (page 1 = 50, page 2 = 1), navigating to page 2 and deleting
    the 51st tag must automatically clamp tagPage back to page 1 and display the 50
    remaining tags instead of showing 'No tags configured.' / 'No tags match your filter.'.
    """
    from src.backend.core.database import SessionLocal
    from src.backend.models.taxonomy import Tag

    prefix = f"R3DelClamp{uuid.uuid4().hex[:5]}"
    seed_db = SessionLocal()
    try:
        seed_db.add_all(
            [
                Tag(name=f"{prefix} Tag {i:03d}", slug=f"{prefix.lower()}-tag-{i:03d}")
                for i in range(51)
            ]
        )
        seed_db.commit()
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page_errors, _ = _attach_runtime_guards(page)

    try:
        _login_ui(page, live_server, "admin@folio.test")
        page.goto(f"{live_server}/#/admin/taxonomy")
        page.wait_for_selector("#tagsListArea table", timeout=8000)

        page.fill("#taxonomyTagSearchInput", prefix)
        page.wait_for_function(
            "() => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '51'",
            timeout=6000,
        )
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 1 of 2')", timeout=5000)
        assert page.locator("#tagsListArea tbody tr").count() == 50

        # Navigate to Page 2 where only tag #050 resides
        page.click("#tagsNextPageBtn")
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 2 of 2')", timeout=5000)
        assert page.locator("#tagsListArea tbody tr").count() == 1
        assert f"{prefix} Tag 050" in page.locator("#tagsListArea").inner_text()

        # Delete the last tag on Page 2 -> must clamp automatically to Page 1 (50 remaining tags)
        page.click("#tagsListArea tbody tr:first-child .del-tag-btn")
        page.wait_for_selector(".dialog")
        page.click(".dialog button:has-text('Delete Tag')")

        page.wait_for_function(
            "() => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '50'",
            timeout=6000,
        )
        page.wait_for_selector("#tagsListArea table tbody tr", timeout=6000)
        assert page.locator("#tagsListArea .empty-state").count() == 0
        assert page.locator("#tagsListArea tbody tr").count() == 50
        assert page.locator("#tagsPaginationBar").inner_text().strip() == ""
        _assert_no_runtime_errors(page, page_errors)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Tag).filter(Tag.slug.like(f"{prefix.lower()}-%")).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r3_03_delete_only_remaining_tag_renders_clean_empty_state_without_loop(live_server, browser_instance):
    """
    R3-03 (True Empty Boundary):
    Deleting the sole remaining matching tag (total 1 -> 0) must render the clean empty
    state once without infinite clamping requests.
    """
    from src.backend.core.database import SessionLocal
    from src.backend.models.taxonomy import Tag

    prefix = f"R3OnlyOne{uuid.uuid4().hex[:5]}"
    seed_db = SessionLocal()
    try:
        seed_db.add(Tag(name=f"{prefix} Solo", slug=f"{prefix.lower()}-solo"))
        seed_db.commit()
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page_errors, _ = _attach_runtime_guards(page)

    try:
        _login_ui(page, live_server, "admin@folio.test")
        page.goto(f"{live_server}/#/admin/taxonomy")
        page.wait_for_selector("#tagsListArea table", timeout=8000)

        page.fill("#taxonomyTagSearchInput", prefix)
        page.wait_for_function(
            "() => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '1'",
            timeout=6000,
        )

        tag_get_calls = []
        page.on(
            "request",
            lambda req: tag_get_calls.append(req.url)
            if req.method == "GET" and "/api/v1/admin/tags" in req.url
            else None,
        )

        page.click("#tagsListArea tbody tr:first-child .del-tag-btn")
        page.wait_for_selector(".dialog")
        page.click(".dialog button:has-text('Delete Tag')")

        page.wait_for_function(
            "() => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '0'",
            timeout=6000,
        )
        page.wait_for_selector("#tagsListArea .empty-state", timeout=5000)
        assert "No tags match your filter." in page.locator("#tagsListArea").inner_text()
        assert page.locator("#tagsPaginationBar").inner_text().strip() == ""
        assert len(tag_get_calls) == 1, f"Expected single reload GET on empty boundary, got: {tag_get_calls}"
        _assert_no_runtime_errors(page, page_errors)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Tag).filter(Tag.slug.like(f"{prefix.lower()}-%")).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r3_03_edit_last_tag_on_page_2_out_of_filter_clamps_to_page_1(live_server, browser_instance):
    """
    R3-03 (Edit Out-Of-Filter Case):
    With 51 matching tags and active filter, editing the 51st tag on page 2 so it no
    longer matches the filter must clamp back to page 1 showing the remaining 50 items.
    """
    from src.backend.core.database import SessionLocal
    from src.backend.models.taxonomy import Tag

    prefix = f"R3EditClamp{uuid.uuid4().hex[:5]}"
    renamed = f"UnmatchedTag_{uuid.uuid4().hex[:6]}"
    seed_db = SessionLocal()
    try:
        seed_db.add_all(
            [
                Tag(name=f"{prefix} Tag {i:03d}", slug=f"{prefix.lower()}-tag-{i:03d}")
                for i in range(51)
            ]
        )
        seed_db.commit()
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page_errors, _ = _attach_runtime_guards(page)

    try:
        _login_ui(page, live_server, "admin@folio.test")
        page.goto(f"{live_server}/#/admin/taxonomy")
        page.wait_for_selector("#tagsListArea table", timeout=8000)

        page.fill("#taxonomyTagSearchInput", prefix)
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 1 of 2')", timeout=6000)
        page.click("#tagsNextPageBtn")
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 2 of 2')", timeout=5000)
        assert page.locator("#tagsListArea tbody tr").count() == 1

        page.click("#tagsListArea tbody tr:first-child .edit-tag-btn")
        page.wait_for_selector("#tagModalName")
        page.fill("#tagModalName", renamed)
        page.click("#saveTagModalBtn")

        page.wait_for_function(
            "() => document.querySelector('#tagsTotalBadge')?.textContent?.trim() === '50'",
            timeout=6000,
        )
        page.wait_for_selector("#tagsListArea table tbody tr", timeout=6000)
        assert page.locator("#tagsListArea .empty-state").count() == 0
        assert page.locator("#tagsListArea tbody tr").count() == 50
        _assert_no_runtime_errors(page, page_errors)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Tag).filter(
                (Tag.slug.like(f"{prefix.lower()}-%")) | (Tag.name == renamed)
            ).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r3_03_stale_search_guard_error_retry_and_mobile_viewport(live_server, browser_instance):
    """
    R3-03 (Stale Guard, Retry Recovery, Mobile Overflow):
    - Delayed response for an earlier filter query must not overwrite a newer filter's results.
    - 503 failure shows #retryTagsLoadBtn and recovers cleanly on click.
    - Mobile viewport (390x844) renders paginated controls without horizontal page overflow.
    """
    import time
    from src.backend.core.database import SessionLocal
    from src.backend.models.taxonomy import Tag

    prefix_a = f"R3SlowA{uuid.uuid4().hex[:5]}"
    prefix_b = f"R3FastB{uuid.uuid4().hex[:5]}"
    seed_db = SessionLocal()
    try:
        seed_db.add_all(
            [Tag(name=f"{prefix_a} {i:02d}", slug=f"{prefix_a.lower()}-{i:02d}") for i in range(52)]
            + [Tag(name=f"{prefix_b} Target", slug=f"{prefix_b.lower()}-target")]
        )
        seed_db.commit()
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page_errors, _ = _attach_runtime_guards(page)

    try:
        _login_ui(page, live_server, "admin@folio.test")
        page.goto(f"{live_server}/#/admin/taxonomy")
        page.wait_for_selector("#tagsListArea table", timeout=8000)

        # Mobile overflow check with pagination controls visible
        page.fill("#taxonomyTagSearchInput", prefix_a)
        page.wait_for_selector("#tagsPaginationBar:has-text('Page 1 of 2')", timeout=6000)
        overflow = page.evaluate(
            "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
        )
        assert overflow["scrollWidth"] <= overflow["innerWidth"], f"Mobile horizontal overflow: {overflow}"

        # Hold SlowA route response and release it AFTER FastB completes,
        # proving stale response ordering cannot overwrite newer query results.
        page.fill("#taxonomyTagSearchInput", "")
        page.wait_for_selector("#tagsListArea table", timeout=6000)

        held_slow_a = []

        def route_out_of_order(route):
            url = route.request.url
            if f"q={prefix_a}" in url:
                held_slow_a.append(route)
            else:
                route.continue_()

        page.route("**/api/v1/admin/tags**", route_out_of_order)
        page.fill("#taxonomyTagSearchInput", prefix_a)
        # Wait until debounced SlowA HTTP request actually hits Playwright router
        deadline = time.monotonic() + 5.0
        while not held_slow_a and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        assert held_slow_a, "SlowA request was never dispatched"

        # Immediately change query to prefix_b; FastB responds immediately
        page.fill("#taxonomyTagSearchInput", prefix_b)
        page.wait_for_function(
            "txt => document.querySelector('#tagsListArea')?.innerText?.includes(txt)",
            arg=f"{prefix_b} Target",
            timeout=6000,
        )

        # Now fulfill stale SlowA request late with stale data; FastB must stay rendered
        stale_payload = (
            '{"items":[{"id":"stale-1","name":"' + prefix_a + ' StaleItem","slug":"stale-1","document_count":0}],'
            '"page":1,"page_size":50,"total":1,"total_pages":1}'
        )
        for stale_route in held_slow_a:
            stale_route.fulfill(status=200, content_type="application/json", body=stale_payload)

        page.wait_for_timeout(150)
        rendered_text = page.locator("#tagsListArea").inner_text()
        assert f"{prefix_b} Target" in rendered_text
        assert f"{prefix_a} StaleItem" not in rendered_text
        page.unroute("**/api/v1/admin/tags**")

        # 503 Error + Retry recovery check
        fail_next = {"fail": True}

        def route_503(route):
            if fail_next["fail"]:
                fail_next["fail"] = False
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":{"code":"UNAVAILABLE","message":"Temporary tag backend failure"}}',
                )
            else:
                route.continue_()

        page.route("**/api/v1/admin/tags**", route_503)
        page.fill("#taxonomyTagSearchInput", prefix_b)
        page.wait_for_selector("#retryTagsLoadBtn", state="visible", timeout=6000)
        page.click("#retryTagsLoadBtn")
        page.wait_for_selector("#tagsListArea table", timeout=6000)
        assert f"{prefix_b} Target" in page.locator("#tagsListArea").inner_text()
        _assert_no_runtime_errors(page, page_errors)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Tag).filter(
                (Tag.slug.like(f"{prefix_a.lower()}-%")) | (Tag.slug.like(f"{prefix_b.lower()}-%"))
            ).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_r3_07_math_headings_toc_no_duplication_slug_and_scroll(live_server, browser_instance):
    """
    R3-07:
    Document headings containing KaTeX equations must:
    - Render KaTeX equations visually inside the article body (.document-reading-column).
    - NOT duplicate MathML + annotation + visual HTML text inside the generated Table of Contents
      (e.g. 'x2x^2x2' or 'alphai\\alpha_i' duplication) or mangle heading IDs/slugs.
    - Produce unique slugs for duplicate math headings and navigate/scroll cleanly on TOC click.
    - Preserve XSS safety on headings and keep fenced code blocks raw.
    """
    from datetime import datetime, timezone
    from src.backend.core.database import SessionLocal
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category

    seed_db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        cat = seed_db.query(Category).first()
        assert cat is not None
        doc = Document(
            title=f"R3-07 Math TOC Paper {uuid.uuid4().hex[:6]}",
            summary="Heading math TOC verification.",
            content=(
                "## 1. Scale \\(x^2\\) Overview\n\n"
                "Body equation: $$E = mc^2$$\n\n"
                "## 2. Alpha \\(\\alpha_i\\) Convergence\n\n"
                + ("\n\n".join(f"Spacer paragraph {i} for viewport scrolling verification." for i in range(45)))
                + "\n\n## Summary \\(x^2\\)\n\n"
                "First summary.\n\n"
                "## Summary \\(x^2\\)\n\n"
                "Second summary with identical heading.\n\n"
                "## Safety Probe <img src=x onerror=window.__r3TocXss=true>\n\n"
                "```latex\n"
                "## \\(not_a_heading_math\\)\n"
                "```\n"
            ),
            category_id=cat.id,
            status="published",
            created_at=now,
            published_at=now,
        )
        seed_db.add(doc)
        seed_db.commit()
        doc_id = doc.id
    finally:
        seed_db.close()

    context = browser_instance.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    page_errors, _ = _attach_runtime_guards(page)

    try:
        page.goto(f"{live_server}/#/documents/{doc_id}")
        page.wait_for_selector(".document-toc .toc-list a", timeout=8000)
        page.wait_for_selector(".document-reading-column h2 .katex", timeout=8000)

        toc_data = page.evaluate(
            """() => {
                const links = Array.from(document.querySelectorAll('.document-toc .toc-list a'));
                const headings = Array.from(document.querySelectorAll('.document-reading-column h2'));
                return {
                    linkTexts: links.map(a => a.textContent.trim()),
                    linkHrefs: links.map(a => a.getAttribute('href')),
                    tocKatexCount: document.querySelectorAll('.document-toc .katex, .document-toc math, .document-toc annotation').length,
                    bodyHeadingKatexCount: document.querySelectorAll('.document-reading-column h2 .katex').length,
                    headingIds: headings.map(h => h.id),
                    xssFired: Boolean(window.__r3TocXss),
                };
            }"""
        )

        # KaTeX still renders inside reading column headings, but TOC stays free of duplicated KaTeX DOM fragments
        assert toc_data["bodyHeadingKatexCount"] >= 4
        assert toc_data["tocKatexCount"] == 0, f"TOC unexpectedly contains KaTeX/MathML nodes: {toc_data}"

        labels = toc_data["linkTexts"]
        assert len(labels) == 5
        assert "1. Scale" in labels[0] and "Overview" in labels[0]
        assert "x2x^2x2" not in labels[0], f"Duplicated KaTeX text in TOC label: {labels[0]!r}"
        assert labels[0].count("x^2") <= 1 and labels[0].count("x2") == 0

        assert "2. Alpha" in labels[1] and "Convergence" in labels[1]
        assert labels[1].count("alpha_i") <= 1

        # Unique slug IDs for duplicate math headings & clean slugification
        hrefs = toc_data["linkHrefs"]
        assert len(set(hrefs)) == len(hrefs), f"Duplicate TOC href slugs: {hrefs}"
        assert hrefs == [f"#{hid}" for hid in toc_data["headingIds"]]
        assert "x-2-x-2" not in hrefs[0], f"Duplicated TeX leaked into slug: {hrefs[0]!r}"
        assert "1-scale-x-2-overview" == toc_data["headingIds"][0]

        # XSS payload stripped cleanly
        assert toc_data["xssFired"] is False

        # Click duplicate second Summary TOC anchor -> smooth-scrolls target into view cleanly
        target_id = toc_data["headingIds"][3]
        page.click(f".document-toc a[href='#{target_id}']")
        page.wait_for_function(
            """(id) => {
                const el = document.getElementById(id);
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                return rect.top >= -10 && rect.top < window.innerHeight;
            }""",
            arg=target_id,
            timeout=5000,
        )
        _assert_no_runtime_errors(page, page_errors)
    finally:
        context.close()
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Document).filter(Document.id == doc_id).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()
