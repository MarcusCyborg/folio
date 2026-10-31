# Folio review: implementation and desktop UI

Method: dual-agent (A: design_review; B: design_detector), plus an independent backend/source review by the coordinator.

Reviewed on 2026-10-31, against commit `40d5068`, `ASSIGNMENT.md`, and the Folio handoff brief. This is a review, not a completed remediation pass. Application source was not changed.

## Findings that should be fixed before submission

### F1 — P1: Markdown editor preview permits JavaScript event attributes

Location: `src/frontend/admin/content_views.js:1050`, inserted at `src/frontend/admin/content_views.js:494`.

`renderSafeMarkdown` escapes text, then constructs an anchor by substituting the captured Markdown URL directly into a quoted HTML attribute. `escapeText` does not escape double quotes. A URL containing a quote can therefore escape `href` and create an event handler. The server-side sanitizer used for the public reading view does not protect this separate preview renderer.

Minimal harmless reproduction input:

```text
[hover me](https://example.invalid/"onpointerenter="document.title=123)
```

The transformation used by the implementation produces an anchor with these parsed attributes:

```json
{"href":"https://example.invalid/","onpointerenter":"document.title=123","target":"_blank","rel":"noopener noreferrer"}
```

Verification: reproduced the affected transformation and parsed its HTML with lxml; the event attribute survives. No malicious document was saved, and no script was executed in a user's account. If a staff member saves this Markdown, a higher-privilege editor who opens Preview can be exposed to script execution in the Folio origin.

Fix: use a maintained Markdown parser and sanitize its final HTML, or use a permission-protected backend preview using the existing sanitizer. A text escape before regex HTML construction is insufficient. Add a preview regression test that checks quote-containing URLs and generated event attributes.

### F2 — P1: Unsaved document changes can disappear on ordinary app navigation

Locations: `src/frontend/admin/content_views.js:396`, `src/frontend/core/router.js:58`, `src/frontend/core/router.js:94`.

The editor guards native page unload and its own `editorBackLink`. Sidebar links, the top Library link, and browser history within the hash router bypass that link. The router immediately calls cleanup and clears the container. Hash changes do not cause native `beforeunload`, so an unfinished document is lost without the promised confirmation.

Verification: confirmed from the complete guard/router control flow. The existing automated tests exercise the guarded editor Back link; this review did not complete a live admin-browser reproduction because the in-app browser failed to submit login despite the direct login API working.

Fix: put a cancellable leave guard in the router before abort/cleanup/clear, cover sidebar/header/history transitions, and leave input state intact when the user cancels.

### F3 — P2: “Save as Draft” keeps an existing published document public

Locations: `src/frontend/admin/content_views.js:356`, `src/frontend/admin/content_views.js:564`, `src/frontend/admin/content_views.js:602`.

The button calls `saveDocument('draft')`. For existing documents, only the `publish` and `unpublish` action values trigger a status change. Consequently this button updates a published document's content and leaves its status published. A user expecting a private draft instead changes public content.

Verification: direct source/control-flow finding. Reproduction to add: open an existing published article, edit it, click Save as Draft, then check public visibility/status.

Fix: make the action actually change status to draft, or rename it to Save Changes and provide an explicit Save & Unpublish operation. Match the label and the persisted behavior.

### F4 — P2: Concurrent click retries are counted twice

Locations: `src/backend/models/event.py:17`, `src/backend/services/library/events_service.py:69`.

The actor/request-key index is not unique. `record_click` checks for an existing record and inserts later, so two concurrent requests can both pass the check. This breaks the handoff's idempotency contract and inflates click analytics used for Phase 2.

Verification: reproduced against the separate `folio_test` database. Two sessions were synchronized just before flushing the same actor/request key: **2 requests produced 2 distinct click IDs and 2 persisted rows**. Only review-created test events were removed afterward.

Fix: add a database uniqueness constraint/partial unique index for the intended idempotency key, handle conflicting inserts by returning the original record, and verify that reuse of a key with a different payload is rejected. Add a concurrency test, not only sequential duplicate calls.

### F5 — P2: Reloading a result page creates a new search-result click

Location: `src/frontend/public/detail_view.js:83`.

Click logging runs whenever the detail route contains `search_event_id`, and generates a new request key on each render. Refreshing that URL or restoring it through browser history records another click even when no search result was clicked again. This is separate from a new view, which the plan deliberately allows on refresh.

Verification: source-confirmed route lifecycle; not a browser network-trace reproduction in this review.

Fix: record the result click at activation of the actual result link, or carry a one-use navigation event with a stable key. Keep detail views and result clicks as separate measurements.

### F6 — P2: Valid maximum date crashes the public list API

Location: `src/backend/services/library/catalog_service.py:121`.

`date_to=9999-12-31` parses as a valid Python date, but calculating its next day overflows. The public request returns HTTP 500 rather than the standard validation error.

Verification: `GET /api/v1/documents?date_to=9999-12-31` on the running application returned `500 Internal Server Error`.

Fix: constrain accepted filter dates or handle the upper boundary without adding a day; cover the boundary in API validation tests. This is an edge-case robustness issue, not the main cause of the poor UI.

### F7 — P2: Fresh setup cannot run the advertised full test suite from declared dependencies

Locations: `requirements-dev.txt:1`, `tests/frontend/public/test_public_flows.py:10`, `README.md:62`.

Frontend tests import `playwright.sync_api`, but Playwright is not declared in the development requirements and browser setup is absent from Quickstart. Quickstart installs runtime requirements plus pytest, whereas TestClient also needs the development HTTP client dependency. The already-populated local environment hides this problem.

Verification: dependency/import/README inspection. A clean dependency installation was not performed, so this review does not claim a reproduced clean-install trace.

Fix: declare and pin a compatible test dependency set, document browser installation or a supported system-browser requirement, install `requirements-dev.txt` in the testing instructions, and state the need to migrate/seed the separate test DB.

## Why the UI feels unfinished

The implementation follows the broad palette and serif/sans brief. Its weak point is the relationship between information, spacing and actions. The screen structures appear to have been accepted once controls existed and tests could interact with them. The following are specific problems visible in the current page or saved evidence, not a general objection to light themes or serif typography.

### D1 — P2: Catalog rows combine dense content with poorly used space

Locations: `src/frontend/public/public.css:207`, `src/frontend/public/public.css:253`, `src/frontend/public/library_view.js:290`.

The white rows have zero horizontal padding, so their text touches the surface edge. Metadata appears before the title; a full summary paragraph follows; tags and three counters create another horizontal band. Real Wikipedia summaries take four or more lines, while the brief asks for two or three. The result is visually flat and text-heavy even though there is substantial empty space elsewhere.

Fix: choose either a separator-based list directly on the paper background or a white surface with a real inset. Make title the first reading anchor, consolidate metadata, clamp catalog summaries to three lines, and reduce secondary counters. Preserve full summary/content in the detail view.

### D2 — P2: Dataset presentation undermines the research-library identity

Locations: `scripts/build_fixtures.py:72`, `scripts/build_fixtures.py:101`, `scripts/build_fixtures.py:155`.

Measured fixture facts:

- 100 published documents plus 3 drafts; **0 records have a cover image URL**.
- 63 of the 100 published articles fall under Technology & Society; only 6 under AI/ML and 2 under Computer Science & Systems.
- 12 summaries still contain `[edit]` or `[citation needed]` artifacts.
- Work ethic is classified as Scientific Research & Publishing; Work–life balance as Neuroscience & Cognitive Science.
- Added dates are generated from record position, not actual import timestamps, without the source notes clearly describing them as demo dates.

The classifier uses the first keyword hit from title/intro and defaults to Technology & Society. Summary cleaning preserves some crawler debris. The source notes call the set curated, but these examples show that the automatic output was not sufficiently checked.

Fix: review and map the 100 records deliberately, clean the excerpts, label demo dates honestly or use real import dates, and add a few relevant licensed/local figures if the detail-image requirement is to be demonstrated. Images need not be added to every catalog row. Content quality contributes as much as CSS to the first impression.

### D3 — P2: Admin actions visually overpower the document being managed

Locations: `src/frontend/admin/content_views.js:153`, `src/frontend/admin/content_views.js:160`, `src/frontend/admin/admin.css:154`.

Each table row presents Edit, Publish/Unpublish, a red Delete button and Edit SEO together. The non-wrapping action group takes substantial width while long titles are truncated. Bright blue category badges, green status badges and repeated red buttons compete with the teal brand accent. The user's eye is drawn to deletion before the document title.

Fix: keep title/Edit as the primary action; place secondary and destructive operations in a row menu, with confirmation preserved. Widen the title column and reduce badge emphasis. Group the ten admin navigation entries by job rather than giving each equal visual weight.

### D4 — P2: Analytics labels shrink as the date range grows

Locations: `src/frontend/admin/analytics_views.js:573`, `src/frontend/admin/analytics_views.js:589`.

The SVG viewBox grows with the number of days while the rendered chart is fixed at 144px tall and 100% width. Date labels are 10 units inside that SVG, so they shrink to roughly 6px in the saved 30-day desktop screenshot and shrink further over 90 days. There is no readable value axis. The chart occupies space without providing readable trend detail.

Fix: reserve approximately 220–260px for the plot, keep label text around 11–12 CSS pixels, select fewer date ticks based on available width, and add a restrained Y-axis/grid. Keep the table as the exact-value companion.

### D5 — P2: Long documents lack section navigation

Locations: `src/frontend/public/detail_view.js:167`, `src/frontend/public/detail_view.js:172`.

The live Work ethic page has eight section headings and approximately 9,434px total page height, but no table of contents or section links. Source attribution is below the entire article. A reader must scroll or use browser Find to locate a section or verify the source.

Fix: build a heading-derived table of contents and expose the source near the author/date. Preserve the existing approximately 760px reading column and generous line height; those are useful choices.

### Details to address after structure

- Self-host fonts as planned; `src/frontend/index.html:7` currently depends on Google Fonts and there is no local fonts folder.
- Use a coherent icon set instead of eye/heart/comment emoji with inconsistent appearance.
- Bring Save/Publish into an editor action bar visible while working; currently actions are below the full form (`content_views.js:354`).
- Review labels such as Scholar, Executive Summary and Peer Notes against the actual Wikipedia content; avoid implying research validation that has not occurred.
- SEO title is saved but public detail sets the browser title from `doc.title`, not `doc.seo_title` (`detail_view.js:68`).
- Site name/description settings persist in the database, but the shell remains hardcoded and does not load those values (`app.js:95`, `index.html:17`).

## What the previous verification report does and does not prove

The existing report states 66/66 tests pass. This review independently reran the **51 backend tests**, which passed with 15 warnings in 12.86 seconds:

```powershell
.\env\Scripts\python.exe -m pytest tests/backend -q -p no:cacheprovider
```

The configured application database is `folio`; the verified, separate test database is `folio_test`. Test execution used that separate database. This review did not rerun the 15 frontend tests because the suite overwrites existing screenshot evidence and also performs persistent test workflows. It inspected those tests and their existing images instead, alongside live public-page browsing.

Two weaknesses in the visual QA claims:

1. `tests/frontend/public/test_public_flows.py:83` asserts that a screenshot file exists. `tests/frontend/admin/test_admin_screenshots.py:188` asserts that there are at least 15 image files. These are capture checks, not assertions of alignment, clipping, hierarchy, legibility or design quality.
2. `device_scale_factor=1.25` (`test_public_flows.py:70`, `test_admin_screenshots.py:177`) simulates pixel density; it does not by itself simulate browser page zoom. The existing “125% zoom certified” claim is not supported by that setting alone.

The stored `library_1440x900.png` and admin captures include 106 published records and repeated Quantum Computing test articles. The current live catalog has 100 published Wikipedia articles with substantially longer summaries. Testing with short repeated fixtures has masked layout issues present in the real content.

The in-app browser rendered the live public catalog and detail. Its admin login submission returned `Failed to fetch`, while a direct session/CSRF/login API sequence succeeded with HTTP 200. This observation is recorded as a browser-verification limitation, not attributed to an application defect. Admin visual observations are based on saved screenshots plus current source. Existing app server was left running; temporary review tabs were closed.

## Design score and strengths

Nielsen heuristic scores are reviewer judgments over the observed scope, not automated certification or an assignment grade.

| Heuristic | Score / 4 | Main observation |
|---|---:|---|
| System status | 3 | Loading, counts, filters, toasts and dirty indicators exist |
| Match to user language | 2 | Some academic claims/labels do not match source content |
| User control | 2 | Useful reset/back controls; incomplete leave guard |
| Consistency | 2 | Shared type/controls; divergent badges and emoji |
| Error prevention | 2 | Validation/confirmations exist; editor transitions need protection |
| Recognition | 2 | Visible navigation; missing article TOC |
| Efficiency | 2 | Search/filter/paging work; repetitive admin actions |
| Aesthetic/minimalism | 2 | Dense metadata and competing controls |
| Error recovery | 3 | Empty/error states generally offer a useful exit |
| Help | 2 | Basic hints; limited contextual guidance |
| **Total** | **22/40** | **Significant usability and visual improvements needed** |

Keep the paper/ink/teal direction, serif/sans pairing, reading width, clear filter-reset affordances and useful empty states. A large decorative hero or a new color theme would not address the identified problems.

Persona observations: a reader struggles to judge and navigate a long article; a content manager must process too many equally emphasized actions and can lose unsaved work; an analyst cannot readily read chart labels. The initial calm impression weakens when crawl artifacts and repetitive admin controls appear.

## Deterministic design scan

Assessment B ran the bundled detector once over `src/frontend`: **5 warnings, 0 errors**, covering `cream-palette` once and `side-tab` four times. Raw evidence: `detector/detector.json`; browser/cleanup notes: `detector/evidence.md`.

These signals do not explain the main defects. The cream background is intentional in the brief, and three of the left borders denote info/error/success notices. They are plausible false positives, not five established design failures. No browser overlay was injected: the exposed evaluate API is read-only. The scan was isolated from Assessment A until that design review finished.

## Recommended remediation sequence

1. Fix preview safety, editor leave protection and Save as Draft behavior. Add regression tests for these exact failures.
2. Fix click-event uniqueness and navigation semantics; repair reproducible API/setup issues.
3. Curate and clean the fixture actually used for the demo. Treat this as content preparation, not a styling task.
4. Redesign one Library screen using real long/short records at 1366x768 and 1440x900. Review its rendered result before spreading the pattern.
5. Apply the agreed hierarchy to document detail and admin; simplify row actions and repair the chart.
6. Re-capture stable clean-demo states, verify real browser zoom and revise the QA report to distinguish checks from visual judgments.

The earlier handoff plan supplied colors, fonts, layout guidance and parallel ownership, but did not require approval of a rendered reference screen before the frontend branches expanded. That is a weakness in the plan itself. A clear visual checkpoint and one owner of cross-screen design decisions should be added to the next pass.

Assignment coverage has advanced substantially: the backend workflow and role-based modules are real and the 51 backend tests passed. This review does not support an unconditional “everything completed and visually verified” claim. It supports targeted correction and a focused visual pass, rather than rebuilding the working backend.

Questions skipped: this request is for a review/report; the existing brief provides enough scope to give concrete findings and a prioritized next pass.
